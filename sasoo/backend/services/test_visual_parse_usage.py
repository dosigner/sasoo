"""visual 단계 Gemini 파서 usage → analysis_results 원장 배선 테스트 (오프라인).

검증 항목:
  1. 성공(gemini visual 파싱) 시 원장에 phase="visual_parse"로 1회 기록 + 값 검증.
  2. usage 부재(ODL 폴백/캐시 히트) 시 미기록.
  3. DB 오류(예: 파일럿·미초기화 환경) 시 조용히 스킵, 파이프라인 불변.
  4. thread-local 채널이 _run_convert를 건드리지 않고 gemini usage를 manifest로 끌어올림.
"""

from __future__ import annotations

import copy
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

import fitz

import services.odl_parser as odl
from services.pricing import calc_cost

MODEL = "gemini-3.5-flash"


def _usage(pages: int = 3, tin: int = 1000, tout: int = 500, tthought: int = 120) -> dict:
    return {
        "engine": "gemini",
        "model": MODEL,
        "pages": pages,
        "tokens_in": tin,
        "tokens_out": tout,
        "tokens_thought": tthought,
        "cost_usd": 0.123,  # 채널이 준 값 — 기록 헬퍼는 무시하고 calc_cost로 재계산한다.
    }


class RefreshRecordsUsageTests(unittest.IsolatedAsyncioTestCase):
    async def _run_refresh(self, manifest: dict):
        insert_mock = AsyncMock()
        with patch(
            "services.odl_parser.ensure_visual_artifacts_async",
            new=AsyncMock(return_value=manifest),
        ), patch(
            "services.odl_parser.sync_figures_for_paper", new=AsyncMock()
        ) as fig_mock, patch(
            "services.odl_parser.sync_tables_for_paper", new=AsyncMock()
        ) as tbl_mock, patch(
            "services.odl_parser.execute_insert", new=insert_mock
        ):
            returned = await odl._refresh_paper_artifacts(42, Path("/tmp/paper"))
        return returned, insert_mock, fig_mock, tbl_mock

    async def test_success_records_once_with_values(self):
        manifest = {"engine": "gemini", "_visual_parse_usage": _usage()}
        returned, insert_mock, fig_mock, tbl_mock = await self._run_refresh(manifest)

        # 기록 1회
        insert_mock.assert_awaited_once()
        params = insert_mock.await_args.args[1]
        # (paper_id, phase, result, model, tokens_in, tokens_out, cost, input_hash)
        self.assertEqual(params[0], 42)
        self.assertEqual(params[1], "visual_parse")
        self.assertEqual(params[3], MODEL)
        self.assertEqual(params[4], 1000)
        self.assertEqual(params[5], 500)
        self.assertAlmostEqual(params[6], calc_cost(MODEL, 1000, 500))
        self.assertAlmostEqual(params[6], 0.006)  # 1000*1.5/1e6 + 500*9/1e6

        payload = json.loads(params[2])
        self.assertEqual(payload["engine"], "gemini")
        self.assertEqual(payload["pages"], 3)
        self.assertEqual(payload["tokens_thought"], 120)

        # 아티팩트 sync는 그대로 수행되고, transient 키는 걷혀 나간다.
        fig_mock.assert_awaited_once()
        tbl_mock.assert_awaited_once()
        self.assertNotIn("_visual_parse_usage", returned)

    async def test_no_usage_key_records_nothing(self):
        # ODL 폴백/캐시 히트 → manifest에 transient 키 없음.
        manifest = {"engine": "odl-java"}
        returned, insert_mock, fig_mock, tbl_mock = await self._run_refresh(manifest)
        insert_mock.assert_not_awaited()
        fig_mock.assert_awaited_once()
        tbl_mock.assert_awaited_once()

    async def test_zero_tokens_records_nothing(self):
        manifest = {"engine": "gemini", "_visual_parse_usage": _usage(tin=0, tout=0)}
        _, insert_mock, _, _ = await self._run_refresh(manifest)
        insert_mock.assert_not_awaited()

    async def test_db_error_is_swallowed(self):
        # DB 미초기화/오류 환경: 기록 실패해도 refresh는 정상 완료해야 한다.
        manifest = {"engine": "gemini", "_visual_parse_usage": _usage()}
        boom = AsyncMock(side_effect=RuntimeError("Database not initialized"))
        with patch(
            "services.odl_parser.ensure_visual_artifacts_async",
            new=AsyncMock(return_value=manifest),
        ), patch(
            "services.odl_parser.sync_figures_for_paper", new=AsyncMock()
        ), patch(
            "services.odl_parser.sync_tables_for_paper", new=AsyncMock()
        ), patch(
            "services.odl_parser.execute_insert", new=boom
        ):
            # 예외가 전파되지 않아야 한다.
            returned = await odl._refresh_paper_artifacts(7, Path("/tmp/paper"))
        boom.assert_awaited_once()
        self.assertNotIn("_visual_parse_usage", returned)


