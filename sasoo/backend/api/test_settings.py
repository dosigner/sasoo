import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from api import settings
from models.schemas import SettingsUpdate


class SettingsRouteTests(unittest.IsolatedAsyncioTestCase):
    async def test_get_settings_recovers_blank_library_path(self) -> None:
        normalized_path = "/tmp/sasoo-library"
        rows = [
            {"key": "library_path", "value": ""},
            {"key": "pdf_parser_mode", "value": "java"},
            {"key": "extraction_pipeline_version", "value": "resolver_v1"},
            {"key": "extraction_pipeline_force_fallback", "value": "false"},
        ]

        with patch("api.settings._ensure_defaults", new=AsyncMock()) as ensure_defaults:
            with patch("api.settings.fetch_all", new=AsyncMock(return_value=rows)):
                with patch("api.settings._set_setting", new=AsyncMock()) as set_setting:
                    with patch("api.settings.get_library_root", return_value=Path(normalized_path)):
                        response = await settings.get_settings()

        ensure_defaults.assert_awaited_once()
        set_setting.assert_any_await("library_path", normalized_path)
        self.assertEqual(response.library_path, normalized_path)

    async def test_new_researcher_settings_defaults(self) -> None:
        rows = [
            {"key": "library_path", "value": "/tmp/sasoo-library"},
            {"key": "pdf_parser_mode", "value": "java"},
            {"key": "extraction_pipeline_version", "value": "resolver_v1"},
            {"key": "extraction_pipeline_force_fallback", "value": "false"},
        ]

        with patch("api.settings._ensure_defaults", new=AsyncMock()):
            with patch("api.settings.fetch_all", new=AsyncMock(return_value=rows)):
                with patch("api.settings._set_setting", new=AsyncMock()):
                    response = await settings.get_settings()

        self.assertEqual(response.research_context, "")
        self.assertEqual(response.default_explanation_level, "masters")

    async def test_update_researcher_settings(self) -> None:
        store: dict[str, str] = {
            "library_path": "/tmp/sasoo-library",
            "pdf_parser_mode": "java",
            "extraction_pipeline_version": "resolver_v1",
            "extraction_pipeline_force_fallback": "false",
        }

        async def fake_set_setting(key: str, value: str) -> None:
            store[key] = value

        async def fake_fetch_all(*args, **kwargs):
            return [{"key": k, "value": v} for k, v in store.items()]

        with patch("api.settings._ensure_defaults", new=AsyncMock()):
            with patch("api.settings.fetch_all", new=AsyncMock(side_effect=fake_fetch_all)):
                with patch("api.settings._set_setting", new=AsyncMock(side_effect=fake_set_setting)):
                    update = SettingsUpdate(
                        research_context="페로브스카이트 태양전지 소자 물리",
                        default_explanation_level="phd",
                    )
                    response = await settings.update_settings(update)

        self.assertEqual(response.research_context, "페로브스카이트 태양전지 소자 물리")
        self.assertEqual(response.default_explanation_level, "phd")


if __name__ == "__main__":
    unittest.main()
