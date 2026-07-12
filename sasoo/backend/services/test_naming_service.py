from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, patch

from services import naming_service


class GenerateFolderNameTests(unittest.IsolatedAsyncioTestCase):
    async def test_calls_call_interaction_with_expected_contract_and_returns_sanitized_text(self) -> None:
        fake_call = AsyncMock(
            return_value={
                "text": "2024_NatPhoton_MetasurfLens_Optics",
                "model": "gemini-3.1-flash-lite",
                "tokens_in": 42,
                "tokens_out": 8,
            }
        )

        with patch("services.naming_service.call_interaction", new=fake_call):
            result = await naming_service.generate_folder_name(
                title="Metasurface lens for broadband imaging",
                year=2024,
                journal="Nature Photonics",
                domain="optics",
                abstract="We demonstrate a metasurface lens...",
            )

        fake_call.assert_awaited_once()
        args, kwargs = fake_call.call_args
        prompt = args[0]
        self.assertIsInstance(prompt, str)
        self.assertIn("Metasurface lens for broadband imaging", prompt)

        self.assertEqual(kwargs["model"], "gemini-3.1-flash-lite")
        self.assertEqual(kwargs["thinking_level"], "minimal")
        self.assertIs(kwargs["store"], False)
        self.assertEqual(kwargs["system_instruction"], naming_service._NAMING_SYSTEM_INSTRUCTION)

        self.assertEqual(result, "2024_NatPhoton_MetasurfLens_Optics")

    async def test_call_interaction_error_falls_back_to_uuid_name(self) -> None:
        fake_call = AsyncMock(side_effect=RuntimeError("boom"))

        with patch("services.naming_service.call_interaction", new=fake_call):
            result = await naming_service.generate_folder_name(
                title="Some Paper Title", year=2023,
            )

        self.assertTrue(result.startswith("2023_Some_Paper_Title_"))


class GenerateFigureNamesTests(unittest.IsolatedAsyncioTestCase):
    async def test_calls_call_interaction_with_response_schema_and_returns_sanitized_names(self) -> None:
        captions_and_pages = [
            {"figure_num": "p2_img1", "caption": "SEM cross-section of the device", "page": 2},
            {"figure_num": "p3_img1", "caption": "Transmission spectrum measurement", "page": 3},
        ]
        fake_call = AsyncMock(
            return_value={
                "text": '["fig1_sem_cross_section", "fig2_transmission_spectrum"]',
                "model": "gemini-3.1-flash-lite",
                "tokens_in": 30,
                "tokens_out": 12,
            }
        )

        with patch("services.naming_service.call_interaction", new=fake_call):
            result = await naming_service.generate_figure_names(captions_and_pages)

        fake_call.assert_awaited_once()
        args, kwargs = fake_call.call_args
        prompt = args[0]
        self.assertIsInstance(prompt, str)
        self.assertIn("SEM cross-section of the device", prompt)

        self.assertEqual(kwargs["model"], "gemini-3.1-flash-lite")
        self.assertEqual(kwargs["thinking_level"], "minimal")
        self.assertIs(kwargs["store"], False)
        self.assertEqual(kwargs["system_instruction"], naming_service._NAMING_SYSTEM_INSTRUCTION)
        self.assertEqual(kwargs["response_schema"], naming_service._FIGURE_NAMES_RESPONSE_SCHEMA)
        self.assertNotIn("response_mime_type", kwargs)

        self.assertEqual(result, ["fig1_sem_cross_section", "fig2_transmission_spectrum"])

    async def test_empty_input_skips_call_interaction(self) -> None:
        fake_call = AsyncMock(side_effect=AssertionError("call_interaction should not run"))

        with patch("services.naming_service.call_interaction", new=fake_call):
            result = await naming_service.generate_figure_names([])

        fake_call.assert_not_awaited()
        self.assertEqual(result, [])

    async def test_count_mismatch_falls_back_to_original_figure_nums(self) -> None:
        captions_and_pages = [
            {"figure_num": "p2_img1", "caption": "SEM cross-section", "page": 2},
            {"figure_num": "p3_img1", "caption": "Transmission spectrum", "page": 3},
        ]
        fake_call = AsyncMock(
            return_value={"text": '["only_one_name"]', "model": "gemini-3.1-flash-lite"}
        )

        with patch("services.naming_service.call_interaction", new=fake_call):
            result = await naming_service.generate_figure_names(captions_and_pages)

        self.assertEqual(result, ["p2_img1", "p3_img1"])


class GeneratePaperbananaNameTests(unittest.IsolatedAsyncioTestCase):
    async def test_calls_call_interaction_with_expected_contract_and_returns_sanitized_text(self) -> None:
        fake_call = AsyncMock(
            return_value={
                "text": "optical_setup_illustration",
                "model": "gemini-3.1-flash-lite",
                "tokens_in": 20,
                "tokens_out": 6,
            }
        )

        with patch("services.naming_service.call_interaction", new=fake_call):
            result = await naming_service.generate_paperbanana_name(
                title="Optical Setup Diagram",
                description="A schematic of the optical bench.",
            )

        fake_call.assert_awaited_once()
        args, kwargs = fake_call.call_args
        prompt = args[0]
        self.assertIsInstance(prompt, str)
        self.assertIn("Optical Setup Diagram", prompt)

        self.assertEqual(kwargs["model"], "gemini-3.1-flash-lite")
        self.assertEqual(kwargs["thinking_level"], "minimal")
        self.assertIs(kwargs["store"], False)
        self.assertEqual(kwargs["system_instruction"], naming_service._NAMING_SYSTEM_INSTRUCTION)

        self.assertEqual(result, "optical_setup_illustration")

    async def test_call_interaction_error_falls_back_to_sanitized_title(self) -> None:
        fake_call = AsyncMock(side_effect=RuntimeError("boom"))

        with patch("services.naming_service.call_interaction", new=fake_call):
            result = await naming_service.generate_paperbanana_name(title="Optical Setup Diagram")

        self.assertEqual(result, "optical_setup_diagram")


if __name__ == "__main__":
    unittest.main()
