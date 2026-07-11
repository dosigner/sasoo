import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from api import settings


class SettingsRouteTests(unittest.IsolatedAsyncioTestCase):
    """
    The settings API always speaks of a single "library_path" -- the path for
    the machine it is running on -- while storage keeps one per platform. These
    cover that translation, and the case that started it: a settings database
    carried from Windows to a Mac.
    """

    async def test_get_settings_reports_this_platforms_library_root(self) -> None:
        platform_root = "/tmp/sasoo-library"
        rows = [
            {"key": "library_path", "value": ""},
            {"key": "pdf_parser_mode", "value": "java"},
            {"key": "extraction_pipeline_version", "value": "resolver_v1"},
            {"key": "extraction_pipeline_force_fallback", "value": "false"},
        ]

        with (
            patch("api.settings._ensure_defaults", new=AsyncMock()) as ensure_defaults,
            patch("api.settings.fetch_all", new=AsyncMock(return_value=rows)),
            patch("api.settings._set_setting", new=AsyncMock()),
            patch("api.settings.get_library_root", return_value=Path(platform_root)),
        ):
            response = await settings.get_settings()

        ensure_defaults.assert_awaited_once()
        self.assertEqual(response.library_path, platform_root)

    async def test_windows_path_in_storage_is_not_reported_to_a_mac(self) -> None:
        """The stored Windows value must never reach the client as-is."""
        platform_root = "/Users/dongj/sasoo/library"
        rows = [
            {"key": "library_path", "value": r"C:\Users\dongj\Documents\sasoo\library"},
            {"key": "pdf_parser_mode", "value": "java"},
            {"key": "extraction_pipeline_version", "value": "resolver_v1"},
            {"key": "extraction_pipeline_force_fallback", "value": "false"},
        ]

        with (
            patch("api.settings._ensure_defaults", new=AsyncMock()),
            patch("api.settings.fetch_all", new=AsyncMock(return_value=rows)),
            patch("api.settings._set_setting", new=AsyncMock()),
            patch("api.settings.get_library_root", return_value=Path(platform_root)),
        ):
            response = await settings.get_settings()

        self.assertEqual(response.library_path, platform_root)
        self.assertNotIn("C:", response.library_path)

    async def test_ensure_library_path_seeds_the_platform_key(self) -> None:
        # Already resolved: on macOS /tmp is itself a symlink to /private/tmp,
        # and _ensure_library_path resolves before storing.
        resolved = Path("/tmp/sasoo-library").resolve(strict=False)
        db = AsyncMock()

        with (
            patch("api.settings.fetch_one", new=AsyncMock(return_value=None)),
            patch("api.settings.get_library_root", return_value=resolved),
            patch("api.settings.library_path_setting_key", return_value="library_path_darwin"),
            patch("pathlib.Path.mkdir"),
        ):
            await settings._ensure_library_path(db)

        db.execute.assert_awaited_once()
        sql, params = db.execute.await_args.args
        self.assertIn("INSERT", sql)
        self.assertEqual(params, ("library_path_darwin", str(resolved)))

    async def test_ensure_library_path_leaves_a_good_value_alone(self) -> None:
        resolved = Path("/tmp/sasoo-library").resolve(strict=False)
        db = AsyncMock()

        with (
            patch("api.settings.fetch_one", new=AsyncMock(return_value={"value": str(resolved)})),
            patch("api.settings.get_library_root", return_value=resolved),
            patch("api.settings.library_path_setting_key", return_value="library_path_darwin"),
        ):
            await settings._ensure_library_path(db)

        db.execute.assert_not_awaited()

    async def test_get_settings_includes_openai_fields_with_defaults(self) -> None:
        """openai_api_key/image_provider/image_quality must appear even when unset in storage."""
        platform_root = "/tmp/sasoo-library"
        rows = [
            {"key": "library_path", "value": ""},
            {"key": "pdf_parser_mode", "value": "java"},
            {"key": "extraction_pipeline_version", "value": "resolver_v1"},
            {"key": "extraction_pipeline_force_fallback", "value": "false"},
        ]

        with (
            patch("api.settings._ensure_defaults", new=AsyncMock()),
            patch("api.settings.fetch_all", new=AsyncMock(return_value=rows)),
            patch("api.settings._set_setting", new=AsyncMock()),
            patch("api.settings.get_library_root", return_value=Path(platform_root)),
        ):
            response = await settings.get_settings()

        self.assertEqual(response.openai_api_key, "")
        self.assertFalse(response.openai_key_unreadable)
        self.assertEqual(response.image_provider, "openai")
        self.assertEqual(response.image_quality, "high")


if __name__ == "__main__":
    unittest.main()
