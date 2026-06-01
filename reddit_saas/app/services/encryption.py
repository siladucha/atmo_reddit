"""Field encryption service — encrypts sensitive model fields at rest.

Uses Fernet symmetric encryption (AES-128-CBC with HMAC-SHA256).
Key sourced from FIELD_ENCRYPTION_KEY environment variable.

Usage:
    from app.services.encryption import get_encryptor

    enc = get_encryptor()
    ciphertext = enc.encrypt("my_secret_password")
    plaintext = enc.decrypt(ciphertext)
"""

import logging
import os
from functools import lru_cache

from cryptography.fernet import Fernet, InvalidToken

logger = logging.getLogger(__name__)


class FieldEncryptor:
    """Encrypts/decrypts sensitive model fields using Fernet (AES-128-CBC + HMAC)."""

    def __init__(self, key: str | bytes):
        """Initialize with a Fernet key.

        Args:
            key: Base64-encoded 32-byte key. Generate via Fernet.generate_key().
        """
        if isinstance(key, str):
            key = key.encode()
        self._fernet = Fernet(key)

    def encrypt(self, plaintext: str) -> str:
        """Encrypt a plaintext string, return base64 ciphertext."""
        if not plaintext:
            raise ValueError("Cannot encrypt empty string")
        return self._fernet.encrypt(plaintext.encode()).decode()

    def decrypt(self, ciphertext: str) -> str:
        """Decrypt a ciphertext string, return plaintext.

        Raises:
            InvalidToken: If the ciphertext is invalid or the key is wrong.
        """
        if not ciphertext:
            raise ValueError("Cannot decrypt empty string")
        return self._fernet.decrypt(ciphertext.encode()).decode()

    def is_valid_ciphertext(self, ciphertext: str) -> bool:
        """Check if a string is valid Fernet ciphertext (without decrypting)."""
        try:
            self.decrypt(ciphertext)
            return True
        except (InvalidToken, ValueError):
            return False


@lru_cache(maxsize=1)
def get_encryptor() -> FieldEncryptor:
    """Get the singleton FieldEncryptor instance.

    Key is read from FIELD_ENCRYPTION_KEY environment variable.
    If not set, generates a key and logs a warning (dev mode only).
    """
    key = os.environ.get("FIELD_ENCRYPTION_KEY")
    if not key:
        # Development fallback — generate ephemeral key
        # WARNING: Data encrypted with this key will be unreadable after restart
        logger.warning(
            "FIELD_ENCRYPTION_KEY not set — using ephemeral key. "
            "Encrypted data will be lost on restart. Set FIELD_ENCRYPTION_KEY in .env for production."
        )
        key = Fernet.generate_key().decode()
    return FieldEncryptor(key)


def generate_encryption_key() -> str:
    """Generate a new Fernet encryption key (for .env setup).

    Run: python -c "from app.services.encryption import generate_encryption_key; print(generate_encryption_key())"
    """
    return Fernet.generate_key().decode()
