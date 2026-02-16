"""
ZEFCP Bridge — ZEFCP → Wisdom Mesh forwarding.
Patent Claim 25.1f: Zero-Energy BLE Communication — Forward reassembled
observations and fragments to the Wisdom Mesh; verify Ed25519 signatures;
include transport metadata for assembly tracking.
"""

from __future__ import annotations

import logging
from typing import Any, Optional
from uuid import UUID, uuid4

from app.models.mesh import MeshMessage, MeshMessageType, MeshPriority
from app.models.zefcp import FibreObservation, MicroFragment
from app.services.zefcp.crypto import FibreFragmentCrypto

logger = logging.getLogger(__name__)


# =============================================================================
# ZEFCP BRIDGE
# =============================================================================


class ZEFCPBridge:
    """
    Forwards ZEFCP observations and fragments to the Wisdom Mesh.
    Patent Claim 25.1f: Verifies Ed25519 signatures, creates MeshMessages
    with transport metadata, publishes to mesh with appropriate priority.
    """

    @staticmethod
    def _parse_fibre_sender_id(fibre_id: str) -> UUID:
        """Parse fibre_id to UUID if valid, else return new UUID."""
        try:
            return UUID(fibre_id)
        except (ValueError, TypeError):
            return uuid4()

    def __init__(self, mesh_client: Any, endpoint_id: str) -> None:
        """
        Initialize bridge with mesh client and endpoint identifier.

        Args:
            mesh_client: Wisdom Mesh client with async publish(message) -> bool.
            endpoint_id: This Spider Web endpoint's identifier.
        """
        self._mesh = mesh_client
        self._endpoint_id = endpoint_id

    async def forward_observation(
        self,
        observation: FibreObservation,
        fibre_public_key: Optional[bytes] = None,
        sovereign_mind_id: Optional[UUID] = None,
    ) -> None:
        """
        Verify Ed25519 signature on observation and forward to Wisdom Mesh.
        Patent Claim 25.1f: Creates MeshMessage type=INSIGHT, priority=HIGH,
        recipient=sovereign-mind; includes transport metadata (assembly info).

        Args:
            observation: Reassembled FibreObservation from local assembly.
            fibre_public_key: Optional Ed25519 public key bytes for verification.
                If provided and observation has signature, verification is required.
            sovereign_mind_id: Optional UUID of Sovereign Mind for direct routing.
        """
        # Verify Ed25519 signature when key is provided
        if fibre_public_key and observation.ed25519_signature:
            crypto = FibreFragmentCrypto(b"")  # No swarm secret needed for verify
            obs_data = observation.model_dump_json(exclude={"ed25519_signature"}).encode()
            if not crypto.verify_observation(
                observation_data=obs_data,
                signature=observation.ed25519_signature,
                fibre_public_key=fibre_public_key,
            ):
                logger.warning(
                    "ZEFCP: Observation signature verification failed, dropping: %s",
                    observation.observation_id,
                )
                return

        # Build transport metadata (assembly info)
        transport_meta: dict[str, Any] = {}
        if observation.assembly_total_fragments is not None:
            transport_meta["assembly_total_fragments"] = observation.assembly_total_fragments
        if observation.assembly_local_count is not None:
            transport_meta["assembly_local_count"] = observation.assembly_local_count
        if observation.assembly_remote_count is not None:
            transport_meta["assembly_remote_count"] = observation.assembly_remote_count
        if observation.assembly_duration_seconds is not None:
            transport_meta["assembly_duration_seconds"] = observation.assembly_duration_seconds
        if observation.assembly_endpoint_id is not None:
            transport_meta["assembly_endpoint_id"] = observation.assembly_endpoint_id
        else:
            transport_meta["assembly_endpoint_id"] = self._endpoint_id

        message = MeshMessage(
            message_type=MeshMessageType.INSIGHT,
            priority=MeshPriority.HIGH,
            sender_id=self._parse_fibre_sender_id(observation.fibre_id),
            sender_type="fibre",
            recipient_id=sovereign_mind_id,
            domain_tags=["sovereign-mind"],
            subject="ZEFCP Observation",
            body={
                "observation": observation.model_dump(mode="json"),
                "transport_metadata": transport_meta,
            },
        )

        await self._mesh.publish(message)

    async def forward_fragment(self, fragment: MicroFragment) -> None:
        """
        Forward a micro-fragment to the Wisdom Mesh for distributed assembly.
        Patent Claim 25.1f: Creates MeshMessage type=FIBRE_FRAGMENT,
        batch_eligible=True for temporal batching.
        """
        message = MeshMessage(
            message_type=MeshMessageType.FIBRE_FRAGMENT,
            priority=MeshPriority.NORMAL,
            sender_id=uuid4(),
            sender_type="fibre",
            domain_tags=["zefcp-fragments"],
            subject="MicroFragment",
            body={
                "fragment": fragment.model_dump(mode="json"),
                "payload_bytes": list(fragment.payload),
            },
            metadata={"batch_eligible": True},
        )
        await self._mesh.publish(message)
