from __future__ import annotations

import os
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from models import database
from services import crypto, odl_parser


class RuntimeLibraryPathTests(unittest.TestCase):
    def test_get_paper_dir_falls_back_to_default_root_for_existing_papers(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            app_root = tmp_path / "appdata"
            default_root = app_root / "library"
            custom_root = tmp_path / "custom-library"
            default_paper = default_root / "paper-123"

            default_paper.mkdir(parents=True, exist_ok=True)
            custom_root.mkdir(parents=True, exist_ok=True)

            db_path = app_root / "sasoo.db"
            app_root.mkdir(parents=True, exist_ok=True)
            conn = sqlite3.connect(db_path)
            try:
                conn.execute("CREATE TABLE settings (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
                conn.execute(
                    "INSERT INTO settings (key, value) VALUES (?, ?)",
                    ("library_path", str(custom_root)),
                )
                conn.commit()
            finally:
                conn.close()

            with patch.dict(os.environ, {"SASOO_ENV": "production"}, clear=False):
                with patch("models.database._get_app_data_root", return_value=app_root):
                    self.assertEqual(database.get_library_root(), custom_root)
                    self.assertEqual(database.get_paper_dir("paper-123"), default_paper)
                    self.assertEqual(
                        database.get_paper_dir("paper-456"),
                        custom_root / "paper-456",
                    )

    def test_library_asset_to_static_url_uses_current_library_root(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir) / "custom-library"
            asset = root / "paper-1" / "figures" / "Fig 1.png"
            asset.parent.mkdir(parents=True, exist_ok=True)
            asset.write_bytes(b"png")

            with patch("services.odl_parser.get_library_root", return_value=root):
                self.assertEqual(
                    odl_parser._library_asset_to_static_url(str(asset)),
                    "/static/library/paper-1/figures/Fig%201.png",
                )


class CryptoStorageTests(unittest.TestCase):
    """
    Encryption must not depend on the OS keyring.

    Keyring backends can block or fail inside bundled Python subprocesses on
    macOS, so packaged builds have always used the file key. The key store used
    to be chosen by launch mode, which meant a key written in development was
    unreadable once packaged. Encryption now uses the file key in every mode;
    the keyring is read-only fallback for values sealed by older builds.
    """

    def test_encryption_uses_the_file_key_not_the_keyring(self) -> None:
        fake_key = b"fake-key"
        for env in ("production", "development"):
            with self.subTest(env=env):
                with patch.dict(os.environ, {"SASOO_ENV": env}, clear=False):
                    with (
                        patch("services.crypto._read_file_key", return_value=fake_key) as file_key,
                        patch("services.crypto._read_keyring_key") as keyring_key,
                    ):
                        self.assertEqual(crypto._encryption_key(), fake_key)
                        file_key.assert_called_once()
                        keyring_key.assert_not_called()
