"""
Sasoo - API Key Encryption Utility
Encrypts/decrypts API keys stored in SQLite using Fernet symmetric encryption.

New encryption keys live in the operating system credential store (macOS
Keychain, Windows Credential Manager, or the configured Linux keyring). The
legacy `<app-data>/.sasoo_key` file is read only to migrate existing values; it
is no longer the operating default because copying the app-data folder would
otherwise disclose both the database and its decryption key.

Decryption never creates a key. The previous code did, so a read against a
cleared keychain would quietly mint a fresh key and then fail to decrypt with
it, permanently masking the fact that the original key was gone.
"""

import logging
import os
from typing import Optional

from cryptography.fernet import Fernet, InvalidToken
from keyring.errors import KeyringError

logger = logging.getLogger(__name__)

# Keyring service/account identifiers
_KEYRING_SERVICE = "sasoo-desktop"
_KEYRING_ACCOUNT = "fernet-key"

# Prefix to distinguish encrypted values from plaintext in the DB
ENCRYPTED_PREFIX = "enc:v1:"

_KEY_FILENAME = ".sasoo_key"


class CryptoKeyStoreError(RuntimeError):
    """The encryption key could not be safely read or persisted."""


class CryptoMigrationError(RuntimeError):
    """A legacy ciphertext could not be migrated without data loss."""


# ---------------------------------------------------------------------------
# Key stores
# ---------------------------------------------------------------------------

def _key_path():
    from models.database import APP_DATA_ROOT

    return APP_DATA_ROOT / _KEY_FILENAME


def _restrict_file_permissions(path) -> bool:
    if os.name == "nt":
        try:
            import subprocess

            result = subprocess.run(
                ["icacls", str(path), "/inheritance:r", "/grant:r",
                 f"{os.environ.get('USERNAME', 'CURRENT_USER')}:(R,W)"],
                capture_output=True, check=False,
            )
            return result.returncode == 0
        except OSError:
            logger.warning("Could not restrict permissions on %s", path)
            return False

    try:
        os.chmod(path, 0o600)
        return (path.stat().st_mode & 0o077) == 0
    except OSError:
        logger.warning("Could not chmod 0600 on %s", path)
        return False


def _read_file_key() -> Optional[bytes]:
    """Read the on-disk key. Never creates one."""
    path = _key_path()
    if not path.exists():
        return None
    if path.is_symlink() or not path.is_file():
        logger.error("Refusing to read an unsafe encryption key path: %s", path)
        return None
    if not _restrict_file_permissions(path):
        logger.error("Encryption key permissions could not be secured: %s", path)
        return None
    try:
        key = path.read_bytes().strip()
    except OSError:
        logger.error("Could not read encryption key: %s", path)
        return None
    return key or None


def _create_file_key() -> bytes:
    """Generate the on-disk key with owner-only permissions."""
    path = _key_path()
    new_key = Fernet.generate_key()
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        existing_key = _read_file_key()
        if existing_key:
            return existing_key
        raise CryptoKeyStoreError(f"Could not safely read existing encryption key: {path}")

    with os.fdopen(descriptor, "wb") as key_file:
        key_file.write(new_key)
        key_file.flush()
        os.fsync(key_file.fileno())

    if not _restrict_file_permissions(path):
        raise CryptoKeyStoreError(f"Could not secure encryption key permissions: {path}")

    logger.info("Generated new Fernet key: %s", path)
    return new_key


def _read_keyring_key() -> Optional[bytes]:
    """Read the OS keychain key. Never creates one.

    Kept for values encrypted by builds that defaulted to the keychain.
    Keyring backends can block or fail inside bundled Python subprocesses on
    macOS, so a failure here is downgraded to "no key" rather than raised.
    """
    try:
        import keyring as kr

        stored = kr.get_password(_KEYRING_SERVICE, _KEYRING_ACCOUNT)
    except (ImportError, KeyringError, OSError) as exc:
        logger.debug("Keyring unavailable: %s", exc)
        return None
    return stored.encode("utf-8") if stored else None


def _prefer_file_key() -> bool:
    """Emergency opt-out for systems without an OS credential store."""
    explicit = os.environ.get("SASOO_USE_FILE_KEY", "")
    return explicit.strip().lower() in {"1", "true", "yes", "on"}


