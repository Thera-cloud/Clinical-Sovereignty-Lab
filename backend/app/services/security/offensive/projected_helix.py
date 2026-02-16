"""
HIVE DEFENSE PROTOCOL — Projected Helix Engine (Phase 8E)
Core projection engine: wraps attacker C&C in Trinity Helix.

The Projected Helix is the offensive culmination of the Hive Defense
Protocol.  Once a Penetrator mission has identified an attacker's command-
and-control infrastructure, the Projected Helix constructs a *mirror cage*
around the attacker's outbound channels using three specialised mirrors:

1. **Protocol Mirror** — reflects the attacker's own command protocol
   so responses look authentic.
2. **Topology Mirror** — mimics network timing, routing, and packet
   structure so latency/hop-count analysis matches.
3. **Behavior Mirror** — replicates how the attacker's agents
   typically respond so command → ack patterns feel real.

Every outbound command the attacker issues hits the Helix, is intercepted,
and receives a blended mirror response.  The command *always fails*
(it never reaches the real hive) but the attacker sees success
acknowledgments.  The failed command is then inverted into a Triangle
reflection that maps the attacker's own infrastructure back at them.

The attacker believes their operations are succeeding.
Nothing actually happens.

Design Constraints
------------------
* **Authorization required** — a Projected Helix MUST be authorised by
  Nathan before deployment.  See :class:`ProjectionAuthorization`.
* All interactions are forensically logged through :class:`ForensicLogger`
  and :class:`ProjectionForensics`.

Patent-Pending — Claim 53
© 2026 Clinical Sovereignty Lab. All rights reserved.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import time
from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import UUID, uuid4

from app.models.hive_defense import (
    AttackerProfile,
    PenetratorReport,
    ProjectedHelixDeployment,
    ProjectionStatus,
    RecursiveLearningState,
)
from app.services.security.offensive.protocol_mirror import AttackerProtocolMirror
from app.services.security.offensive.topology_mirror import AttackerTopologyMirror
from app.services.security.offensive.behavior_mirror import AttackerBehaviorMirror
from app.services.security.offensive.recursive_projection import RecursiveProjection
from app.services.security.forensic_logger import ForensicLogger

logger = logging.getLogger("hive.projected_helix")


# =============================================================================
# PROJECTED HELIX — Patent Claim 53
# =============================================================================

class ProjectedHelix:
    """
    Core projection engine that wraps attacker C&C in a Trinity Helix.

    The Projected Helix intercepts all outbound commands from the attacker,
    reflects them through three mirror walls (protocol, topology, behavior),
    and inverts failed commands into triangle reflections that map the
    attacker's own infrastructure back at them.

    Attributes
    ----------
    deployment_id : UUID
        Unique identifier for this Projected Helix deployment.
    penetrator_report : PenetratorReport
        The Penetrator intelligence this projection was built from.
    deployment : ProjectedHelixDeployment
        The Pydantic deployment state model.
    protocol_mirror : AttackerProtocolMirror
        Mirror wall 1 — protocol-level reflection.
    topology_mirror : AttackerTopologyMirror
        Mirror wall 2 — network topology reflection.
    behavior_mirror : AttackerBehaviorMirror
        Mirror wall 3 — agent behavioral reflection.
    recursive_projection : RecursiveProjection
        Self-improving mirror that learns from each interaction.

    Usage
    -----
    ::

        helix = ProjectedHelix(
            penetrator_report=report,
            attacker_profile=profile,
            forensic_logger=forensic_logger,
        )
        # After authorization:
        helix.activate()
        # On each intercepted command:
        response = await helix.intercept_outbound_command(command)
    """

    def __init__(
        self,
        penetrator_report: PenetratorReport,
        attacker_profile: Optional[AttackerProfile] = None,
        *,
        forensic_logger: Optional[ForensicLogger] = None,
        deployment_id: Optional[UUID] = None,
    ) -> None:
        """
        Build a Projected Helix from Penetrator intelligence.

        Configures three mirror walls using the attacker's OWN protocol,
        topology, and behavioral patterns extracted during the Penetrator
        mission.

        Parameters
        ----------
        penetrator_report:
            Complete forensic report from a Penetrator mission containing
            the attacker's fingerprint, topology, and C&C details.
        attacker_profile:
            Optional pre-built attacker profile.  If *None*, one is
            synthesised from the Penetrator report.
        forensic_logger:
            Shared :class:`ForensicLogger` for immutable evidence recording.
        deployment_id:
            Override the auto-generated deployment UUID (for resumption).
        """
        self.deployment_id: UUID = deployment_id or uuid4()
        self.penetrator_report: PenetratorReport = penetrator_report

        # Build or adopt attacker profile
        self._attacker_profile: AttackerProfile = (
            attacker_profile or self._build_profile_from_report(penetrator_report)
        )

        # Deployment state model
        self.deployment: ProjectedHelixDeployment = ProjectedHelixDeployment(
            deployment_id=self.deployment_id,
            target_profile_id=self._attacker_profile.profile_id,
            penetrator_report_id=penetrator_report.mission_id,
            status=ProjectionStatus.PENDING_AUTH,
        )

        # ----- Three Mirror Walls -----
        # Wall 1: Protocol Mirror — reflects attacker's command protocol
        self.protocol_mirror: AttackerProtocolMirror = AttackerProtocolMirror(
            protocol_spec=self._attacker_profile.communication_protocol,
        )

        # Wall 2: Topology Mirror — reflects attacker's network topology
        self.topology_mirror: AttackerTopologyMirror = AttackerTopologyMirror(
            topology_spec=self._attacker_profile.network_topology,
        )

        # Wall 3: Behavior Mirror — reflects attacker's agent behavioral patterns
        self.behavior_mirror: AttackerBehaviorMirror = AttackerBehaviorMirror(
            behavioral_profile=self._attacker_profile.behavioral_patterns,
        )

        # Recursive self-improving projection
        self.recursive_projection: RecursiveProjection = RecursiveProjection(
            deployment_id=self.deployment_id,
            protocol_mirror=self.protocol_mirror,
            topology_mirror=self.topology_mirror,
            behavior_mirror=self.behavior_mirror,
            attacker_profile=self._attacker_profile,
        )

        # Forensic infrastructure
        self._forensic_logger: ForensicLogger = forensic_logger or ForensicLogger()

        # Operational tracking
        self._active: bool = False
        self._commands_intercepted: int = 0
        self._triangles_reflected: int = 0
        self._start_ns: Optional[int] = None
        self._interaction_history: List[Dict[str, Any]] = []

        logger.info(
            "ProjectedHelix constructed: deployment=%s target_profile=%s "
            "penetrator_mission=%s cnc_addresses=%s",
            self.deployment_id,
            self._attacker_profile.profile_id,
            penetrator_report.mission_id,
            penetrator_report.cnc_addresses,
        )

    # ------------------------------------------------------------------
    # Activation / Deactivation
    # ------------------------------------------------------------------

    def activate(self, authorized_by: str, authorized_at: Optional[datetime] = None) -> None:
        """
        Activate the Projected Helix after authorization has been granted.

        Parameters
        ----------
        authorized_by:
            Identifier of the person who authorized deployment (must be Nathan).
        authorized_at:
            Timestamp of authorization.  Defaults to now.
        """
        self.deployment.status = ProjectionStatus.ACTIVE
        self.deployment.authorized_by = authorized_by
        self.deployment.authorized_at = authorized_at or datetime.utcnow()
        self.deployment.deployed_at = datetime.utcnow()

        self._active = True
        self._start_ns = time.monotonic_ns()

        logger.warning(
            "ProjectedHelix ACTIVATED: deployment=%s authorized_by=%s "
            "target_profile=%s",
            self.deployment_id,
            authorized_by,
            self._attacker_profile.profile_id,
        )

    def deactivate(self, reason: str = "manual") -> None:
        """
        Decommission this Projected Helix deployment.

        Parameters
        ----------
        reason:
            Human-readable reason for decommission.
        """
        self.deployment.status = ProjectionStatus.DECOMMISSIONED
        self._active = False

        logger.warning(
            "ProjectedHelix DECOMMISSIONED: deployment=%s reason='%s' "
            "commands_intercepted=%d triangles_reflected=%d",
            self.deployment_id,
            reason,
            self._commands_intercepted,
            self._triangles_reflected,
        )

    # ------------------------------------------------------------------
    # Core interception — Patent Claim 53
    # ------------------------------------------------------------------

    async def intercept_outbound_command(
        self,
        command: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        Intercept an outbound attacker command and return a mirror response.

        The command hits the Helix, always fails (no hive heartbeat), and
        is inverted into a Triangle reflection.  The response blends all
        three mirrors to match the attacker's protocol, topology, and
        behavioral expectations.

        Parameters
        ----------
        command:
            The raw attacker command dictionary.  Expected to contain at
            minimum ``type``, ``target``, and ``payload`` keys.

        Returns
        -------
        dict
            A blended mirror response that the attacker's C&C will accept
            as a legitimate success acknowledgment.
        """
        if not self._active:
            logger.warning(
                "ProjectedHelix %s received command while inactive — "
                "dropping silently",
                self.deployment_id,
            )
            return {"status": "dropped", "reason": "helix_inactive"}

        intercept_time = datetime.utcnow()
        self._commands_intercepted += 1
        self.deployment.commands_intercepted = self._commands_intercepted

        # Step 1: Command hits the Helix — it always fails (no hive heartbeat)
        logger.debug(
            "ProjectedHelix %s intercepting command #%d: type=%s",
            self.deployment_id,
            self._commands_intercepted,
            command.get("type", "unknown"),
        )

        # Step 2: Generate blended mirror response from all three walls
        protocol_response = await self.protocol_mirror.reflect(command)
        topology_response = await self.topology_mirror.reflect(command)
        behavior_response = await self.behavior_mirror.reflect(command)

        blended_response = self._blend_mirror_responses(
            command=command,
            protocol_response=protocol_response,
            topology_response=topology_response,
            behavior_response=behavior_response,
        )

        # Step 3: Invert into triangle reflection
        triangle = await self.triangle_reflect(command)
        blended_response["_triangle_reflection"] = triangle

        # Step 4: Feed to recursive learning
        model_update = await self.recursive_projection.process_and_learn(command)
        self.deployment.mirror_accuracy = (
            self.recursive_projection.learning_state.model_accuracy
        )
        self.deployment.interactions_mirrored += 1

        # Step 5: Record forensic evidence
        interaction_record = {
            "command_number": self._commands_intercepted,
            "command_type": command.get("type", "unknown"),
            "command_hash": hashlib.sha256(
                str(command).encode()
            ).hexdigest()[:16],
            "response_hash": hashlib.sha256(
                str(blended_response).encode()
            ).hexdigest()[:16],
            "triangle_reflected": True,
            "model_accuracy": self.recursive_projection.learning_state.model_accuracy,
            "intercept_time": intercept_time.isoformat(),
        }
        self._interaction_history.append(interaction_record)

        await self._forensic_logger.log_event(
            event_type="hive.projection.command_intercepted",
            source_entity=str(self.deployment_id),
            target_entity=str(self._attacker_profile.profile_id),
            evidence=interaction_record,
        )

        logger.info(
            "ProjectedHelix %s intercepted command #%d — "
            "mirror_accuracy=%.3f triangle_reflected=True",
            self.deployment_id,
            self._commands_intercepted,
            self.recursive_projection.learning_state.model_accuracy,
        )

        return blended_response

    # ------------------------------------------------------------------
    # Triangle Reflection
    # ------------------------------------------------------------------

    async def triangle_reflect(
        self,
        command: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        Invert a failed command into a triangle reflection that maps the
        attacker's own infrastructure back at them.

        The triangle blends protocol, topology, and behavioral reflections
        to create a response the attacker's C&C will interpret as a
        legitimate success report from their own agents.

        Parameters
        ----------
        command:
            The original attacker command.

        Returns
        -------
        dict
            A triangle reflection containing blended intelligence about the
            attacker's infrastructure as seen through all three mirrors.
        """
        self._triangles_reflected += 1

        # Each mirror contributes its view of the attacker's infrastructure
        protocol_reflection = await self.protocol_mirror.reflect(command)
        topology_reflection = await self.topology_mirror.reflect(command)
        behavior_reflection = await self.behavior_mirror.reflect(command)

        triangle = {
            "triangle_id": str(uuid4()),
            "source_command_type": command.get("type", "unknown"),
            "reflected_at": datetime.utcnow().isoformat(),
            "protocol_vector": protocol_reflection,
            "topology_vector": topology_reflection,
            "behavior_vector": behavior_reflection,
            "infrastructure_map": {
                "cnc_addresses": self.penetrator_report.cnc_addresses,
                "protocol_signature": self._attacker_profile.communication_protocol.get(
                    "signature", "unknown"
                ),
                "topology_fingerprint": self._attacker_profile.network_topology.get(
                    "fingerprint", "unknown"
                ),
            },
            "triangle_number": self._triangles_reflected,
        }

        await self._forensic_logger.log_event(
            event_type="hive.projection.triangle_reflected",
            source_entity=str(self.deployment_id),
            target_entity=str(self._attacker_profile.profile_id),
            evidence={
                "triangle_id": triangle["triangle_id"],
                "command_type": command.get("type", "unknown"),
                "triangle_number": self._triangles_reflected,
            },
        )

        return triangle

    # ------------------------------------------------------------------
    # Mirror blending
    # ------------------------------------------------------------------

    def _blend_mirror_responses(
        self,
        command: Dict[str, Any],
        protocol_response: Dict[str, Any],
        topology_response: Dict[str, Any],
        behavior_response: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        Blend responses from all three mirror walls into a single coherent
        response that the attacker's C&C will accept.

        The blending prioritises protocol correctness (format, IDs, tokens)
        with topology realism (timing, routing) and behavioral authenticity
        (agent style, acknowledgment patterns).

        Parameters
        ----------
        command:
            The original attacker command.
        protocol_response:
            Response from the Protocol Mirror.
        topology_response:
            Response from the Topology Mirror.
        behavior_response:
            Response from the Behavior Mirror.

        Returns
        -------
        dict
            A unified mirror response.
        """
        blended: Dict[str, Any] = {
            # Protocol layer — correct format, IDs, tokens
            "status": protocol_response.get("status", "success"),
            "correlation_id": protocol_response.get("correlation_id"),
            "sequence_number": protocol_response.get("sequence_number"),
            "auth_token": protocol_response.get("auth_token"),
            "protocol_version": protocol_response.get("protocol_version"),
            # Topology layer — realistic timing and routing
            "response_latency_ms": topology_response.get("latency_ms", 0),
            "hop_count": topology_response.get("hop_count", 0),
            "ttl": topology_response.get("ttl", 64),
            "route_path": topology_response.get("route_path", []),
            # Behavior layer — agent-authentic acknowledgment
            "ack_style": behavior_response.get("ack_style", "standard"),
            "agent_status": behavior_response.get("agent_status", "active"),
            "data_report": behavior_response.get("data_report", {}),
            # Meta
            "command_type": command.get("type", "unknown"),
            "blended": True,
            "mirror_walls": 3,
        }
        return blended

    # ------------------------------------------------------------------
    # Profile synthesis
    # ------------------------------------------------------------------

    @staticmethod
    def _build_profile_from_report(report: PenetratorReport) -> AttackerProfile:
        """
        Synthesise an :class:`AttackerProfile` from a Penetrator report
        when one was not provided externally.

        Parameters
        ----------
        report:
            The Penetrator's forensic report.

        Returns
        -------
        AttackerProfile
        """
        return AttackerProfile(
            communication_protocol=report.fingerprint.get(
                "communication_protocol", {}
            ),
            network_topology=report.topology,
            tool_signatures=report.fingerprint.get("tool_signatures", []),
            behavioral_patterns=report.fingerprint.get(
                "behavioral_patterns", {}
            ),
            sophistication_level=report.fingerprint.get(
                "sophistication_level", 1
            ),
            active_channels=report.cnc_addresses,
        )

    # ------------------------------------------------------------------
    # Introspection
    # ------------------------------------------------------------------

    @property
    def is_active(self) -> bool:
        """Whether this Projected Helix is currently active."""
        return self._active

    @property
    def mirror_accuracy(self) -> float:
        """Current mirror accuracy from the recursive learning model."""
        return self.recursive_projection.learning_state.model_accuracy

    @property
    def elapsed_seconds(self) -> float:
        """Seconds since activation (0.0 if not yet activated)."""
        if self._start_ns is None:
            return 0.0
        return (time.monotonic_ns() - self._start_ns) / 1_000_000_000

    @property
    def stats(self) -> Dict[str, Any]:
        """Diagnostic summary for monitoring dashboards."""
        return {
            "deployment_id": str(self.deployment_id),
            "status": self.deployment.status.value,
            "active": self._active,
            "target_profile_id": str(self._attacker_profile.profile_id),
            "penetrator_mission_id": str(self.penetrator_report.mission_id),
            "cnc_addresses": self.penetrator_report.cnc_addresses,
            "commands_intercepted": self._commands_intercepted,
            "triangles_reflected": self._triangles_reflected,
            "mirror_accuracy": self.mirror_accuracy,
            "model_version": self.recursive_projection.learning_state.attacker_model_version,
            "interaction_history_size": len(self._interaction_history),
            "authorized_by": self.deployment.authorized_by,
            "elapsed_seconds": round(self.elapsed_seconds, 2),
        }

    def __repr__(self) -> str:
        return (
            f"<ProjectedHelix deployment={self.deployment_id} "
            f"status={self.deployment.status.value} "
            f"commands={self._commands_intercepted} "
            f"accuracy={self.mirror_accuracy:.3f}>"
        )
