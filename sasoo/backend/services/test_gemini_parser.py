"""
gemini_parser 오프라인 단위 테스트.

call_interaction을 mock해 네트워크 없이 실행한다. 검증 항목:
  (1) run_convert_gemini의 3-tuple 계약과 트리 형태,
  (2) 조립된 트리를 실제 build_document_manifest -> build_figure_candidates에 넣어
      image 후보가 나오는지(프로덕션 하류 경로 그대로),
  (3) box_2d -> ODL bbox 좌표 환산 정확성,
  (4) 페이지 호출이 계속 실패하면 재시도 후 전체 예외.
"""

from __future__ import annotations

import asyncio
import importlib
import json
import os
import re
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import AsyncMock, patch

import fitz

from services import gemini_parser
from services.gemini_parser import (
    GeminiParserError,
    _box2d_to_odl_bbox,
    run_convert_gemini,
)
from services.document_manifest import build_document_manifest
from services.figure_candidates import build_figure_candidates
from services.llm.gemini_client import _apply_media_resolution
from services.models import MODEL_LUNA, MODEL_VISUAL

PAGE_WIDTH = 612.0
PAGE_HEIGHT = 792.0


def _make_pdf(path: Path, pages: int = 2) -> None:
    """빈 letter 크기 페이지 PDF를 생성한다(래스터 이미지 블록 없음)."""
    doc = fitz.open()
    for _ in range(pages):
        doc.new_page(width=PAGE_WIDTH, height=PAGE_HEIGHT)
    doc.save(str(path))
    doc.close()


# 큰 figure 이미지(비-tiny, 비-strip) + figure 캡션 + 본문 요소를 담은 canned 페이지 응답.
_CANNED_PAGE = {
    "markdown": (
        "# Test Heading\n\n"
        "Some body paragraph text.\n\n"
        "![Figure 1](placeholder)\n\n"
        "Figure 1: A representative test figure."
    ),
    "elements": [
        {"type": "heading", "box_2d": [40, 80, 90, 900], "text": "Test Heading"},
        {"type": "paragraph", "box_2d": [110, 80, 140, 900], "text": "Some body paragraph text."},
        {"type": "image", "box_2d": [150, 120, 620, 900], "text": ""},
        {"type": "caption", "box_2d": [640, 120, 700, 900], "text": "Figure 1: A representative test figure."},
    ],
}


def _fake_call(**token_overrides) -> AsyncMock:
    payload = {
        "text": json.dumps(_CANNED_PAGE),
        "model": "gemini-3.5-flash",
        "tokens_in": token_overrides.get("tokens_in", 100),
        "tokens_out": token_overrides.get("tokens_out", 50),
        "tokens_thought": token_overrides.get("tokens_thought", 10),
        "interaction_id": None,
    }
    return AsyncMock(return_value=payload)


class Box2dConversionTests(unittest.TestCase):
    def test_known_box(self):
        # ymin=100, xmin=200, ymax=300, xmax=400 on a 612x792 page.
        bbox = _box2d_to_odl_bbox([100, 200, 300, 400], PAGE_WIDTH, PAGE_HEIGHT)
        self.assertIsNotNone(bbox)
        assert bbox is not None
        x_left, y_bottom, x_right, y_top = bbox
        self.assertAlmostEqual(x_left, 200 / 1000 * PAGE_WIDTH, places=4)     # 122.4
        self.assertAlmostEqual(x_right, 400 / 1000 * PAGE_WIDTH, places=4)    # 244.8
        self.assertAlmostEqual(y_bottom, (1 - 300 / 1000) * PAGE_HEIGHT, 4)   # 554.4
        self.assertAlmostEqual(y_top, (1 - 100 / 1000) * PAGE_HEIGHT, 4)      # 712.8
        # ODL 규약: y_bottom < y_top, 좌하단 원점.
        self.assertLess(y_bottom, y_top)

    def test_clamps_and_orders(self):
        # 범위 초과 + 뒤집힌 좌표도 클램프/정렬된다.
        bbox = _box2d_to_odl_bbox([1200, -50, 300, 400], PAGE_WIDTH, PAGE_HEIGHT)
        assert bbox is not None
        x_left, y_bottom, x_right, y_top = bbox
        self.assertGreaterEqual(x_left, 0.0)
        self.assertLessEqual(y_top, PAGE_HEIGHT)
        self.assertLess(y_bottom, y_top)
        self.assertLess(x_left, x_right)

    def test_invalid_box_returns_none(self):
        self.assertIsNone(_box2d_to_odl_bbox([1, 2, 3], PAGE_WIDTH, PAGE_HEIGHT))
        self.assertIsNone(_box2d_to_odl_bbox(None, PAGE_WIDTH, PAGE_HEIGHT))


