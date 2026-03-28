"""
HIVE DEFENSE v4.3 — Sovereign Layer
Hardware-rooted key management hierarchy and AES-256-GCM encryption.

Key Hierarchy:
  Level 0: Master Key (YubiKey PIV / hardware token)
  Level 1: Category keys (derived via HKDF-SHA256)
  Level 2: Per-record keys (derived via HKDF-SHA256 from category key)

Categories: clinical, financial, family, heritage, infrastructure
"""

import base64
import hashlib
import logging
import os
import secrets
from typing import Any, Dict, Optional, Tuple

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

_logger = logging.getLogger("sovereign_layer")

# Key categories for HKDF derivation
KEY_CATEGORIES = {
    "clinical": b"sovereign:clinical:v1",
    "financial": b"sovereign:financial:v1",
    "family": b"sovereign:family:v1",
    "heritage": b"sovereign:heritage:v1",
    "infrastructure": b"sovereign:infrastructure:v1",
}


class SovereignKeyManager:
    """
    Hardware-rooted key management with HKDF-SHA256 derivation.

    In production, Level 0 master key lives in a hardware security module
    (YubiKey PIV or Nitrokey). For development, it falls back to an
    environment variable.
    """

    def __init__(self):
        self._master_key: Optional[bytes] = None
        self._category_keys: Dict[str, bytes] = {}
        self._initialized = False

    def initialize(self, master_key: Optional[bytes] = None) -> None:
        """
        Initialize the key manager.
        In production: master_key comes from hardware token.
        In dev: falls back to SOVEREIGN_MASTER_KEY env var or generates ephemeral.
        """
        if master_key:
            self._master_key = master_key
        else:
            env_key = os.getenv("SOVEREIGN_MASTER_KEY")
            if env_key:
                self._master_key = base64.b64decode(env_key)
            else:
                _logger.warning("No master key configured — generating ephemeral key (dev only)")
                self._master_key = secrets.token_bytes(32)

        # Derive category keys
        for category, info in KEY_CATEGORIES.items():
            self._category_keys[category] = self._derive_key(
                self._master_key, info, b"category"
            )

        self._initialized = True
        _logger.info("SovereignKeyManager initialized: %d categories", len(self._category_keys))

    def derive_record_key(self, category: str, record_id: str) -> bytes:
        """Derive a per-record AES-256 key from the category key."""
        if not self._initialized:
            raise RuntimeError("SovereignKeyManager not initialized")

        category_key = self._category_keys.get(category)
        if not category_key:
            raise ValueError(f"Unknown key category: {category}")

        return self._derive_key(
            category_key,
            record_id.encode(),
            b"record",
        )

    def encrypt(self, category: str, record_id: str, plaintext: bytes) -> bytes:
        """
        Encrypt data with AES-256-GCM using a per-record derived key.
        Returns: nonce (12 bytes) + ciphertext + tag
        """
        key = self.derive_record_key(category, record_id)
        nonce = secrets.token_bytes(12)
        aesgcm = AESGCM(key)
        ciphertext = aesgcm.encrypt(nonce, plaintext, None)
        return nonce + ciphertext

    def decrypt(self, category: str, record_id: str, encrypted_data: bytes) -> bytes:
        """
        Decrypt AES-256-GCM encrypted data.
        Input: nonce (12 bytes) + ciphertext + tag
        """
        key = self.derive_record_key(category, record_id)
        nonce = encrypted_data[:12]
        ciphertext = encrypted_data[12:]
        aesgcm = AESGCM(key)
        return aesgcm.decrypt(nonce, ciphertext, None)

    @staticmethod
    def _derive_key(parent_key: bytes, info: bytes, salt: bytes) -> bytes:
        """Derive a 256-bit key using HKDF-SHA256."""
        hkdf = HKDF(
            algorithm=hashes.SHA256(),
            length=32,
            salt=salt,
            info=info,
        )
        return hkdf.derive(parent_key)

    def get_category_key_id(self, category: str) -> str:
        """Get a non-secret identifier for a category key (for audit logging)."""
        if category not in self._category_keys:
            return "unknown"
        return hashlib.sha256(self._category_keys[category]).hexdigest()[:16]

    def is_initialized(self) -> bool:
        """Check if the key manager is ready."""
        return self._initialized
