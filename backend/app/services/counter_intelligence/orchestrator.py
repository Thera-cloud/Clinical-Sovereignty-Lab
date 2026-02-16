"""
Immune Response Orchestrator — Central coordinator for the counter-intelligence
pipeline.  Receives attack signals from Spider Web, Bridge Server, REST API,
and Wisdom Mesh; feeds them through fingerprinting → pattern analysis → threat
assessment; and dispatches graduated responses across Tiers 1-3.

Escalation thresholds:
  LOW      – single failed attempt ➜ log + fingerprint
  MEDIUM   – 5+ correlated failures ➜ alert swarm, begin tracking
  HIGH     – confirmed attack ➜ deploy honeypots, canaries, tarpit
  CRITICAL – sustained attack on specific Fibres ➜ counter-fragments + seeds
  APT      – multi-vector, persistent ➜ full Tier 3 + cascade seeds
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from enum import IntEnum, Enum
from typing import Any, Dict, List, Optional
from uuid import UUID, uuid4

logger = logging.getLogger("counter_intelligence.orchestrator")


# =============================================================================
# ENUMS
# =============================================================================

class ThreatLevel(IntEnum):
    LOW = 1
    MEDIUM = 2
    HIGH = 3
    CRITICAL = 4
    APT = 5


class AttackType(str, Enum):
    BRUTE_FORCE = "brute_force"
    INJECTION = "injection"
    SPOOFING = "spoofing"
    REPLAY = "replay"
    SWEEP = "sweep"
    ESCALATION = "escalation"
    APT = "apt"
    UNKNOWN = "unknown"


class AttackSource(str, Enum):
    BLE = "ble"
    WEBSOCKET = "websocket"
    REST = "rest"
    MESH = "mesh"


# =============================================================================
# DATA CLASSES
# =============================================================================

class AttackSignal:
    """Raw signal from a detection layer."""

    __slots__ = (
        "signal_id", "source", "timestamp", "device_address",
        "ip_address", "user_agent", "payload", "failure_type",
        "target_fibre_id", "metadata",
    )

    def __init__(
        self,
        source: AttackSource,
        failure_type: str,
        *,
        device_address: Optional[str] = None,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None,
        payload: Optional[bytes] = None,
        target_fibre_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        self.signal_id = uuid4()
        self.source = source
        self.timestamp = datetime.now(timezone.utc)
        self.device_address = device_address
        self.ip_address = ip_address
        self.user_agent = user_agent
        self.payload = payload
        self.failure_type = failure_type
        self.target_fibre_id = target_fibre_id
        self.metadata = metadata or {}


class ThreatAssessment:
    """Output of the pattern analyser: attacker profile + recommended response."""

    __slots__ = (
        "attacker_profile_id", "threat_level", "attack_type",
        "recommended_tier", "target_fibres", "estimated_sophistication",
        "assessed_at",
    )

    def __init__(
        self,
        attacker_profile_id: UUID,
        threat_level: ThreatLevel,
        attack_type: AttackType,
        target_fibres: Optional[List[str]] = None,
        estimated_sophistication: float = 0.0,
    ) -> None:
        self.attacker_profile_id = attacker_profile_id
        self.threat_level = threat_level
        self.attack_type = attack_type
        self.target_fibres = target_fibres or []
        self.estimated_sophistication = estimated_sophistication
        self.assessed_at = datetime.now(timezone.utc)

        # Map threat level to response tier
        if threat_level <= ThreatLevel.MEDIUM:
            self.recommended_tier = 1
        elif threat_level == ThreatLevel.HIGH:
            self.recommended_tier = 2
        else:
            self.recommended_tier = 3


# =============================================================================
# IMMUNE RESPONSE ORCHESTRATOR
# =============================================================================

class ImmuneResponseOrchestrator:
    """
    Central coordinator for the Sovereign Counter-Intelligence pipeline.

    Wiring:
        Detection layers → ingest_signal() → fingerprinter → pattern_analyzer
        → threat assessment → dispatch response (Tier 1 / 2 / 3)
    """

    def __init__(
        self,
        db_pool=None,
        fingerprinter=None,
        pattern_analyzer=None,
        threat_db=None,
        honeypot_service=None,
        canary_service=None,
        tarpit_engine=None,
        seed_crafter=None,
        counter_emitter=None,
        beacon_listener=None,
        reverse_mapper=None,
        wisdom_mesh=None,
        tier3_enabled: bool = False,
    ) -> None:
        self.db_pool = db_pool
        self._fingerprinter = fingerprinter
        self._pattern_analyzer = pattern_analyzer
        self._threat_db = threat_db
        self._honeypot = honeypot_service
        self._canary = canary_service
        self._tarpit = tarpit_engine
        self._seed_crafter = seed_crafter
        self._counter_emitter = counter_emitter
        self._beacon_listener = beacon_listener
        self._reverse_mapper = reverse_mapper
        self._wisdom_mesh = wisdom_mesh
        self._tier3_enabled = tier3_enabled

        # In-memory signal queue for async processing
        self._signal_queue: asyncio.Queue[AttackSignal] = asyncio.Queue(maxsize=10_000)
        self._running = False
        self._process_task: Optional[asyncio.Task] = None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Start the background signal processor."""
        if self._running:
            return
        self._running = True
        self._process_task = asyncio.create_task(self._process_loop())
        logger.info("Immune Response Orchestrator started")

    async def stop(self) -> None:
        """Gracefully stop the processor."""
        self._running = False
        if self._process_task:
            self._process_task.cancel()
            try:
                await self._process_task
            except asyncio.CancelledError:
                pass
        logger.info("Immune Response Orchestrator stopped")

    # ------------------------------------------------------------------
    # Signal Ingestion (called by detection layers)
    # ------------------------------------------------------------------

    async def ingest_signal(self, signal: AttackSignal) -> None:
        """
        Accept an attack signal from any detection layer.

        Called by:
          - Spider Web on detection failure (BLE)
          - Bridge Server on failed auth (WebSocket)
          - API middleware on suspicious request (REST)
          - Sovereign Immunity on guard_message failure (Mesh)
        """
        try:
            self._signal_queue.put_nowait(signal)
        except asyncio.QueueFull:
            logger.warning("Signal queue full — dropping oldest signal")
            try:
                self._signal_queue.get_nowait()
            except asyncio.QueueEmpty:
                pass
            self._signal_queue.put_nowait(signal)

    # ------------------------------------------------------------------
    # Background Processing Loop
    # ------------------------------------------------------------------

    async def _process_loop(self) -> None:
        """Continuously drain the signal queue and process each signal."""
        while self._running:
            try:
                signal = await asyncio.wait_for(
                    self._signal_queue.get(), timeout=5.0,
                )
            except asyncio.TimeoutError:
                continue
            except asyncio.CancelledError:
                break

            try:
                await self._handle_signal(signal)
            except Exception as exc:
                logger.error("Error handling signal %s: %s", signal.signal_id, exc)

    async def _handle_signal(self, signal: AttackSignal) -> None:
        """
        Full pipeline for a single attack signal:
          1. Fingerprint the source
          2. Log the event in threat DB
          3. Run pattern analysis
          4. Assess threat level
          5. Dispatch graduated response
        """
        # Step 1: Fingerprint
        profile_id: Optional[UUID] = None
        if self._fingerprinter:
            profile_id = await self._fingerprinter.process_signal(signal)

        # Step 2: Log
        if self._threat_db and profile_id:
            await self._threat_db.log_event(
                profile_id=profile_id,
                event_type=signal.failure_type,
                event_data={
                    "source": signal.source.value,
                    "device_address": signal.device_address,
                    "ip_address": signal.ip_address,
                    "user_agent": signal.user_agent,
                    "target_fibre_id": signal.target_fibre_id,
                    "metadata": signal.metadata,
                },
                source_layer=signal.source.value,
                target_fibre_id=signal.target_fibre_id,
            )

        # Step 3: Pattern analysis → threat assessment
        assessment: Optional[ThreatAssessment] = None
        if self._pattern_analyzer and profile_id:
            assessment = await self._pattern_analyzer.assess(profile_id)

        if assessment is None:
            return

        # Step 4-5: Dispatch graduated response
        await self._dispatch_response(assessment)

    # ------------------------------------------------------------------
    # Graduated Response Dispatch
    # ------------------------------------------------------------------

    async def _dispatch_response(self, assessment: ThreatAssessment) -> None:
        """Route to the appropriate tier based on threat assessment."""
        tier = assessment.recommended_tier
        logger.info(
            "Dispatching tier %d response for attacker %s (level=%s, type=%s)",
            tier,
            assessment.attacker_profile_id,
            assessment.threat_level.name,
            assessment.attack_type.value,
        )

        # Tier 1 always runs — intelligence + swarm alert
        await self._tier1_respond(assessment)

        if tier >= 2:
            await self._tier2_respond(assessment)

        if tier >= 3:
            await self._tier3_respond(assessment)

    # ------------------------------------------------------------------
    # Tier 1: Intelligence + Swarm Alert
    # ------------------------------------------------------------------

    async def _tier1_respond(self, assessment: ThreatAssessment) -> None:
        """Track and alert the swarm."""
        # Update threat DB with assessment
        if self._threat_db:
            await self._threat_db.update_threat_level(
                assessment.attacker_profile_id,
                assessment.threat_level,
            )

        # Broadcast THREAT_ALERT to Wisdom Mesh
        if self._wisdom_mesh and assessment.threat_level >= ThreatLevel.MEDIUM:
            fingerprint = None
            if self._fingerprinter:
                fingerprint = await self._fingerprinter.get_profile(
                    assessment.attacker_profile_id,
                )
            await self._broadcast_threat_alert(assessment, fingerprint)

        logger.info(
            "Tier 1: Logged + alerted swarm for attacker %s",
            assessment.attacker_profile_id,
        )

    async def _broadcast_threat_alert(
        self, assessment: ThreatAssessment, fingerprint: Optional[Dict],
    ) -> None:
        """Publish THREAT_ALERT to Wisdom Mesh so all Fibres can watch."""
        if not self._wisdom_mesh:
            return
        try:
            from app.models.mesh import MeshMessage, MeshMessageType, MeshPriority

            alert_body = {
                "alert_type": "THREAT_ALERT",
                "attacker_profile_id": str(assessment.attacker_profile_id),
                "threat_level": assessment.threat_level.name,
                "attack_type": assessment.attack_type.value,
                "target_fibres": assessment.target_fibres,
                "fingerprint": fingerprint,
                "assessed_at": assessment.assessed_at.isoformat(),
            }
            msg = MeshMessage(
                sender_id=UUID("00000000-0000-0000-0000-000000000000"),
                message_type=MeshMessageType.QUARANTINE_NOTICE,
                body=alert_body,
                domain_tags=["counter-intelligence", "threat-alert"],
                priority=MeshPriority.HIGH,
            )
            await self._wisdom_mesh.publish(msg)
        except Exception as exc:
            logger.error("Failed to broadcast threat alert: %s", exc)

    # ------------------------------------------------------------------
    # Tier 2: Deceptive Defense
    # ------------------------------------------------------------------

    async def _tier2_respond(self, assessment: ThreatAssessment) -> None:
        """Deploy honeypots, canaries, and tarpit."""
        tasks = []

        if self._honeypot:
            tasks.append(
                self._honeypot.deploy_for_attacker(
                    str(assessment.attacker_profile_id),
                    assessment.target_fibres,
                )
            )

        if self._canary:
            tasks.append(
                self._canary.deploy_canaries(
                    str(assessment.attacker_profile_id),
                    assessment.attack_type.value,
                )
            )

        if self._tarpit:
            tasks.append(
                self._tarpit.activate_for_attacker(
                    str(assessment.attacker_profile_id),
                    assessment.threat_level,
                )
            )

        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

        # Log counter-measure deployment
        if self._threat_db:
            await self._threat_db.log_counter_measure(
                attacker_id=assessment.attacker_profile_id,
                measure_type="tier2_deceptive_defense",
                result={"honeypot": bool(self._honeypot),
                        "canary": bool(self._canary),
                        "tarpit": bool(self._tarpit)},
            )

        logger.info(
            "Tier 2: Deployed honeypots/canaries/tarpit for attacker %s",
            assessment.attacker_profile_id,
        )

    # ------------------------------------------------------------------
    # Tier 3: Active Retrieval Seeds
    # ------------------------------------------------------------------

    async def _tier3_respond(self, assessment: ThreatAssessment) -> None:
        """Emit counter-fragments and retrieval seeds."""
        if not self._tier3_enabled:
            logger.warning(
                "Tier 3 requested but disabled (TIER_3_ENABLED=false). "
                "Enable after legal review."
            )
            return

        tasks = []

        if self._seed_crafter:
            tasks.append(
                self._seed_crafter.craft_for_attacker(
                    str(assessment.attacker_profile_id),
                    assessment.attack_type.value,
                )
            )

        if self._counter_emitter and self._fingerprinter:
            profile = await self._fingerprinter.get_profile(
                assessment.attacker_profile_id,
            )
            if profile:
                tasks.append(
                    self._counter_emitter.target_attacker(profile)
                )

        if tasks:
            results = await asyncio.gather(*tasks, return_exceptions=True)
            seeds = [r for r in results if isinstance(r, list)]
            if seeds and self._counter_emitter:
                for seed_batch in seeds:
                    for seed in seed_batch:
                        await self._counter_emitter.queue_seed(seed)

        # Log
        if self._threat_db:
            await self._threat_db.log_counter_measure(
                attacker_id=assessment.attacker_profile_id,
                measure_type="tier3_retrieval_seeds",
                result={"tier3_enabled": True,
                        "seed_crafter": bool(self._seed_crafter),
                        "counter_emitter": bool(self._counter_emitter)},
            )

        logger.info(
            "Tier 3: Deployed retrieval seeds for attacker %s",
            assessment.attacker_profile_id,
        )

    # ------------------------------------------------------------------
    # Manual Escalation
    # ------------------------------------------------------------------

    async def escalate(
        self, profile_id: UUID, target_tier: int, reason: str = "",
    ) -> Dict[str, Any]:
        """Manually escalate an attacker to a higher response tier."""
        level_map = {1: ThreatLevel.MEDIUM, 2: ThreatLevel.HIGH,
                     3: ThreatLevel.CRITICAL}
        level = level_map.get(target_tier, ThreatLevel.CRITICAL)

        assessment = ThreatAssessment(
            attacker_profile_id=profile_id,
            threat_level=level,
            attack_type=AttackType.UNKNOWN,
        )

        await self._dispatch_response(assessment)

        return {
            "profile_id": str(profile_id),
            "escalated_to_tier": target_tier,
            "reason": reason,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    # ------------------------------------------------------------------
    # Status
    # ------------------------------------------------------------------

    def get_status(self) -> Dict[str, Any]:
        """Return orchestrator health status."""
        return {
            "running": self._running,
            "queue_size": self._signal_queue.qsize(),
            "tier3_enabled": self._tier3_enabled,
            "services": {
                "fingerprinter": self._fingerprinter is not None,
                "pattern_analyzer": self._pattern_analyzer is not None,
                "threat_db": self._threat_db is not None,
                "honeypot": self._honeypot is not None,
                "canary": self._canary is not None,
                "tarpit": self._tarpit is not None,
                "seed_crafter": self._seed_crafter is not None,
                "counter_emitter": self._counter_emitter is not None,
                "beacon_listener": self._beacon_listener is not None,
                "reverse_mapper": self._reverse_mapper is not None,
            },
        }
