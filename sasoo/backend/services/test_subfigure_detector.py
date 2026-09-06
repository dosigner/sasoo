from __future__ import annotations

import base64
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from PIL import Image

from models.paper import Figure
from services.subfigure_detector import (
    MAX_SUBFIGURES,
    SubFigureDetector,
    _normalize_sub_label,
)
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
            # FLASH_HQ(3.7/3.8 Flash)는 minimal을 400으로 거부한다 — low로 상향
            # (model_registry.py의 subfigure role, 2026-08-22).
            self.assertEqual(kwargs["thinking_level"], "low")
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


class SubLabelValidationTests(unittest.TestCase):
    """서브피겨 라벨 검증 — 모델이 패널 라벨 대신 내용을 서술하면 분해를 받지 않는다.

    검증이 없던 시절 실측(paper 43): 부모 8개에 서브피겨 25개가 붙었고, 라벨이
    "ASD PR CURVES (LEFT)", "FIGURE 6", "TABLE 2" 같은 서술문이었다. 이것들이 그대로
    figure_num에 이어붙어 "Fig. 8ASD PR CURVES (LEFT)", "Fig. 7TABLE 2"가 갤러리에 남았다.
    """

    def test_accepts_conventional_panel_labels(self):
        for raw, expected in [
            ("A", "A"), ("a", "A"), ("(b)", "B"), ("c.", "C"),
            ("1", "1"), ("(2)", "2"), (" d ", "D"),
        ]:
            with self.subTest(raw=raw):
                self.assertEqual(_normalize_sub_label(raw), expected)

    def test_rejects_descriptive_text(self):
        # 실측에서 실제로 들어왔던 값들.
        for raw in [
            "ASD PR CURVES (LEFT)", "MSRA MAES", "SED1", "FIGURE 6", "TABLE 2",
            "", None, "left panel", "A-B",
        ]:
            with self.subTest(raw=raw):
                self.assertIsNone(_normalize_sub_label(raw))

    def _parse(self, subfigures):
        detector = SubFigureDetector()
        payload = {
            "has_subfigures": True, "layout": "grid", "confidence": 0.9,
            "subfigures": subfigures,
        }
        return detector._parse_response(json.dumps(payload), "Fig. 8")

    def test_all_invalid_labels_drops_the_whole_split(self):
        result = self._parse([
            {"label": "ASD PR CURVES (LEFT)", "bbox": [0, 0, 0.5, 0.5], "description": "x"},
            {"label": "MSRA MAES", "bbox": [0.5, 0, 1, 0.5], "description": "y"},
        ])
        self.assertFalse(result.has_subfigures)
        self.assertEqual(result.subfigures, [])

    def test_partially_valid_keeps_only_valid(self):
        result = self._parse([
            {"label": "A", "bbox": [0, 0, 0.5, 0.5], "description": "panel a"},
            {"label": "TABLE 2", "bbox": [0.5, 0, 1, 0.5], "description": "a table"},
            {"label": "(b)", "bbox": [0, 0.5, 0.5, 1], "description": "panel b"},
        ])
        self.assertTrue(result.has_subfigures)
        self.assertEqual([s.label for s in result.subfigures], ["A", "B"])

    def test_too_many_panels_is_treated_as_misdetection(self):
        many = [
            {"label": chr(ord("A") + i), "bbox": [0, 0, 0.1, 0.1], "description": ""}
            for i in range(MAX_SUBFIGURES + 1)
        ]
        result = self._parse(many)
        self.assertFalse(result.has_subfigures)
        self.assertEqual(result.subfigures, [])

    def test_valid_split_still_works(self):
        result = self._parse([
            {"label": "A", "bbox": [0, 0, 0.5, 0.5], "description": "p"},
            {"label": "B", "bbox": [0.5, 0, 1, 0.5], "description": "q"},
        ])
        self.assertTrue(result.has_subfigures)
        self.assertEqual([s.label for s in result.subfigures], ["A", "B"])