def _root(content: str) -> dict:
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


class ChannelCaptureTests(unittest.TestCase):
    """_run_convert(mock 경계)를 건드리지 않고 gemini usage가 manifest로 올라오는지."""

    def setUp(self):
        # Task 9: _build_resolver_v1_manifest가 active_provider()를 호출한다.
        self._active_provider_patch = patch(
            "services.odl_parser.active_provider", new=AsyncMock(return_value="gemini"),
        )
        self._active_provider_patch.start()
        self.addCleanup(self._active_provider_patch.stop)

    def _make_paper(self, tmp_dir: str) -> Path:
        paper_dir = Path(tmp_dir)
        pdf_path = paper_dir / "paper.pdf"
        doc = fitz.open()
        page = doc.new_page(width=300, height=400)
        page.insert_text((72, 72), "seed", fontsize=12)
        doc.save(pdf_path)
        doc.close()
        return paper_dir

    def test_gemini_usage_bubbles_into_manifest_key(self):
        async def _fake_run_convert_gemini(
            pdf_path, output_dir, figures_dir, *, usage_out=None, provider="gemini"
        ):
            # 실제 API 대신, 채널이 넘겨준 usage_out을 run_convert_gemini와 동일 계약으로 채운다.
            if usage_out is not None:
                usage_out.update(
                    {
                        "engine": "gemini",
                        "model": MODEL,
                        "pages": 1,
                        "tokens_in": 800,
                        "tokens_out": 300,
                        "tokens_thought": 40,
                        "cost_usd": calc_cost(MODEL, 800, 300),
                    }
                )
            return copy.deepcopy(_root("GEMINI VISUAL TEXT")), "GEMINI VISUAL TEXT", "gemini"

        with tempfile.TemporaryDirectory() as tmp_dir:
            paper_dir = self._make_paper(tmp_dir)
            env = {"GEMINI_API_KEY": "test-key", "SASOO_PDF_VISUAL_ENGINE": "gemini"}
            with patch.dict(os.environ, env), patch(
                "services.odl_parser.ensure_text_artifacts"
            ), patch(
                "services.gemini_parser.run_convert_gemini",
                new=_fake_run_convert_gemini,
            ):
                manifest = odl.ensure_visual_artifacts(
                    paper_dir, mode="java", extraction_pipeline_version="legacy", force=True
                )

        usage = manifest.get("_visual_parse_usage")
        self.assertIsNotNone(usage, "gemini usage가 manifest로 올라오지 않음")
        assert usage is not None
        self.assertEqual(usage["engine"], "gemini")
        self.assertEqual(usage["tokens_in"], 800)
        self.assertEqual(usage["tokens_out"], 300)
        # 채널은 호출 후 비워진다(스레드 재사용 시 stale 방지).
        self.assertIsNone(getattr(odl._visual_parse_usage_channel, "usage", None))

    def test_channel_stays_empty_when_engine_is_odl(self):
        # visual 엔진을 ODL로 강제하면 gemini 파서가 안 돌아 usage 키가 없어야 한다.
        def _all_odl(pdf_path, output_dir, figures_dir, mode, engine=None, stage="text"):
            return copy.deepcopy(_root("ODL TEXT")), "ODL TEXT", "odl-java"

        with tempfile.TemporaryDirectory() as tmp_dir:
            paper_dir = self._make_paper(tmp_dir)
            with patch("services.odl_parser._run_convert", side_effect=_all_odl), patch(
                "services.odl_parser.ensure_text_artifacts"
            ):
                manifest = odl.ensure_visual_artifacts(
                    paper_dir, mode="java", extraction_pipeline_version="legacy", force=True
                )
        self.assertNotIn("_visual_parse_usage", manifest)


