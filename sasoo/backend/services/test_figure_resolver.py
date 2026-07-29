from __future__ import annotations

import base64
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from PIL import Image

from services import figure_resolver
from services.models import MODEL_FLASH_HQ


def _make_png(path: Path, size: tuple[int, int] = (40, 20)) -> bytes:
    path.parent.mkdir(parents=True, exist_ok=True)
    image = Image.new("RGB", size, color="white")
    image.save(path, "PNG")
    return path.read_bytes()


class MaybeSelectCandidateCallInteractionTests(unittest.IsolatedAsyncioTestCase):
    async def test_calls_call_interaction_with_image_dict_and_model_contract(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            paper_dir = Path(tmp_dir)
            raster_rel = "pages/page_1.png"
            image_bytes = _make_png(paper_dir / raster_rel)

            group = [
                {"id": "cand:1", "bbox": [10.0, 10.0, 50.0, 50.0], "source_kind": "pymupdf_image"},
                {"id": "cand:2", "bbox": [60.0, 10.0, 120.0, 60.0], "source_kind": "pymupdf_image"},
            ]
            page = {"page_size": {"width": 300.0, "height": 400.0}, "raster_path": raster_rel}

            fake_call = AsyncMock(
                return_value={
                    "text": '{"selected_candidate_id": "cand:2", "confidence": 0.1}',
                    "model": MODEL_FLASH_HQ,
                    "tokens_in": 1,
                    "tokens_out": 1,
                }
            )

            with patch.dict(os.environ, {"GEMINI_API_KEY": "test-key"}), \
                 patch("services.figure_resolver.call_interaction", new=fake_call):
                chosen, delta, model_used = await figure_resolver._maybe_select_candidate(
                    group, page, {}, figure_resolver._RasterCache(paper_dir), "resolver-v1",
                )

            fake_call.assert_awaited_once()
            args, kwargs = fake_call.call_args
            contents = args[0]
            self.assertEqual(contents[0]["type"], "image")
            self.assertEqual(contents[0]["mime_type"], "image/png")
            self.assertEqual(base64.b64decode(contents[0]["data"]), image_bytes)
            self.assertEqual(contents[1]["type"], "text")
            self.assertEqual(kwargs["model"], MODEL_FLASH_HQ)
            self.assertEqual(kwargs["thinking_level"], "minimal")
            self.assertIs(kwargs["store"], False)

            self.assertEqual(chosen["id"], "cand:2")
            self.assertEqual(model_used, MODEL_FLASH_HQ)

    async def test_call_interaction_exception_falls_back_to_heuristic(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            paper_dir = Path(tmp_dir)
            raster_rel = "pages/page_1.png"
            _make_png(paper_dir / raster_rel)

            group = [
                {"id": "cand:1", "bbox": [10.0, 10.0, 50.0, 50.0], "source_kind": "pymupdf_image"},
                {"id": "cand:2", "bbox": [60.0, 10.0, 120.0, 60.0], "source_kind": "pymupdf_image"},
            ]
            page = {"page_size": {"width": 300.0, "height": 400.0}, "raster_path": raster_rel}

            fake_call = AsyncMock(side_effect=RuntimeError("boom"))

            with patch.dict(os.environ, {"GEMINI_API_KEY": "test-key"}), \
                 patch("services.figure_resolver.call_interaction", new=fake_call):
                chosen, delta, model_used = await figure_resolver._maybe_select_candidate(
                    group, page, {}, figure_resolver._RasterCache(paper_dir), "resolver-v1",
                )

            self.assertEqual(delta, 0.0)
            self.assertEqual(model_used, "heuristic")

    async def test_no_api_key_skips_call_interaction(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            paper_dir = Path(tmp_dir)
            raster_rel = "pages/page_1.png"
            _make_png(paper_dir / raster_rel)

            group = [
                {"id": "cand:1", "bbox": [10.0, 10.0, 50.0, 50.0], "source_kind": "pymupdf_image"},
                {"id": "cand:2", "bbox": [60.0, 10.0, 120.0, 60.0], "source_kind": "pymupdf_image"},
            ]
            page = {"page_size": {"width": 300.0, "height": 400.0}, "raster_path": raster_rel}

            fake_call = AsyncMock(side_effect=AssertionError("call_interaction should not run"))

            with patch.dict(os.environ, {}, clear=False):
                os.environ.pop("GEMINI_API_KEY", None)
                with patch("services.figure_resolver.call_interaction", new=fake_call):
                    chosen, delta, model_used = await figure_resolver._maybe_select_candidate(
                        group, page, {}, figure_resolver._RasterCache(paper_dir), "resolver-v1",
                    )

            fake_call.assert_not_awaited()
            self.assertEqual(model_used, "heuristic")


class MaybeRerankCaptionCallInteractionTests(unittest.IsolatedAsyncioTestCase):
    async def test_calls_call_interaction_with_image_dict_and_model_contract(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            paper_dir = Path(tmp_dir)
            raster_rel = "pages/page_1.png"
            image_bytes = _make_png(paper_dir / raster_rel)

            candidate = {
                "best_caption_id": "cap:1",
                "bbox": [1.0, 2.0, 3.0, 4.0],
                "linked_caption_ids": ["cap:1", "cap:2"],
                "needs_vlm_rerank": True,
            }
            captions_by_id = {
                "cap:1": {"id": "cap:1", "text": "Figure 1 caption", "bbox": [0.0, 0.0, 10.0, 10.0]},
                "cap:2": {"id": "cap:2", "text": "Figure 1 duplicate caption", "bbox": [0.0, 0.0, 10.0, 10.0]},
            }
            page = {"raster_path": raster_rel}

            fake_call = AsyncMock(
                return_value={
                    "text": '{"selected_caption_id": "cap:2", "confidence": 0.12}',
                    "model": MODEL_FLASH_HQ,
                    "tokens_in": 1,
                    "tokens_out": 1,
                }
            )

            with patch.dict(os.environ, {"GEMINI_API_KEY": "test-key"}), \
                 patch("services.figure_resolver.call_interaction", new=fake_call):
                selected, delta, model_used = await figure_resolver._maybe_rerank_caption(
                    candidate, page, captions_by_id, figure_resolver._RasterCache(paper_dir), "resolver-v1",
                )

            fake_call.assert_awaited_once()
            args, kwargs = fake_call.call_args
            contents = args[0]
            self.assertEqual(contents[0]["type"], "image")
            self.assertEqual(contents[0]["mime_type"], "image/png")
            self.assertEqual(base64.b64decode(contents[0]["data"]), image_bytes)
            self.assertEqual(contents[1]["type"], "text")
            self.assertEqual(kwargs["model"], MODEL_FLASH_HQ)
            self.assertEqual(kwargs["thinking_level"], "minimal")
            self.assertIs(kwargs["store"], False)

            self.assertEqual(selected, "cap:2")
            self.assertAlmostEqual(delta, 0.12)
            self.assertEqual(model_used, MODEL_FLASH_HQ)


if __name__ == "__main__":
    unittest.main()


class ResolveConcurrencyAndOrderingTests(unittest.IsolatedAsyncioTestCase):
    """resolve_figure_candidates 병렬화의 두 계약을 고정한다.

    (1) 그룹별 VLM 판정이 실제로 동시에 나간다(순차 루프였다면 최대 동시 1).
    (2) 그림 번호·파일명·출력 순서는 후보 그룹 원래 순서를 그대로 따른다 —
        병렬화가 순서를 흔들면 같은 논문을 다시 분석할 때 그림 번호가 바뀐다.
    """

    def _manifest(self, paper_dir: Path, pages: int):
        import fitz

        pdf_path = paper_dir / "sample.pdf"
        doc = fitz.open()
        for _ in range(pages):
            doc.new_page(width=300, height=400)
        doc.save(str(pdf_path))
        doc.close()

        manifest_pages = []
        captions = []
        candidates = []
        for page_number in range(1, pages + 1):
            raster_rel = f".page_rasters/page_{page_number}.png"
            _make_png(paper_dir / raster_rel, size=(300, 400))
            manifest_pages.append(
                {
                    "page_number": page_number,
                    "page_size": {"width": 300.0, "height": 400.0},
                    "raster_path": raster_rel,
                }
            )
            caption_id = f"cap:{page_number}"
            captions.append(
                {
                    "id": caption_id,
                    "text": f"Figure {page_number}: sample caption",
                    "bbox": [20.0, 20.0, 280.0, 40.0],
                    "linked_content_id": None,
                }
            )
            # 그룹당 후보 2개 -> _needs_candidate_recheck가 True -> VLM 판정이 걸린다.
            for n in range(2):
                candidates.append(
                    {
                        "id": f"figcand:p{page_number}:n{n}",
                        "page_number": page_number,
                        "bbox": [30.0 + n, 60.0, 270.0, 340.0],
                        "source_kind": "pymupdf_image",
                        "linked_caption_ids": [caption_id],
                        "best_caption_id": caption_id,
                        "needs_vlm_rerank": False,
                    }
                )
        return pdf_path, {
            "engine": "gemini",
            "pages": manifest_pages,
            "captions": captions,
            "figure_candidates": candidates,
        }

    async def test_vlm_decisions_run_concurrently_and_order_is_preserved(self) -> None:
        import asyncio

        pages = 6
        inflight = {"now": 0, "max": 0}

        async def fake_call(contents, **kwargs):
            inflight["now"] += 1
            inflight["max"] = max(inflight["max"], inflight["now"])
            try:
                await asyncio.sleep(0.02)
            finally:
                inflight["now"] -= 1
            return {
                "text": '{"selected_candidate_id": "none", "confidence": 0.05}',
                "model": MODEL_FLASH_HQ,
                "tokens_in": 1,
                "tokens_out": 1,
            }

        with tempfile.TemporaryDirectory() as tmp_dir:
            paper_dir = Path(tmp_dir)
            pdf_path, manifest = self._manifest(paper_dir, pages)

            with patch.dict(os.environ, {"GEMINI_API_KEY": "test-key"}), \
                 patch("services.figure_resolver.call_interaction", new=fake_call), \
                 patch("services.figure_resolver._maybe_detect_subfigures", new=AsyncMock(return_value=[])):
                result = await figure_resolver.resolve_figure_candidates(
                    manifest,
                    paper_dir=paper_dir,
                    pdf_path=pdf_path,
                    resolver_version="resolver-v1",
                )

            self.assertGreater(inflight["max"], 1, "VLM 판정이 여전히 순차로 나가고 있다")

            figures = result["figures"]
            self.assertEqual(len(figures), pages)
            # 출력 순서 = 후보 그룹 순서(페이지 오름차순)
            self.assertEqual([f["page_number"] for f in figures], list(range(1, pages + 1)))
            # 캡션에서 뽑은 그림 번호가 페이지 순서대로 부여된다
            self.assertEqual(
                [f["figure_num"] for f in figures],
                [f"Fig. {n}" for n in range(1, pages + 1)],
            )
            # 크롭 파일이 실제로 그림 번호대로 쓰였다
            for figure in figures:
                self.assertTrue((paper_dir / figure["file_path"]).exists())

    async def test_page_raster_read_once_per_page(self) -> None:
        """같은 페이지에 VLM 호출이 여러 번 걸려도 래스터는 페이지당 1회만 읽는다."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            paper_dir = Path(tmp_dir)
            raster_rel = "pages/page_1.png"
            _make_png(paper_dir / raster_rel)
            page = {"page_number": 1, "page_size": {"width": 300.0, "height": 400.0},
                    "raster_path": raster_rel}

            cache = figure_resolver._RasterCache(paper_dir)
            first = cache.get(page)
            (paper_dir / raster_rel).unlink()  # 파일을 지워도 캐시가 살아 있어야 한다
            second = cache.get(page)

            self.assertIsNotNone(first)
            self.assertEqual(first, second)


class CaptionlessFigureSuppressionTests(unittest.IsolatedAsyncioTestCase):
    """캡션에 연결되지 않은 후보를 언제 그림으로 인정할지.

    로고·아이콘·수식 이미지 같은 것들이 각각 그림으로 승격돼 목록을 부풀렸다
    (실측: 캡션 8개인 문서에서 그림 16개, 이름이 "p9_fig7" 꼴). 다만 파서가 캡션을
    아예 못 잡은 문서에서는 진짜 그림도 전부 캡션이 없으므로 무조건 버리면 안 된다.
    """

    @staticmethod
    def _manifest(with_caption: bool):
        page = {
            "page_number": 1,
            "page_size": {"width": 612.0, "height": 792.0},
            "raster_path": None,
        }
        captions = []
        candidates = [
            {   # 캡션에 연결되지 않은 후보 — 로고/장식 같은 것
                "id": "figcand:p1:n0",
                "page_number": 1,
                "bbox": [60.0, 400.0, 550.0, 700.0],
                "source_kind": "pymupdf_image",
                "linked_caption_ids": [],
                "best_caption_id": None,
                "needs_vlm_rerank": False,
            }
        ]
        if with_caption:
            captions.append({
                "id": "cap:p1:n0", "page_number": 1, "kind": "figure",
                "bbox": [72.0, 340.0, 540.0, 360.0],
                "text": "Figure 1: A real captioned figure.", "linked_content_id": None, "order": 0,
            })
            candidates.append({
                "id": "figcand:p1:n1",
                "page_number": 1,
                "bbox": [60.0, 60.0, 550.0, 330.0],
                "source_kind": "pymupdf_image",
                "linked_caption_ids": ["cap:p1:n0"],
                "best_caption_id": "cap:p1:n0",
                "needs_vlm_rerank": False,
            })
        return {"engine": "gemini", "pages": [page], "captions": captions,
                "figure_candidates": candidates}

    async def _resolve(self, manifest):
        import fitz
        with tempfile.TemporaryDirectory() as tmp:
            paper_dir = Path(tmp)
            pdf = paper_dir / "s.pdf"
            doc = fitz.open(); doc.new_page(width=612, height=792); doc.save(str(pdf)); doc.close()
            with patch("services.figure_resolver._maybe_detect_subfigures",
                       new=AsyncMock(return_value=[])):
                result = await figure_resolver.resolve_figure_candidates(
                    manifest, paper_dir=paper_dir, pdf_path=pdf, resolver_version="resolver-v1"
                )
        return result["figures"]

    async def test_captionless_candidate_is_dropped(self):
        figures = await self._resolve(self._manifest(with_caption=True))
        nums = [f["figure_num"] for f in figures]
        self.assertEqual(nums, ["Fig. 1"], f"캡션 없는 후보가 그림으로 남았다: {nums}")

    async def test_captionless_candidate_dropped_even_without_any_caption(self):
        """캡션이 하나도 없는 문서에서도 버린다 — 사용자 결정(2026-07-29).

        예전에는 "문서에 캡션이 있을 때만 억제"하는 안전장치가 있었으나, 캡션 서식
        정규화 이후 전 논문이 캡션을 충분히 잡아 그 분기가 한 번도 발동하지 않았다
        (12편 결과가 전부 동일). 대신 전멸 시 경고 로그를 남긴다.
        """
        with self.assertLogs("services.figure_resolver", level="WARNING") as captured:
            figures = await self._resolve(self._manifest(with_caption=False))
        self.assertEqual(figures, [])
        self.assertTrue(any("그림 0개" in line for line in captured.output),
                        "전멸했는데 진단용 경고가 없다")
