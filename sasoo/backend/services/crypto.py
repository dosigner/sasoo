"""
Sasoo - API Key Encryption Utility
Encrypts/decrypts API keys stored in SQLite using Fernet symmetric encryption.

The key lives in a file next to the database (`<library>/.sasoo_key`, mode 0600).
It used to depend on how the app was launched -- OS keychain in development,
file in packaged builds -- which meant a key written by one mode was unreadable
by the other, and the app reported "no API key" with no way to tell that a key
was in fact stored. Encryption now always uses the file key, which both modes
can reach, while decryption still accepts keys from the OS keychain so that
values written by older builds keep working.

Decryption never creates a key. The previous code did, so a read against a
cleared keychain would quietly mint a fresh key and then fail to decrypt with
it, permanently masking the fact that the original key was gone.
"""

import logging
import os
from typing import Optional

from cryptography.fernet import Fernet, InvalidToken

logger = logging.getLogger(__name__)

# Keyring service/account identifiers
_KEYRING_SERVICE = "sasoo-desktop"
_KEYRING_ACCOUNT = "fernet-key"

# Prefix to distinguish encrypted values from plaintext in the DB
ENCRYPTED_PREFIX = "enc:v1:"

_KEY_FILENAME = ".sasoo_key"


# ---------------------------------------------------------------------------
# Key stores
# ---------------------------------------------------------------------------

def _key_path():
    from models.database import APP_DATA_ROOT

    return APP_DATA_ROOT / _KEY_FILENAME


def _read_file_key() -> Optional[bytes]:
    """Read the on-disk key. Never creates one."""
    path = _key_path()
    if not path.exists():
        return None
    key = path.read_bytes().strip()
    return key or None


def _create_file_key() -> bytes:
    """Generate the on-disk key with owner-only permissions."""
    path = _key_path()
    new_key = Fernet.generate_key()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(new_key)

    if os.name == "nt":
        try:
            import subprocess

            subprocess.run(
                ["icacls", str(path), "/inheritance:r", "/grant:r",
                 f"{os.environ.get('USERNAME', 'CURRENT_USER')}:(R,W)"],
                capture_output=True, check=False,
            )
        except Exception:
            logger.warning("Could not restrict permissions on %s", path)
    else:
        try:
            os.chmod(path, 0o600)
        except OSError:
            logger.warning("Could not chmod 0600 on %s", path)

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
    except Exception as exc:
        logger.debug("Keyring unavailable: %s", exc)
        return None
    return stored.encode("utf-8") if stored else None


def _prefer_os_keyring() -> bool:
    """Opt in to encrypting with the OS keychain instead of the file key."""
    explicit = os.environ.get("SASOO_USE_OS_KEYRING", "")
    return explicit.strip().lower() in {"1", "true", "yes", "on"}


def _encryption_key() -> bytes:
    """The key NEW values are encrypted with. Creates one if none exists."""
    if _prefer_os_keyring():
        existing = _read_keyring_key()
        if existing:
            return existing
        new_key = Fernet.generate_key()
        try:
            import keyring as kr

            kr.set_password(_KEYRING_SERVICE, _KEYRING_ACCOUNT, new_key.decode("utf-8"))
            logger.info("Generated new Fernet key in the OS keychain")
            return new_key
        except Exception as exc:
            logger.warning("Could not write to keyring (%s); using file key", exc)

    return _read_file_key() or _create_file_key()


def _decryption_keys() -> list[bytes]:
    """Every key a stored value might have been encrypted with. No side effects."""
    keys: list[bytes] = []
    for candidate in (_read_file_key(), _read_keyring_key()):
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
