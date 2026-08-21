"""Java 런타임 검증 + visual 양방향 폴백 + 사용자 대면 메시지 회귀 테스트.

이 파일은 다음을 고정한다.
  - _java_executable_works: 실제 `java -version`으로 스텁(exit≠0)을 거부하고 결과를 캐싱.
  - ensure_java_runtime: 검증 통과한 번들 java만 반환, 전부 무효면 OdlRuntimeError.
  - ensure_visual_artifacts: Java가 안 되면 Gemini로, 둘 다 없으면 명확한 한국어 에러.
  - 사용자 대면 메시지: raw java.com 안내를 한국어 안내로 변환(실제 파싱 실패는 보존).
"""

from __future__ import annotations

import contextlib
import copy
import os
import stat
import subprocess
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

import fitz

# services.odl_parser는 import 시 services.subfigure_detector를 요구할 수 있으므로,
# 실제 무거운 detector 대신 경량 스텁을 심어 둔다(test_odl_parser와 동일 패턴).
_subfig_stub = types.ModuleType("services.subfigure_detector")


class _StubSubFigureDetector:
    async def detect_subfigures(self, *args, **kwargs):
        return types.SimpleNamespace(has_subfigures=False, confidence=0.0)

    async def extract_subfigures(self, *args, **kwargs):
        return []


_subfig_stub.SubFigureDetector = _StubSubFigureDetector
sys.modules.setdefault("services.subfigure_detector", _subfig_stub)

from services import odl_parser as odl
from services.odl_parser import (
    OdlParserError,
    OdlRuntimeError,
    _convert_error_message,
    _java_executable_works,
    _java_missing_user_message,
    _plan_visual_engines,
    ensure_java_runtime,
    ensure_visual_artifacts,
    explain_odl_failure,
)


@contextlib.contextmanager
def _env(**overrides):
    """파서/런타임 관련 env를 격리한다. 값이 None이면 미설정."""
    keys = [
        "SASOO_PDF_ENGINE",
        "SASOO_PDF_TEXT_ENGINE",
        "SASOO_PDF_VISUAL_ENGINE",
        "GEMINI_API_KEY",
        "SASOO_JAVA_HOME",
        "JAVA_HOME",
    ]
    saved = {k: os.environ.get(k) for k in keys}
    for k in keys:
        os.environ.pop(k, None)
    for k, v in overrides.items():
        if v is not None:
            os.environ[k] = v
    try:
        yield
    finally:
        for k in keys:
            os.environ.pop(k, None)
            if saved[k] is not None:
                os.environ[k] = saved[k]


def _bundled_java() -> Path:
    """번들 java 실행 파일 경로. 소스와 동일한 플랫폼별 이름 해석을 쓴다.

    번들 런타임은 macOS 전용(Mach-O)이라 Windows 체크아웃에도 `bin/java` 파일 자체는
    존재한다. 이름을 "java"로 고정하면 Windows에서 exists()가 참이 되어 실행 불가능한
    Mach-O를 유효한 번들로 오인하고, 아래 테스트들이 skip 대신 실패한다.
    """
    return odl._java_executable_for_home(odl._backend_root() / "java-runtime")


def _write_exec_script(path: Path, body: str) -> None:
    path.write_text(body, encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)


def _minimal_root(content: str) -> dict:
    return {
        "title": "T",
        "author": "A",
        "number of pages": 1,
        "kids": [
            {
                "type": "paragraph",
                "id": 1,
                "page number": 1,
                "bounding box": [10, 10, 120, 40],
                "content": content,
            }
        ],
    }


class JavaExecutableValidationTests(unittest.TestCase):
    def setUp(self) -> None:
        odl._JAVA_VALIDATION_CACHE.clear()

    def tearDown(self) -> None:
        odl._JAVA_VALIDATION_CACHE.clear()

    def test_bundled_java_is_detected_as_working(self) -> None:
        bundled = _bundled_java()
        if not bundled.exists():
            self.skipTest("번들 java 런타임이 없음")
        self.assertTrue(_java_executable_works(bundled))

    @unittest.skipIf(sys.platform == "win32", "POSIX 스텁 스크립트 테스트")
    def test_failing_stub_is_rejected(self) -> None:
        # macOS /usr/bin/java 스텁처럼 존재하지만 exit≠0으로 죽는 가짜 java.
        with tempfile.TemporaryDirectory() as tmp:
            stub = Path(tmp) / "java"
            _write_exec_script(stub, "#!/bin/sh\necho 'no runtime' 1>&2\nexit 1\n")
            self.assertFalse(_java_executable_works(stub))

    def test_missing_path_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            missing = Path(tmp) / "does_not_exist" / "java"
            self.assertFalse(_java_executable_works(missing))

    @unittest.skipIf(sys.platform == "win32", "POSIX 스텁 스크립트 테스트")
    def test_result_is_cached_and_not_reprobed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            stub = Path(tmp) / "java"
            _write_exec_script(stub, "#!/bin/sh\nexit 1\n")
            self.assertFalse(_java_executable_works(stub))  # 프로브 → False, 캐시됨
            # 파일을 정상(exit 0)으로 바꿔도, 캐시된 False가 유지되어야 한다(재프로브 없음).
            _write_exec_script(stub, "#!/bin/sh\nexit 0\n")
            self.assertFalse(_java_executable_works(stub))
            self.assertIs(odl._JAVA_VALIDATION_CACHE[str(stub)], False)


