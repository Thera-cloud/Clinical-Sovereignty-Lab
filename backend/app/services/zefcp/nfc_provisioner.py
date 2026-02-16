"""
ZEFCP NFC Provisioner — NFC tap-to-onboard device provisioning.
Patent Claim 25.7: Zero-Energy BLE Communication — NFC tap transfers
swarm secret and identity credentials; short range (<4cm) ensures
provisioning cannot be intercepted remotely.
"""

from __future__ import annotations

from typing import Any, List, Optional

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from app.models.zefcp import BLETransportConfig, NFCProvisioningPayload
from app.services.zefcp.constants import KEY_LENGTH_BYTES, NONCE_LENGTH_BYTES


# =============================================================================
# NFC PROVISIONER
# =============================================================================


class NFCProvisioner:
    """
    Provisions devices via NFC tap for Zero-Energy BLE transport.
    Patent Claim 25.7: Generates device keypair, signs with Sovereign Mind,
    encrypts swarm secret for device-only decryption.
    """

    def __init__(
        self,
        swarm_secret: bytes,
        sovereign_mind_private_key: bytes,
        default_config: Optional[Any] = None,
    ) -> None:
        """
        Initialize with swarm secret and Sovereign Mind signing key.

        Args:
            swarm_secret: Shared secret for ZEFCP transport (encrypted for device).
            sovereign_mind_private_key: Ed25519 private key bytes for signing.
            default_config: Optional BLETransportConfig; uses default if None.
        """
        self._swarm_secret = swarm_secret
        self._sovereign_private = Ed25519PrivateKey.from_private_bytes(
            sovereign_mind_private_key
        )
        self._default_config = default_config or BLETransportConfig()

    async def provision_device(
        self,
        device_id: str,
        domain_tags: Optional[List[str]] = None,
    ) -> NFCProvisioningPayload:
        """
        Generate provisioning payload for a device via NFC tap.
        Patent Claim 25.7: Ed25519 keypair for device, sign device_id with
        Sovereign Mind key, encrypt swarm secret for device.

        Args:
            device_id: Unique device identifier.
            domain_tags: Optional domain tags for mesh routing.

        Returns:
            NFCProvisioningPayload ready for NFC transfer.
        """
        # Generate Ed25519 keypair for device
        device_private = Ed25519PrivateKey.generate()
        device_private_bytes = device_private.private_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PrivateFormat.Raw,
            encryption_algorithm=serialization.NoEncryption(),
        )
        device_public_bytes = device_private.public_key().public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw,
        )

        # Sign device_id with Sovereign Mind key
        identity_signature = self._sovereign_private.sign(device_id.encode())

        # Encrypt swarm secret for device (key derivable only by device)
        swarm_secret_encrypted = self._encrypt_for_device(
            self._swarm_secret,
            device_id=device_id,
            device_private_bytes=device_private_bytes,
        )

        return NFCProvisioningPayload(
            device_id=device_id,
            swarm_secret_encrypted=swarm_secret_encrypted,
            identity_signature=identity_signature,
            transport_config=self._default_config.model_copy(),
            device_keypair_seed=device_private_bytes,
            observation_key_material=b"",
            mesh_endpoint_config={"device_public_key": device_public_bytes.hex()},
            assigned_domain_tags=domain_tags or [],
        )

    async def provision_session_batch(
        self,
        session_id: str,
        device_ids: List[str],
    ) -> List[NFCProvisioningPayload]:
        """
        Provision multiple devices for a Family Sanctuary session.
        Patent Claim 25.7.

        Args:
            session_id: Session identifier (for logging/tracking).
            device_ids: List of device IDs to provision.

        Returns:
            List of NFCProvisioningPayload, one per device.
        """
        payloads = []
        for device_id in device_ids:
            payload = await self.provision_device(device_id)
            payloads.append(payload)
        return payloads

    def _encrypt_for_device(
        self,
        plaintext: bytes,
        device_id: str,
        device_private_bytes: bytes,
    ) -> bytes:
        """
        Encrypt plaintext with key derivable only by the device.
        Uses HKDF(device_private_key, salt, info=device_id) as AES key.
        """
        hkdf = HKDF(
            algorithm=hashes.SHA256(),
            length=KEY_LENGTH_BYTES,
            salt=b"zefcp-nfc-provision",
            info=device_id.encode(),
        )
        key = hkdf.derive(device_private_bytes)
        digest = hashes.Hash(hashes.SHA256())
        digest.update(device_id.encode())
        digest.update(device_private_bytes[:16])
        nonce_bytes = digest.finalize()[:NONCE_LENGTH_BYTES]
        cipher = Cipher(algorithms.AES(key), modes.CTR(nonce_bytes))
        encryptor = cipher.encryptor()
        return encryptor.update(plaintext) + encryptor.finalize()
