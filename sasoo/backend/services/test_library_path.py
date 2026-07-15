"""
Tests for per-platform library path resolution (models/database.py).

The bug these guard against: a settings database carried from a Windows machine
to a Mac stored

    library_path = C:\\Users\\dongj\\Documents\\논문\\sasoo\\backend\\library

On POSIX that is not an absolute path -- backslashes are ordinary characters, so
it is a legal *relative* filename. Path.resolve() therefore glued it onto the
process's working directory and the library silently pointed at

    /Users/dongj/dev/.../sasoo/backend/C:\\Users\\dongj\\...\\library

which does not exist. The path is now stored per platform, and anything that is
not absolute here is refused rather than resolved.
"""

import os
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from models import database


def _foreign_library_path() -> str:
    if os.name == "nt":
        return "/Users/dongj/sasoo/library"
    return r"C:\Users\dongj\Documents\sasoo\library"


class UsableLibraryPathTests(unittest.TestCase):
    def test_other_platform_path_is_not_usable(self) -> None:
        self.assertIsNone(database.usable_library_path(_foreign_library_path()))

    def test_absolute_native_path_is_usable(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "sasoo-library"
            self.assertEqual(database.usable_library_path(str(path)), path)

    def test_home_relative_path_is_expanded(self) -> None:
        resolved = database.usable_library_path("~/sasoo/library")
        self.assertIsNotNone(resolved)
        self.assertTrue(resolved.is_absolute())

    def test_relative_and_empty_paths_are_refused(self) -> None:
        for value in ("", "   ", None, "library", "./library", "../library"):
            with self.subTest(value=value):
                self.assertIsNone(database.usable_library_path(value))

    @unittest.skipIf(os.name == "nt", "The glued legacy path is a POSIX-only case")
    def test_already_glued_path_is_refused(self) -> None:
        """
        The value an older build actually persisted.

        Rejecting non-absolute paths is not enough to catch this one: the
        gluing already happened, so it IS absolute on POSIX and would sail
        through, still pointing at a directory that never existed.
        """
        glued = (
            "/Users/dongj/dev/논문_사수_개발중/sasoo/backend/"
            r"C:\Users\dongj\Documents\논문\sasoo\backend\library"
        )
        self.assertTrue(Path(glued).is_absolute(), "precondition: it is absolute")
        self.assertIsNone(
            database.usable_library_path(glued),
            "a POSIX path carrying a drive letter or backslash came from Windows",
        )

    @unittest.skipIf(os.name == "nt", "Backslashes have native meaning on Windows")
    def test_backslash_alone_is_enough_to_refuse_on_posix(self) -> None:
        self.assertIsNone(database.usable_library_path(r"/Users/dongj\library"))


class PlatformScopedKeyTests(unittest.TestCase):
    def setUp(self) -> None:
        database.invalidate_library_root_cache()

    def test_key_is_scoped_per_platform(self) -> None:
        for platform, expected in (
            ("darwin", "library_path_darwin"),
            ("win32", "library_path_win32"),
            ("linux", "library_path_linux"),
        ):
            with self.subTest(platform=platform):
                with patch.object(database.sys, "platform", platform):
                    self.assertEqual(database.library_path_setting_key(), expected)

    def test_platform_specific_path_keeps_foreign_path_untouched(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            native_path = root / "native-library"
            foreign_key = (
                "library_path_darwin"
                if database.sys.platform != "darwin"
                else "library_path_win32"
            )
            self._write_settings(root, {
                database.library_path_setting_key(): str(native_path),
                foreign_key: _foreign_library_path(),
            })

            with patch.object(database, "_get_app_data_root", lambda: root):
                self.assertEqual(
                    database.get_library_root(), native_path,
                )
            self.assertEqual(self._read_setting(root, foreign_key), _foreign_library_path())

    def test_other_platform_legacy_value_does_not_leak_into_native_root(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            default = root / "default-library"
            self._write_settings(root, {"library_path": _foreign_library_path()})

            with (
                patch.object(database, "_get_app_data_root", lambda: root),
                patch.object(database, "_get_default_library_root", lambda: default),
            ):
                resolved = database.get_library_root()

            self.assertEqual(
                resolved, default,
                "an unusable stored path must fall back to the platform default",
            )

    def test_legacy_value_is_still_honoured_on_the_platform_that_wrote_it(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            native_path = root / "native-library"
            self._write_settings(root, {"library_path": str(native_path)})

            with patch.object(database, "_get_app_data_root", lambda: root):
                self.assertEqual(
                    database.get_library_root(), native_path,
                )

    def test_platform_key_wins_over_legacy(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            old_path = root / "old-library"
            new_path = root / "new-library"
            self._write_settings(root, {
                "library_path": str(old_path),
                database.library_path_setting_key(): str(new_path),
            })

            with patch.object(database, "_get_app_data_root", lambda: root):
                self.assertEqual(
                    database.get_library_root(), new_path
                )

    # -- helpers ---------------------------------------------------------

    @staticmethod
    def _write_settings(root: Path, values: dict[str, str]) -> None:
        conn = sqlite3.connect(str(root / "sasoo.db"))
        conn.execute("CREATE TABLE settings (key TEXT PRIMARY KEY, value TEXT)")
        conn.executemany(
            "INSERT INTO settings (key, value) VALUES (?, ?)", values.items()
        )
        conn.commit()
        conn.close()

    @staticmethod
    def _read_setting(root: Path, key: str) -> str:
        conn = sqlite3.connect(str(root / "sasoo.db"))
        row = conn.execute(
            "SELECT value FROM settings WHERE key = ?", (key,)
        ).fetchone()
        conn.close()
        return row[0] if row else ""


class LibraryRootCacheTests(unittest.TestCase):
    """
    get_library_root() runs inside async request handlers on nearly every
    endpoint, and each uncached call opens a synchronous SQLite connection on
    the event loop. These tests pin the TTL cache that keeps that to at most
    one read per TTL window -- and pin that the cache can be bypassed exactly
    two ways: explicit invalidation and TTL expiry.
    """

    def _configure(self, root: Path, path: str) -> None:
        conn = sqlite3.connect(str(root / "sasoo.db"))
        conn.execute(
            "CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT)"
        )
        conn.execute(
            "INSERT INTO settings (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (database.library_path_setting_key(), path),
        )
        conn.commit()
        conn.close()

    def test_second_call_within_ttl_skips_sqlite(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            expected = root / "sasoo-library"
            self._configure(root, str(expected))
            with patch.object(database, "_get_app_data_root", lambda: root):
                first = database.get_library_root()
                with patch.object(
                    database.sqlite3,
                    "connect",
                    side_effect=AssertionError("sqlite reopened within TTL"),
                ):
                    second = database.get_library_root()

        self.assertEqual(first, expected)
        self.assertEqual(second, first)

    def test_invalidate_forces_reread(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            old_path = root / "old-library"
            new_path = root / "new-library"
            self._configure(root, str(old_path))
            with patch.object(database, "_get_app_data_root", lambda: root):
                self.assertEqual(
                    database.get_library_root(), old_path
                )
                self._configure(root, str(new_path))
                database.invalidate_library_root_cache()
                self.assertEqual(
                    database.get_library_root(), new_path
                )

    def test_ttl_expiry_forces_reread(self) -> None:
        clock = {"t": 0.0}
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            old_path = root / "old-library"
            new_path = root / "new-library"
            self._configure(root, str(old_path))
            with (
                patch.object(database, "_get_app_data_root", lambda: root),
                patch.object(
                    database.time, "monotonic", side_effect=lambda: clock["t"]
                ),
            ):
                self.assertEqual(
                    database.get_library_root(), old_path
                )
                self._configure(root, str(new_path))
                clock["t"] = 100.0
                self.assertEqual(
                    database.get_library_root(), new_path
                )


if __name__ == "__main__":
    unittest.main()