class FallbackAndTextRootTests(unittest.TestCase):
    """F1(폴백 우회 방지) + F2(부분 실패 원장 기록) + F4(텍스트 계약 본문 보전)."""

    def setUp(self):
        # Task 9: _build_resolver_v1_manifest가 active_provider()를 호출한다.
        self._active_provider_patch = patch(
            "services.odl_parser.active_provider", new=AsyncMock(return_value="gemini"),
        )
        self._active_provider_patch.start()
        self.addCleanup(self._active_provider_patch.stop)

    def _make_paper(self, tmp_dir: str) -> Path:
        paper_dir = Path(tmp_dir)
        pdf_path = paper_dir / "paper.pdf"
        doc = fitz.open()
        page = doc.new_page(width=300, height=400)
        page.insert_text((72, 72), "seed", fontsize=12)
        doc.save(pdf_path)
        doc.close()
        return paper_dir

    def test_run_convert_gemini_wraps_non_gemini_error_as_odl_error(self):
        # F1: gemini 경로가 GeminiParserError가 아닌 raw 예외(예: fitz.open 실패)를 던져도
        # _run_convert_gemini가 OdlParserError로 감싸야 상위 폴백이 동작한다(원인 체이닝 유지).
        async def _raise_raw(
            pdf_path, output_dir, figures_dir, *, usage_out=None, provider="gemini"
        ):
            raise RuntimeError("raw fitz explosion")

        with tempfile.TemporaryDirectory() as tmp_dir:
            paper_dir = Path(tmp_dir)
            with patch("services.gemini_parser.run_convert_gemini", new=_raise_raw):
                with self.assertRaises(odl.OdlParserError) as ctx:
                    odl._run_convert_gemini(
                        paper_dir / "x.pdf", paper_dir, paper_dir / "figures"
                    )
            self.assertIsInstance(ctx.exception.__cause__, RuntimeError)

    def test_partial_gemini_failure_records_billed_pages_via_odl_fallback(self):
        # F2: 부분 실패로 gemini가 raise하고 ODL 폴백이 일어나도, 이미 과금된 gemini 페이지의
        # usage가 채널을 통해 manifest로 올라와 원장에 기록되게 한다(최종 엔진은 ODL).
        async def _partial_then_raise(
            pdf_path, output_dir, figures_dir, *, usage_out=None, provider="gemini"
        ):
            from services.gemini_parser import GeminiParserError

            if usage_out is not None:
                usage_out.update(
                    {
                        "engine": "gemini",
                        "model": MODEL,
                        "pages": 1,
                        "tokens_in": 800,
                        "tokens_out": 300,
                        "tokens_thought": 40,
                        "cost_usd": calc_cost(MODEL, 800, 300),
                        "partial": True,
                    }
                )
            raise GeminiParserError("2/3 page(s) failed; first error: rate limit")

        def _fake_odl(pdf_path, output_dir, figures_dir, mode):
            return copy.deepcopy(_root("ODL FALLBACK TEXT")), "ODL FALLBACK TEXT", "odl-java"

        with tempfile.TemporaryDirectory() as tmp_dir:
            paper_dir = self._make_paper(tmp_dir)
            env = {"GEMINI_API_KEY": "test-key", "SASOO_PDF_VISUAL_ENGINE": "gemini"}
            with patch.dict(os.environ, env), patch(
                "services.odl_parser.ensure_text_artifacts"
            ), patch(
                "services.gemini_parser.run_convert_gemini", new=_partial_then_raise
            ), patch(
                "services.odl_parser._run_convert_odl", side_effect=_fake_odl
            ):
                manifest = odl.ensure_visual_artifacts(
                    paper_dir, mode="java", extraction_pipeline_version="legacy", force=True
                )

        self.assertEqual(manifest.get("engine"), "odl-java")  # 최종 아티팩트는 ODL 폴백
        usage = manifest.get("_visual_parse_usage")
        self.assertIsNotNone(usage, "부분 실패한 gemini 지출이 원장 배선으로 올라오지 않음")
        assert usage is not None
        self.assertEqual(usage["engine"], "gemini")
        self.assertEqual(usage["tokens_in"], 800)
        self.assertEqual(usage["tokens_out"], 300)
        self.assertTrue(usage.get("partial"))

    def test_manifest_to_text_root_restores_body_for_gemini(self):
        # F4: gemini slim 매니페스트(text_blocks 공동화)에서 {stem}.json 텍스트 루트가 full_text의
        # 페이지 마커를 근거로 본문 paragraph를 복원해야 한다(.md와 본문 일치).
        manifest = {
            "engine": "gemini",
            "metadata": {"title": "T", "authors": "A", "page_count": 2},
            "full_text": (
                "--- Page 1 ---\n\nBody paragraph one.\n\n"
                "--- Page 2 ---\n\nBody paragraph two."
            ),
            "pages": [
                {"page_number": 1, "text_blocks": []},
                {"page_number": 2, "text_blocks": []},
            ],
        }
        root = odl._manifest_to_text_root(manifest)
        kids = root["kids"]
        self.assertEqual(len(kids), 2)
        self.assertEqual(kids[0]["type"], "paragraph")
        self.assertEqual(kids[0]["page number"], 1)
        self.assertIn("Body paragraph one.", kids[0]["content"])
        self.assertEqual(kids[1]["page number"], 2)
        self.assertIn("Body paragraph two.", kids[1]["content"])

    def test_promoted_gemini_json_contract_has_body_text(self):
        # F4 end-to-end(파일 쓰기까지): 프로덕션 기본(resolver_v1)의 gemini 매니페스트는
        # full_text=markdown(본문+페이지 마커)이고 pages[*].text_blocks는 공동화(heading/caption만)다.
        # _ensure_text_contract_files가 승격 overwrite로 {stem}.json을 쓸 때, 그 텍스트 루트가
        # text_blocks가 아니라 full_text에서 본문 paragraph를 복원해 담는지 확인한다.
        with tempfile.TemporaryDirectory() as tmp_dir:
            paper_dir = self._make_paper(tmp_dir)
            manifest = {
                "engine": "gemini",
                "pdf_file": "paper.pdf",
                "markdown_file": "paper.md",
                "json_file": "paper.json",
                "metadata": {"title": "T", "authors": "A", "page_count": 2},
                "full_text": (
                    "--- Page 1 ---\n\n# Heading\n\nReal body sentence on page one.\n\n"
                    "--- Page 2 ---\n\nReal body sentence on page two."
                ),
                # slim: per-page text_blocks에 본문 없음(공동화).
                "pages": [
                    {"page_number": 1, "text_blocks": []},
                    {"page_number": 2, "text_blocks": []},
                ],
            }
            odl._ensure_text_contract_files(paper_dir, manifest, overwrite=True)
            text_root = json.loads((paper_dir / "paper.json").read_text(encoding="utf-8"))

        contents = " ".join(str(k.get("content", "")) for k in text_root["kids"])
        self.assertIn("Real body sentence on page one.", contents)
        self.assertIn("Real body sentence on page two.", contents)

    def test_manifest_to_text_root_keeps_textblocks_path_for_non_gemini(self):
        # 비-gemini(ODL/pymupdf) 매니페스트는 기존 text_blocks 경로 불변 — full_text가 있어도
        # gemini 분기를 타지 않는다(여기선 text_blocks가 비어 kids도 빈다).
        manifest = {
            "engine": "odl-java",
            "metadata": {"page_count": 1},
            "full_text": "--- Page 1 ---\n\nShould be ignored for non-gemini.",
            "pages": [{"page_number": 1, "text_blocks": []}],
        }
        root = odl._manifest_to_text_root(manifest)
        self.assertEqual(root["kids"], [])


if __name__ == "__main__":
    unittest.main()