def _create_keyring_key() -> bytes:
    new_key = Fernet.generate_key()
    try:
        import keyring as kr

        kr.set_password(_KEYRING_SERVICE, _KEYRING_ACCOUNT, new_key.decode("utf-8"))
    except (ImportError, KeyringError, OSError) as exc:
        raise CryptoKeyStoreError(
            "The OS credential store is unavailable; API keys were not saved."
        ) from exc

    logger.info("Generated new Fernet key in the OS credential store")
    return new_key


def _encryption_key() -> bytes:
    """The key NEW values are encrypted with. Creates one if none exists."""
    if _prefer_file_key():
        logger.warning("SASOO_USE_FILE_KEY is enabled; using the legacy file key store")
        return _read_file_key() or _create_file_key()

    return _read_keyring_key() or _create_keyring_key()


def _decryption_keys() -> list[bytes]:
    """Every key a stored value might have been encrypted with. No side effects."""
    keys: list[bytes] = []
    for candidate in (_read_keyring_key(), _read_file_key()):
        if candidate and candidate not in keys:
            keys.append(candidate)
    return keys


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def encrypt_value(plaintext: str) -> str:
    """Encrypt a plaintext value. Returns prefixed encrypted string."""
    if not plaintext:
        return plaintext
    token = Fernet(_encryption_key()).encrypt(plaintext.encode("utf-8"))
    return ENCRYPTED_PREFIX + token.decode("utf-8")


def migrate_value_to_primary(stored: str) -> str:
    """Re-encrypt a plaintext or legacy-file value with the current primary key."""
    if not stored:
        return stored

    primary_key = _encryption_key()
    if is_encrypted(stored):
        token = stored[len(ENCRYPTED_PREFIX):].encode("utf-8")
        try:
            Fernet(primary_key).decrypt(token)
            return stored
        except InvalidToken:
            plaintext = decrypt_value(stored)
            if not plaintext:
                raise CryptoMigrationError("Stored API key could not be decrypted for migration.")
    else:
        plaintext = stored

    migrated = Fernet(primary_key).encrypt(plaintext.encode("utf-8"))
    return ENCRYPTED_PREFIX + migrated.decode("utf-8")


def remove_legacy_file_key() -> bool:
    """Delete the colocated legacy key after every stored secret is migrated."""
    if _prefer_file_key():
        return False

    path = _key_path()
    if not path.exists():
        return False
    if path.is_symlink() or not path.is_file():
        logger.error("Refusing to remove an unsafe encryption key path: %s", path)
        return False
    try:
        path.unlink()
    except OSError as exc:
        logger.warning("Could not remove migrated legacy encryption key %s: %s", path, exc)
        return False
    logger.info("Removed migrated legacy encryption key: %s", path)
    return True


def decrypt_value(stored: str) -> str:
    """
    Decrypt a stored value, trying every key we have.

    Returns "" when the value is encrypted but no available key opens it --
    the key is gone and the user must re-enter the secret. Callers that need
    to tell that case apart from "nothing stored" should use is_unreadable().
    """
    if not stored:
        return stored
    if not stored.startswith(ENCRYPTED_PREFIX):
        # Plaintext value — not yet migrated
        return stored

    token = stored[len(ENCRYPTED_PREFIX):].encode("utf-8")
    keys = _decryption_keys()
    if not keys:
        logger.error(
            "A value is encrypted but no encryption key exists (%s is missing "
            "and the OS keychain has no entry). Re-enter the key in Settings.",
            _key_path(),
        )
        return ""

    for key in keys:
        try:
            return Fernet(key).decrypt(token).decode("utf-8")
        except InvalidToken:
            continue

    logger.error(
        "Stored value could not be decrypted with any of the %d available "
        "key(s) — the key it was encrypted with is gone. "
        "Re-enter the key in Settings to overwrite it.",
        len(keys),
    )
    return ""


def is_encrypted(value: str) -> bool:
    """Check if a stored value is already encrypted."""
    return value.startswith(ENCRYPTED_PREFIX) if value else False


def is_unreadable(stored: str) -> bool:
    """
    True when a value IS stored but cannot be decrypted.

    This is the case that looks identical to "no key configured" from the
    outside, which is what made the failure so hard to diagnose.
    """
    if not stored or not is_encrypted(stored):
        return False
    return not decrypt_value(stored)