class RunConvertGeminiTests(unittest.IsolatedAsyncioTestCase):
    async def test_three_tuple_and_tree_shape(self):
        with TemporaryDirectory() as tmp:
            tmpdir = Path(tmp)
            pdf_path = tmpdir / "sample.pdf"
            _make_pdf(pdf_path, pages=2)

            with patch.dict(os.environ, {"GEMINI_API_KEY": "test-key"}), patch(
                "services.gemini_parser.call_interaction", new=_fake_call()
            ):
                root, markdown_text, engine = await run_convert_gemini(
                    pdf_path, tmpdir, tmpdir / "figures"
                )

            self.assertEqual(engine, "gemini")
            self.assertIsInstance(root, dict)
            self.assertIn("kids", root)
            self.assertEqual(root["number of pages"], 2)
            self.assertIsInstance(markdown_text, str)
            self.assertIn("Test Heading", markdown_text)

            # image 노드는 content 없이 bbox만, 각 노드는 정수 id를 가진다.
            image_nodes = [k for k in root["kids"] if k["type"] == "image"]
            self.assertEqual(len(image_nodes), 2)  # 페이지당 1개
            for node in image_nodes:
                self.assertIn("bbox", node)
                self.assertNotIn("content", node)
                self.assertIsInstance(node["id"], int)

    async def test_tree_yields_image_candidates(self):
        with TemporaryDirectory() as tmp:
            tmpdir = Path(tmp)
            pdf_path = tmpdir / "sample.pdf"
            _make_pdf(pdf_path, pages=2)

            with patch.dict(os.environ, {"GEMINI_API_KEY": "test-key"}), patch(
                "services.gemini_parser.call_interaction", new=_fake_call()
            ):
                root, markdown_text, engine = await run_convert_gemini(
                    pdf_path, tmpdir, tmpdir / "figures"
                )

            # 프로덕션 하류 경로 그대로: 트리 -> 매니페스트 -> figure 후보.
            manifest = build_document_manifest(
                pdf_path=pdf_path,
                paper_dir=tmpdir,
                root=root,
                markdown_text=markdown_text,
                actual_engine=engine,
                requested_mode="gemini",
                extraction_pipeline_version="resolver_v1",
                parser_version="test",
                resolver_version="test",
                generate_page_rasters=False,
            )

            # 매니페스트가 image_blocks / figure 캡션을 실제로 담았는지.
            image_block_total = sum(len(p["image_blocks"]) for p in manifest["pages"])
            self.assertEqual(image_block_total, 2)
            figure_captions = [c for c in manifest["captions"] if c["kind"] == "figure"]
            self.assertGreaterEqual(len(figure_captions), 1)

            candidates = build_figure_candidates(manifest, pdf_path=pdf_path)
            self.assertGreaterEqual(len(candidates), 1)
            self.assertTrue(all("bbox" in c for c in candidates))

    async def test_usage_out_populated(self):
        with TemporaryDirectory() as tmp:
            tmpdir = Path(tmp)
            pdf_path = tmpdir / "sample.pdf"
            _make_pdf(pdf_path, pages=2)

            usage: dict = {}
            with patch.dict(os.environ, {"GEMINI_API_KEY": "test-key"}), patch(
                "services.gemini_parser.call_interaction", new=_fake_call()
            ):
                await run_convert_gemini(
                    pdf_path, tmpdir, tmpdir / "figures", usage_out=usage
                )

            self.assertEqual(usage["pages"], 2)
            self.assertEqual(usage["tokens_in"], 200)   # 100 x 2 페이지
            self.assertEqual(usage["tokens_out"], 100)  # 50 x 2 페이지
            self.assertGreater(usage["cost_usd"], 0.0)
            self.assertEqual(usage["engine"], "gemini")

    async def test_page_failure_raises(self):
        with TemporaryDirectory() as tmp:
            tmpdir = Path(tmp)
            pdf_path = tmpdir / "sample.pdf"
            _make_pdf(pdf_path, pages=2)

            failing = AsyncMock(side_effect=RuntimeError("boom"))
            with patch.dict(os.environ, {"GEMINI_API_KEY": "test-key"}), patch(
                "services.gemini_parser.call_interaction", new=failing
            ):
                with self.assertRaises(GeminiParserError):
                    await run_convert_gemini(pdf_path, tmpdir, tmpdir / "figures")

            # 페이지마다 최초 시도 + 재시도 1회 = 페이지당 2회 이상 호출.
            self.assertGreaterEqual(failing.await_count, 2)

    async def test_tuning_levers_forwarded_to_call(self):
        # 파서가 media_resolution / thinking_level(둘 다 env 기본값)을 call_interaction에
        # 그대로 전달하는지 확인한다.
        with TemporaryDirectory() as tmp:
            tmpdir = Path(tmp)
            pdf_path = tmpdir / "sample.pdf"
            _make_pdf(pdf_path, pages=1)

            fake = _fake_call()
            with patch.dict(os.environ, {"GEMINI_API_KEY": "test-key"}), patch(
                "services.gemini_parser.call_interaction", new=fake
            ):
                await run_convert_gemini(pdf_path, tmpdir, tmpdir / "figures")

            _, kwargs = fake.call_args
            self.assertEqual(
                kwargs.get("media_resolution"), gemini_parser._MEDIA_RESOLUTION or None
            )
            # provider 기본값(gemini)에서 registry의 pdf_parse effort는 "low"다 —
            # FLASH_HQ(3.7 Flash)가 minimal을 400으로 거부해서 2026-08-22에 올렸다
            # (test_gemini_keeps_current_model_and_minimal_effort와 동일한 회귀 방어).
            self.assertEqual(
                kwargs.get("thinking_level"), gemini_parser._THINKING_OVERRIDE or "low"
            )

    @unittest.skipUnless(gemini_parser._ELEMENTS_SLIM, "slim 스키마 전용")
    async def test_slim_schema_drops_paragraph_keeps_visual_and_heading(self):
        # 기본(slim) 모드: paragraph/formula 노드는 트리에서 탈락하고, 시각요소·heading은 유지.
        with TemporaryDirectory() as tmp:
            tmpdir = Path(tmp)
            pdf_path = tmpdir / "sample.pdf"
            _make_pdf(pdf_path, pages=1)

            with patch.dict(os.environ, {"GEMINI_API_KEY": "test-key"}), patch(
                "services.gemini_parser.call_interaction", new=_fake_call()
            ):
                root, _markdown, _engine = await run_convert_gemini(
                    pdf_path, tmpdir, tmpdir / "figures"
                )

            types = {node["type"] for node in root["kids"]}
            self.assertIn("image", types)
            self.assertIn("caption", types)
            self.assertIn("heading", types)
            self.assertNotIn("paragraph", types)

    async def test_full_text_uses_markdown_with_page_markers(self):
        # gemini full_text는 markdown(페이지 마커 포함)에서 나온다 — 본문 유실 방지 + audit 보전.
        with TemporaryDirectory() as tmp:
            tmpdir = Path(tmp)
            pdf_path = tmpdir / "sample.pdf"
            _make_pdf(pdf_path, pages=2)

            with patch.dict(os.environ, {"GEMINI_API_KEY": "test-key"}), patch(
                "services.gemini_parser.call_interaction", new=_fake_call()
            ):
                root, markdown_text, engine = await run_convert_gemini(
                    pdf_path, tmpdir, tmpdir / "figures"
                )

            self.assertIn("--- Page 1 ---", markdown_text)
            self.assertIn("--- Page 2 ---", markdown_text)
            self.assertIn("Some body paragraph text.", markdown_text)

            manifest = build_document_manifest(
                pdf_path=pdf_path,
                paper_dir=tmpdir,
                root=root,
                markdown_text=markdown_text,
                actual_engine=engine,
                requested_mode="gemini",
                extraction_pipeline_version="resolver_v1",
                parser_version="test",
                resolver_version="test",
                generate_page_rasters=False,
            )
            # gemini 분기: full_text == markdown_text (트리 조립본이 아니라 markdown).
            self.assertEqual(manifest["full_text"], markdown_text)
            self.assertIn("--- Page 1 ---", manifest["full_text"])
            self.assertIn("Some body paragraph text.", manifest["full_text"])


