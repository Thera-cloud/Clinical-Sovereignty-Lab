"""
PII Field Encryption — Fernet symmetric (AES-128-CBC + HMAC-SHA256).

Encrypts email, phone, and conversation content at the application layer
before writing to PostgreSQL. Decrypts on read.

Uses SKYEYE_TOKEN_ENCRYPTION_KEY (same key as TokenCipher) for simplicity.

Fail-closed policy (Slice 0.5):
- In production (ENVIRONMENT=production) or when ENCRYPTION_STRICT=true, a
  missing / invalid key raises PIIEncryptionError instead of silently
  passing plaintext through. This is required by Exhibit G / BAA §6.2 —
  Little Nate is under contract not to store conversation content or PII
  in the clear.
- In dev / test / staging, the historic passthrough behavior is preserved
  so local runs don't need a key configured.
"""

import logging
import os
from typing import Optional

logger = logging.getLogger(__name__)

_ENCRYPTION_KEY = os.getenv("SKYEYE_TOKEN_ENCRYPTION_KEY", "")
_ENVIRONMENT = (os.getenv("ENVIRONMENT") or "").strip().lower()
_STRICT_OVERRIDE = (os.getenv("ENCRYPTION_STRICT") or "").strip().lower()

if _STRICT_OVERRIDE in ("true", "1", "yes", "on"):
    _STRICT = True
elif _STRICT_OVERRIDE in ("false", "0", "no", "off"):
    _STRICT = False
else:
    _STRICT = _ENVIRONMENT == "production"

_fernet = None
_warned = False


class PIIEncryptionError(RuntimeError):
    """Raised in strict mode when PII cannot be encrypted/decrypted safely."""


def _get_fernet():
    global _fernet, _warned
    if _fernet is not None:
        return _fernet
    if not _ENCRYPTION_KEY:
        if not _warned:
            if _STRICT:
                logger.error(
                    "PII encryption DISABLED in strict mode — "
                    "SKYEYE_TOKEN_ENCRYPTION_KEY not set. Writes will fail."
                )
            else:
                logger.warning("PII encryption disabled — SKYEYE_TOKEN_ENCRYPTION_KEY not set")
            _warned = True
        return None
    try:
        from cryptography.fernet import Fernet
        _fernet = Fernet(_ENCRYPTION_KEY.encode() if isinstance(_ENCRYPTION_KEY, str) else _ENCRYPTION_KEY)
        return _fernet
    except Exception as e:
        if not _warned:
            logger.error("PII encryption init failed: %s", e)
            _warned = True
        return None


def encrypt_pii(value: Optional[str]) -> Optional[str]:
    """Encrypt a PII field.

    Strict mode: raises PIIEncryptionError if the key is missing or
    encryption fails. Non-strict mode: returns the original plaintext
    (legacy dev/test behavior).
    """
    if not value:
        return value
    f = _get_fernet()
    if f is None:
        if _STRICT:
            raise PIIEncryptionError(
                "encrypt_pii called in strict mode without a valid encryption key"
            )
        return value
    try:
        return f.encrypt(value.encode()).decode()
    except Exception as e:
        if _STRICT:
            logger.error("PII encrypt failed in strict mode: %s", e)
            raise PIIEncryptionError(f"encrypt_pii failed: {e}") from e
        logger.warning("PII encrypt failed: %s", e)
        return value


def decrypt_pii(value: Optional[str]) -> Optional[str]:
    """Decrypt a PII field. Auto-detects plaintext (not starting with gAAAAA).
    NEVER returns raw ciphertext — returns a safe placeholder on failure."""
    if not value:
        return value
    if not value.startswith("gAAAAA"):
        return value
    f = _get_fernet()
    if f is None:
        logger.warning("PII decrypt skipped — no encryption key available")
        return "[encrypted — key unavailable]"
    try:
        return f.decrypt(value.encode()).decode()
    except Exception as e:
        logger.warning("PII decrypt failed for value len=%d: %s", len(value), e)
        return "[encrypted — decrypt failed]"


def is_encrypted(value: Optional[str]) -> bool:
    """Check if a value appears to be Fernet-encrypted."""
    return bool(value and value.startswith("gAAAAA"))


def is_strict_mode() -> bool:
    """Whether PII encryption is running in fail-closed strict mode."""
    return _STRICT
