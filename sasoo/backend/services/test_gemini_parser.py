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

import json
import os
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
from services.llm.interactions_client import _apply_media_resolution

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
            self.assertEqual(
                kwargs.get("thinking_level"), gemini_parser._THINKING_LEVEL or None
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
