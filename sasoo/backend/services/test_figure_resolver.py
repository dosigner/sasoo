from __future__ import annotations

import base64
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from PIL import Image

from services import figure_resolver


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
                    "model": "gemini-3.5-flash",
                    "tokens_in": 1,
                    "tokens_out": 1,
                }
            )

            with patch.dict(os.environ, {"GEMINI_API_KEY": "test-key"}), \
                 patch("services.figure_resolver.call_interaction", new=fake_call):
                chosen, delta, model_used = await figure_resolver._maybe_select_candidate(
                    group, page, {}, paper_dir, "resolver-v1",
                )

            fake_call.assert_awaited_once()
            args, kwargs = fake_call.call_args
            contents = args[0]
            self.assertEqual(contents[0]["type"], "image")
            self.assertEqual(contents[0]["mime_type"], "image/png")
            self.assertEqual(base64.b64decode(contents[0]["data"]), image_bytes)
            self.assertEqual(contents[1]["type"], "text")
            self.assertEqual(kwargs["model"], "gemini-3.5-flash")
            self.assertEqual(kwargs["thinking_level"], "minimal")
            self.assertIs(kwargs["store"], False)

            self.assertEqual(chosen["id"], "cand:2")
            self.assertEqual(model_used, "gemini-3.5-flash")

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
                    group, page, {}, paper_dir, "resolver-v1",
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
                        group, page, {}, paper_dir, "resolver-v1",
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
                    "model": "gemini-3.5-flash",
                    "tokens_in": 1,
                    "tokens_out": 1,
                }
            )

            with patch.dict(os.environ, {"GEMINI_API_KEY": "test-key"}), \
                 patch("services.figure_resolver.call_interaction", new=fake_call):
                selected, delta, model_used = await figure_resolver._maybe_rerank_caption(
                    candidate, page, captions_by_id, paper_dir, "resolver-v1",
                )

            fake_call.assert_awaited_once()
            args, kwargs = fake_call.call_args
            contents = args[0]
            self.assertEqual(contents[0]["type"], "image")
            self.assertEqual(contents[0]["mime_type"], "image/png")
            self.assertEqual(base64.b64decode(contents[0]["data"]), image_bytes)
            self.assertEqual(contents[1]["type"], "text")
            self.assertEqual(kwargs["model"], "gemini-3.5-flash")
            self.assertEqual(kwargs["thinking_level"], "minimal")
            self.assertIs(kwargs["store"], False)

            self.assertEqual(selected, "cap:2")
            self.assertAlmostEqual(delta, 0.12)
            self.assertEqual(model_used, "gemini-3.5-flash")


if __name__ == "__main__":
    unittest.main()
