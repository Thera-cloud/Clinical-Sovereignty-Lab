"""
HIVE DEFENSE PROTOCOL — Penetrator Fibre (Phase 8A)
Specialised stealth Fibre for counter-intelligence attack tracing.

The Penetrator is a single-use, covert agent spawned by the Hive when a
containment zone captures suspicious activity.  It executes a disciplined
five-phase mission to identify, fingerprint, and map the attacker's
infrastructure before delivering a comprehensive forensic report to
Big Nate and the Observer Fibre.

Mission Phases
--------------
1. **OBSERVE** — enter the containment zone silently, monitor traffic
   patterns, and map communication topology.
2. **TRACE** — follow network paths backward from the containment zone,
   correlate timing, and identify origin addresses.
3. **FINGERPRINT** — construct a behavioural signature of the attacker's
   methodology using the :class:`AttackerFingerprintDB`.
4. **MAP** — build a full attack topology: entry vectors, compromised
   (fake) Fibres, targeted data, duration, and sophistication rating.
5. **REPORT** — compile a :class:`PenetratorReport`, deliver it to
   Big Nate and Observer, and recommend an Infinite Mirror Trap if a
   command-and-control server has been identified.

Design Constraints
------------------
* ``stealth_mode = True`` — the Penetrator emits **no** Trail Emissions
  on the Wisdom Mesh and does not participate in heartbeat rounds.
* All evidence is recorded through the :class:`ForensicLogger`.
* The Penetrator self-destructs (deactivates) after REPORT phase.

Patent-Pending — Claim 34
© 2026 Clinical Sovereignty Lab. All rights reserved.
"""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import UUID, uuid4

from app.models.hive_defense import (
    AttackerProfile,
    PenetratorPhase,
    PenetratorReport,
)
from app.services.security.attacker_fingerprint import AttackerFingerprintDB
from app.services.security.forensic_logger import ForensicLogger

logger = logging.getLogger("hive.penetrator")


# =============================================================================
# PENETRATOR FIBRE
# =============================================================================

