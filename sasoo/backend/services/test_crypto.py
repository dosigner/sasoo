"""
Tests for services/crypto.py.

The bug these guard against: the encryption key store used to depend on how the
app was launched (OS keychain in dev, file when packaged), so a key written by
one mode was unreadable by the other -- and the failure surfaced as a bare
"no API key configured", with a read silently minting a fresh key that masked
the loss for good.
"""

import sys
import types
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from cryptography.fernet import Fernet

# crypto.py imports APP_DATA_ROOT from models.database lazily, inside _key_path().
# Stub the module so these tests never touch the real library directory.
_database_stub = types.ModuleType("models.database")
_database_stub.APP_DATA_ROOT = Path("/nonexistent")
sys.modules.setdefault("models.database", _database_stub)

from services import crypto  # noqa: E402


class CryptoTests(unittest.TestCase):
    def setUp(self):
        self._tmp = TemporaryDirectory()
        self.root = Path(self._tmp.name)
        # Point the file-key store at a temp dir, and default to no keychain.
        self._patchers = [
            patch.object(crypto, "_key_path", lambda: self.root / ".sasoo_key"),
            patch.object(crypto, "_read_keyring_key", lambda: None),
            patch.dict("os.environ", {"SASOO_USE_OS_KEYRING": ""}, clear=False),
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

    def test_plaintext_passes_through(self):
        # Values from before encryption was introduced are returned as-is.
        self.assertEqual(crypto.decrypt_value("AIza-plain"), "AIza-plain")
        self.assertFalse(crypto.is_unreadable("AIza-plain"))

    def test_empty_value(self):
        self.assertEqual(crypto.decrypt_value(""), "")
        self.assertFalse(crypto.is_unreadable(""))

    def test_key_file_is_owner_only(self):
        crypto.encrypt_value("x")
        mode = (self.root / ".sasoo_key").stat().st_mode & 0o777
        self.assertEqual(mode, 0o600)

    # -- the cross-mode bug ----------------------------------------------

    def test_value_encrypted_with_keychain_key_still_decrypts(self):
        """A key written by an old dev build (keychain) must still open."""
        keychain_key = Fernet.generate_key()
        token = crypto.ENCRYPTED_PREFIX + Fernet(keychain_key).encrypt(
            b"from-keychain"
        ).decode()

        # A file key also exists, but it is NOT the one that sealed the value.
        crypto.encrypt_value("unrelated")

        with patch.object(crypto, "_read_keyring_key", lambda: keychain_key):
            self.assertEqual(crypto.decrypt_value(token), "from-keychain")
            self.assertFalse(crypto.is_unreadable(token))

    def test_keychain_written_value_readable_when_keychain_unavailable_is_flagged(self):
        """Packaged builds cannot reach the keychain; say so instead of lying."""
        keychain_key = Fernet.generate_key()
        token = crypto.ENCRYPTED_PREFIX + Fernet(keychain_key).encrypt(b"v").decode()
        crypto.encrypt_value("unrelated")  # creates a file key that will not match

        # _read_keyring_key already patched to None -> keychain unreachable.
        self.assertEqual(crypto.decrypt_value(token), "")
        self.assertTrue(crypto.is_unreadable(token))

    # -- the silent-failure bug ------------------------------------------

    def test_lost_key_is_reported_not_hidden(self):
        token = crypto.encrypt_value("secret")
        (self.root / ".sasoo_key").unlink()  # the key is gone

        self.assertEqual(crypto.decrypt_value(token), "")
        self.assertTrue(
            crypto.is_unreadable(token),
            "a stored-but-undecryptable value must be distinguishable from 'nothing stored'",
        )

    def test_decrypt_never_creates_a_key(self):
        """A read must not mint a key -- that used to mask the loss for good."""
        token = crypto.encrypt_value("secret")
        key_file = self.root / ".sasoo_key"
        original = key_file.read_bytes()
        key_file.unlink()

        crypto.decrypt_value(token)

        self.assertFalse(
            key_file.exists(),
            "decrypt_value regenerated the key file, hiding that the real key was lost",
        )

        # And once the real key is restored, the value opens again.
        key_file.write_bytes(original)
        self.assertEqual(crypto.decrypt_value(token), "secret")

    def test_reencrypting_recovers_the_setting(self):
        """Re-entering the key in Settings must overwrite the unreadable value."""
        stale = crypto.encrypt_value("old")
        (self.root / ".sasoo_key").unlink()
        self.assertTrue(crypto.is_unreadable(stale))

        fresh = crypto.encrypt_value("new")  # creates a fresh key
        self.assertEqual(crypto.decrypt_value(fresh), "new")
        self.assertFalse(crypto.is_unreadable(fresh))


if __name__ == "__main__":
    unittest.main()
