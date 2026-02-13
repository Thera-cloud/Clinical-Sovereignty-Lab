"""
SOVEREIGN SWARM — Identity Chain Service
Ed25519 keypair generation, hierarchical signing, and chain verification.
Phase 1E — P0 infrastructure that all Fibre operations depend on.

Architecture:
    Sovereign Mind (master key)
        └── signs Fibre public keys at spawn
            └── Fibres sign their own Mesh messages

    Verification: Any party can walk the chain back to the master key.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
from datetime import datetime
from typing import Any, Dict, Optional, Tuple
from uuid import UUID, uuid4

from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)
from cryptography.hazmat.primitives import serialization
from cryptography.exceptions import InvalidSignature

from app.services.exceptions import IdentityException, SecurityException


# =============================================================================
# KEY HELPERS
# =============================================================================

def _private_key_to_pem(key: Ed25519PrivateKey) -> str:
    """Serialize private key to PEM string."""
    return key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode()


def _public_key_to_pem(key: Ed25519PublicKey) -> str:
    """Serialize public key to PEM string."""
    return key.public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode()


def _public_key_from_pem(pem: str) -> Ed25519PublicKey:
    """Deserialize public key from PEM string."""
    return serialization.load_pem_public_key(pem.encode())


def _private_key_from_pem(pem: str) -> Ed25519PrivateKey:
    """Deserialize private key from PEM string."""
    return serialization.load_pem_private_key(pem.encode(), password=None)


# =============================================================================
# IDENTITY RECORD
# =============================================================================

class IdentityRecord:
    """Lightweight identity bundle for a Fibre or the Sovereign Mind."""

    def __init__(
        self,
        entity_id: UUID,
        public_key_pem: str,
        parent_signature: Optional[str] = None,
        parent_public_key_pem: Optional[str] = None,
        created_at: Optional[datetime] = None,
    ):
        self.entity_id = entity_id
        self.public_key_pem = public_key_pem
        self.parent_signature = parent_signature  # base64
        self.parent_public_key_pem = parent_public_key_pem
        self.created_at = created_at or datetime.utcnow()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "entity_id": str(self.entity_id),
            "public_key_pem": self.public_key_pem,
            "parent_signature": self.parent_signature,
            "parent_public_key_pem": self.parent_public_key_pem,
            "created_at": self.created_at.isoformat(),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "IdentityRecord":
        return cls(
            entity_id=UUID(data["entity_id"]),
            public_key_pem=data["public_key_pem"],
            parent_signature=data.get("parent_signature"),
            parent_public_key_pem=data.get("parent_public_key_pem"),
            created_at=datetime.fromisoformat(data["created_at"]) if data.get("created_at") else None,
        )


# =============================================================================
# IDENTITY CHAIN SERVICE
# =============================================================================

class IdentityChainService:
    """
    Manages Ed25519 identity hierarchy for the Sovereign Swarm.

    Usage:
        service = IdentityChainService()

        # Generate or load master key (Sovereign Mind)
        service.initialize_master_key()           # generates new
        service.load_master_key(pem_string)        # from env/vault

        # Spawn a Fibre identity
        record = service.create_fibre_identity(fibre_id)

        # Fibre signs a message
        signature = service.sign_message(private_key_pem, payload)

        # Verify message authenticity
        is_valid = service.verify_message(public_key_pem, payload, signature)

        # Verify full chain (Fibre -> Sovereign Mind)
        is_legit = service.verify_chain(record)
    """

    def __init__(self):
        self._master_private_key: Optional[Ed25519PrivateKey] = None
        self._master_public_key: Optional[Ed25519PublicKey] = None
        self._master_public_pem: Optional[str] = None
        self._master_id: UUID = uuid4()
        self._fibre_identities: Dict[UUID, IdentityRecord] = {}

    # ── Master Key Management ──

    def initialize_master_key(self) -> str:
        """Generate a new Sovereign Mind master keypair. Returns the private PEM (store securely!)."""
        self._master_private_key = Ed25519PrivateKey.generate()
        self._master_public_key = self._master_private_key.public_key()
        self._master_public_pem = _public_key_to_pem(self._master_public_key)
        print(f">>> [IDENTITY CHAIN] Master key generated. ID={self._master_id}")
        return _private_key_to_pem(self._master_private_key)

    def load_master_key(self, private_key_pem: str) -> None:
        """Load the Sovereign Mind master key from a PEM string (from .env / Azure Key Vault)."""
        try:
            self._master_private_key = _private_key_from_pem(private_key_pem)
            self._master_public_key = self._master_private_key.public_key()
            self._master_public_pem = _public_key_to_pem(self._master_public_key)
            print(f">>> [IDENTITY CHAIN] Master key loaded. ID={self._master_id}")
        except Exception as e:
            raise IdentityException(
                entity_id=self._master_id,
                reason=f"Failed to load master key: {e}",
            )

    @property
    def master_public_pem(self) -> str:
        if not self._master_public_pem:
            raise IdentityException(reason="Master key not initialized")
        return self._master_public_pem

    # ── Fibre Identity ──

    def create_fibre_identity(self, fibre_id: UUID) -> Tuple[IdentityRecord, str]:
        """
        Generate a new Ed25519 keypair for a Fibre and sign the public key with the master key.
        Returns (IdentityRecord, private_key_pem).
        The private key should be securely stored — it is NOT kept in this service.
        """
        if not self._master_private_key:
            raise IdentityException(reason="Master key not initialized — cannot sign Fibre identities")

        # Generate Fibre keypair
        fibre_private = Ed25519PrivateKey.generate()
        fibre_public = fibre_private.public_key()
        fibre_public_pem = _public_key_to_pem(fibre_public)

        # Master signs the Fibre's public key
        signature_bytes = self._master_private_key.sign(fibre_public_pem.encode())
        signature_b64 = base64.b64encode(signature_bytes).decode()

        record = IdentityRecord(
            entity_id=fibre_id,
            public_key_pem=fibre_public_pem,
            parent_signature=signature_b64,
            parent_public_key_pem=self._master_public_pem,
        )
        self._fibre_identities[fibre_id] = record

        print(f">>> [IDENTITY CHAIN] Fibre identity created: {fibre_id}")
        return record, _private_key_to_pem(fibre_private)

    def get_fibre_identity(self, fibre_id: UUID) -> Optional[IdentityRecord]:
        return self._fibre_identities.get(fibre_id)

    # ── Signing ──

    @staticmethod
    def sign_message(private_key_pem: str, payload: Dict[str, Any]) -> str:
        """Sign an arbitrary JSON-serializable payload. Returns base64 signature."""
        private_key = _private_key_from_pem(private_key_pem)
        canonical = json.dumps(payload, sort_keys=True, default=str).encode()
        signature = private_key.sign(canonical)
        return base64.b64encode(signature).decode()

    @staticmethod
    def verify_message(public_key_pem: str, payload: Dict[str, Any], signature_b64: str) -> bool:
        """Verify a signed payload. Returns True if valid."""
        try:
            public_key = _public_key_from_pem(public_key_pem)
            canonical = json.dumps(payload, sort_keys=True, default=str).encode()
            sig_bytes = base64.b64decode(signature_b64)
            public_key.verify(sig_bytes, canonical)
            return True
        except (InvalidSignature, Exception):
            return False

    # ── Chain Verification ──

    def verify_chain(self, record: IdentityRecord) -> bool:
        """
        Walk the identity chain from Fibre → Sovereign Mind.
        Confirms that the parent (master) signed the Fibre's public key.
        """
        if not record.parent_signature or not record.parent_public_key_pem:
            return False

        try:
            parent_pub = _public_key_from_pem(record.parent_public_key_pem)
            sig_bytes = base64.b64decode(record.parent_signature)
            parent_pub.verify(sig_bytes, record.public_key_pem.encode())

            # Optionally confirm the parent IS the master
            if self._master_public_pem and record.parent_public_key_pem != self._master_public_pem:
                # In a deeper hierarchy, we would recurse. For now, single-level.
                return False

            return True
        except InvalidSignature:
            return False
        except Exception:
            return False

    # ── Utilities ──

    @staticmethod
    def fingerprint(public_key_pem: str) -> str:
        """SHA-256 fingerprint of a public key (for logging, not security)."""
        return hashlib.sha256(public_key_pem.encode()).hexdigest()[:16]

    def revoke_fibre_identity(self, fibre_id: UUID) -> bool:
        """Remove a Fibre's identity from the registry (part of pruning)."""
        if fibre_id in self._fibre_identities:
            del self._fibre_identities[fibre_id]
            print(f">>> [IDENTITY CHAIN] Fibre identity revoked: {fibre_id}")
            return True
        return False
