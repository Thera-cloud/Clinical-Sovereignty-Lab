"""
Field-Level Encryption for Sensitive JSONB Data

Encrypts/decrypts specific fields within JSONB payloads before they are
persisted to PostgreSQL. Used for voice biometrics, trigger contexts,
and other PII-sensitive therapy data stored at rest.

The encryption key is derived from the FIELD_ENCRYPTION_KEY env var.
If not set, falls back to a derivation from JWT_SECRET for backward
compatibility, then to a warning-mode passthrough (no encryption).

Usage:
    from app.field_encryption import encrypt_fields, decrypt_fields

    # Before INSERT:
    safe_json = encrypt_fields({"trigger_context": "sensitive...", "avg_p_ent": 0.5})

    # After SELECT:
    clear_json = decrypt_fields(safe_json)
"""

import base64
import hashlib
import json
import logging
import os
from typing import Any, Dict, Optional, Set

logger = logging.getLogger(__name__)

# Fields that should be encrypted when persisted to PostgreSQL JSONB
ENCRYPTED_FIELDS: Set[str] = frozenset({
    "trigger_context",
    "pitch_mean", "pitch_variance",
    "energy", "speech_rate", "pause_ratio",
    "voice_stress", "voice_warmth",
    "biometric_raw",
})

_fernet = None
_passthrough = False


def _get_fernet():
    """Lazy-init Fernet cipher from env key."""
    global _fernet, _passthrough
    if _fernet is not None or _passthrough:
        return _fernet

    key_material = (
        os.environ.get("FIELD_ENCRYPTION_KEY")
        or os.environ.get("JWT_SECRET")
    )
    if not key_material:
        logger.warning("[FIELD_ENCRYPTION] No FIELD_ENCRYPTION_KEY or JWT_SECRET — "
                       "biometric data will NOT be encrypted at rest!")
        _passthrough = True
        return None

    try:
        from cryptography.fernet import Fernet
        # Derive a 32-byte key from the material, then base64-encode for Fernet
        derived = hashlib.sha256(key_material.encode("utf-8")).digest()
        fernet_key = base64.urlsafe_b64encode(derived)
        _fernet = Fernet(fernet_key)
        logger.info("[FIELD_ENCRYPTION] Fernet cipher initialized for biometric field encryption")
    except Exception as e:
        logger.error(f"[FIELD_ENCRYPTION] Failed to init Fernet: {e}")
        _passthrough = True
    return _fernet


def encrypt_value(value: Any) -> str:
    """Encrypt a single value, returning a prefixed ciphertext string."""
    f = _get_fernet()
    if f is None:
        return value  # Passthrough
    plaintext = json.dumps(value).encode("utf-8")
    return "ENC:" + f.encrypt(plaintext).decode("utf-8")


def decrypt_value(value: Any) -> Any:
    """Decrypt a single value if it bears the ENC: prefix."""
    if not isinstance(value, str) or not value.startswith("ENC:"):
        return value
    f = _get_fernet()
    if f is None:
        return value  # Can't decrypt without key
    try:
        ciphertext = value[4:].encode("utf-8")
        plaintext = f.decrypt(ciphertext)
        return json.loads(plaintext)
    except Exception as e:
        logger.warning(f"[FIELD_ENCRYPTION] Decrypt failed: {e}")
        return value  # Return encrypted blob rather than crash


def encrypt_fields(data: Dict[str, Any]) -> Dict[str, Any]:
    """Encrypt sensitive fields in a dictionary before DB persistence."""
    if not data or _passthrough:
        return data
    result = dict(data)
    for key in ENCRYPTED_FIELDS:
        if key in result and result[key] is not None:
            result[key] = encrypt_value(result[key])
    return result


def decrypt_fields(data: Dict[str, Any]) -> Dict[str, Any]:
    """Decrypt sensitive fields after reading from DB."""
    if not data:
        return data
    result = dict(data)
    for key in ENCRYPTED_FIELDS:
        if key in result:
            result[key] = decrypt_value(result[key])
    return result
