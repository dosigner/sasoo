from __future__ import annotations

import base64
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from PIL import Image

from models.paper import Figure
from services.subfigure_detector import SubFigureDetector
from services.models import MODEL_FLASH_HQ


def _make_png(path: Path, size: tuple[int, int] = (40, 20)) -> bytes:
    image = Image.new("RGB", size, color="white")
    image.save(path, "PNG")
    return path.read_bytes()


class SubFigureDetectorCallInteractionTests(unittest.IsolatedAsyncioTestCase):
    async def test_detect_subfigures_calls_call_interaction_with_image_content_dict(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            image_path = Path(tmp_dir) / "fig1.png"
            image_bytes = _make_png(image_path)
            figure = Figure(
                figure_id="Fig. 1",
                page_number=1,
                bbox=(0.0, 0.0, 1.0, 1.0),
                image_path=image_path,
            )

            fake_call = AsyncMock(
                return_value={
                    "text": (
                        '{"has_subfigures": true, "layout": "horizontal", '
                        '"confidence": 0.9, "subfigures": '
                        '[{"label": "A", "bbox": [0.0, 0.0, 0.5, 1.0], "description": "left panel"}]}'
                    ),
                    "model": MODEL_FLASH_HQ,
                    "tokens_in": 10,
                    "tokens_out": 5,
                }
            )

            with patch("services.subfigure_detector.call_interaction", new=fake_call):
                detector = SubFigureDetector()
                result = await detector.detect_subfigures(figure)

            fake_call.assert_awaited_once()
            args, kwargs = fake_call.call_args
            contents = args[0]

            # 이미지 content dict + 텍스트 content dict 리스트
            self.assertIsInstance(contents, list)
            self.assertEqual(len(contents), 2)
            self.assertEqual(contents[0]["type"], "image")
            self.assertEqual(contents[0]["mime_type"], "image/png")
            self.assertEqual(
                base64.b64decode(contents[0]["data"]),
                image_bytes,
            )
            self.assertEqual(contents[1]["type"], "text")
            self.assertIn("sub-figures", contents[1]["text"])

            # 모델/thinking/store 계약
            self.assertEqual(kwargs["model"], MODEL_FLASH_HQ)
            self.assertEqual(kwargs["thinking_level"], "minimal")
            self.assertIs(kwargs["store"], False)
            self.assertIn("response_schema", kwargs)

            self.assertTrue(result.has_subfigures)
            self.assertEqual(result.layout, "horizontal")
            self.assertEqual(len(result.subfigures), 1)
            self.assertEqual(result.subfigures[0].label, "A")

    async def test_detect_subfigures_missing_image_skips_call_interaction(self) -> None:
        figure = Figure(
            figure_id="Fig. 2",
            page_number=1,
            bbox=(0.0, 0.0, 1.0, 1.0),
            image_path=Path("/nonexistent/path/fig2.png"),
        )
        fake_call = AsyncMock(side_effect=AssertionError("call_interaction should not run"))

        with patch("services.subfigure_detector.call_interaction", new=fake_call):
            detector = SubFigureDetector()
            result = await detector.detect_subfigures(figure)

        fake_call.assert_not_awaited()
        self.assertFalse(result.has_subfigures)
        self.assertEqual(result.raw_response, "Image file not found")

    async def test_detect_subfigures_call_interaction_error_falls_back_gracefully(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            image_path = Path(tmp_dir) / "fig3.png"
            _make_png(image_path)
            figure = Figure(
                figure_id="Fig. 3",
                page_number=1,
                bbox=(0.0, 0.0, 1.0, 1.0),
                image_path=image_path,
            )

            fake_call = AsyncMock(side_effect=RuntimeError("boom"))

            with patch("services.subfigure_detector.call_interaction", new=fake_call):
                detector = SubFigureDetector()
                result = await detector.detect_subfigures(figure)

            self.assertFalse(result.has_subfigures)
            self.assertIn("Error: boom", result.raw_response)


if __name__ == "__main__":
    unittest.main()
