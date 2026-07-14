import os
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

import main
from services.api_key_runtime import load_api_keys_from_settings
from services.crypto import CryptoKeyStoreError


class CryptoStartupMigrationTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.original_gemini_key = os.environ.pop("GEMINI_API_KEY", None)

    def tearDown(self) -> None:
        if self.original_gemini_key is None:
            os.environ.pop("GEMINI_API_KEY", None)
        else:
            os.environ["GEMINI_API_KEY"] = self.original_gemini_key

    async def test_startup_migrates_file_ciphertext_before_removing_file_key(self) -> None:
        rows = [
            {"key": "gemini_api_key", "value": "enc:v1:legacy"},
            {"key": "pdf_visual_engine", "value": "gemini"},
        ]
        events = []

        async def record_update(*_args) -> None:
            events.append("update")

        def record_removal() -> None:
            events.append("remove")

        with (
            patch("main.init_db", new=AsyncMock()),
            patch("main.get_library_root", return_value=Path("/tmp/library")),
            patch("services.log_setup.setup_logging"),
            patch("models.database.fetch_all", new=AsyncMock(return_value=rows)),
            patch(
                "models.database.execute_update",
                new=AsyncMock(side_effect=record_update),
            ) as update,
            patch("services.crypto.decrypt_value", return_value="AIza-new"),
            patch("services.crypto.migrate_value_to_primary", return_value="enc:v1:keychain"),
            patch(
                "services.crypto.remove_legacy_file_key",
                side_effect=record_removal,
            ) as remove_file_key,
            patch("services.agents.load_all_agents"),
        ):
            await main.bootstrap_runtime(worker=False)

        update.assert_awaited_once_with(
            "UPDATE settings SET value = ? WHERE key = ?",
            ("enc:v1:keychain", "gemini_api_key"),
        )
        remove_file_key.assert_called_once_with()
        self.assertEqual(events, ["update", "remove"])
        self.assertEqual(os.environ.get("GEMINI_API_KEY"), "AIza-new")

    async def test_startup_keeps_file_key_when_keychain_migration_fails(self) -> None:
        rows = [{"key": "gemini_api_key", "value": "enc:v1:legacy"}]

        with (
            patch("main.init_db", new=AsyncMock()),
            patch("main.get_library_root", return_value=Path("/tmp/library")),
            patch("services.log_setup.setup_logging"),
            patch("models.database.fetch_all", new=AsyncMock(return_value=rows)),
            patch("models.database.execute_update", new=AsyncMock()) as update,
            patch("services.crypto.decrypt_value", return_value="AIza-new"),
            patch(
                "services.crypto.migrate_value_to_primary",
                side_effect=CryptoKeyStoreError("keychain locked"),
            ),
            patch("services.crypto.remove_legacy_file_key") as remove_file_key,
            patch("services.agents.load_all_agents"),
        ):
            await main.bootstrap_runtime(worker=False)

        update.assert_not_awaited()
        remove_file_key.assert_not_called()
        self.assertEqual(os.environ.get("GEMINI_API_KEY"), "AIza-new")

    async def test_worker_loads_key_without_migrating_shared_storage(self) -> None:
        with (
            patch("services.crypto.decrypt_value", return_value="AIza-worker"),
            patch("services.crypto.migrate_value_to_primary") as migrate,
            patch("services.crypto.remove_legacy_file_key") as remove_file_key,
            patch("models.database.execute_update", new=AsyncMock()) as update,
        ):
            await load_api_keys_from_settings(
                {"gemini_api_key": "enc:v1:legacy"},
                worker=True,
            )

        migrate.assert_not_called()
        update.assert_not_awaited()
        remove_file_key.assert_not_called()
        self.assertEqual(os.environ.get("GEMINI_API_KEY"), "AIza-worker")


if __name__ == "__main__":
    unittest.main()
