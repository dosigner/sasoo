"""
Sasoo - API Key Encryption Utility
Encrypts/decrypts API keys stored in SQLite using Fernet symmetric encryption.
The encryption key is stored in the OS keychain via the `keyring` library.
"""

import logging
import os
import sys
from typing import Optional

from cryptography.fernet import Fernet, InvalidToken

logger = logging.getLogger(__name__)

# Keyring service/account identifiers
_KEYRING_SERVICE = "sasoo-desktop"
_KEYRING_ACCOUNT = "fernet-key"

# Prefix to distinguish encrypted values from plaintext in the DB
ENCRYPTED_PREFIX = "enc:v1:"


def _get_or_create_fernet_key() -> bytes:
    """
    Retrieve the Fernet key from the OS keychain, or generate and store one.
    Falls back to a file-based key if keyring is unavailable.
    """
    if not _should_use_os_keyring():
        return _get_or_create_file_key()

    try:
        import keyring as kr

        stored = kr.get_password(_KEYRING_SERVICE, _KEYRING_ACCOUNT)
        if stored:
            return stored.encode("utf-8")

        # Generate a new key and store it
        new_key = Fernet.generate_key()
        kr.set_password(_KEYRING_SERVICE, _KEYRING_ACCOUNT, new_key.decode("utf-8"))
        logger.info("Generated new Fernet key and stored in OS keychain")
        return new_key
    except Exception as exc:
        logger.warning("Keyring unavailable (%s), falling back to file-based key", exc)
        return _get_or_create_file_key()


def _should_use_os_keyring() -> bool:
    """
    Use OS keyring only when explicitly enabled or during development.

    Packaged desktop builds prefer a local file-based key because keyring
    backends can block or fail inside bundled Python subprocesses on macOS.
    """
    explicit = os.environ.get("SASOO_USE_OS_KEYRING")
    if explicit is not None:
        return explicit.strip().lower() in {"1", "true", "yes", "on"}

    if os.environ.get("SASOO_DISABLE_OS_KEYRING", "").strip().lower() in {"1", "true", "yes", "on"}:
        return False

    is_packaged_desktop = bool(getattr(sys, "frozen", False)) or os.environ.get("SASOO_ENV") == "production"
    return not is_packaged_desktop


def _get_or_create_file_key() -> bytes:
    """Fallback: store the Fernet key in a file with restricted permissions."""
    from models.database import APP_DATA_ROOT

    key_file = APP_DATA_ROOT / ".sasoo_key"
    if key_file.exists():
        return key_file.read_bytes().strip()

    new_key = Fernet.generate_key()
    APP_DATA_ROOT.mkdir(parents=True, exist_ok=True)
    key_file.write_bytes(new_key)

    # Restrict permissions on Windows
    if os.name == "nt":
        try:
            import subprocess
            subprocess.run(
                ["icacls", str(key_file), "/inheritance:r", "/grant:r",
                 f"{os.environ.get('USERNAME', 'CURRENT_USER')}:(R,W)"],
                capture_output=True, check=False,
            )
        except Exception:
            pass

    logger.info("Generated new Fernet key and stored in file: %s", key_file)
    return new_key


def _get_fernet() -> Fernet:
    """Return a Fernet instance with the current key."""
    key = _get_or_create_fernet_key()
    return Fernet(key)


def encrypt_value(plaintext: str) -> str:
    """Encrypt a plaintext value. Returns prefixed encrypted string."""
    if not plaintext:
        return plaintext
    f = _get_fernet()
    token = f.encrypt(plaintext.encode("utf-8"))
    return ENCRYPTED_PREFIX + token.decode("utf-8")


def decrypt_value(stored: str) -> str:
    """
    Decrypt a stored value.
    If the value is not encrypted (no prefix), returns it as-is (plaintext migration).
    """
    if not stored:
        return stored
    if not stored.startswith(ENCRYPTED_PREFIX):
        # Plaintext value — not yet migrated
        return stored
    token = stored[len(ENCRYPTED_PREFIX):]
    f = _get_fernet()
    try:
        return f.decrypt(token.encode("utf-8")).decode("utf-8")
    except InvalidToken:
        logger.error("Failed to decrypt value — key may have changed")
        return ""


def is_encrypted(value: str) -> bool:
    """Check if a stored value is already encrypted."""
    return value.startswith(ENCRYPTED_PREFIX) if value else False
