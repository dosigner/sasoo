import os
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from fastapi import HTTPException

from api import settings
from models.schemas import SettingsUpdate


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

    async def test_update_library_path_invalidates_cached_root(self) -> None:
        """
        get_library_root() is cached with a TTL; changing the path through the
        API must drop that cache so the very next read sees the new root.
        """
        update = SettingsUpdate(library_path="/tmp/sasoo-moved-library")

        with (
            patch("api.settings._set_setting", new=AsyncMock()),
            patch("api.settings.get_settings", new=AsyncMock(return_value=None)),
            patch("api.settings.invalidate_library_root_cache") as invalidate,
            patch("pathlib.Path.mkdir"),
        ):
            await settings.update_settings(update)

        invalidate.assert_called_once()

    async def test_ensure_library_path_invalidates_cache_after_write(self) -> None:
        resolved = Path("/tmp/sasoo-library").resolve(strict=False)
        db = AsyncMock()

        with (
            patch("api.settings.fetch_one", new=AsyncMock(return_value=None)),
            patch("api.settings.get_library_root", return_value=resolved),
            patch("api.settings.library_path_setting_key", return_value="library_path_darwin"),
            patch("api.settings.invalidate_library_root_cache") as invalidate,
            patch("pathlib.Path.mkdir"),
        ):
            await settings._ensure_library_path(db)

        invalidate.assert_called_once()

    async def test_ensure_library_path_refreshes_resolution_before_comparing(self) -> None:
        """
        _ensure_library_path "repairs" the stored value whenever it differs
        from get_library_root(). If resolution comes from a stale cache entry,
        a legitimate value written to the DB out-of-band gets overwritten with
        the cached one -- so the cache must be dropped BEFORE resolving.
        (Caught live: a direct sqlite edit was reverted by the next
        GET /api/settings.)
        """
        from unittest.mock import MagicMock

        resolved = Path("/tmp/sasoo-library").resolve(strict=False)
        db = AsyncMock()
        order = MagicMock()
        order.resolve.return_value = resolved

        with (
            patch(
                "api.settings.fetch_one",
                new=AsyncMock(return_value={"value": str(resolved)}),
            ),
            patch("api.settings.get_library_root", order.resolve),
            patch("api.settings.library_path_setting_key", return_value="library_path_darwin"),
            patch("api.settings.invalidate_library_root_cache", order.invalidate),
        ):
            await settings._ensure_library_path(db)

        called = [name for name, _args, _kwargs in order.mock_calls]
        self.assertIn("invalidate", called, "cache must be dropped before resolving")
        self.assertLess(
            called.index("invalidate"),
            called.index("resolve"),
            "invalidation must happen before get_library_root() resolves",
        )

    async def test_get_settings_includes_openai_fields_with_defaults(self) -> None:
        """openai_api_key/image_provider/image_quality must appear even when unset in storage."""
        platform_root = "/tmp/sasoo-library"
        rows = [
            {"key": "library_path", "value": ""},
            {"key": "pdf_parser_mode", "value": "java"},
            {"key": "extraction_pipeline_version", "value": "resolver_v1"},
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

    def test_image_settings_reject_invalid_values(self) -> None:
        """SettingsUpdate should reject invalid image_provider and image_quality values."""
        import pydantic
        from models.schemas import SettingsUpdate

        with self.assertRaises(pydantic.ValidationError):
            SettingsUpdate(image_provider="dall-e")
        with self.assertRaises(pydantic.ValidationError):
            SettingsUpdate(image_quality="ultra")
        # Valid values should pass
        SettingsUpdate(image_provider="gemini", image_quality="medium")

    async def test_new_researcher_settings_defaults(self) -> None:
        rows = [
            {"key": "library_path", "value": "/tmp/sasoo-library"},
            {"key": "pdf_parser_mode", "value": "java"},
            {"key": "extraction_pipeline_version", "value": "resolver_v1"},
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


class PdfVisualEngineSettingTests(unittest.IsolatedAsyncioTestCase):
    """
    The Figure-extraction (visual) engine choice: gemini (paid, high quality)
    or odl (free). Saving it must persist to storage AND update
    SASOO_PDF_VISUAL_ENGINE, which odl_parser._resolve_stage_engine reads at
    call time so the next parse honours it without a restart.
    """

    def setUp(self) -> None:
        # Isolate the process env var these tests touch.
        self._saved_env = os.environ.get("SASOO_PDF_VISUAL_ENGINE")
        os.environ.pop("SASOO_PDF_VISUAL_ENGINE", None)

    def tearDown(self) -> None:
        if self._saved_env is None:
            os.environ.pop("SASOO_PDF_VISUAL_ENGINE", None)
        else:
            os.environ["SASOO_PDF_VISUAL_ENGINE"] = self._saved_env

    async def test_default_visual_engine_is_gemini(self) -> None:
        rows = [
            {"key": "library_path", "value": "/tmp/sasoo-library"},
            {"key": "pdf_parser_mode", "value": "java"},
            {"key": "extraction_pipeline_version", "value": "resolver_v1"},
        ]

        with (
            patch("api.settings._ensure_defaults", new=AsyncMock()),
            patch("api.settings.fetch_all", new=AsyncMock(return_value=rows)),
            patch("api.settings._set_setting", new=AsyncMock()),
        ):
            response = await settings.get_settings()

        # Absent from storage -> the schema/route default (gemini) is reported.
        self.assertEqual(response.pdf_visual_engine, "gemini")

    async def test_update_visual_engine_persists_and_updates_env(self) -> None:
        store: dict[str, str] = {
            "library_path": "/tmp/sasoo-library",
            "pdf_parser_mode": "java",
            "extraction_pipeline_version": "resolver_v1",
            "pdf_visual_engine": "gemini",
        }

        async def fake_set_setting(key: str, value: str) -> None:
            store[key] = value

        async def fake_fetch_all(*args, **kwargs):
            return [{"key": k, "value": v} for k, v in store.items()]

        with (
            patch("api.settings._ensure_defaults", new=AsyncMock()),
            patch("api.settings.fetch_all", new=AsyncMock(side_effect=fake_fetch_all)),
            patch("api.settings._set_setting", new=AsyncMock(side_effect=fake_set_setting)),
        ):
            response = await settings.update_settings(
                SettingsUpdate(pdf_visual_engine="odl")
            )

        self.assertEqual(store["pdf_visual_engine"], "odl")
        self.assertEqual(response.pdf_visual_engine, "odl")
        # The whole point: env is live for the next parse, no restart.
        self.assertEqual(os.environ.get("SASOO_PDF_VISUAL_ENGINE"), "odl")

    async def test_update_visual_engine_rejects_unknown_value(self) -> None:
        with (
            patch("api.settings._ensure_defaults", new=AsyncMock()),
            patch("api.settings._set_setting", new=AsyncMock()) as set_setting,
        ):
            with self.assertRaises(HTTPException) as ctx:
                await settings.update_settings(
                    SettingsUpdate(pdf_visual_engine="claude")
                )

        self.assertEqual(ctx.exception.status_code, 400)
        # Rejected before any write, and env is left untouched.
        set_setting.assert_not_awaited()
        self.assertIsNone(os.environ.get("SASOO_PDF_VISUAL_ENGINE"))


if __name__ == "__main__":
    unittest.main()