class EnsureJavaRuntimeTests(unittest.TestCase):
    def setUp(self) -> None:
        odl._JAVA_VALIDATION_CACHE.clear()
        self._saved = {k: os.environ.get(k) for k in ("JAVA_HOME", "PATH", "SASOO_JAVA_HOME")}

    def tearDown(self) -> None:
        odl._JAVA_VALIDATION_CACHE.clear()
        for k, v in self._saved.items():
            os.environ.pop(k, None)
            if v is not None:
                os.environ[k] = v

    def test_returns_validated_bundled_java(self) -> None:
        if not _bundled_java().exists():
            self.skipTest("번들 java 런타임이 없음")
        with _env():  # SASOO_JAVA_HOME/JAVA_HOME 제거 → 번들 후보가 첫 유효 후보
            result = Path(ensure_java_runtime())
            self.assertTrue(_java_executable_works(result))
            self.assertEqual(result.name, _bundled_java().name)
            self.assertIn("java-runtime", result.parts)
            # 검증된 java의 bin이 PATH에 prepend되고 JAVA_HOME이 세팅되어야 한다.
            self.assertEqual(os.environ.get("PATH", "").split(os.pathsep)[0], str(result.parent))
            self.assertTrue(os.environ.get("JAVA_HOME"))

    def test_raises_when_no_valid_java_anywhere(self) -> None:
        # 번들 후보 없음 + PATH의 java도 없음(또는 스텁) → OdlRuntimeError.
        with _env(), patch(
            "services.odl_parser._runtime_candidates", return_value=[]
        ), patch("services.odl_parser.shutil.which", return_value=None):
            with self.assertRaises(OdlRuntimeError) as ctx:
                ensure_java_runtime()
        self.assertIn("Java", str(ctx.exception))

    def test_rejects_path_java_stub(self) -> None:
        # 번들 없음 + PATH에 java가 있지만 스텁(exit≠0) → 검증 실패 → OdlRuntimeError.
        with tempfile.TemporaryDirectory() as tmp:
            stub = Path(tmp) / "java"
            _write_exec_script(stub, "#!/bin/sh\nexit 1\n")
            with _env(), patch(
                "services.odl_parser._runtime_candidates", return_value=[]
            ), patch("services.odl_parser.shutil.which", return_value=str(stub)):
                with self.assertRaises(OdlRuntimeError):
                    ensure_java_runtime()


class VisualEnginePlanTests(unittest.TestCase):
    def test_java_ok_and_key_present_tries_gemini_then_odl(self) -> None:
        with _env(GEMINI_API_KEY="k"), patch(
            "services.odl_parser._java_runtime_available", return_value=True
        ):
            self.assertEqual(_plan_visual_engines("gemini"), ["gemini", "odl"])

    def test_java_invalid_but_key_present_uses_gemini_only(self) -> None:
        with _env(GEMINI_API_KEY="k"), patch(
            "services.odl_parser._java_runtime_available", return_value=False
        ):
            self.assertEqual(_plan_visual_engines("gemini"), ["gemini"])

    def test_no_key_but_java_ok_uses_odl_only(self) -> None:
        with _env(), patch(
            "services.odl_parser._java_runtime_available", return_value=True
        ):
            self.assertEqual(_plan_visual_engines("gemini"), ["odl"])

    def test_nothing_available_returns_empty_plan(self) -> None:
        with _env(), patch(
            "services.odl_parser._java_runtime_available", return_value=False
        ):
            self.assertEqual(_plan_visual_engines("gemini"), [])


