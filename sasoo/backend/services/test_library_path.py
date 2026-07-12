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

import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from models import database


class UsableLibraryPathTests(unittest.TestCase):
    def test_windows_path_is_not_usable_on_posix(self) -> None:
        win = r"C:\Users\dongj\Documents\sasoo\backend\library"
        with patch.object(database.sys, "platform", "darwin"):
            self.assertIsNone(
                database.usable_library_path(win),
                "a Windows path must be refused on POSIX, not resolved against the CWD",
            )

    def test_absolute_posix_path_is_usable(self) -> None:
        self.assertEqual(
            database.usable_library_path("/Users/dongj/sasoo/library"),
            Path("/Users/dongj/sasoo/library"),
        )

    def test_home_relative_path_is_expanded(self) -> None:
        resolved = database.usable_library_path("~/sasoo/library")
        self.assertIsNotNone(resolved)
        self.assertTrue(resolved.is_absolute())

    def test_relative_and_empty_paths_are_refused(self) -> None:
        for value in ("", "   ", None, "library", "./library", "../library"):
            with self.subTest(value=value):
                self.assertIsNone(database.usable_library_path(value))

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
        with patch.object(database.sys, "platform", "darwin"):
            self.assertTrue(Path(glued).is_absolute(), "precondition: it is absolute")
            self.assertIsNone(
                database.usable_library_path(glued),
                "a POSIX path carrying a drive letter or backslash came from Windows",
            )

    def test_backslash_alone_is_enough_to_refuse_on_posix(self) -> None:
        with patch.object(database.sys, "platform", "darwin"):
            self.assertIsNone(database.usable_library_path(r"/Users/dongj\library"))


class PlatformScopedKeyTests(unittest.TestCase):
    def test_key_is_scoped_per_platform(self) -> None:
        for platform, expected in (
            ("darwin", "library_path_darwin"),
            ("win32", "library_path_win32"),
            ("linux", "library_path_linux"),
        ):
            with self.subTest(platform=platform):
                with patch.object(database.sys, "platform", platform):
                    self.assertEqual(database.library_path_setting_key(), expected)

    def test_mac_and_windows_keep_separate_paths(self) -> None:
        """One settings DB, two machines, two library roots."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._write_settings(root, {
                "library_path_darwin": "/Users/dongj/sasoo/library",
                "library_path_win32": r"C:\Users\dongj\Documents\sasoo\library",
            })

            with patch.object(database, "_get_app_data_root", lambda: root):
                with patch.object(database.sys, "platform", "darwin"):
                    self.assertEqual(
                        database.get_library_root(),
                        Path("/Users/dongj/sasoo/library"),
                    )
                # The Windows value is still there, untouched, for that machine.
                self.assertEqual(
                    self._read_setting(root, "library_path_win32"),
                    r"C:\Users\dongj\Documents\sasoo\library",
                )

    def test_windows_legacy_value_does_not_leak_into_the_mac_root(self) -> None:
        """The actual bug: a Windows-written library_path read on a Mac."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            default = root / "default-library"
            self._write_settings(root, {
                "library_path": r"C:\Users\dongj\Documents\논문\sasoo\backend\library",
            })

            with (
                patch.object(database, "_get_app_data_root", lambda: root),
                patch.object(database, "_get_default_library_root", lambda: default),
                patch.object(database.sys, "platform", "darwin"),
            ):
                resolved = database.get_library_root()

            self.assertEqual(
                resolved, default,
                "an unusable stored path must fall back to the platform default",
            )
            self.assertNotIn(
                "C:", str(resolved),
                "the Windows path was glued onto the resolved root again",
            )

    def test_legacy_value_is_still_honoured_on_the_platform_that_wrote_it(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._write_settings(root, {"library_path": "/Users/dongj/sasoo/library"})

            with (
                patch.object(database, "_get_app_data_root", lambda: root),
                patch.object(database.sys, "platform", "darwin"),
            ):
                self.assertEqual(
                    database.get_library_root(),
                    Path("/Users/dongj/sasoo/library"),
                )

    def test_platform_key_wins_over_legacy(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._write_settings(root, {
                "library_path": "/Users/dongj/old/library",
                "library_path_darwin": "/Users/dongj/new/library",
            })

            with (
                patch.object(database, "_get_app_data_root", lambda: root),
                patch.object(database.sys, "platform", "darwin"),
            ):
                self.assertEqual(
                    database.get_library_root(), Path("/Users/dongj/new/library")
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


if __name__ == "__main__":
    unittest.main()