class Penetrator:
    """
    Stealth counter-intelligence Fibre for tracing and fingerprinting attackers.

    A Penetrator is spawned by a parent Fibre (typically the Hive Observer or
    Containment Manager) and operates entirely within a designated containment
    zone.  It progresses through five sequential phases—OBSERVE, TRACE,
    FINGERPRINT, MAP, REPORT—collecting forensic evidence at every step.

    Attributes
    ----------
    mission_id : UUID
        Unique identifier for this Penetrator's mission.
    parent_fibre_id : UUID
        The Fibre that spawned this Penetrator.
    containment_zone : str
        The namespace / zone identifier the Penetrator operates in.
    stealth_mode : bool
        Always ``True``.  Penetrators emit no Trail Emissions.
    phase : PenetratorPhase
        Current mission phase.
    report : PenetratorReport
        The forensic report being assembled throughout the mission.

    Usage
    -----
    ::

        pen = Penetrator(
            parent_fibre_id=observer.fibre_id,
            containment_zone="mirror-ns-42",
            forensic_logger=forensic_logger,
            fingerprint_db=fingerprint_db,
        )
        report = await pen.execute_mission()
    """

    def __init__(
        self,
        parent_fibre_id: UUID,
        containment_zone: str,
        *,
        forensic_logger: Optional[ForensicLogger] = None,
        fingerprint_db: Optional[AttackerFingerprintDB] = None,
    ) -> None:
        """
        Spawn a new Penetrator.

        Parameters
        ----------
        parent_fibre_id:
            The UUID of the Fibre that authorised the Penetrator's creation.
        containment_zone:
            Identifier of the mirror-dimension containment zone to operate in.
        forensic_logger:
            Shared :class:`ForensicLogger` for immutable evidence recording.
        fingerprint_db:
            Shared :class:`AttackerFingerprintDB` for attacker matching and
            storage.
        """
        self.mission_id: UUID = uuid4()
        self.parent_fibre_id: UUID = parent_fibre_id
        self.containment_zone: str = containment_zone

        # Stealth — no Trail Emissions, no heartbeat participation
        self.stealth_mode: bool = True

        # Phase tracking
        self.phase: PenetratorPhase = PenetratorPhase.OBSERVE
        self._phase_timestamps: Dict[str, datetime] = {}

        # Forensic infrastructure
        self._forensic_logger: ForensicLogger = forensic_logger or ForensicLogger()
        self._fingerprint_db: AttackerFingerprintDB = (
            fingerprint_db or AttackerFingerprintDB()
        )

        # Working data accumulated across phases
        self._traffic_observations: List[Dict[str, Any]] = []
        self._communication_map: Dict[str, List[str]] = {}
        self._origin_traces: List[Dict[str, Any]] = []
        self._timing_correlations: List[Dict[str, Any]] = []
        self._attacker_profile: Optional[AttackerProfile] = None
        self._attack_topology: Dict[str, Any] = {}

        # The report we're building
        self.report: PenetratorReport = PenetratorReport(
            mission_id=self.mission_id,
            spawned_from=self.parent_fibre_id,
            target_zone=self.containment_zone,
            phase=PenetratorPhase.OBSERVE,
            started_at=datetime.utcnow(),
        )

        # Lifecycle
        self._active: bool = True
        self._start_ns: int = time.monotonic_ns()

        logger.info(
            "Penetrator spawned: mission=%s parent=%s zone=%s",
            self.mission_id,
            self.parent_fibre_id,
            self.containment_zone,
        )

    # ------------------------------------------------------------------
    # Main mission entry point
    # ------------------------------------------------------------------

    async def execute_mission(self) -> PenetratorReport:
        """
        Execute the full five-phase Penetrator mission.

        Each phase runs sequentially.  If any phase raises an exception the
        mission is aborted and a partial report is returned with whatever
        evidence has been collected so far.

        Returns
        -------
        PenetratorReport
            The complete (or partial, on error) forensic report.
        """
        try:
            await self._phase_observe()
            await self._phase_trace()
            await self._phase_fingerprint()
            await self._phase_map()
            await self._phase_report()
        except Exception as exc:
            logger.exception(
                "Penetrator %s mission aborted during phase %s: %s",
                self.mission_id,
                self.phase.value,
                exc,
            )
            self.report.recommendation = (
                f"Mission aborted during {self.phase.value}: {exc}"
            )
            await self._forensic_logger.log_event(
                event_type="hive.penetrator.mission_aborted",
                source_entity=str(self.mission_id),
                target_entity=self.containment_zone,
                evidence={"phase": self.phase.value, "error": str(exc)},
            )
        finally:
            self.report.completed_at = datetime.utcnow()
            self._active = False

        return self.report

    # ------------------------------------------------------------------
    # Phase 1: OBSERVE
    # ------------------------------------------------------------------

    async def _phase_observe(self) -> None:
        """
        Phase 1 — OBSERVE.

        Enter the containment zone, silently watch traffic, and map
        communication patterns between entities.

        Collected data
        --------------
        * Raw traffic observations (source, destination, payload hashes,
          timestamps).
        * Initial communication adjacency map.
        """
        self._transition_phase(PenetratorPhase.OBSERVE)

        logger.info(
            "Penetrator %s entering OBSERVE phase in zone '%s'",
            self.mission_id,
            self.containment_zone,
        )

        # Simulate observing traffic within the containment zone.
        # In production, this hooks into the Mirror Dimension's signal
        # stream for the target namespace.
        observation = {
            "zone": self.containment_zone,
            "entry_time": datetime.utcnow().isoformat(),
            "signals_observed": 0,
            "unique_sources": [],
            "unique_destinations": [],
            "communication_adjacency": {},
        }

        self._traffic_observations.append(observation)
        self.report.observations.append(observation)

        await self._forensic_logger.log_event(
            event_type="hive.penetrator.observe_started",
            source_entity=str(self.mission_id),
            target_entity=self.containment_zone,
            evidence=observation,
        )

        logger.info(
            "Penetrator %s OBSERVE complete — %d observations collected",
            self.mission_id,
            len(self._traffic_observations),
        )

    # ------------------------------------------------------------------
    # Phase 2: TRACE
    # ------------------------------------------------------------------

    async def _phase_trace(self) -> None:
        """
        Phase 2 — TRACE.

        Follow network paths backward from the containment zone, identify
        origin IP addresses, and correlate timing patterns to reveal the
        attacker's infrastructure.

        Collected data
        --------------
        * Origin traces (IP, timestamp, path hops).
        * Timing correlation entries (source → latency → likely C&C).
        """
        self._transition_phase(PenetratorPhase.TRACE)

        logger.info(
            "Penetrator %s entering TRACE phase", self.mission_id
        )

        # Analyse traffic observations to extract origin information.
        trace_result: Dict[str, Any] = {
            "zone": self.containment_zone,
            "traced_at": datetime.utcnow().isoformat(),
            "origin_ips": [],
            "path_hops": [],
            "timing_correlations": [],
            "cnc_candidates": [],
        }

        self._origin_traces.append(trace_result)
        self.report.origin_traces.append(trace_result)

        await self._forensic_logger.log_event(
            event_type="hive.penetrator.trace_complete",
            source_entity=str(self.mission_id),
            target_entity=self.containment_zone,
            evidence=trace_result,
        )

        logger.info(
            "Penetrator %s TRACE complete — %d origin trace(s)",
            self.mission_id,
            len(self._origin_traces),
        )

    # ------------------------------------------------------------------
    # Phase 3: FINGERPRINT
    # ------------------------------------------------------------------

    async def _phase_fingerprint(self) -> None:
        """
        Phase 3 — FINGERPRINT.

        Build a behavioural signature of the attacker's methodology.
        If a matching profile already exists in the
        :class:`AttackerFingerprintDB`, enrich it; otherwise, create a
        new one.

        Collected data
        --------------
        * :class:`AttackerProfile` (new or enriched).
        """
        self._transition_phase(PenetratorPhase.FINGERPRINT)

        logger.info(
            "Penetrator %s entering FINGERPRINT phase", self.mission_id
        )

        # Build observed behaviour from traffic + trace data
        observed_behavior = self._synthesise_behavioral_vector()

        # Try to match against known attackers
        existing_match = await self._fingerprint_db.match_fingerprint(
            observed_behavior
        )

        if existing_match:
            logger.info(
                "Penetrator %s matched existing attacker profile %s",
                self.mission_id,
                existing_match.profile_id,
            )
            # Enrich the existing profile
            await self._fingerprint_db.update_fingerprint(
                existing_match.profile_id,
                observed_behavior,
            )
            self._attacker_profile = existing_match
        else:
            # Create a new attacker profile
            profile = AttackerProfile(
                behavioral_patterns=observed_behavior,
                tool_signatures=self._extract_tool_signatures(),
                sophistication_level=self._estimate_sophistication(),
                first_seen=datetime.utcnow(),
                last_seen=datetime.utcnow(),
            )
            await self._fingerprint_db.add_fingerprint(profile)
            self._attacker_profile = profile

            logger.info(
                "Penetrator %s created new attacker profile %s "
                "(sophistication=%d)",
                self.mission_id,
                profile.profile_id,
                profile.sophistication_level,
            )

        self.report.fingerprint = {
            "profile_id": str(self._attacker_profile.profile_id),
            "sophistication_level": self._attacker_profile.sophistication_level,
            "tool_signatures": self._attacker_profile.tool_signatures,
            "behavioral_patterns": self._attacker_profile.behavioral_patterns,
            "is_returning_attacker": existing_match is not None,
        }

        await self._forensic_logger.log_event(
            event_type="hive.penetrator.fingerprint_complete",
            source_entity=str(self.mission_id),
            target_entity=self.containment_zone,
            evidence=self.report.fingerprint,
        )

    # ------------------------------------------------------------------
    # Phase 4: MAP
    # ------------------------------------------------------------------

    async def _phase_map(self) -> None:
        """
        Phase 4 — MAP.

        Generate a comprehensive attack topology covering entry vectors,
        fake Fibres injected, data assets targeted, duration of the
        intrusion, and an overall sophistication assessment.

        Collected data
        --------------
        * Attack topology dict stored in ``report.topology``.
        """
        self._transition_phase(PenetratorPhase.MAP)

        logger.info(
            "Penetrator %s entering MAP phase", self.mission_id
        )

        elapsed_ns = time.monotonic_ns() - self._start_ns
        elapsed_sec = elapsed_ns / 1_000_000_000

        topology: Dict[str, Any] = {
            "zone": self.containment_zone,
            "mapped_at": datetime.utcnow().isoformat(),
            "entry_vectors": self._identify_entry_vectors(),
            "fake_fibres_detected": self._detect_fake_fibres(),
            "data_targeted": self._identify_targeted_data(),
            "intrusion_duration_estimate_sec": elapsed_sec,
            "sophistication_rating": (
                self._attacker_profile.sophistication_level
                if self._attacker_profile
                else 1
            ),
            "cnc_servers": self._identify_cnc_servers(),
            "communication_topology": self._communication_map,
        }

        self._attack_topology = topology
        self.report.topology = topology

        # Determine if C&C was identified
        cnc_servers = topology.get("cnc_servers", [])
        if cnc_servers:
            self.report.cnc_server_identified = True
            self.report.cnc_addresses = cnc_servers

        await self._forensic_logger.log_event(
            event_type="hive.penetrator.map_complete",
            source_entity=str(self.mission_id),
            target_entity=self.containment_zone,
            evidence=topology,
        )

        logger.info(
            "Penetrator %s MAP complete — cnc_identified=%s, "
            "entry_vectors=%d",
            self.mission_id,
            self.report.cnc_server_identified,
            len(topology.get("entry_vectors", [])),
        )

    # ------------------------------------------------------------------
    # Phase 5: REPORT
    # ------------------------------------------------------------------

    async def _phase_report(self) -> None:
        """
        Phase 5 — REPORT.

        Compile the final :class:`PenetratorReport`, determine the
        recommended response (Infinite Mirror Trap if C&C identified),
        and deliver the report to Big Nate and the Observer Fibre.
        """
        self._transition_phase(PenetratorPhase.REPORT)

        logger.info(
            "Penetrator %s entering REPORT phase", self.mission_id
        )

        # Build recommendation
        if self.report.cnc_server_identified:
            self.report.recommendation = (
                "RECOMMEND: Deploy Infinite Mirror Trap against identified "
                f"C&C server(s): {', '.join(self.report.cnc_addresses)}. "
                "Attacker sophistication level: "
                f"{self._attacker_profile.sophistication_level if self._attacker_profile else 'unknown'}."
            )
        else:
            self.report.recommendation = (
                "No C&C server positively identified.  Recommend continued "
                "containment observation and Ghost Swarm deployment for "
                "additional intelligence gathering."
            )

        self.report.phase = PenetratorPhase.COMPLETE
        self.report.completed_at = datetime.utcnow()

        await self._forensic_logger.log_event(
            event_type="hive.penetrator.report_ready",
            source_entity=str(self.mission_id),
            target_entity=self.containment_zone,
            evidence={
                "mission_id": str(self.mission_id),
                "cnc_identified": self.report.cnc_server_identified,
                "cnc_addresses": self.report.cnc_addresses,
                "recommendation": self.report.recommendation,
                "phases_completed": list(self._phase_timestamps.keys()),
            },
        )

        # Self-deactivate — Penetrators are single-use
        self._active = False

        logger.info(
            "Penetrator %s mission COMPLETE — report delivered. "
            "recommendation='%s'",
            self.mission_id,
            self.report.recommendation[:120],
        )

    # ------------------------------------------------------------------
    # Phase helpers
    # ------------------------------------------------------------------

    def _transition_phase(self, new_phase: PenetratorPhase) -> None:
        """Record the phase transition with a timestamp."""
        self.phase = new_phase
        self.report.phase = new_phase
        self._phase_timestamps[new_phase.value] = datetime.utcnow()

    def _synthesise_behavioral_vector(self) -> Dict[str, Any]:
        """
        Synthesise a behavioural vector from collected traffic observations
        and trace data for use with the :class:`AttackerFingerprintDB`.
        """
        # In a production deployment these values would be computed from
        # real traffic metrics.  Here we provide a structured skeleton
        # that downstream consumers (fingerprint DB, reports) can populate.
        vector: Dict[str, Any] = {
            "scan_frequency": 0.0,
            "payload_entropy": 0.0,
            "protocol_diversity": 0.0,
            "timing_regularity": 0.0,
            "evasion_sophistication": 0.0,
            "lateral_movement": 0.0,
            "data_exfil_volume": 0.0,
            "persistence_attempts": 0.0,
            "tool_reuse_ratio": 0.0,
            "response_latency": 0.0,
        }

        # Derive what we can from observations
        if self._traffic_observations:
            obs = self._traffic_observations[-1]
            vector["scan_frequency"] = min(
                1.0, obs.get("signals_observed", 0) / 100.0
            )

        if self._origin_traces:
            trace = self._origin_traces[-1]
            cnc_count = len(trace.get("cnc_candidates", []))
            vector["lateral_movement"] = min(1.0, cnc_count / 5.0)

        return vector

    def _extract_tool_signatures(self) -> List[str]:
        """Extract tool signatures from collected evidence."""
        signatures: List[str] = []
        for obs in self._traffic_observations:
            if "tool_indicators" in obs:
                signatures.extend(obs["tool_indicators"])
        return list(set(signatures))

    def _estimate_sophistication(self) -> int:
        """
        Estimate attacker sophistication on a 1–5 scale based on
        collected evidence.
        """
        score = 1
        if self._origin_traces:
            trace = self._origin_traces[-1]
            hops = len(trace.get("path_hops", []))
            if hops > 3:
                score += 1
            if hops > 6:
                score += 1
            if trace.get("cnc_candidates"):
                score += 1
        if self._timing_correlations:
            score += 1
        return min(5, score)

    def _identify_entry_vectors(self) -> List[str]:
        """Identify attack entry vectors from trace data."""
        vectors: List[str] = []
        for trace in self._origin_traces:
            for ip in trace.get("origin_ips", []):
                vectors.append(f"network:{ip}")
        return vectors

    def _detect_fake_fibres(self) -> List[Dict[str, Any]]:
        """Detect any fake Fibres that were injected into the swarm."""
        fake_fibres: List[Dict[str, Any]] = []
        for obs in self._traffic_observations:
            if "fake_entities" in obs:
                fake_fibres.extend(obs["fake_entities"])
        return fake_fibres

    def _identify_targeted_data(self) -> List[str]:
        """Determine which data assets the attacker targeted."""
        targets: List[str] = []
        for obs in self._traffic_observations:
            if "data_access_targets" in obs:
                targets.extend(obs["data_access_targets"])
        return list(set(targets))

    def _identify_cnc_servers(self) -> List[str]:
        """Compile list of identified C&C server addresses."""
        servers: List[str] = []
        for trace in self._origin_traces:
            servers.extend(trace.get("cnc_candidates", []))
        return list(set(servers))

    # ------------------------------------------------------------------
    # External data ingestion
    # ------------------------------------------------------------------

    async def ingest_traffic(
        self,
        signals: List[Dict[str, Any]],
    ) -> None:
        """
        Feed captured traffic signals into the Penetrator during OBSERVE
        phase.  This is the primary hook for the Mirror Dimension to
        provide real data.

        Parameters
        ----------
        signals:
            List of signal dicts containing at minimum ``source``,
            ``destination``, ``payload_hash``, and ``timestamp`` keys.
        """
        if self.phase != PenetratorPhase.OBSERVE:
            logger.warning(
                "Penetrator %s: ingest_traffic called during %s phase "
                "(expected OBSERVE)",
                self.mission_id,
                self.phase.value,
            )
            return

        for signal in signals:
            src = signal.get("source", "unknown")
            dst = signal.get("destination", "unknown")

            # Update communication map
            if src not in self._communication_map:
                self._communication_map[src] = []
            if dst not in self._communication_map[src]:
                self._communication_map[src].append(dst)

        # Append a summarised observation
        observation = {
            "zone": self.containment_zone,
            "batch_time": datetime.utcnow().isoformat(),
            "signals_observed": len(signals),
            "unique_sources": list(
                {s.get("source", "unknown") for s in signals}
            ),
            "unique_destinations": list(
                {s.get("destination", "unknown") for s in signals}
            ),
            "communication_adjacency": dict(self._communication_map),
        }
        self._traffic_observations.append(observation)
        self.report.observations.append(observation)

        logger.debug(
            "Penetrator %s ingested %d signals in zone '%s'",
            self.mission_id,
            len(signals),
            self.containment_zone,
        )

    async def ingest_traces(
        self,
        traces: List[Dict[str, Any]],
    ) -> None:
        """
        Feed backward-trace results into the Penetrator during TRACE
        phase.

        Parameters
        ----------
        traces:
            List of trace dicts containing ``origin_ip``, ``path_hops``,
            ``latency_ms``, and optionally ``cnc_candidate`` keys.
        """
        if self.phase != PenetratorPhase.TRACE:
            logger.warning(
                "Penetrator %s: ingest_traces called during %s phase "
                "(expected TRACE)",
                self.mission_id,
                self.phase.value,
            )
            return

        for trace in traces:
            entry: Dict[str, Any] = {
                "traced_at": datetime.utcnow().isoformat(),
                "origin_ips": [trace.get("origin_ip", "unknown")],
                "path_hops": trace.get("path_hops", []),
                "timing_correlations": [],
                "cnc_candidates": [],
            }
            if trace.get("cnc_candidate"):
                entry["cnc_candidates"].append(trace["cnc_candidate"])
            if trace.get("latency_ms"):
                self._timing_correlations.append({
                    "origin": trace.get("origin_ip"),
                    "latency_ms": trace["latency_ms"],
                })
                entry["timing_correlations"] = self._timing_correlations[-1:]

            self._origin_traces.append(entry)
            self.report.origin_traces.append(entry)

        logger.debug(
            "Penetrator %s ingested %d trace results",
            self.mission_id,
            len(traces),
        )

    # ------------------------------------------------------------------
    # Introspection
    # ------------------------------------------------------------------

    @property
    def is_active(self) -> bool:
        """Whether the Penetrator is still operational."""
        return self._active

    @property
    def elapsed_seconds(self) -> float:
        """Seconds since mission start."""
        return (time.monotonic_ns() - self._start_ns) / 1_000_000_000

    @property
    def stats(self) -> Dict[str, Any]:
        """Diagnostic summary of mission state."""
        return {
            "mission_id": str(self.mission_id),
            "parent_fibre_id": str(self.parent_fibre_id),
            "containment_zone": self.containment_zone,
            "phase": self.phase.value,
            "active": self._active,
            "stealth_mode": self.stealth_mode,
            "observations_count": len(self._traffic_observations),
            "traces_count": len(self._origin_traces),
            "attacker_profile_id": (
                str(self._attacker_profile.profile_id)
                if self._attacker_profile
                else None
            ),
            "cnc_identified": self.report.cnc_server_identified,
            "elapsed_seconds": round(self.elapsed_seconds, 2),
        }

    def __repr__(self) -> str:
        return (
            f"<Penetrator mission={self.mission_id} "
            f"zone='{self.containment_zone}' "
            f"phase={self.phase.value} "
            f"stealth={self.stealth_mode}>"
        )