class FailFastAndPartialUsageTests(unittest.IsolatedAsyncioTestCase):
    """F5(시스템성 오류 fail-fast) + F2(부분 실패 시 성공 페이지 과금 보전) + F6(문서 재사용)."""

    async def test_systemic_error_fails_fast_without_fanning_out(self):
        # F5: 모든 페이지가 실패하는 시스템성 오류(bad key/쿼터)에서, 첫 웨이브만 시도하고
        # 나머지 페이지는 팬아웃하지 않아야 한다.
        #
        # 프로브 단위가 "페이지 1 단독" -> "첫 웨이브 전체"로 바뀌었다(happy path에서 페이지
        # 1을 혼자 기다리던 직렬 구간 제거). fail-fast 성질은 그대로다: 웨이브 전멸이면
        # 나머지 페이지는 시도조차 하지 않는다. 문서를 웨이브보다 크게 잡아야 이 성질이 보인다.
        pages = gemini_parser.PAGE_CONCURRENCY * 2 + 4
        with TemporaryDirectory() as tmp:
            tmpdir = Path(tmp)
            pdf_path = tmpdir / "sample.pdf"
            _make_pdf(pdf_path, pages=pages)

            failing = AsyncMock(side_effect=RuntimeError("bad api key"))
            with patch.dict(os.environ, {"GEMINI_API_KEY": "test-key"}), patch(
                "services.gemini_parser.call_interaction", new=failing
            ):
                with self.assertRaises(GeminiParserError):
                    await run_convert_gemini(pdf_path, tmpdir, tmpdir / "figures")

            # 첫 웨이브(PAGE_CONCURRENCY 페이지) × 시도 2회만. 나머지 페이지는 시도조차 안 함.
            self.assertEqual(failing.await_count, gemini_parser.PAGE_CONCURRENCY * 2)
            self.assertLess(failing.await_count, pages * 2)

    async def test_partial_failure_populates_usage_before_raising(self):
        # F2: 페이지 1 성공(과금됨) + 페이지 2,3 실패 → run_convert_gemini는 raise하되,
        # 이미 과금된 페이지 1의 토큰을 usage_out에 반영해야 한다(partial=True).
        with TemporaryDirectory() as tmp:
            tmpdir = Path(tmp)
            pdf_path = tmpdir / "sample.pdf"
            _make_pdf(pdf_path, pages=3)

            call_index = {"n": 0}

            async def _seq(*args, **kwargs):
                i = call_index["n"]
                call_index["n"] += 1
                if i == 0:  # 페이지 1(프로브)만 성공 — 프로브가 성공해야 나머지가 팬아웃된다.
                    return {
                        "text": json.dumps(_CANNED_PAGE),
                        "model": "gemini-3.5-flash",
                        "tokens_in": 100,
                        "tokens_out": 50,
                        "tokens_thought": 10,
                        "interaction_id": None,
                    }
                raise RuntimeError("rate limited on later page")

            usage: dict = {}
            with patch.dict(os.environ, {"GEMINI_API_KEY": "test-key"}), patch(
                "services.gemini_parser.call_interaction", new=_seq
            ):
                with self.assertRaises(GeminiParserError):
                    await run_convert_gemini(
                        pdf_path, tmpdir, tmpdir / "figures", usage_out=usage
                    )

            # 성공 페이지 1건의 지출이 원장에 남도록 usage_out이 채워진다.
            self.assertEqual(usage.get("engine"), "gemini")
            self.assertEqual(usage.get("pages"), 1)
            self.assertEqual(usage.get("tokens_in"), 100)
            self.assertEqual(usage.get("tokens_out"), 50)
            self.assertTrue(usage.get("partial"))
            self.assertGreater(usage.get("cost_usd", 0.0), 0.0)

    async def test_document_reused_not_reopened_per_page(self):
        # F6: 페이지마다 fitz.open(전체 재파싱)하지 않는다. open 횟수 = 메타데이터 1회 +
        # 풀 크기 min(PAGE_CONCURRENCY, pages)회 뿐이며, 페이지 수보다 적어야 한다.
        # 페이지 수를 동시성보다 크게 잡아야 "페이지당 재파싱 아님"이 실제로 검증된다.
        pages = gemini_parser.PAGE_CONCURRENCY * 2
        with TemporaryDirectory() as tmp:
            tmpdir = Path(tmp)
            pdf_path = tmpdir / "sample.pdf"
            _make_pdf(pdf_path, pages=pages)

            with patch.dict(os.environ, {"GEMINI_API_KEY": "test-key"}), patch(
                "services.gemini_parser.call_interaction", new=_fake_call()
            ), patch.object(
                gemini_parser.fitz, "open", wraps=fitz.open
            ) as open_spy:
                await run_convert_gemini(pdf_path, tmpdir, tmpdir / "figures")

            pool_size = min(gemini_parser.PAGE_CONCURRENCY, pages)
            self.assertEqual(open_spy.call_count, pool_size + 1)
            self.assertLess(open_spy.call_count, pages)  # 페이지당 1회 재파싱이 아님

    async def test_corrupt_pdf_uses_memory_stream_and_raises_gemini_parser_error(self):
        # F1: fitz.open이 거부하는 파일(비-PDF 바이트)은 raw fitz 예외가 아니라 GeminiParserError로
        # 나와야 폴백(ensure_visual_artifacts의 except OdlParserError 체인)이 동작한다.
        with TemporaryDirectory() as tmp:
            tmpdir = Path(tmp)
            bad_path = tmpdir / "corrupt.pdf"
            bad_path.write_bytes(b"%PDF-1.4 this is not a real pdf \x00\x01\x02")

            with (
                patch.dict(os.environ, {"GEMINI_API_KEY": "test-key"}),
                patch.object(gemini_parser.fitz, "open", wraps=fitz.open) as open_spy,
            ):
                with self.assertRaises(GeminiParserError):
                    await run_convert_gemini(bad_path, tmpdir, tmpdir / "figures")

            open_spy.assert_called_once_with(stream=bad_path.read_bytes(), filetype="pdf")


