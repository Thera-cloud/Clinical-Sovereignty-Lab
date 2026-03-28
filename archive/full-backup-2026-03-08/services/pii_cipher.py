"""
PII Field Encryption — Fernet symmetric (AES-128-CBC + HMAC-SHA256).

Encrypts email, phone, and conversation content at the application layer
before writing to PostgreSQL. Decrypts on read.

Uses SKYEYE_TOKEN_ENCRYPTION_KEY (same key as TokenCipher) for simplicity.
If no key is set, passes data through in plaintext with a warning.
"""

import logging
import os
from typing import Optional

logger = logging.getLogger(__name__)

_ENCRYPTION_KEY = os.getenv("SKYEYE_TOKEN_ENCRYPTION_KEY", "")
_fernet = None
_warned = False


def _get_fernet():
    global _fernet, _warned
    if _fernet is not None:
        return _fernet
    if not _ENCRYPTION_KEY:
        if not _warned:
            logger.warning("PII encryption disabled — SKYEYE_TOKEN_ENCRYPTION_KEY not set")
            _warned = True
        return None
    try:
        from cryptography.fernet import Fernet
        _fernet = Fernet(_ENCRYPTION_KEY.encode() if isinstance(_ENCRYPTION_KEY, str) else _ENCRYPTION_KEY)
        return _fernet
    except Exception as e:
        if not _warned:
            logger.warning("PII encryption init failed: %s", e)
            _warned = True
        return None


def encrypt_pii(value: Optional[str]) -> Optional[str]:
    """Encrypt a PII field. Returns encrypted string or original if no key."""
    if not value:
        return value
    f = _get_fernet()
    if f is None:
        return value
    try:
        return f.encrypt(value.encode()).decode()
    except Exception as e:
        logger.warning("PII encrypt failed: %s", e)
        return value


def decrypt_pii(value: Optional[str]) -> Optional[str]:
    """Decrypt a PII field. Auto-detects plaintext (not starting with gAAAAA)."""
    if not value:
        return value
    if not value.startswith("gAAAAA"):
        return value
    f = _get_fernet()
    if f is None:
        return value
    try:
        return f.decrypt(value.encode()).decode()
    except Exception as e:
        logger.warning("PII decrypt failed (returning raw): %s", e)
        return value


def is_encrypted(value: Optional[str]) -> bool:
    """Check if a value appears to be Fernet-encrypted."""
    return bool(value and value.startswith("gAAAAA"))
