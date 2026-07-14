import os
import sqlite3
from collections.abc import Mapping

from filelock import Timeout


async def load_api_keys_from_settings(
    settings: Mapping[str, str],
    worker: bool,
) -> None:
    from models.database import execute_update, fetch_all
    from services.crypto import (
        CryptoKeyStoreError,
        CryptoMigrationError,
        credential_store_lock,
        decrypt_value,
        migrate_value_to_primary,
        remove_legacy_file_key,
    )

    environment_names = {
        "gemini_api_key": "GEMINI_API_KEY",
        "openai_api_key": "OPENAI_API_KEY",
    }
    for setting_key, environment_name in environment_names.items():
        stored = settings.get(setting_key)
        if not stored:
            continue

        decrypted = decrypt_value(stored)
        if not decrypted:
            if not worker:
                migration_complete = False
            continue

        os.environ[environment_name] = decrypted
    if worker:
        print("[Sasoo] API keys loaded from database into environment.")
        return

    try:
        with credential_store_lock():
            rows = await fetch_all(
                "SELECT key, value FROM settings WHERE key IN (?, ?)",
                tuple(environment_names),
            )
            current_settings = {row["key"]: row["value"] for row in rows}
            migration_attempted = False
            migration_complete = True
            for setting_key, environment_name in environment_names.items():
                stored = current_settings.get(setting_key)
                if not stored:
                    continue

                decrypted = decrypt_value(stored)
                if not decrypted:
                    migration_complete = False
                    continue
                os.environ[environment_name] = decrypted
                migration_attempted = True
                try:
                    migrated = migrate_value_to_primary(stored)
                    if migrated != stored:
                        updated = await execute_update(
                            "UPDATE settings SET value = ? WHERE key = ? AND value = ?",
                            (migrated, setting_key, stored),
                        )
                        if updated != 1:
                            migration_complete = False
                except (CryptoKeyStoreError, CryptoMigrationError, sqlite3.Error, OSError) as exc:
                    migration_complete = False
                    print(
                        f"[Sasoo] Warning: Could not migrate {setting_key} "
                        f"to the OS credential store: {exc}"
                    )

            if migration_attempted and migration_complete:
                try:
                    verification_rows = await fetch_all(
                        "SELECT key, value FROM settings WHERE key IN (?, ?)",
                        tuple(environment_names),
                    )
                    for row in verification_rows:
                        stored = row["value"]
                        if stored and migrate_value_to_primary(stored) != stored:
                            migration_complete = False
                            break
                except (CryptoKeyStoreError, CryptoMigrationError, sqlite3.Error, OSError) as exc:
                    migration_complete = False
                    print(f"[Sasoo] Warning: Could not verify API key migration: {exc}")
                if migration_complete:
                    remove_legacy_file_key()
    except Timeout as exc:
        print(f"[Sasoo] Warning: Could not acquire the credential migration lock: {exc}")
    print("[Sasoo] API keys loaded from database into environment.")