class MediaResolutionInjectionTests(unittest.TestCase):
    def test_injects_resolution_into_image_parts_without_mutating(self):
        parts = [
            {"type": "image", "data": "b64", "mime_type": "image/png"},
            {"type": "text", "text": "hi"},
        ]
        out = _apply_media_resolution(parts, "low")
        self.assertEqual(out[0]["resolution"], "low")
        self.assertNotIn("resolution", out[1])
        # 원본 파트는 변형되지 않는다.
        self.assertNotIn("resolution", parts[0])

    def test_noop_when_no_media_resolution(self):
        parts = [{"type": "image", "data": "x"}]
        self.assertIs(_apply_media_resolution(parts, None), parts)

    def test_noop_when_no_image_part(self):
        parts = [{"type": "text", "text": "hi"}]
        self.assertIs(_apply_media_resolution(parts, "low"), parts)


if __name__ == "__main__":
    unittest.main()


class PartialFailureToleranceTests(unittest.IsolatedAsyncioTestCase):
    """소수 페이지 실패를 문서 전체 폐기가 아니라 보충으로 처리한다.

    실측 로그에서 9페이지 중 1페이지가 저작권 필터 400에 걸려 이미 성공(=과금)한
    8페이지가 통째로 버려지고 ODL이 문서를 처음부터 다시 파싱했다.
    """

    @staticmethod
    def _make_distinct_pdf(path: Path, pages: int) -> dict[int, int]:
        """페이지마다 다른 양의 텍스트를 넣어 렌더 결과가 페이지별로 구분되게 한다.

        공용 _make_pdf는 빈 페이지를 만들어 전 페이지 PNG가 동일해진다 — 그러면
        "특정 페이지만 실패" 시나리오를 표현할 수 없다.
        반환: {렌더된 PNG base64 길이 -> 페이지 번호}는 호출 시점에만 알 수 있으므로
        여기서는 PDF만 만들고, 페이지 구분은 _seq_call이 등장 순서로 학습한다.
        """
        doc = fitz.open()
        for i in range(pages):
            page = doc.new_page(width=PAGE_WIDTH, height=PAGE_HEIGHT)
            # 페이지마다 줄 수를 다르게 해 래스터 바이트 길이가 확실히 달라지게 한다.
            for line in range(i + 1):
                page.insert_text((72, 100 + line * 14), f"page {i + 1} line {line} lorem ipsum")
        doc.save(str(path))
        doc.close()
        return {}

    def _seq_call(self, fail_pages: set[int]):
        """페이지를 렌더된 PNG 내용으로 구분해, 지정한 페이지만 계속 실패시킨다.

        base64 자체를 키로 쓴다(길이만 쓰면 서로 다른 페이지가 우연히 같은 길이일 수 있다).
        페이지 번호는 '처음 등장한 순서'가 아니라 PDF 페이지 순서를 알아야 하므로,
        호출부가 미리 렌더해 만든 매핑을 쓴다.
        """
        seen: dict[str, int] = {}
        order: list[str] = []

        async def _call(prompt, **kwargs):
            b64 = ""
            for part in prompt:
                if isinstance(part, dict) and part.get("type") == "image":
                    b64 = part.get("data", "")
            if b64 not in seen:
                order.append(b64)
                seen[b64] = self._page_map.get(b64, -1)
            idx = seen[b64]
            if idx in fail_pages:
                raise RuntimeError(f"blocked page {idx}")
            return {
                "text": json.dumps(_CANNED_PAGE),
                "model": "gemini-3.6-flash",
                "tokens_in": 100, "tokens_out": 50, "tokens_thought": 0,
                "interaction_id": None,
            }

        return _call

    def _build_page_map(self, pdf_path: Path, pages: int) -> None:
        """프로덕션과 동일한 방식으로 각 페이지를 렌더해 base64 -> 페이지번호 표를 만든다."""
        import base64 as _b64

        from services.gemini_parser import RENDER_DPI

        doc = fitz.open(str(pdf_path))
        try:
            self._page_map = {}
            for i in range(pages):
                matrix = fitz.Matrix(RENDER_DPI / 72.0, RENDER_DPI / 72.0)
                pix = doc[i].get_pixmap(matrix=matrix, alpha=False)
                self._page_map[_b64.b64encode(pix.tobytes("png")).decode("ascii")] = i + 1
        finally:
            doc.close()
        self.assertEqual(len(self._page_map), pages, "페이지별 렌더 결과가 구분되지 않는다")

    async def test_single_page_failure_is_filled_not_fatal(self):
        pages = 10
        with TemporaryDirectory() as tmp:
            tmpdir = Path(tmp)
            pdf_path = tmpdir / "sample.pdf"
            self._make_distinct_pdf(pdf_path, pages)
            self._build_page_map(pdf_path, pages)

            usage: dict = {}
            with patch.dict(os.environ, {"GEMINI_API_KEY": "test-key"}), patch(
                "services.gemini_parser.call_interaction", new=self._seq_call({4})
            ):
                root, markdown, engine = await run_convert_gemini(
                    pdf_path, tmpdir, tmpdir / "figures", usage_out=usage
                )

            self.assertEqual(engine, "gemini")
            # 실패 페이지가 기록돼 하류가 aggressive 재시도로 덮을 수 있어야 한다.
            self.assertEqual(root["parser_failed_pages"], [4])
            self.assertTrue(usage["partial"])
            self.assertEqual(usage["pages"], pages - 1)  # 과금은 성공분만

            # 본문에 구멍이 없어야 한다 — 모든 페이지 마커가 정확한 번호로 존재.
            for n in range(1, pages + 1):
                self.assertIn(f"--- Page {n} ---", markdown)
            # 실패 페이지는 PyMuPDF 축자 텍스트로 메워진다.
            self.assertIn("Page 4", markdown)

    async def test_page_markers_keep_real_numbers_when_a_page_fails(self):
        """실패 페이지가 있어도 마커 번호가 밀리지 않는다(enumerate 재번호 회귀 방지)."""
        with TemporaryDirectory() as tmp:
            tmpdir = Path(tmp)
            pdf_path = tmpdir / "sample.pdf"
            self._make_distinct_pdf(pdf_path, 10)
            self._build_page_map(pdf_path, 10)

            with patch.dict(os.environ, {"GEMINI_API_KEY": "test-key"}), patch(
                "services.gemini_parser.call_interaction", new=self._seq_call({2})
            ):
                _, markdown, _ = await run_convert_gemini(pdf_path, tmpdir, tmpdir / "figures")

            markers = re.findall(r"--- Page (\d+) ---", markdown)
            self.assertEqual([int(m) for m in markers], list(range(1, 11)))

    async def test_too_many_failures_still_falls_back(self):
        """임계값(20%, 최소 1)을 넘으면 예전처럼 raise해 엔진 폴백을 태운다."""
        with TemporaryDirectory() as tmp:
            tmpdir = Path(tmp)
            pdf_path = tmpdir / "sample.pdf"
            self._make_distinct_pdf(pdf_path, 10)
            self._build_page_map(pdf_path, 10)

            with patch.dict(os.environ, {"GEMINI_API_KEY": "test-key"}), patch(
                "services.gemini_parser.call_interaction", new=self._seq_call({2, 3, 4})
            ):
                with self.assertRaises(GeminiParserError):
                    await run_convert_gemini(pdf_path, tmpdir, tmpdir / "figures")

    def test_partial_failure_budget_scales_with_length(self):
        from services.gemini_parser import _partial_failure_budget

        self.assertEqual(_partial_failure_budget(1), 0)   # 1페이지 전멸은 항상 폴백
        self.assertEqual(_partial_failure_budget(3), 1)
        self.assertEqual(_partial_failure_budget(9), 1)
        self.assertEqual(_partial_failure_budget(20), 4)
        self.assertEqual(_partial_failure_budget(30), 6)


