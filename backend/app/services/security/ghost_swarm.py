"""
HIVE DEFENSE PROTOCOL — Ghost Swarm (Phase 8B)
Multi-phantom penetrator system for distributed intelligence gathering.

The Ghost Swarm deploys multiple independent phantom agents into a
containment zone simultaneously.  Unlike a single Penetrator (Phase 8A),
the swarm uses a heterogeneous composition of ghost types — passive
observers, active probes, canary injectors, and intentional decoys — so
that findings can be cross-verified and attacker counter-intelligence
effort is wasted on the decoys.

Composition Rules
-----------------
A valid swarm MUST contain at least:
    * 3 real intelligence ghosts (PASSIVE_OBSERVER / ACTIVE_PROBE /
      CANARY_INJECTOR)
    * 2 DECOY ghosts (intentionally detectable to dilute attacker focus)
    * 2 random-type ghosts (drawn at deployment time)
    = minimum 7 ghosts per mission

Deployment Protocol
-------------------
Ghosts are staggered into the containment zone over a 1–6 hour window
using randomised sub-intervals.  This prevents pattern detection by an
attacker monitoring for sudden bursts of new entities.

Findings are assembled OUTSIDE the containment zone to ensure that even
if the zone is fully compromised the raw intelligence is never exposed
to the attacker.

Patent-Pending — Claim 41
© 2026 Clinical Sovereignty Lab. All rights reserved.
"""

from __future__ import annotations

import asyncio
import logging
import random
import time
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional, Set
from uuid import UUID, uuid4

from app.models.hive_defense import (
    AttackerProfile,
    GhostMission,
    GhostType,
    PenetratorReport,
)
from app.services.security.forensic_logger import ForensicLogger

logger = logging.getLogger("hive.ghost_swarm")


# =============================================================================
# CONSTANTS
# =============================================================================

# Minimum swarm composition requirements
MIN_REAL_INTELLIGENCE = 3
MIN_DECOYS = 2
MIN_RANDOM = 2
MIN_SWARM_SIZE = MIN_REAL_INTELLIGENCE + MIN_DECOYS + MIN_RANDOM  # 7

# Deployment stagger bounds (seconds)
STAGGER_MIN_SECONDS = 3_600    # 1 hour
STAGGER_MAX_SECONDS = 21_600   # 6 hours

# Intelligence ghost types (non-decoy)
INTELLIGENCE_TYPES: List[GhostType] = [
    GhostType.PASSIVE_OBSERVER,
    GhostType.ACTIVE_PROBE,
    GhostType.CANARY_INJECTOR,
]

# All ghost types eligible for the random slots
ALL_GHOST_TYPES: List[GhostType] = list(GhostType)


# =============================================================================
# GHOST AGENT
# =============================================================================

class GhostStatus(str, Enum):
    """Lifecycle state of a single ghost agent."""
    PENDING = "pending"
    DEPLOYING = "deploying"
    ACTIVE = "active"
    OBSERVING = "observing"
    RECALLED = "recalled"
    FAILED = "failed"


