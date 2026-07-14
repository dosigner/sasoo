"""
Tests for services/crypto.py.

The operating default must keep the Fernet key in the OS credential store, not
next to the encrypted SQLite database. Legacy file keys remain readable only
long enough to migrate existing ciphertext.
"""

import sys
import types
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from cryptography.fernet import Fernet
from keyring.errors import KeyringError

from services import crypto  # noqa: E402


class CryptoTests(unittest.TestCase):
    def setUp(self):
        self._tmp = TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.keyring_key = None
        keyring_stub = types.ModuleType("keyring")
        keyring_stub.get_password = lambda _service, _account: (
            self.keyring_key.decode("utf-8") if self.keyring_key else None
        )

        def set_password(_service, _account, value):
            self.keyring_key = value.encode("utf-8")

        keyring_stub.set_password = set_password
        self._patchers = [
            patch.object(crypto, "_key_path", lambda: self.root / ".sasoo_key"),
            patch.dict(sys.modules, {"keyring": keyring_stub}),
            patch.dict("os.environ", {"SASOO_USE_FILE_KEY": ""}, clear=False),
        ]
        for p in self._patchers:
            p.start()

    def tearDown(self):
        for p in self._patchers:
            p.stop()
        self._tmp.cleanup()

    # -- basics ----------------------------------------------------------

    def test_round_trip(self):
        token = crypto.encrypt_value("AIza-secret")
        self.assertTrue(token.startswith(crypto.ENCRYPTED_PREFIX))
        self.assertNotIn("AIza-secret", token)
        self.assertEqual(crypto.decrypt_value(token), "AIza-secret")
        self.assertIsNotNone(self.keyring_key)
        self.assertFalse((self.root / ".sasoo_key").exists())

    def test_plaintext_passes_through(self):
        # Values from before encryption was introduced are returned as-is.
        self.assertEqual(crypto.decrypt_value("AIza-plain"), "AIza-plain")
        self.assertFalse(crypto.is_unreadable("AIza-plain"))

    def test_empty_value(self):
        self.assertEqual(crypto.decrypt_value(""), "")
        self.assertFalse(crypto.is_unreadable(""))

    def test_legacy_key_file_is_owner_only(self):
        crypto._create_file_key()
        mode = (self.root / ".sasoo_key").stat().st_mode & 0o777
        self.assertEqual(mode, 0o600)

    @unittest.skipIf(sys.platform == "win32", "POSIX permission bits are unavailable")
    def test_existing_key_file_permissions_are_restricted(self):
        key_file = self.root / ".sasoo_key"
        key_file.write_bytes(Fernet.generate_key())
        key_file.chmod(0o644)

        crypto._read_file_key()

        mode = key_file.stat().st_mode & 0o777
        self.assertEqual(mode, 0o600)

    # -- the cross-mode bug ----------------------------------------------

    def test_value_encrypted_with_keychain_key_still_decrypts(self):
        """A key written by an old dev build (keychain) must still open."""
        keychain_key = Fernet.generate_key()
        token = crypto.ENCRYPTED_PREFIX + Fernet(keychain_key).encrypt(
            b"from-keychain"
        ).decode()

        # A file key also exists, but it is NOT the one that sealed the value.
        crypto._create_file_key()

        with patch.object(crypto, "_read_keyring_key", lambda: keychain_key):
            self.assertEqual(crypto.decrypt_value(token), "from-keychain")
            self.assertFalse(crypto.is_unreadable(token))

    def test_keychain_written_value_readable_when_keychain_unavailable_is_flagged(self):
        """Packaged builds cannot reach the keychain; say so instead of lying."""
        keychain_key = Fernet.generate_key()
        token = crypto.ENCRYPTED_PREFIX + Fernet(keychain_key).encrypt(b"v").decode()
        crypto._create_file_key()  # creates a file key that will not match

        self.keyring_key = None
        self.assertEqual(crypto.decrypt_value(token), "")
        self.assertTrue(crypto.is_unreadable(token))

    # -- the silent-failure bug ------------------------------------------

    def test_lost_key_is_reported_not_hidden(self):
        token = crypto.encrypt_value("secret")
        self.keyring_key = None

        self.assertEqual(crypto.decrypt_value(token), "")
        self.assertTrue(
            crypto.is_unreadable(token),
            "a stored-but-undecryptable value must be distinguishable from 'nothing stored'",
        )

    def test_decrypt_never_creates_a_key(self):
        """A read must not mint a key -- that used to mask the loss for good."""
        token = crypto.encrypt_value("secret")
        original = self.keyring_key
        self.keyring_key = None

        crypto.decrypt_value(token)

        self.assertIsNone(self.keyring_key)
        self.assertFalse((self.root / ".sasoo_key").exists())

        # And once the real key is restored, the value opens again.
        self.keyring_key = original
        self.assertEqual(crypto.decrypt_value(token), "secret")

    def test_reencrypting_recovers_the_setting(self):
        """Re-entering the key in Settings must overwrite the unreadable value."""
        stale = crypto.encrypt_value("old")
        self.keyring_key = None
        self.assertTrue(crypto.is_unreadable(stale))

        fresh = crypto.encrypt_value("new")
        self.assertEqual(crypto.decrypt_value(fresh), "new")
        self.assertFalse(crypto.is_unreadable(fresh))

    def test_legacy_file_ciphertext_migrates_to_keyring(self):
        legacy_key = crypto._create_file_key()
        legacy = crypto.ENCRYPTED_PREFIX + Fernet(legacy_key).encrypt(b"old").decode()

        migrated = crypto.migrate_value_to_primary(legacy)

        self.assertNotEqual(migrated, legacy)
        self.assertIsNotNone(self.keyring_key)
        self.assertTrue(crypto.remove_legacy_file_key())
        self.assertFalse((self.root / ".sasoo_key").exists())
        self.assertEqual(crypto.decrypt_value(migrated), "old")

    def test_invalid_keyring_entry_is_replaced_during_legacy_migration(self):
        legacy_key = crypto._create_file_key()
        legacy = crypto.ENCRYPTED_PREFIX + Fernet(legacy_key).encrypt(b"old").decode()
        self.keyring_key = b"not-a-fernet-key"

        migrated = crypto.migrate_value_to_primary(legacy)

        self.assertNotEqual(self.keyring_key, b"not-a-fernet-key")
        self.assertEqual(crypto.decrypt_value(migrated), "old")

    def test_transient_keyring_read_failure_never_overwrites_existing_key(self):
        existing_key = Fernet.generate_key()
        self.keyring_key = existing_key
        keyring_module = sys.modules["keyring"]
        keyring_module.get_password = lambda *_args: (_ for _ in ()).throw(
            KeyringError("keychain locked")
        )

        with self.assertRaisesRegex(RuntimeError, "could not be read"):
            crypto.encrypt_value("secret")

        self.assertEqual(self.keyring_key, existing_key)

    def test_legacy_file_key_remains_readable_when_keyring_read_fails(self):
        legacy_key = crypto._create_file_key()
        legacy = crypto.ENCRYPTED_PREFIX + Fernet(legacy_key).encrypt(b"old").decode()
        keyring_module = sys.modules["keyring"]
        keyring_module.get_password = lambda *_args: (_ for _ in ()).throw(
            KeyringError("keychain locked")
        )

        self.assertEqual(crypto.decrypt_value(legacy), "old")

    def test_keyring_failure_does_not_fall_back_next_to_database(self):
        keyring_module = sys.modules["keyring"]
        keyring_module.set_password = lambda *_args: (_ for _ in ()).throw(
            KeyringError("keychain locked")
        )

        with self.assertRaisesRegex(RuntimeError, "OS credential store"):
            crypto.encrypt_value("secret")

        self.assertFalse((self.root / ".sasoo_key").exists())


if __name__ == "__main__":
    unittest.main()