class TestParserProviderRouting(unittest.TestCase):
    """페이지 호출이 provider에 따라 올바른 모델·effort로 나가는지."""

    def _run(self, provider: str, usage_out: dict | None = None) -> dict:
        """1페이지 PDF를 파싱하고 call_interaction에 실제로 넘어간 kwargs를 돌려준다."""
        page_json = json.dumps({
            "markdown": "# T",
            "elements": [{"type": "image", "box_2d": [10, 10, 200, 200], "text": ""}],
        })
        captured: dict = {}

        async def _fake_call(prompt, **kwargs):
            captured.update(kwargs)
            return {"text": page_json, "tokens_in": 1, "tokens_out": 1, "model": kwargs["model"]}

        with TemporaryDirectory() as tmp:
            pdf = Path(tmp) / "one.pdf"
            doc = fitz.open()
            doc.new_page()
            doc.save(str(pdf))
            doc.close()
            with patch.object(gemini_parser, "call_interaction", new=AsyncMock(side_effect=_fake_call)):
                asyncio.run(run_convert_gemini(
                    pdf, Path(tmp), Path(tmp), provider=provider, usage_out=usage_out
                ))
        return captured

    def test_gemini_keeps_current_model_and_minimal_effort(self):
        """회귀 방어: Gemini는 현행과 동일해야 한다.

        effort는 minimal이 아니라 low다 — FLASH_HQ(3.7 Flash)가 minimal을 400으로
        거부해서 model_registry.py의 pdf_parse role을 2026-08-22에 low로 올렸다.
        """
        kwargs = self._run("gemini")
        self.assertEqual(kwargs["model"], MODEL_VISUAL)
        self.assertEqual(kwargs["thinking_level"], "low")

    def test_openai_uses_luna_and_low_effort(self):
        """minimal을 그대로 보내면 openai_client가 reasoning.effort=minimal로 전달해
        BadRequestError가 난다(openai_client.py:130-131). low여야 한다."""
        kwargs = self._run("openai")
        self.assertEqual(kwargs["model"], MODEL_LUNA)
        self.assertEqual(kwargs["thinking_level"], "low")

    def test_usage_out_model_label_matches_provider(self):
        """usage_out["model"]이 실제로 호출한 모델과 일치해야 한다(회귀 방어: gemini).

        OpenAI로 판독해도 원장에 gemini-3.6-flash로 남으면 Task 4의 provider별
        모델/비용 기록이 스스로를 반박한다."""
        gemini_usage: dict = {}
        self._run("gemini", usage_out=gemini_usage)
        self.assertEqual(gemini_usage["model"], MODEL_VISUAL)

        openai_usage: dict = {}
        self._run("openai", usage_out=openai_usage)
        self.assertEqual(openai_usage["model"], MODEL_LUNA)

    def test_env_thinking_override_still_wins(self):
        """SASOO_GEMINI_PARSER_THINKING 레버는 베이스라인 재현 절차가 의존한다."""
        # 복원 reload는 with 블록 밖(env가 원상복구된 뒤)에서 해야 한다. patch.dict 안에서
        # reload하면 THINKING=high가 여전히 걸려 있어 모듈이 override 상태로 계속 오염되고,
        # unittest는 테스트 메서드를 알파벳 순으로 실행하므로 이 테스트가 먼저 돌면
        # 이후의 다른 테스트(test_gemini_..., test_openai_...)가 그 오염을 물려받는다.
        try:
            with patch.dict(os.environ, {"SASOO_GEMINI_PARSER_THINKING": "high"}):
                importlib.reload(gemini_parser)
                kwargs = self._run("openai")
                self.assertEqual(kwargs["thinking_level"], "high")
        finally:
            importlib.reload(gemini_parser)