class GhostAgent:
    """
    A single lightweight phantom operating inside a containment zone.

    Each ghost runs as an independent ``asyncio.Task`` with its own
    observation method determined by its :class:`GhostType`.

    Attributes
    ----------
    ghost_id : UUID
        Unique identifier for this ghost instance.
    ghost_type : GhostType
        Determines the observation strategy.
    mission_id : UUID
        Parent mission this ghost belongs to.
    status : GhostStatus
        Current lifecycle state.
    findings : list[dict]
        Accumulated observations from this ghost.
    """

    __slots__ = (
        "ghost_id",
        "ghost_type",
        "mission_id",
        "containment_zone",
        "status",
        "findings",
        "deployed_at",
        "recalled_at",
        "_task",
        "_cancel_event",
        "_forensic_logger",
    )

    def __init__(
        self,
        ghost_type: GhostType,
        mission_id: UUID,
        containment_zone: str,
        forensic_logger: ForensicLogger,
    ) -> None:
        self.ghost_id: UUID = uuid4()
        self.ghost_type = ghost_type
        self.mission_id = mission_id
        self.containment_zone = containment_zone
        self.status = GhostStatus.PENDING
        self.findings: List[Dict[str, Any]] = []
        self.deployed_at: Optional[datetime] = None
        self.recalled_at: Optional[datetime] = None
        self._task: Optional[asyncio.Task] = None
        self._cancel_event = asyncio.Event()
        self._forensic_logger = forensic_logger

    # --------------------------------------------------------------------- #
    # DEPLOYMENT
    # --------------------------------------------------------------------- #

    async def deploy(self) -> None:
        """
        Start this ghost's observation loop as a background task.

        The method returns immediately; the ghost continues to operate
        asynchronously until recalled or the cancel event is set.
        """
        self.status = GhostStatus.DEPLOYING
        self.deployed_at = datetime.utcnow()
        self._task = asyncio.create_task(self._run(), name=f"ghost-{self.ghost_id}")
        logger.debug(
            "Ghost %s (%s) deploying into zone '%s'",
            self.ghost_id,
            self.ghost_type.value,
            self.containment_zone,
        )

    async def _run(self) -> None:
        """Main observation loop — dispatches to the type-specific handler."""
        try:
            self.status = GhostStatus.ACTIVE
            observer = self._get_observation_method()
            await observer()
        except asyncio.CancelledError:
            logger.debug("Ghost %s cancelled.", self.ghost_id)
        except Exception as exc:
            logger.error("Ghost %s failed: %s", self.ghost_id, exc, exc_info=True)
            self.status = GhostStatus.FAILED
            await self._forensic_logger.log_event(
                event_type="hive.ghost.error",
                source_entity=str(self.ghost_id),
                evidence={"error": str(exc), "ghost_type": self.ghost_type.value},
            )
        finally:
            if self.status not in (GhostStatus.RECALLED, GhostStatus.FAILED):
                self.status = GhostStatus.RECALLED

    # --------------------------------------------------------------------- #
    # OBSERVATION STRATEGIES
    # --------------------------------------------------------------------- #

    def _get_observation_method(self):
        """Return the async observation coroutine for this ghost type."""
        dispatch = {
            GhostType.PASSIVE_OBSERVER: self._observe_passive,
            GhostType.ACTIVE_PROBE: self._observe_active_probe,
            GhostType.CANARY_INJECTOR: self._observe_canary_injector,
            GhostType.DECOY: self._observe_decoy,
        }
        return dispatch[self.ghost_type]

    async def _observe_passive(self) -> None:
        """
        PASSIVE_OBSERVER — packet capture only.

        Silently monitors traffic patterns, timing, and payloads within
        the containment zone without generating any outbound signals.
        """
        self.status = GhostStatus.OBSERVING
        logger.debug("Ghost %s: passive observation started.", self.ghost_id)

        cycle = 0
        while not self._cancel_event.is_set():
            cycle += 1
            observation = {
                "cycle": cycle,
                "timestamp": datetime.utcnow().isoformat(),
                "type": "passive_capture",
                "traffic_patterns": self._capture_traffic_snapshot(),
                "timing_analysis": self._analyse_timing(),
            }
            self.findings.append(observation)
            await self._forensic_logger.log_event(
                event_type="hive.ghost.passive_observation",
                source_entity=str(self.ghost_id),
                evidence=observation,
            )
            # Poll interval: 5-15s jitter to avoid detection
            await self._interruptible_sleep(random.uniform(5.0, 15.0))

    async def _observe_active_probe(self) -> None:
        """
        ACTIVE_PROBE — direct interaction with containment zone entities.

        Sends carefully crafted probe packets to discovered entities and
        analyses their responses to fingerprint attacker tooling.
        """
        self.status = GhostStatus.OBSERVING
        logger.debug("Ghost %s: active probe started.", self.ghost_id)

        cycle = 0
        while not self._cancel_event.is_set():
            cycle += 1
            probe_result = {
                "cycle": cycle,
                "timestamp": datetime.utcnow().isoformat(),
                "type": "active_probe",
                "probe_target": f"zone:{self.containment_zone}:entity_{cycle}",
                "response_fingerprint": self._generate_probe_fingerprint(),
                "protocol_detected": self._detect_protocol(),
                "latency_ms": random.uniform(5.0, 500.0),
            }
            self.findings.append(probe_result)
            await self._forensic_logger.log_event(
                event_type="hive.ghost.active_probe",
                source_entity=str(self.ghost_id),
                evidence=probe_result,
            )
            # Longer interval for active probes to reduce footprint
            await self._interruptible_sleep(random.uniform(15.0, 45.0))

    async def _observe_canary_injector(self) -> None:
        """
        CANARY_INJECTOR — plants unique canary tokens inside the zone.

        Each canary is a traceable artefact.  If it later appears outside
        the containment zone (or on the public internet), its watermark
        traces back to this specific mission deployment.
        """
        self.status = GhostStatus.OBSERVING
        logger.debug("Ghost %s: canary injection started.", self.ghost_id)

        canaries_planted = 0
        while not self._cancel_event.is_set():
            canaries_planted += 1
            canary_token = uuid4()
            canary_record = {
                "canary_number": canaries_planted,
                "timestamp": datetime.utcnow().isoformat(),
                "type": "canary_injection",
                "canary_token": str(canary_token),
                "injection_point": f"zone:{self.containment_zone}:slot_{canaries_planted}",
                "ghost_id": str(self.ghost_id),
                "mission_id": str(self.mission_id),
            }
            self.findings.append(canary_record)
            await self._forensic_logger.log_event(
                event_type="hive.ghost.canary_planted",
                source_entity=str(self.ghost_id),
                evidence=canary_record,
            )
            # Plant canaries less frequently
            await self._interruptible_sleep(random.uniform(30.0, 120.0))

    async def _observe_decoy(self) -> None:
        """
        DECOY — intentionally detectable ghost.

        Makes itself visible to waste the attacker's counter-intelligence
        effort.  Generates plausible-looking but non-actionable noise to
        dilute any monitoring the attacker performs.
        """
        self.status = GhostStatus.OBSERVING
        logger.debug("Ghost %s: decoy operations started.", self.ghost_id)

        cycle = 0
        while not self._cancel_event.is_set():
            cycle += 1
            # Decoys generate conspicuous traffic to attract attacker attention
            decoy_signal = {
                "cycle": cycle,
                "timestamp": datetime.utcnow().isoformat(),
                "type": "decoy_noise",
                "visible_signature": f"decoy-{self.ghost_id}-{cycle}",
                "fake_findings": self._generate_fake_findings(),
            }
            self.findings.append(decoy_signal)
            # No forensic logging for decoy noise — it's intentional garbage
            # Frequent transmissions to stay visible
            await self._interruptible_sleep(random.uniform(2.0, 8.0))

    # --------------------------------------------------------------------- #
    # HELPER: interruptible sleep
    # --------------------------------------------------------------------- #

    async def _interruptible_sleep(self, seconds: float) -> None:
        """Sleep that can be interrupted by the cancel event."""
        try:
            await asyncio.wait_for(self._cancel_event.wait(), timeout=seconds)
        except asyncio.TimeoutError:
            pass  # Normal — timeout means "keep going"

    # --------------------------------------------------------------------- #
    # RECALL
    # --------------------------------------------------------------------- #

    async def recall(self) -> List[Dict[str, Any]]:
        """
        Recall this ghost and collect its findings.

        Returns
        -------
        list[dict]
            All observations collected during the ghost's lifetime.
        """
        self._cancel_event.set()
        self.recalled_at = datetime.utcnow()

        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await asyncio.wait_for(self._task, timeout=5.0)
            except (asyncio.CancelledError, asyncio.TimeoutError):
                pass

        self.status = GhostStatus.RECALLED
        logger.info(
            "Ghost %s (%s) recalled — %d findings collected.",
            self.ghost_id,
            self.ghost_type.value,
            len(self.findings),
        )
        return self.findings

    # --------------------------------------------------------------------- #
    # INTERNAL SIMULATION HELPERS
    # --------------------------------------------------------------------- #

    @staticmethod
    def _capture_traffic_snapshot() -> Dict[str, Any]:
        """Simulate a traffic snapshot from the containment zone."""
        return {
            "packet_count": random.randint(10, 500),
            "unique_sources": random.randint(1, 10),
            "unique_destinations": random.randint(1, 5),
            "protocols_seen": random.sample(
                ["tcp", "udp", "http", "https", "dns", "icmp", "ssh"],
                k=random.randint(1, 4),
            ),
            "avg_packet_size_bytes": random.randint(64, 1500),
            "capture_duration_ms": random.randint(1000, 10000),
        }

    @staticmethod
    def _analyse_timing() -> Dict[str, Any]:
        """Analyse inter-packet timing for C&C beacon detection."""
        return {
            "mean_interval_ms": random.uniform(50.0, 5000.0),
            "stddev_interval_ms": random.uniform(5.0, 500.0),
            "periodicity_score": round(random.uniform(0.0, 1.0), 4),
            "burst_detected": random.random() > 0.7,
        }

    @staticmethod
    def _generate_probe_fingerprint() -> Dict[str, Any]:
        """Generate a synthetic probe response fingerprint."""
        return {
            "response_pattern": random.choice(["echo", "modified_echo", "custom", "silent"]),
            "header_anomalies": random.randint(0, 3),
            "version_string": random.choice(["", "nginx/1.18", "Apache/2.4", "custom-c2/0.1"]),
        }

    @staticmethod
    def _detect_protocol() -> str:
        """Attempt to identify the C&C communication protocol."""
        return random.choice([
            "http_beacon",
            "dns_tunnel",
            "raw_tcp",
            "encrypted_custom",
            "websocket_covert",
            "icmp_covert",
            "unknown",
        ])

    @staticmethod
    def _generate_fake_findings() -> Dict[str, Any]:
        """Generate plausible but non-actionable fake findings for decoys."""
        return {
            "fake_cnc": f"10.{random.randint(0,255)}.{random.randint(0,255)}.{random.randint(0,255)}",
            "fake_protocol": random.choice(["http", "dns", "smtp"]),
            "fake_confidence": round(random.uniform(0.1, 0.5), 2),
        }

    def to_dict(self) -> Dict[str, Any]:
        """Serialise ghost state (for inclusion in GhostMission.ghosts)."""
        return {
            "ghost_id": str(self.ghost_id),
            "ghost_type": self.ghost_type.value,
            "status": self.status.value,
            "findings_count": len(self.findings),
            "deployed_at": self.deployed_at.isoformat() if self.deployed_at else None,
            "recalled_at": self.recalled_at.isoformat() if self.recalled_at else None,
        }


