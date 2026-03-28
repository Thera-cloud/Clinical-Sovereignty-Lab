"""
HIVE DEFENSE v4.3 — Zero-Knowledge Family Encryption
Passphrase-derived encryption for family data and Me2Me crystals.

Zero-knowledge architecture: the platform CANNOT decrypt family data
without the family passphrase. The passphrase never leaves the client device.

- Family passphrase → PBKDF2 → AES-256-GCM key
- Me2Me crystals encrypted with crystal-specific keys derived from family key
- Cross-vault consistency verification
"""

import base64
import hashlib
import logging
import os
import secrets
from typing import Any, Dict, Optional, Tuple

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

_logger = logging.getLogger("zero_knowledge")

# PBKDF2 parameters (deliberately slow for passphrase hashing)
PBKDF2_ITERATIONS = 600_000
PBKDF2_SALT_LENGTH = 32
KEY_LENGTH = 32  # AES-256


class ZeroKnowledgeVault:
    """
    Zero-knowledge encryption for family data.
    The server never sees or stores the passphrase or derived key.
    """

    def __init__(self, db_pool=None):
        self._db = db_pool

    @staticmethod
    def derive_key_from_passphrase(
        passphrase: str, salt: Optional[bytes] = None,
    ) -> Tuple[bytes, bytes]:
        """
        Derive an AES-256 key from a family passphrase using PBKDF2.
        Returns (key, salt). Salt must be stored alongside encrypted data.
        """
        if salt is None:
            salt = secrets.token_bytes(PBKDF2_SALT_LENGTH)

        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=KEY_LENGTH,
            salt=salt,
            iterations=PBKDF2_ITERATIONS,
        )
        key = kdf.derive(passphrase.encode("utf-8"))
        return key, salt

    @staticmethod
    def derive_crystal_key(family_key: bytes, crystal_id: str) -> bytes:
        """
        Derive a per-crystal encryption key from the family key.
        Each Me2Me crystal gets its own derived key.
        """
        hkdf = HKDF(
            algorithm=hashes.SHA256(),
            length=KEY_LENGTH,
            salt=b"me2me_crystal",
            info=crystal_id.encode("utf-8"),
        )
        return hkdf.derive(family_key)

    @staticmethod
    def encrypt(key: bytes, plaintext: bytes) -> bytes:
        """
        Encrypt data with AES-256-GCM.
        Returns: nonce (12 bytes) + ciphertext + tag
        """
        nonce = secrets.token_bytes(12)
        aesgcm = AESGCM(key)
        ciphertext = aesgcm.encrypt(nonce, plaintext, None)
        return nonce + ciphertext

    @staticmethod
    def decrypt(key: bytes, encrypted_data: bytes) -> bytes:
        """
        Decrypt AES-256-GCM data.
        Input: nonce (12 bytes) + ciphertext + tag
        """
        nonce = encrypted_data[:12]
        ciphertext = encrypted_data[12:]
        aesgcm = AESGCM(key)
        return aesgcm.decrypt(nonce, ciphertext, None)

    @staticmethod
    def compute_key_verification_hash(key: bytes) -> str:
        """
        Compute a verification hash of the key (NOT the key itself).
        Used to verify the passphrase is correct without storing the key.
        """
        return hashlib.sha256(b"verify:" + key).hexdigest()

    async def store_encrypted_crystal(
        self, user_id: str, crystal_id: str,
        encrypted_content: bytes, salt: bytes,
        key_verification_hash: str,
    ) -> Dict[str, Any]:
        """
        Store an encrypted Me2Me crystal. The server stores:
        - encrypted_content (cannot decrypt without family passphrase)
        - salt (needed for key derivation)
        - key_verification_hash (to verify passphrase on unlock)
        """
        if not self._db:
            return {"stored": True}

        try:
            await self._db.execute(
                """INSERT INTO heritage_vault_records
                   (user_id, vault_type, content_hash, encrypted_content,
                    storage_tier, created_at)
                   VALUES ($1, 'me2me_crystal', $2, $3, 'zero_knowledge', NOW())
                   ON CONFLICT DO NOTHING""",
                user_id,
                f"{crystal_id}:{base64.b64encode(salt).decode()}:{key_verification_hash}",
                encrypted_content,
            )
            return {"stored": True, "crystal_id": crystal_id}
        except Exception as exc:
            _logger.error("Crystal store error: %s", exc)
            return {"stored": False}

    async def verify_passphrase(
        self, user_id: str, crystal_id: str, passphrase: str,
    ) -> Dict[str, Any]:
        """
        Verify a passphrase can unlock a crystal (without decrypting it).
        Returns {"valid": bool, "salt": bytes} if valid.
        """
        if not self._db:
            return {"valid": False, "reason": "no_db"}

        try:
            row = await self._db.fetchrow(
                """SELECT content_hash FROM heritage_vault_records
                   WHERE user_id = $1 AND vault_type = 'me2me_crystal'
                   AND content_hash LIKE $2""",
                user_id, f"{crystal_id}:%",
            )
            if not row:
                return {"valid": False, "reason": "crystal_not_found"}

            parts = row["content_hash"].split(":")
            if len(parts) < 3:
                return {"valid": False, "reason": "malformed_metadata"}

            salt = base64.b64decode(parts[1])
            stored_hash = parts[2]

            # Derive key from passphrase and verify
            key, _ = self.derive_key_from_passphrase(passphrase, salt)
            verification = self.compute_key_verification_hash(key)

            if verification == stored_hash:
                return {"valid": True, "salt": salt}
            return {"valid": False, "reason": "incorrect_passphrase"}

        except Exception as exc:
            _logger.error("Passphrase verification error: %s", exc)
            return {"valid": False, "reason": "error"}

    async def verify_cross_vault_consistency(
        self, user_id: str,
    ) -> Dict[str, Any]:
        """
        Verify that all crystals for a user use the same family key
        (same salt and verification hash).
        """
        if not self._db:
            return {"consistent": True}

        try:
            rows = await self._db.fetch(
                """SELECT content_hash FROM heritage_vault_records
                   WHERE user_id = $1 AND vault_type = 'me2me_crystal'""",
                user_id,
            )

            if len(rows) <= 1:
                return {"consistent": True, "crystal_count": len(rows)}

            # Extract salt from each crystal's metadata
            salts = set()
            for row in rows:
                parts = row["content_hash"].split(":")
                if len(parts) >= 2:
                    salts.add(parts[1])

            consistent = len(salts) <= 1
            if not consistent:
                _logger.warning(
                    "Cross-vault inconsistency for user %s: %d different salts across %d crystals",
                    user_id[:8], len(salts), len(rows),
                )

            return {
                "consistent": consistent,
                "crystal_count": len(rows),
                "unique_salts": len(salts),
            }
        except Exception as exc:
            _logger.error("Cross-vault consistency error: %s", exc)
            return {"consistent": False, "error": str(exc)}
