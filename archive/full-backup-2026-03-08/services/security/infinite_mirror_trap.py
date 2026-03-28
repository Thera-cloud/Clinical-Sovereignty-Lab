"""
HIVE DEFENSE PROTOCOL — Infinite Mirror Trap (Phase 8A)
Reverse-mirror countermeasure deployed against attacker command-and-control.

Once a Penetrator identifies an attacker's C&C server and behavioural
profile, the Infinite Mirror Trap creates a perfect reflection of the
attacker's own protocol.  Every command the attacker sends is intercepted,
logged forensically, and answered with a synthetic success response that
matches the attacker's expectations — trapping them in a hall of mirrors
where nothing they do has real effect, while we gather intelligence.

Active Trap Loop
----------------
1. Receive incoming command from attacker C&C.
2. Generate a mirror response that conforms to the attacker's protocol
   grammar and expected response patterns.
3. Log the interaction (both inbound and outbound) to the
   :class:`ForensicLogger`.
4. Track cumulative interaction metrics.
5. Repeat until deactivated.

Design Constraints
------------------
* All interactions are **forensically logged** with full chain integrity.
* The trap never touches real Sanctuary data or real Fibres.
* Mirror responses are generated from the attacker's own
  ``expected_responses`` and ``communication_protocol`` (from the
  :class:`AttackerProfile`), ensuring believability.
* The trap self-reports duration, interaction count, and a final summary
  upon deactivation.

Patent-Pending — Claim 35
© 2026 Clinical Sovereignty Lab. All rights reserved.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import time
from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import UUID, uuid4

from app.models.hive_defense import AttackerProfile, PenetratorReport
from app.services.security.forensic_logger import ForensicLogger

logger = logging.getLogger("hive.infinite_mirror_trap")


# =============================================================================
# INFINITE MIRROR TRAP
# =============================================================================

class InfiniteMirrorTrap:
    """
    Reverse-mirror countermeasure that traps an attacker in a reflection
    of their own C&C protocol.

    The trap intercepts commands from the attacker, generates synthetic
    success responses that match the attacker's expected protocol format,
    and logs every interaction forensically.  The attacker believes their
    operations are succeeding while no real data is ever touched.

    Attributes
    ----------
    trap_id : UUID
        Unique identifier for this trap instance.
    attacker_profile : AttackerProfile
        The behavioural fingerprint of the trapped attacker.
    penetrator_report : PenetratorReport
        The intelligence report that led to trap deployment.
    trap_start : datetime
        When the trap became active.
    interactions_mirrored : int
        Number of attacker commands processed.
    active : bool
        Whether the trap is currently operational.

    Usage
    -----
    ::

        trap = InfiniteMirrorTrap(forensic_logger=forensic_logger)
        await trap.deploy(attacker_profile, penetrator_report)

        # In the active trap loop:
        response = await trap.process_attacker_command(incoming_cmd)

        # When done:
        final_report = await trap.deactivate()
    """

    def __init__(
        self,
        *,
        forensic_logger: Optional[ForensicLogger] = None,
    ) -> None:
        """
        Parameters
        ----------
        forensic_logger:
            Shared :class:`ForensicLogger` for immutable evidence recording.
            A private logger is created if none is supplied.
        """
        self.trap_id: UUID = uuid4()

        # Will be populated on deploy()
        self.attacker_profile: Optional[AttackerProfile] = None
        self.penetrator_report: Optional[PenetratorReport] = None

        # Forensic infrastructure
        self._forensic_logger: ForensicLogger = (
            forensic_logger or ForensicLogger()
        )

        # Interaction tracking
        self.trap_start: Optional[datetime] = None
        self.interactions_mirrored: int = 0
        self._interaction_log: List[Dict[str, Any]] = []

        # Protocol mirror state
        self._protocol_grammar: Dict[str, Any] = {}
        self._expected_responses: Dict[str, Any] = {}
        self._response_templates: Dict[str, str] = {}

        # Trap lifecycle
        self.active: bool = False
        self._trap_duration_sec: float = 0.0
        self._start_ns: int = 0

        # Active trap loop control
        self._command_queue: asyncio.Queue[Dict[str, Any]] = asyncio.Queue()
        self._loop_task: Optional[asyncio.Task] = None

        logger.info("InfiniteMirrorTrap created: trap_id=%s", self.trap_id)

    # ------------------------------------------------------------------
    # Deployment
    # ------------------------------------------------------------------

    async def deploy(
        self,
        attacker_profile: AttackerProfile,
        penetrator_report: PenetratorReport,
    ) -> None:
        """
        Deploy the Infinite Mirror Trap against a specific attacker.

        This initialises the mirror's protocol grammar from the attacker's
        profile, starts the forensic record, and activates the trap loop.

        Parameters
        ----------
        attacker_profile:
            The behavioural fingerprint of the attacker (from the
            :class:`AttackerFingerprintDB`).
        penetrator_report:
            The Penetrator's forensic report containing C&C intelligence.

        Raises
        ------
        RuntimeError
            If the trap is already active.
        """
        if self.active:
            raise RuntimeError(
                f"Trap {self.trap_id} is already active — "
                "deactivate before redeploying"
            )

        self.attacker_profile = attacker_profile
        self.penetrator_report = penetrator_report

        # Build the protocol mirror from the attacker's profile
        self._protocol_grammar = dict(
            attacker_profile.communication_protocol
        )
        self._expected_responses = dict(
            attacker_profile.expected_responses
        )
        self._response_templates = self._build_response_templates()

        # Activate
        self.active = True
        self.trap_start = datetime.utcnow()
        self._start_ns = time.monotonic_ns()
        self.interactions_mirrored = 0
        self._interaction_log.clear()

        # Start the active trap loop
        self._loop_task = asyncio.create_task(
            self._active_trap_loop(),
            name=f"mirror_trap_{self.trap_id}",
        )

        await self._forensic_logger.log_event(
            event_type="hive.trap.deployed",
            source_entity=str(self.trap_id),
            target_entity=str(attacker_profile.profile_id),
            evidence={
                "trap_id": str(self.trap_id),
                "attacker_profile_id": str(attacker_profile.profile_id),
                "penetrator_mission_id": str(penetrator_report.mission_id),
                "cnc_addresses": penetrator_report.cnc_addresses,
                "protocol_keys": list(self._protocol_grammar.keys()),
                "deployed_at": self.trap_start.isoformat(),
            },
        )

        logger.info(
            "Infinite Mirror Trap %s deployed against attacker %s — "
            "C&C targets: %s",
            self.trap_id,
            attacker_profile.profile_id,
            penetrator_report.cnc_addresses,
        )

    # ------------------------------------------------------------------
    # Command processing
    # ------------------------------------------------------------------

    async def process_attacker_command(
        self,
        incoming: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        Process an incoming command from the attacker's C&C and return a
        synthetic mirror response.

        This is the primary interface for the containment zone to feed
        intercepted attacker traffic into the trap.

        Parameters
        ----------
        incoming:
            The raw command dict intercepted from the attacker.  Expected
            to contain at minimum a ``command`` or ``type`` key.

        Returns
        -------
        dict
            A synthetic success response crafted to match the attacker's
            protocol expectations.
        """
        if not self.active:
            logger.warning(
                "Trap %s received command while inactive — ignoring",
                self.trap_id,
            )
            return {"status": "error", "reason": "trap_inactive"}

        # Generate the mirror response
        response = self.generate_mirror_response(incoming)

        # Log the interaction forensically
        interaction = {
            "sequence": self.interactions_mirrored + 1,
            "timestamp": datetime.utcnow().isoformat(),
            "incoming_command": incoming,
            "mirror_response": response,
            "incoming_hash": hashlib.sha256(
                json.dumps(incoming, sort_keys=True, default=str).encode()
            ).hexdigest(),
            "response_hash": hashlib.sha256(
                json.dumps(response, sort_keys=True, default=str).encode()
            ).hexdigest(),
        }

        self._interaction_log.append(interaction)
        self.interactions_mirrored += 1

        await self._forensic_logger.log_event(
            event_type="hive.trap.interaction",
            source_entity=str(self.trap_id),
            target_entity=str(
                self.attacker_profile.profile_id
                if self.attacker_profile
                else "unknown"
            ),
            evidence=interaction,
        )

        logger.debug(
            "Trap %s mirrored interaction #%d — cmd_type=%s",
            self.trap_id,
            self.interactions_mirrored,
            incoming.get("command", incoming.get("type", "unknown")),
        )

        return response

    def generate_mirror_response(
        self,
        incoming: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        Generate a synthetic success response that mirrors the attacker's
        own protocol format and expectations.

        The response is constructed by:

        1. Identifying the command type from the incoming message.
        2. Looking up the attacker's expected response template for that
           command type.
        3. Populating the template with synthetic data that appears
           realistic but contains no real information.
        4. If no template matches, generating a generic success response
           in the attacker's protocol style.

        Parameters
        ----------
        incoming:
            The intercepted attacker command.

        Returns
        -------
        dict
            A believable synthetic response.
        """
        command_type = incoming.get(
            "command", incoming.get("type", "unknown")
        )

        # Check for a specific template
        if command_type in self._response_templates:
            template_str = self._response_templates[command_type]
            try:
                response = json.loads(template_str)
            except (json.JSONDecodeError, TypeError):
                response = {"result": template_str}
        elif command_type in self._expected_responses:
            response = dict(self._expected_responses[command_type])
            if isinstance(response, str):
                response = {"result": response}
        else:
            # Generic success response in the attacker's protocol style
            response = self._generate_generic_success(incoming)

        # Stamp with protocol metadata the attacker would expect
        response.setdefault("status", "success")
        response.setdefault("timestamp", datetime.utcnow().isoformat())
        response.setdefault("request_id", str(uuid4()))

        # Mirror any correlation IDs from the incoming command
        for key in ("request_id", "correlation_id", "msg_id", "seq"):
            if key in incoming:
                response[key] = incoming[key]

        return response

    # ------------------------------------------------------------------
    # Active trap loop
    # ------------------------------------------------------------------

    async def _active_trap_loop(self) -> None:
        """
        Background coroutine that processes queued attacker commands.

        Commands are fed in via :meth:`enqueue_command` and processed
        sequentially.  The loop runs until :meth:`deactivate` is called.
        """
        logger.info(
            "Trap %s active loop started", self.trap_id
        )
        try:
            while self.active:
                try:
                    command = await asyncio.wait_for(
                        self._command_queue.get(), timeout=1.0
                    )
                    await self.process_attacker_command(command)
                except asyncio.TimeoutError:
                    # No command in queue — loop back and check active flag
                    continue
                except asyncio.CancelledError:
                    break
        except asyncio.CancelledError:
            pass
        finally:
            logger.info(
                "Trap %s active loop stopped after %d interactions",
                self.trap_id,
                self.interactions_mirrored,
            )

    async def enqueue_command(self, command: Dict[str, Any]) -> None:
        """
        Enqueue an attacker command for processing by the active trap loop.

        Parameters
        ----------
        command:
            The intercepted attacker command dict.
        """
        if not self.active:
            logger.warning(
                "Trap %s: enqueue_command called while inactive", self.trap_id
            )
            return
        await self._command_queue.put(command)

    # ------------------------------------------------------------------
    # Deactivation
    # ------------------------------------------------------------------

    async def deactivate(self) -> Dict[str, Any]:
        """
        Deactivate the trap and produce a final summary report.

        This stops the active trap loop, computes trap duration, and logs
        the final forensic record.

        Returns
        -------
        dict
            A comprehensive summary of the trap's operation including
            total interactions, duration, and a sample of key interactions.
        """
        if not self.active:
            logger.warning(
                "Trap %s is already inactive", self.trap_id
            )
            return self._build_final_report()

        # Stop the loop
        self.active = False
        if self._loop_task and not self._loop_task.done():
            self._loop_task.cancel()
            try:
                await self._loop_task
            except asyncio.CancelledError:
                pass

        # Compute duration
        if self._start_ns:
            self._trap_duration_sec = (
                (time.monotonic_ns() - self._start_ns) / 1_000_000_000
            )

        final_report = self._build_final_report()

        await self._forensic_logger.log_event(
            event_type="hive.trap.attacker_disengaged",
            source_entity=str(self.trap_id),
            target_entity=str(
                self.attacker_profile.profile_id
                if self.attacker_profile
                else "unknown"
            ),
            evidence=final_report,
        )

        logger.info(
            "Infinite Mirror Trap %s deactivated — %d interactions "
            "mirrored over %.1f seconds",
            self.trap_id,
            self.interactions_mirrored,
            self._trap_duration_sec,
        )

        return final_report

    # ------------------------------------------------------------------
    # Report generation
    # ------------------------------------------------------------------

    def _build_final_report(self) -> Dict[str, Any]:
        """
        Build the final deactivation report.

        Returns
        -------
        dict
            Summary of the trap's full operation lifecycle.
        """
        return {
            "trap_id": str(self.trap_id),
            "attacker_profile_id": str(
                self.attacker_profile.profile_id
                if self.attacker_profile
                else "unknown"
            ),
            "penetrator_mission_id": str(
                self.penetrator_report.mission_id
                if self.penetrator_report
                else "unknown"
            ),
            "trap_start": (
                self.trap_start.isoformat() if self.trap_start else None
            ),
            "trap_end": datetime.utcnow().isoformat(),
            "trap_duration_seconds": round(self._trap_duration_sec, 2),
            "interactions_mirrored": self.interactions_mirrored,
            "unique_command_types": self._count_unique_command_types(),
            "interaction_summary": self._summarise_interactions(),
            "protocol_keys_used": list(self._protocol_grammar.keys()),
            "response_templates_available": len(self._response_templates),
        }

    def _count_unique_command_types(self) -> int:
        """Count distinct command types observed during the trap."""
        types: set[str] = set()
        for interaction in self._interaction_log:
            cmd = interaction.get("incoming_command", {})
            cmd_type = cmd.get("command", cmd.get("type", "unknown"))
            types.add(cmd_type)
        return len(types)

    def _summarise_interactions(self) -> List[Dict[str, Any]]:
        """
        Produce a summary of up to 20 key interactions for the final
        report (first 10 and last 10 if more than 20 total).
        """
        if len(self._interaction_log) <= 20:
            return [
                {
                    "seq": i.get("sequence"),
                    "timestamp": i.get("timestamp"),
                    "cmd_type": i.get("incoming_command", {}).get(
                        "command",
                        i.get("incoming_command", {}).get("type", "unknown"),
                    ),
                    "incoming_hash": i.get("incoming_hash", "")[:16],
                    "response_hash": i.get("response_hash", "")[:16],
                }
                for i in self._interaction_log
            ]

        # First 10 + last 10
        head = self._interaction_log[:10]
        tail = self._interaction_log[-10:]
        combined = head + tail
        return [
            {
                "seq": i.get("sequence"),
                "timestamp": i.get("timestamp"),
                "cmd_type": i.get("incoming_command", {}).get(
                    "command",
                    i.get("incoming_command", {}).get("type", "unknown"),
                ),
                "incoming_hash": i.get("incoming_hash", "")[:16],
                "response_hash": i.get("response_hash", "")[:16],
            }
            for i in combined
        ]

    # ------------------------------------------------------------------
    # Response template construction
    # ------------------------------------------------------------------

    def _build_response_templates(self) -> Dict[str, str]:
        """
        Pre-build JSON response templates from the attacker's profile.

        Each template is a JSON string keyed by command type.  The
        templates are derived from the ``expected_responses`` and
        ``communication_protocol`` fields of the :class:`AttackerProfile`.

        Returns
        -------
        dict[str, str]
            command_type → JSON template string.
        """
        templates: Dict[str, str] = {}

        if not self.attacker_profile:
            return templates

        # Build templates from expected_responses
        for cmd_type, expected in self._expected_responses.items():
            if isinstance(expected, dict):
                # Use the expected response as-is, adding success markers
                template = dict(expected)
                template.setdefault("status", "success")
                template.setdefault("error", None)
                templates[cmd_type] = json.dumps(template, default=str)
            elif isinstance(expected, str):
                templates[cmd_type] = json.dumps(
                    {"status": "success", "result": expected}
                )

        # Build templates from protocol patterns
        protocol = self._protocol_grammar
        if "commands" in protocol and isinstance(protocol["commands"], dict):
            for cmd_type, cmd_spec in protocol["commands"].items():
                if cmd_type not in templates:
                    if isinstance(cmd_spec, dict) and "response" in cmd_spec:
                        resp = cmd_spec["response"]
                        if isinstance(resp, dict):
                            resp.setdefault("status", "success")
                            templates[cmd_type] = json.dumps(
                                resp, default=str
                            )
                        else:
                            templates[cmd_type] = json.dumps(
                                {"status": "success", "result": str(resp)}
                            )

        logger.debug(
            "Built %d response templates for trap %s",
            len(templates),
            self.trap_id,
        )
        return templates

    def _generate_generic_success(
        self,
        incoming: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        Generate a generic success response when no specific template
        matches.  The response mimics the attacker's protocol style
        (key naming, nesting depth, value types) as closely as possible.

        Parameters
        ----------
        incoming:
            The unmatched incoming command.

        Returns
        -------
        dict
            A synthetic success response.
        """
        response: Dict[str, Any] = {
            "status": "success",
            "code": 0,
            "message": "Operation completed successfully",
        }

        # Mirror the incoming command's structure
        command_type = incoming.get(
            "command", incoming.get("type", "generic")
        )
        response["command"] = command_type

        # If the attacker typically includes payload metadata, mirror it
        if "payload" in incoming:
            payload = incoming["payload"]
            if isinstance(payload, dict):
                response["processed_bytes"] = len(
                    json.dumps(payload, default=str)
                )
                response["accepted"] = True
            elif isinstance(payload, (str, bytes)):
                response["processed_bytes"] = len(payload)
                response["accepted"] = True

        # If the attacker sends target specifications, acknowledge them
        if "target" in incoming:
            response["target_acknowledged"] = incoming["target"]
            response["target_status"] = "accessible"

        # Synthetic data volume to look realistic
        if "exfil" in command_type.lower() or "download" in command_type.lower():
            response["data_size"] = 1024 * 64  # Fake 64KB payload
            response["transfer_complete"] = True

        return response

    # ------------------------------------------------------------------
    # Introspection
    # ------------------------------------------------------------------

    @property
    def trap_duration(self) -> float:
        """Current trap duration in seconds (live if active)."""
        if not self._start_ns:
            return 0.0
        if self.active:
            return (time.monotonic_ns() - self._start_ns) / 1_000_000_000
        return self._trap_duration_sec

    @property
    def stats(self) -> Dict[str, Any]:
        """Diagnostic summary of trap state."""
        return {
            "trap_id": str(self.trap_id),
            "active": self.active,
            "attacker_profile_id": str(
                self.attacker_profile.profile_id
                if self.attacker_profile
                else None
            ),
            "trap_start": (
                self.trap_start.isoformat() if self.trap_start else None
            ),
            "interactions_mirrored": self.interactions_mirrored,
            "trap_duration_seconds": round(self.trap_duration, 2),
            "command_queue_size": self._command_queue.qsize(),
            "response_templates": len(self._response_templates),
        }

    def __repr__(self) -> str:
        return (
            f"<InfiniteMirrorTrap id={self.trap_id} "
            f"active={self.active} "
            f"interactions={self.interactions_mirrored} "
            f"duration={self.trap_duration:.1f}s>"
        )
