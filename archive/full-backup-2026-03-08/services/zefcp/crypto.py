"""
ZEFCP Crypto — Observation encryption and authenticity.
Patent Claim 25.6: Zero-Energy BLE Communication — Authenticated encryption
for fibre observations using HKDF key derivation, AES-128-CTR, and Ed25519.
"""

from __future__ import annotations

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from app.services.zefcp.constants import KEY_DERIVATION_INFO_PREFIX, KEY_LENGTH_BYTES, NONCE_LENGTH_BYTES


# =============================================================================
# FIBRE FRAGMENT CRYPTO
# =============================================================================


class FibreFragmentCrypto:
    """
    Encrypts, decrypts, and authenticates fibre observation payloads.
    Patent Claim 25.6: Observation-level keys derived via HKDF; AES-128-CTR
    with nonce from observation identity; Ed25519 for authenticity.
    """

    def __init__(self, swarm_secret: bytes) -> None:
        """
        Initialize with the shared swarm secret (NFC-provisioned).
        """
        self._swarm_secret = swarm_secret

    def derive_observation_key(self, observation_id: bytes) -> bytes:
        """
        Derive a 128-bit AES key for a specific observation.
        Patent Claim 25.6: HKDF-SHA256 with salt=swarm_secret,
        info=b'fibre-obs-' + observation_id, length=16.
        """
        hkdf = HKDF(
            algorithm=hashes.SHA256(),
            length=KEY_LENGTH_BYTES,
            salt=self._swarm_secret,
            info=KEY_DERIVATION_INFO_PREFIX + observation_id,
        )
        return hkdf.derive(self._swarm_secret)

    def encrypt_payload(
        self,
        plaintext: bytes,
        observation_id: bytes,
    ) -> bytes:
        """
        Encrypt plaintext with AES-128-CTR.
        Patent Claim 25.6: Nonce = SHA256(observation_id)[:16].
        """
        key = self.derive_observation_key(observation_id)
        digest = hashes.Hash(hashes.SHA256())
        digest.update(observation_id)
        nonce = digest.finalize()[:NONCE_LENGTH_BYTES]
        cipher = Cipher(algorithms.AES(key), modes.CTR(nonce))
        encryptor = cipher.encryptor()
        return encryptor.update(plaintext) + encryptor.finalize()

    def decrypt_payload(
        self,
        ciphertext: bytes,
        observation_id: bytes,
    ) -> bytes:
        """
        Decrypt ciphertext (inverse of encrypt_payload).
        Patent Claim 25.6: Same nonce derivation as encryption.
        """
        key = self.derive_observation_key(observation_id)
        digest = hashes.Hash(hashes.SHA256())
        digest.update(observation_id)
        nonce = digest.finalize()[:NONCE_LENGTH_BYTES]
        cipher = Cipher(algorithms.AES(key), modes.CTR(nonce))
        decryptor = cipher.decryptor()
        return decryptor.update(ciphertext) + decryptor.finalize()

    def verify_observation(
        self,
        observation_data: bytes,
        signature: bytes,
        fibre_public_key: bytes,
    ) -> bool:
        """
        Verify Ed25519 signature over observation data.
        Patent Claim 25.6: Fibre authenticates observations with its
        NFC-provisioned keypair. Returns True if valid.
        """
        try:
            public_key = Ed25519PublicKey.from_public_bytes(fibre_public_key)
            public_key.verify(signature, observation_data)
            return True
        except InvalidSignature:
            return False

    def sign_observation(
        self,
        observation_data: bytes,
        private_key_bytes: bytes,
    ) -> bytes:
        """
        Sign observation data with Ed25519 private key.
        Patent Claim 25.6: Fibre signs each observation before fragmentation.
        """
        private_key = Ed25519PrivateKey.from_private_bytes(private_key_bytes)
        return private_key.sign(observation_data)
