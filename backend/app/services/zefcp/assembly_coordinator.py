"""
ZEFCP Assembly Coordinator — Distributed Assembly Across Endpoints.
Patent Claim 25.5: Zero-Energy BLE Communication — The coordinator attempts
local assembly first (fastest path). If complete locally, forwards observation
to Wisdom Mesh (sovereign-mind). If not, forwards fragments to cloud for
distributed assembly across multiple Spider Web endpoints.
"""

from __future__ import annotations

import base64
from typing import Any, Optional

import structlog

from app.models.zefcp import FibreObservation, MicroFragment
from app.models.mesh import MeshMessage, MeshMessageType, MeshPriority
from app.services.zefcp.fragment_buffer import FragmentBuffer

logger = structlog.get_logger(__name__)


# =============================================================================
# DISTRIBUTED ASSEMBLY COORDINATOR
# =============================================================================


class DistributedAssemblyCoordinator:
    """
    Coordinates fragment assembly across local buffer and cloud.
    Patent Claim 25.5: Local assembly preferred; fragment forwarding for
    distributed reconstruction when local assembly is incomplete.
    """

    def __init__(
        self,
        local_buffer: FragmentBuffer,
        mesh_client: Any,
        endpoint_id: str,
    ) -> None:
        """
        Initialize coordinator.

        Args:
            local_buffer: Local fragment buffer for assembly.
            mesh_client: Wisdom Mesh client (publish interface).
            endpoint_id: This endpoint's identifier.
        """
        self._local_buffer = local_buffer
        self._mesh_client = mesh_client
        self._endpoint_id = endpoint_id

    # -------------------------------------------------------------------------
    # Fragment Handler
    # -------------------------------------------------------------------------

    async def on_fragment_detected(self, fragment: MicroFragment) -> Optional[FibreObservation]:
        """
        Process detected fragment: attempt local assembly first.
        If complete locally, forward observation to Wisdom Mesh.
        If not, forward fragment to cloud for distributed assembly.
        """
        observation = await self._local_buffer.ingest(fragment)

        if observation is not None:
            observation.assembly_endpoint_id = self._endpoint_id
            await self._forward_observation(observation)
            return observation

        await self._forward_fragment_to_cloud(fragment)
        return None

    # -------------------------------------------------------------------------
    # Mesh Forwarding
    # -------------------------------------------------------------------------

    async def _forward_observation(self, observation: FibreObservation) -> None:
        """
        Publish completed observation as MeshMessage type INSIGHT to sovereign-mind.
        """
        from uuid import uuid4

        obs_dict = observation.model_dump(mode="json")
        for key in ("coherence_data", "cultural_signal", "foresight_signal", "ed25519_signature"):
            val = obs_dict.get(key)
            if isinstance(val, bytes):
                obs_dict[key] = base64.b64encode(val).decode("ascii")
        message = MeshMessage(
            message_type=MeshMessageType.INSIGHT,
            sender_id=uuid4(),
            sender_type="fibre",
            domain_tags=["sovereign-mind"],
            body={
                "observation": obs_dict,
                "endpoint_id": self._endpoint_id,
            },
            priority=MeshPriority.NORMAL,
        )
        if hasattr(self._mesh_client, "publish"):
            await self._mesh_client.publish(message)
            logger.debug("observation_forwarded", observation_id=str(observation.observation_id))
        else:
            logger.warning("mesh_client_no_publish", endpoint_id=self._endpoint_id)

    async def _forward_fragment_to_cloud(self, fragment: MicroFragment) -> None:
        """
        Publish fragment as MeshMessage type FIBRE_FRAGMENT for distributed assembly.
        """
        from uuid import uuid4

        frag_dict = fragment.model_dump()
        frag_dict["payload"] = base64.b64encode(fragment.payload).decode("ascii")
        message = MeshMessage(
            message_type=MeshMessageType.FIBRE_FRAGMENT,
            sender_id=uuid4(),
            sender_type="fibre",
            domain_tags=["sovereign-mind"],
            body={
                "fragment": frag_dict,
                "endpoint_id": self._endpoint_id,
            },
            priority=MeshPriority.LOW,
        )
        if hasattr(self._mesh_client, "publish"):
            await self._mesh_client.publish(message)
            logger.debug("fragment_forwarded_to_cloud", sequence=fragment.sequence)
        else:
            logger.warning("mesh_client_no_publish", endpoint_id=self._endpoint_id)

    # -------------------------------------------------------------------------
    # Ambient Density
    # -------------------------------------------------------------------------

    def _get_ambient_density(self) -> float:
        """
        Return estimated ambient BLE density (e.g. handshakes per minute).
        Placeholder implementation — integrate with actual BLE scan metrics.
        """
        return 0.0