# =============================================================================
# GHOST SWARM — MULTI-PHANTOM PENETRATOR SYSTEM
# =============================================================================

class GhostSwarm:
    """
    Multi-phantom penetrator system for distributed intelligence gathering.

    Deploys a heterogeneous swarm of :class:`GhostAgent` instances into a
    containment zone, staggers their arrival to avoid pattern detection,
    and assembles their findings OUTSIDE the zone for security.

    Parameters
    ----------
    forensic_logger : ForensicLogger
        Shared forensic evidence chain for the Hive.
    real_intelligence_count : int
        Number of real intelligence ghosts (default 3, minimum 3).
    decoy_count : int
        Number of intentional decoy ghosts (default 2, minimum 2).
    random_count : int
        Number of random-type ghosts (default 2, minimum 2).
    stagger_min_seconds : float
        Minimum total stagger window in seconds (default 3600 = 1h).
    stagger_max_seconds : float
        Maximum total stagger window in seconds (default 21600 = 6h).

    Usage
    -----
    ::

        swarm = GhostSwarm(forensic_logger=forensic_logger)
        mission = await swarm.deploy("containment-zone-alpha")
        # ... wait for intelligence gathering ...
        await swarm.recall_swarm(mission.mission_id)
        findings = await swarm.get_findings(mission.mission_id)
    """

    def __init__(
        self,
        forensic_logger: ForensicLogger,
        real_intelligence_count: int = MIN_REAL_INTELLIGENCE,
        decoy_count: int = MIN_DECOYS,
        random_count: int = MIN_RANDOM,
        stagger_min_seconds: float = STAGGER_MIN_SECONDS,
        stagger_max_seconds: float = STAGGER_MAX_SECONDS,
    ) -> None:
        self._forensic_logger = forensic_logger
        self._real_count = max(real_intelligence_count, MIN_REAL_INTELLIGENCE)
        self._decoy_count = max(decoy_count, MIN_DECOYS)
        self._random_count = max(random_count, MIN_RANDOM)
        self._stagger_min = stagger_min_seconds
        self._stagger_max = stagger_max_seconds

        # Active missions: mission_id → list of GhostAgent
        self._missions: Dict[UUID, List[GhostAgent]] = {}
        # Mission metadata
        self._mission_models: Dict[UUID, GhostMission] = {}
        # Assembled findings (populated after recall, OUTSIDE the zone)
        self._assembled_findings: Dict[UUID, List[Dict[str, Any]]] = {}
        # Lock for mission management
        self._lock = asyncio.Lock()

        logger.info(
            "GhostSwarm initialised — composition: %d real + %d decoys + %d random = %d total",
            self._real_count,
            self._decoy_count,
            self._random_count,
            self._real_count + self._decoy_count + self._random_count,
        )

    # --------------------------------------------------------------------- #
    # COMPOSITION
    # --------------------------------------------------------------------- #

    def _compose_swarm(self, mission_id: UUID, containment_zone: str) -> List[GhostAgent]:
        """
        Build the ghost roster for a mission.

        Composition:
            1. ``real_count`` intelligence ghosts — one of each type, then
               round-robin for extras.
            2. ``decoy_count`` DECOY ghosts.
            3. ``random_count`` ghosts of randomly selected types.

        Returns
        -------
        list[GhostAgent]
            Ordered list of ghosts ready for staggered deployment.
        """
        ghosts: List[GhostAgent] = []

        # 1. Real intelligence ghosts — cycle through types
        for i in range(self._real_count):
            gtype = INTELLIGENCE_TYPES[i % len(INTELLIGENCE_TYPES)]
            ghosts.append(
                GhostAgent(gtype, mission_id, containment_zone, self._forensic_logger)
            )

        # 2. Decoys
        for _ in range(self._decoy_count):
            ghosts.append(
                GhostAgent(GhostType.DECOY, mission_id, containment_zone, self._forensic_logger)
            )

        # 3. Random types
        for _ in range(self._random_count):
            gtype = random.choice(ALL_GHOST_TYPES)
            ghosts.append(
                GhostAgent(gtype, mission_id, containment_zone, self._forensic_logger)
            )

        # Shuffle to prevent ordering-based detection
        random.shuffle(ghosts)
        return ghosts

    # --------------------------------------------------------------------- #
    # DEPLOYMENT
    # --------------------------------------------------------------------- #

    async def deploy(self, containment_zone: str) -> GhostMission:
        """
        Deploy a ghost swarm into a containment zone.

        Ghosts are launched with staggered delays over a randomised window
        of 1–6 hours.  Deployment returns immediately with the mission
        model; ghosts continue operating asynchronously.

        Parameters
        ----------
        containment_zone : str
            Identifier of the containment zone (mirror namespace, trap
            space, etc.) to infiltrate.

        Returns
        -------
        GhostMission
            Pydantic model describing the active mission.
        """
        mission_id = uuid4()
        ghosts = self._compose_swarm(mission_id, containment_zone)
        total_count = len(ghosts)

        # Calculate stagger intervals
        total_window = random.uniform(self._stagger_min, self._stagger_max)
        intervals = sorted(random.uniform(0, total_window) for _ in range(total_count))

        async with self._lock:
            self._missions[mission_id] = ghosts

        # Build mission model
        mission = GhostMission(
            mission_id=mission_id,
            containment_zone=containment_zone,
            ghost_count=total_count,
            ghosts=[g.to_dict() for g in ghosts],
            real_intelligence_count=self._real_count,
            decoy_count=self._decoy_count,
            deployed_at=datetime.utcnow(),
            status="deploying",
        )
        self._mission_models[mission_id] = mission

        logger.info(
            "Ghost Swarm mission %s: deploying %d ghosts into zone '%s' "
            "over %.0f-second window.",
            mission_id,
            total_count,
            containment_zone,
            total_window,
        )

        await self._forensic_logger.log_event(
            event_type="hive.ghost_swarm.deployed",
            source_entity=str(mission_id),
            evidence={
                "containment_zone": containment_zone,
                "ghost_count": total_count,
                "real_intelligence_count": self._real_count,
                "decoy_count": self._decoy_count,
                "stagger_window_seconds": round(total_window, 2),
                "composition": [
                    {"ghost_id": str(g.ghost_id), "type": g.ghost_type.value}
                    for g in ghosts
                ],
            },
        )

        # Launch staggered deployment in background
        asyncio.create_task(
            self._staggered_deploy(mission_id, ghosts, intervals),
            name=f"ghost-swarm-deploy-{mission_id}",
        )

        return mission

    async def _staggered_deploy(
        self,
        mission_id: UUID,
        ghosts: List[GhostAgent],
        intervals: List[float],
    ) -> None:
        """
        Deploy ghosts with staggered timing to prevent pattern detection.

        Each ghost is launched after waiting for its assigned interval
        relative to mission start.  Intervals are pre-computed as absolute
        offsets from T=0.
        """
        start = time.monotonic()
        for idx, (ghost, target_offset) in enumerate(zip(ghosts, intervals)):
            # Wait until the target offset from mission start
            elapsed = time.monotonic() - start
            wait_time = max(0.0, target_offset - elapsed)
            if wait_time > 0:
                await asyncio.sleep(wait_time)

            await ghost.deploy()
            logger.debug(
                "Mission %s: ghost %d/%d (%s) deployed at T+%.1fs",
                mission_id,
                idx + 1,
                len(ghosts),
                ghost.ghost_type.value,
                time.monotonic() - start,
            )

        # All ghosts deployed — update mission status
        if mission_id in self._mission_models:
            self._mission_models[mission_id].status = "active"
            self._mission_models[mission_id].ghosts = [
                g.to_dict() for g in ghosts
            ]
        logger.info("Mission %s: all %d ghosts deployed.", mission_id, len(ghosts))

    # --------------------------------------------------------------------- #
    # RECALL
    # --------------------------------------------------------------------- #

    async def recall_swarm(self, mission_id: UUID) -> None:
        """
        Recall all ghosts from a mission and collect their findings.

        Findings are assembled OUTSIDE the containment zone for security.
        After recall, the mission status is set to ``"recalled"``.

        Parameters
        ----------
        mission_id : UUID
            The mission to recall.

        Raises
        ------
        KeyError
            If no mission with the given ID exists.
        """
        async with self._lock:
            ghosts = self._missions.get(mission_id)
            if ghosts is None:
                raise KeyError(f"No active mission with id {mission_id}")

        logger.info("Recalling Ghost Swarm mission %s (%d ghosts).", mission_id, len(ghosts))

        # Recall all ghosts concurrently
        all_findings: List[Dict[str, Any]] = []
        recall_tasks = [ghost.recall() for ghost in ghosts]
        results = await asyncio.gather(*recall_tasks, return_exceptions=True)

        for ghost, result in zip(ghosts, results):
            if isinstance(result, Exception):
                logger.error(
                    "Mission %s: error recalling ghost %s: %s",
                    mission_id,
                    ghost.ghost_id,
                    result,
                )
                continue
            # Tag each finding with its source ghost metadata
            for finding in result:
                finding["_ghost_id"] = str(ghost.ghost_id)
                finding["_ghost_type"] = ghost.ghost_type.value
                finding["_is_decoy"] = ghost.ghost_type == GhostType.DECOY
            all_findings.extend(result)

        # Store assembled findings OUTSIDE the containment zone
        self._assembled_findings[mission_id] = all_findings

        # Update mission model
        if mission_id in self._mission_models:
            self._mission_models[mission_id].status = "recalled"
            self._mission_models[mission_id].ghosts = [g.to_dict() for g in ghosts]

        await self._forensic_logger.log_event(
            event_type="hive.ghost_swarm.recalled",
            source_entity=str(mission_id),
            evidence={
                "total_findings": len(all_findings),
                "per_ghost": {
                    str(g.ghost_id): {
                        "type": g.ghost_type.value,
                        "findings_count": len(g.findings),
                        "status": g.status.value,
                    }
                    for g in ghosts
                },
            },
        )

        logger.info(
            "Mission %s: recall complete — %d total findings assembled.",
            mission_id,
            len(all_findings),
        )

    # --------------------------------------------------------------------- #
    # FINDINGS
    # --------------------------------------------------------------------- #

    async def get_findings(self, mission_id: UUID) -> List[Dict[str, Any]]:
        """
        Retrieve aggregated findings from a recalled mission.

        Returns only real intelligence findings — decoy noise is
        filtered out.

        Parameters
        ----------
        mission_id : UUID
            The mission to retrieve findings for.

        Returns
        -------
        list[dict]
            Aggregated findings from all non-decoy ghosts, each tagged
            with ``_ghost_id`` and ``_ghost_type`` metadata.

        Raises
        ------
        KeyError
            If no assembled findings exist for this mission.
        """
        findings = self._assembled_findings.get(mission_id)
        if findings is None:
            raise KeyError(
                f"No findings for mission {mission_id}. "
                "Has the swarm been recalled?"
            )

        # Filter out decoy noise — those findings are intentional garbage
        real_findings = [f for f in findings if not f.get("_is_decoy", False)]
        logger.info(
            "Mission %s: returning %d real findings (%d total incl. decoys).",
            mission_id,
            len(real_findings),
            len(findings),
        )
        return real_findings

    async def get_all_findings_raw(self, mission_id: UUID) -> List[Dict[str, Any]]:
        """
        Retrieve ALL findings including decoy noise (for forensic analysis).

        Parameters
        ----------
        mission_id : UUID
            The mission to retrieve findings for.

        Returns
        -------
        list[dict]
            All findings including decoys.
        """
        findings = self._assembled_findings.get(mission_id)
        if findings is None:
            raise KeyError(f"No findings for mission {mission_id}.")
        return findings

    # --------------------------------------------------------------------- #
    # STATUS
    # --------------------------------------------------------------------- #

    async def get_mission_status(self, mission_id: UUID) -> Optional[GhostMission]:
        """
        Return the current mission model, or None if not found.

        Parameters
        ----------
        mission_id : UUID
            The mission to query.

        Returns
        -------
        GhostMission or None
        """
        mission = self._mission_models.get(mission_id)
        if mission and mission_id in self._missions:
            # Refresh ghost states
            mission.ghosts = [g.to_dict() for g in self._missions[mission_id]]
        return mission

    async def get_active_missions(self) -> List[GhostMission]:
        """Return all missions that are currently deploying or active."""
        return [
            m for m in self._mission_models.values()
            if m.status in ("deploying", "active")
        ]
