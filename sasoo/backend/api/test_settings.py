import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from api import settings


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


if __name__ == "__main__":
    unittest.main()
