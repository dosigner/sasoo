import os
import sqlite3
from collections.abc import Mapping


async def load_api_keys_from_settings(
    settings: Mapping[str, str],
    worker: bool,
) -> None:
    from models.database import execute_update
    from services.crypto import (
        CryptoKeyStoreError,
        CryptoMigrationError,
        decrypt_value,
        migrate_value_to_primary,
        remove_legacy_file_key,
    )

    environment_names = {
        "gemini_api_key": "GEMINI_API_KEY",
        "openai_api_key": "OPENAI_API_KEY",
    }
    migration_attempted = False
    migration_complete = True
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
            continue

        migration_attempted = True
        try:
            migrated = migrate_value_to_primary(stored)
            if migrated != stored:
                await execute_update(
                    "UPDATE settings SET value = ? WHERE key = ?",
                    (migrated, setting_key),
                )
        except (CryptoKeyStoreError, CryptoMigrationError, sqlite3.Error, OSError) as exc:
            migration_complete = False
            print(
                f"[Sasoo] Warning: Could not migrate {setting_key} "
                f"to the OS credential store: {exc}"
            )

    if migration_attempted and migration_complete:
        remove_legacy_file_key()
    print("[Sasoo] API keys loaded from database into environment.")