class VisualFallbackTests(unittest.TestCase):
    def _make_paper(self, tmp_dir: str) -> Path:
        paper_dir = Path(tmp_dir)
        pdf_path = paper_dir / "paper.pdf"
        doc = fitz.open()
        page = doc.new_page(width=300, height=400)
        page.insert_text((72, 72), "seed", fontsize=12)
        doc.save(pdf_path)
        doc.close()
        return paper_dir

    def test_java_invalid_falls_back_to_gemini(self) -> None:
        """Java 검증 실패 + 키 존재 → ODL을 건너뛰고 Gemini로 표/그림을 뽑는다."""
        gemini_text = "GEMINI VISUAL BODY table | a | b |"

        def _fake_run_convert(
            pdf_path, output_dir, figures_dir, mode, engine=None, stage="text", provider=None
        ):
            if engine == "odl":
                raise AssertionError("Java 검증 실패 시 odl을 시도하면 안 된다")
            # stage_default(gemini)를 engine=None으로 태운 경로.
            return copy.deepcopy(_minimal_root(gemini_text)), gemini_text, "gemini"

        with tempfile.TemporaryDirectory() as tmp:
            paper_dir = self._make_paper(tmp)
            with _env(GEMINI_API_KEY="k"), patch(
                "services.odl_parser._java_runtime_available", return_value=False
            ), patch(
                "services.odl_parser.ensure_text_artifacts"
            ), patch(
                "services.odl_parser._run_convert", side_effect=_fake_run_convert
            ), patch(
                "services.odl_parser.active_provider", new=AsyncMock(return_value="gemini")
            ):
                manifest = ensure_visual_artifacts(
                    paper_dir, mode="java", extraction_pipeline_version="legacy", force=True
                )

            self.assertEqual(manifest["engine"], "gemini")
            self.assertIn("GEMINI VISUAL BODY", manifest["full_text"])
            self.assertIn("GEMINI VISUAL BODY", (paper_dir / "paper.md").read_text(encoding="utf-8"))

    def test_no_java_and_no_key_raises_clear_korean_error(self) -> None:
        """Java 없음 + 키 없음 → 모호한 java.com이 아니라 명확한 한국어 에러를 던진다."""
        with tempfile.TemporaryDirectory() as tmp:
            paper_dir = self._make_paper(tmp)
            with _env(), patch(
                "services.odl_parser._java_runtime_available", return_value=False
            ), patch(
                "services.odl_parser.ensure_text_artifacts"
            ), patch(
                "services.odl_parser.active_provider", new=AsyncMock(return_value="gemini")
            ):
                with self.assertRaises(OdlRuntimeError) as ctx:
                    ensure_visual_artifacts(
                        paper_dir, mode="java", extraction_pipeline_version="legacy", force=True
                    )
        message = str(ctx.exception)
        self.assertIn("Java", message)
        self.assertIn("Gemini API 키", message)
        self.assertNotIn("java.com", message.lower())


class UserFacingMessageTests(unittest.TestCase):
    def test_convert_error_message_translates_java_com_stub(self) -> None:
        err = subprocess.CalledProcessError(
            1,
            ["java", "-jar", "x.jar"],
            stderr=(
                "The operation couldn't be completed. Unable to locate a Java Runtime.\n"
                "Please visit http://www.java.com for information on installing Java.\n"
            ),
        )
        message = _convert_error_message(err)
        self.assertEqual(message, _java_missing_user_message())
        self.assertNotIn("java.com", message.lower())
        self.assertNotIn("exit code", message)

    def test_convert_error_message_preserves_real_parse_failure(self) -> None:
        err = subprocess.CalledProcessError(
            2, ["java"], stderr="Exception: malformed PDF structure at page 3"
        )
        message = _convert_error_message(err)
        self.assertIn("exit code 2", message)
        self.assertIn("malformed PDF structure", message)

    def test_explain_translates_java_missing_parser_error(self) -> None:
        status, detail = explain_odl_failure(
            OdlParserError("OpenDataLoader convert failed: ... www.java.com ...")
        )
        self.assertEqual(status, 503)
        self.assertEqual(detail, _java_missing_user_message())

    def test_explain_preserves_real_parser_error(self) -> None:
        status, detail = explain_odl_failure(OdlParserError("OpenDataLoader did not produce text."))
        self.assertEqual(status, 422)
        self.assertIn("did not produce text", detail)

    def test_explain_preserves_runtime_error_message(self) -> None:
        # OdlRuntimeError 메시지는 소스에서 구성되므로 그대로 통과(기존 계약 유지).
        status, detail = explain_odl_failure(OdlRuntimeError("Java runtime was not found."))
        self.assertEqual(status, 503)
        self.assertEqual(detail, "Java runtime was not found.")


if __name__ == "__main__":
    unittest.main()
