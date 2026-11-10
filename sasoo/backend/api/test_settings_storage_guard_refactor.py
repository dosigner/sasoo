"""Protect settings storage when credential encryption fails."""

import unittest
from unittest.mock import AsyncMock, patch

import aiosqlite
from fastapi import HTTPException

from api import settings
from models.schemas import SettingsUpdate
from services.crypto import CryptoKeyStoreError


class SettingsStorageGuardTests(unittest.IsolatedAsyncioTestCase):
    async def test_credential_error_does_not_write_any_mixed_update(self):
        async with aiosqlite.connect(":memory:") as db:
            await db.execute("CREATE TABLE settings (key TEXT PRIMARY KEY, value TEXT, updated_at TEXT)")
            await db.execute("INSERT INTO settings VALUES ('theme', 'light', 'original')")
            await db.commit()
            statements = []
            await db.set_trace_callback(statements.append)
            with (
                patch.object(settings, "get_db", new=AsyncMock(return_value=db)),
                patch.object(settings, "_set_settings", wraps=settings._set_settings) as save,
                patch.object(settings, "encrypt_value", side_effect=CryptoKeyStoreError("unavailable")),
            ):
                with self.assertRaises(HTTPException) as error:
                    await settings.update_settings(SettingsUpdate(gemini_api_key="synthetic-key", theme="dark"))
            self.assertEqual(error.exception.status_code, 503)
            save.assert_not_awaited()
            self.assertEqual(await (await db.execute("SELECT key, value, updated_at FROM settings")).fetchall(),
                             [("theme", "light", "original")])
            self.assertFalse(any(sql.lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE", "REPLACE"))
                                 for sql in statements))
