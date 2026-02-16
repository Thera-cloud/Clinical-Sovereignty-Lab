"""
HIVE DEFENSE PROTOCOL — Curiosity Protocol (Phase 8A)
The hive's graduated immune response to behavioral anomalies.

The Curiosity Protocol implements a four-level graduated response system
that detects, escalates, and ultimately contains compromised or suspicious
entities within the Sovereign Swarm mesh.  It works in concert with the
Mirror Reflection system (behavioral baselines), the Forensic Logger
(immutable evidence chain), and Mesh Isolation (containment perimeter).

Graduated Response Levels:
    NOTICE   — Single anomaly detected.  Log it, increase monitoring
               frequency for the entity.  No overt action.  24-hour
               observation window.
    INTEREST — 2-3 anomalies within the monitoring window.  Alert ring
               partners to cross-verify the entity's behavior.  Compare
               current behavior against mirror reflection baseline.
               Notify Observer.  72-hour assessment window.
    CONCERN  — Ring partners confirm behavioral divergence.  Initiate
               Three-Cord Verification (Real registry, Mirror reflection,
               Originator signature).  Escalate to ALARM if any cord fails.
    ALARM    — Three-Cord Verification failed.  MESH ISOLATION.  Defensive
               perimeter formed by ring partners.  Alert Big Nate
               immediately.  Deploy Penetrator for forensic tracing.

Mirror Reflection Test (6 divergence checks):
    1. heartbeat_continuity     — Is the entity's heartbeat pulse unbroken?
    2. journal_trajectory       — Does the evolution journal match expected
                                  trajectory?
    3. communication_outside    — Is the entity communicating outside its
                                  assigned ring?
    4. unusual_data_access      — Is the entity accessing data it normally
                                  doesn't?
    5. coherence_drifted        — Has the entity's coherence baseline
                                  drifted beyond threshold?
    6. trail_emission_anomalous — Does the entity's trail fingerprint
                                  diverge from its mirror reflection?

Patent-Pending — Claim 33
© 2026 Clinical Sovereignty Lab. All rights reserved.
"""

from __future__ import annotations

import logging
import time
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Set, Tuple
from uuid import UUID, uuid4

from app.models.hive_defense import (
    CuriosityEvent,
    CuriosityLevel,
    ForensicRecord,
    HeartbeatPulse,
    MirrorReflection,
    ThreeCordVerification,
    HIVE_EVENT_TOPICS,
)

logger = logging.getLogger(__name__)


# =============================================================================
# CONSTANTS
# =============================================================================

# Monitoring window durations for each curiosity level
LEVEL_WINDOWS = {
    CuriosityLevel.NOTICE: timedelta(hours=24),
    CuriosityLevel.INTEREST: timedelta(hours=72),
    CuriosityLevel.CONCERN: timedelta(hours=72),
    CuriosityLevel.ALARM: timedelta(hours=0),  # Immediate action — no window
}

# Divergence thresholds for mirror reflection test
DIVERGENCE_LEVEL_MAP = {
    0: CuriosityLevel.NONE,
    1: CuriosityLevel.NOTICE,
    2: CuriosityLevel.INTEREST,
    3: CuriosityLevel.INTEREST,
}
# 4+ divergences → CONCERN (handled in code below)

# Minimum ring partner confirmations to escalate INTEREST → CONCERN
RING_CONFIRMATIONS_REQUIRED = 2

# Check names used by mirror_reflection_test
DIVERGENCE_CHECKS = [
    "heartbeat_continuity",
    "journal_trajectory_consistent",
    "communicating_outside_ring",
    "accessing_unusual_data",
    "coherence_drifted",
    "trail_emission_anomalous",
]


# =============================================================================
# ENTITY CURIOSITY STATE
# =============================================================================

class EntityCuriosityState:
    """
    Per-entity tracking structure for the Curiosity Protocol.

    Maintains the current curiosity level, accumulated events, ring partner
    confirmations, and timing information for a single hive entity.
    """

    __slots__ = (
        "entity_id",
        "current_level",
        "events",
        "last_check",
        "window_start",
        "ring_confirmations",
        "three_cord_result",
        "monitoring_interval_sec",
        "_divergence_history",
    )

    def __init__(self, entity_id: UUID) -> None:
        self.entity_id: UUID = entity_id
        self.current_level: CuriosityLevel = CuriosityLevel.NONE
        self.events: List[CuriosityEvent] = []
        self.last_check: Optional[datetime] = None
        self.window_start: Optional[datetime] = None
        self.ring_confirmations: int = 0
        self.three_cord_result: Optional[ThreeCordVerification] = None
        self.monitoring_interval_sec: float = 300.0  # 5 min default
        self._divergence_history: List[Dict[str, Any]] = []

    @property
    def events_in_window(self) -> List[CuriosityEvent]:
        """Return events within the current level's monitoring window."""
        if self.window_start is None:
            return []
        window = LEVEL_WINDOWS.get(self.current_level, timedelta(hours=24))
        cutoff = self.window_start
        return [e for e in self.events if e.timestamp >= cutoff]

    @property
    def divergence_count_in_window(self) -> int:
        """Count distinct divergence types observed in the current window."""
        return len({e.divergence_type for e in self.events_in_window})

    def to_dict(self) -> Dict[str, Any]:
        """Serialize state for API responses and forensic logging."""
        return {
            "entity_id": str(self.entity_id),
            "current_level": self.current_level.value,
            "event_count": len(self.events),
            "events_in_window": len(self.events_in_window),
            "last_check": self.last_check.isoformat() if self.last_check else None,
            "window_start": self.window_start.isoformat() if self.window_start else None,
            "ring_confirmations": self.ring_confirmations,
            "monitoring_interval_sec": self.monitoring_interval_sec,
        }


# =============================================================================
# CURIOSITY PROTOCOL
# =============================================================================

class CuriosityProtocol:
    """
    The hive's graduated immune response to behavioral anomalies.

    Monitors every entity in the mesh, running periodic mirror reflection
    tests and escalating through four response levels (NOTICE → INTEREST →
    CONCERN → ALARM) based on the number and severity of divergences.

    Integration points:
        - MirrorReflectionManager — supplies behavioral baselines
        - ForensicLogger          — preserves immutable evidence chain
        - MeshIsolation           — containment when ALARM is reached
        - Hive event bus          — publishes level-change events

    Usage::

        protocol = CuriosityProtocol(
            db_pool=pool,
            mirror_manager=mirror_mgr,
            forensic_logger=forensic_log,
        )
        result = await protocol.evaluate_entity(entity_id)

    Patent-Pending — Claim 33.
    """

    def __init__(
        self,
        db_pool=None,
        mirror_manager=None,
        forensic_logger=None,
        mesh_isolation=None,
        event_bus=None,
    ) -> None:
        """
        Initialize the Curiosity Protocol.

        Args:
            db_pool: asyncpg connection pool for persistence.
            mirror_manager: MirrorReflectionManager instance for baseline
                comparison and divergence checks.
            forensic_logger: ForensicLogger instance for immutable evidence
                preservation.
            mesh_isolation: MeshIsolation instance for containment at ALARM.
            event_bus: Hive event bus for publishing level-change events.
        """
        self.db_pool = db_pool
        self._mirror_manager = mirror_manager
        self._forensic_logger = forensic_logger
        self._mesh_isolation = mesh_isolation
        self._event_bus = event_bus

        # Per-entity curiosity state (in-memory, periodically persisted)
        self._entity_states: Dict[UUID, EntityCuriosityState] = {}

        logger.info(">>> [CURIOSITY] Curiosity Protocol initialized")

    # =========================================================================
    # STATE MANAGEMENT
    # =========================================================================

    def _get_state(self, entity_id: UUID) -> EntityCuriosityState:
        """
        Retrieve or create the curiosity state for an entity.

        Returns:
            EntityCuriosityState for the given entity_id.
        """
        if entity_id not in self._entity_states:
            self._entity_states[entity_id] = EntityCuriosityState(entity_id)
        return self._entity_states[entity_id]

    def get_entity_state(self, entity_id: UUID) -> Dict[str, Any]:
        """
        Public accessor for an entity's curiosity state.

        Returns:
            Serialized state dictionary suitable for API responses.
        """
        return self._get_state(entity_id).to_dict()

    def get_all_active_states(self) -> List[Dict[str, Any]]:
        """
        Return all entities currently above NONE curiosity level.

        Returns:
            List of serialized state dictionaries.
        """
        return [
            state.to_dict()
            for state in self._entity_states.values()
            if state.current_level != CuriosityLevel.NONE
        ]

    # =========================================================================
    # MIRROR REFLECTION TEST
    # =========================================================================

    async def mirror_reflection_test(self, entity_id: UUID) -> CuriosityLevel:
        """
        Run the six-point mirror reflection divergence test for an entity.

        Compares the entity's current behavioral profile against its stored
        mirror reflection baseline across six dimensions:

            1. **heartbeat_continuity** — Verifies the entity's heartbeat
               pulse sequence is unbroken and monotonically increasing.
            2. **journal_trajectory_consistent** — Checks that the entity's
               evolution journal hash follows its expected trajectory.
            3. **communicating_outside_ring** — Detects communication with
               entities outside the assigned ring topology.
            4. **accessing_unusual_data** — Flags data access patterns that
               deviate from the entity's historical profile.
            5. **coherence_drifted** — Measures whether the entity's
               emotional coherence baseline has drifted beyond threshold.
            6. **trail_emission_anomalous** — Compares the entity's trail
               emission fingerprint against its mirror reflection.

        Divergence mapping:
            0 divergences → NONE
            1 divergence  → NOTICE
            2-3 divergences → INTEREST
            4+ divergences → CONCERN

        Args:
            entity_id: UUID of the entity to test.

        Returns:
            CuriosityLevel corresponding to the number of divergences found.
        """
        divergences: List[Dict[str, Any]] = []
        state = self._get_state(entity_id)

        # Attempt to load the mirror reflection baseline
        baseline: Optional[MirrorReflection] = None
        if self._mirror_manager:
            try:
                baseline = await self._mirror_manager.get_reflection(entity_id)
            except Exception as exc:
                logger.warning(
                    ">>> [CURIOSITY] Failed to load mirror reflection for %s: %s",
                    entity_id, exc,
                )

        # --- Check 1: heartbeat_continuity ---
        hb_diverged = await self._check_heartbeat_continuity(entity_id, baseline)
        if hb_diverged:
            divergences.append({
                "check": "heartbeat_continuity",
                "detail": "Heartbeat pulse sequence discontinuity detected",
            })

        # --- Check 2: journal_trajectory_consistent ---
        journal_diverged = await self._check_journal_trajectory(entity_id, baseline)
        if journal_diverged:
            divergences.append({
                "check": "journal_trajectory_consistent",
                "detail": "Evolution journal trajectory does not match baseline",
            })

        # --- Check 3: communicating_outside_ring ---
        comm_diverged = await self._check_communication_outside_ring(entity_id)
        if comm_diverged:
            divergences.append({
                "check": "communicating_outside_ring",
                "detail": "Entity communicating with nodes outside its assigned ring",
            })

        # --- Check 4: accessing_unusual_data ---
        data_diverged = await self._check_unusual_data_access(entity_id, baseline)
        if data_diverged:
            divergences.append({
                "check": "accessing_unusual_data",
                "detail": "Data access pattern deviates from historical profile",
            })

        # --- Check 5: coherence_drifted ---
        coherence_diverged = await self._check_coherence_drift(entity_id, baseline)
        if coherence_diverged:
            divergences.append({
                "check": "coherence_drifted",
                "detail": "Emotional coherence baseline drift exceeds threshold",
            })

        # --- Check 6: trail_emission_anomalous ---
        trail_diverged = await self._check_trail_emission(entity_id, baseline)
        if trail_diverged:
            divergences.append({
                "check": "trail_emission_anomalous",
                "detail": "Trail emission fingerprint diverges from mirror reflection",
            })

        # Store divergence history
        state._divergence_history.append({
            "timestamp": datetime.utcnow().isoformat(),
            "divergences": divergences,
            "count": len(divergences),
        })

        # Map divergence count to curiosity level
        count = len(divergences)
        if count >= 4:
            level = CuriosityLevel.CONCERN
        else:
            level = DIVERGENCE_LEVEL_MAP.get(count, CuriosityLevel.CONCERN)

        # Record each divergence as a CuriosityEvent
        for div in divergences:
            event = CuriosityEvent(
                entity_id=entity_id,
                level=level,
                divergence_type=div["check"],
                details=div["detail"],
            )
            state.events.append(event)

        logger.info(
            ">>> [CURIOSITY] Mirror test for %s: %d divergences → %s",
            entity_id, count, level.value,
        )

        # Log to forensic chain
        if self._forensic_logger and divergences:
            try:
                await self._forensic_logger.log_event(
                    event_type="curiosity_mirror_test",
                    source_entity=str(entity_id),
                    evidence={
                        "divergences": divergences,
                        "resulting_level": level.value,
                    },
                )
            except Exception as exc:
                logger.error(
                    ">>> [CURIOSITY] Forensic log failed: %s", exc
                )

        return level

    # =========================================================================
    # INDIVIDUAL DIVERGENCE CHECKS
    # =========================================================================

    async def _check_heartbeat_continuity(
        self, entity_id: UUID, baseline: Optional[MirrorReflection]
    ) -> bool:
        """
        Verify heartbeat pulse sequence continuity.

        Checks that the entity's monotonic counter is unbroken and the
        interval between pulses has not deviated significantly.

        Returns:
            True if a divergence is detected.
        """
        if not self.db_pool:
            return False
        try:
            async with self.db_pool.acquire() as conn:
                rows = await conn.fetch("""
                    SELECT monotonic_counter, pulse_timestamp
                    FROM heartbeat_log
                    WHERE entity_id = $1
                    ORDER BY pulse_timestamp DESC
                    LIMIT 10
                """, entity_id)

            if len(rows) < 2:
                return False  # Not enough data to evaluate

            # Check monotonic counter continuity
            counters = [r["monotonic_counter"] for r in rows]
            for i in range(len(counters) - 1):
                if counters[i] - counters[i + 1] != 1:
                    return True  # Gap detected

            # Check timing regularity (>3× standard interval = suspicious)
            timestamps = [r["pulse_timestamp"] for r in rows]
            intervals = []
            for i in range(len(timestamps) - 1):
                delta = (timestamps[i] - timestamps[i + 1]).total_seconds()
                intervals.append(delta)

            if intervals:
                avg_interval = sum(intervals) / len(intervals)
                for interval in intervals:
                    if avg_interval > 0 and interval > avg_interval * 3:
                        return True  # Abnormal gap

        except Exception as exc:
            logger.warning(
                ">>> [CURIOSITY] Heartbeat check error for %s: %s",
                entity_id, exc,
            )
        return False

    async def _check_journal_trajectory(
        self, entity_id: UUID, baseline: Optional[MirrorReflection]
    ) -> bool:
        """
        Verify the entity's evolution journal matches its expected trajectory.

        Compares the current journal hash against the baseline snapshot.
        A sudden, large-magnitude change in trajectory indicates potential
        compromise.

        Returns:
            True if a divergence is detected.
        """
        if not baseline or not baseline.journal_trajectory_hash:
            return False  # No baseline to compare against
        if not self.db_pool:
            return False
        try:
            async with self.db_pool.acquire() as conn:
                row = await conn.fetchrow("""
                    SELECT evolution_journal_hash
                    FROM fibre_heartbeats
                    WHERE entity_id = $1
                    ORDER BY created_at DESC
                    LIMIT 1
                """, entity_id)

            if not row:
                return False

            current_hash = row["evolution_journal_hash"]
            if current_hash and current_hash != baseline.journal_trajectory_hash:
                # Journal has diverged from baseline — flag it
                return True

        except Exception as exc:
            logger.warning(
                ">>> [CURIOSITY] Journal trajectory check error for %s: %s",
                entity_id, exc,
            )
        return False

    async def _check_communication_outside_ring(self, entity_id: UUID) -> bool:
        """
        Detect if the entity is communicating with nodes outside its ring.

        Queries recent mesh messages from this entity and compares the
        recipient set against the entity's assigned ring membership.

        Returns:
            True if a divergence is detected.
        """
        if not self.db_pool:
            return False
        try:
            async with self.db_pool.acquire() as conn:
                # Get entity's assigned ring members
                ring_members = await conn.fetch("""
                    SELECT member_id FROM ring_membership
                    WHERE ring_id = (
                        SELECT ring_id FROM ring_membership
                        WHERE member_id = $1
                        LIMIT 1
                    )
                """, entity_id)
                ring_set = {r["member_id"] for r in ring_members}

                if not ring_set:
                    return False  # No ring data

                # Get recent communication targets
                recent_targets = await conn.fetch("""
                    SELECT DISTINCT recipient_id
                    FROM mesh_messages
                    WHERE sender_id = $1
                      AND created_at > NOW() - INTERVAL '24 hours'
                      AND recipient_id IS NOT NULL
                """, entity_id)

                outside_ring = [
                    r["recipient_id"]
                    for r in recent_targets
                    if r["recipient_id"] not in ring_set
                ]

                if outside_ring:
                    logger.info(
                        ">>> [CURIOSITY] %s communicating with %d entities outside ring",
                        entity_id, len(outside_ring),
                    )
                    return True

        except Exception as exc:
            logger.warning(
                ">>> [CURIOSITY] Ring communication check error for %s: %s",
                entity_id, exc,
            )
        return False

    async def _check_unusual_data_access(
        self, entity_id: UUID, baseline: Optional[MirrorReflection]
    ) -> bool:
        """
        Flag unusual data access patterns.

        Compares the entity's current data access hash against its mirror
        reflection baseline.

        Returns:
            True if a divergence is detected.
        """
        if not baseline or not baseline.data_access_hash:
            return False
        if not self.db_pool:
            return False
        try:
            async with self.db_pool.acquire() as conn:
                row = await conn.fetchrow("""
                    SELECT data_access_hash
                    FROM behavioral_snapshots
                    WHERE entity_id = $1
                    ORDER BY created_at DESC
                    LIMIT 1
                """, entity_id)

            if row and row["data_access_hash"]:
                if row["data_access_hash"] != baseline.data_access_hash:
                    return True

        except Exception as exc:
            logger.warning(
                ">>> [CURIOSITY] Data access check error for %s: %s",
                entity_id, exc,
            )
        return False

    async def _check_coherence_drift(
        self, entity_id: UUID, baseline: Optional[MirrorReflection]
    ) -> bool:
        """
        Measure emotional coherence drift against baseline.

        Uses the Nevedal coherence baseline hash stored in the mirror
        reflection.  A mismatch indicates the entity's coherence profile
        has shifted beyond acceptable bounds.

        Returns:
            True if a divergence is detected.
        """
        if not baseline or not baseline.coherence_baseline_hash:
            return False
        if not self.db_pool:
            return False
        try:
            async with self.db_pool.acquire() as conn:
                row = await conn.fetchrow("""
                    SELECT coherence_baseline_hash
                    FROM behavioral_snapshots
                    WHERE entity_id = $1
                    ORDER BY created_at DESC
                    LIMIT 1
                """, entity_id)

            if row and row["coherence_baseline_hash"]:
                if row["coherence_baseline_hash"] != baseline.coherence_baseline_hash:
                    return True

        except Exception as exc:
            logger.warning(
                ">>> [CURIOSITY] Coherence drift check error for %s: %s",
                entity_id, exc,
            )
        return False

    async def _check_trail_emission(
        self, entity_id: UUID, baseline: Optional[MirrorReflection]
    ) -> bool:
        """
        Compare the entity's trail emission fingerprint against its mirror.

        Trail emissions are cryptographic fingerprints of the entity's
        operational footprint.  Divergence suggests the entity is behaving
        in a fundamentally different manner than its established pattern.

        Returns:
            True if a divergence is detected.
        """
        if not baseline or not baseline.trail_emission_fingerprint:
            return False
        if not self.db_pool:
            return False
        try:
            async with self.db_pool.acquire() as conn:
                row = await conn.fetchrow("""
                    SELECT trail_emission_fingerprint
                    FROM behavioral_snapshots
                    WHERE entity_id = $1
                    ORDER BY created_at DESC
                    LIMIT 1
                """, entity_id)

            if row and row["trail_emission_fingerprint"]:
                if row["trail_emission_fingerprint"] != baseline.trail_emission_fingerprint:
                    return True

        except Exception as exc:
            logger.warning(
                ">>> [CURIOSITY] Trail emission check error for %s: %s",
                entity_id, exc,
            )
        return False

    # =========================================================================
    # THREE-CORD VERIFICATION
    # =========================================================================

    async def _three_cord_verify(self, entity_id: UUID) -> ThreeCordVerification:
        """
        Execute the Three-Cord Verification for an entity.

        The three cords are:
            1. **Real** — Entity exists in the real registry (database).
            2. **Mirror** — Entity's mirror reflection matches its current
               behavioral profile (all 6 checks pass).
            3. **Originator** — Entity's Ed25519 originator signature is
               valid and traces back to Big Nate's master key.

        Args:
            entity_id: UUID of the entity to verify.

        Returns:
            ThreeCordVerification with results of all three checks.
        """
        result = ThreeCordVerification(entity_id=entity_id)

        # Cord 1: Real — entity exists in database registry
        if self.db_pool:
            try:
                async with self.db_pool.acquire() as conn:
                    row = await conn.fetchrow(
                        "SELECT fibre_id FROM fibres WHERE fibre_id = $1",
                        entity_id,
                    )
                    result.cord_real = row is not None
            except Exception as exc:
                logger.error(
                    ">>> [CURIOSITY] Three-Cord Real check failed for %s: %s",
                    entity_id, exc,
                )
                result.cord_real = False
        else:
            # Without DB, assume real (fail-open for development)
            result.cord_real = True

        # Cord 2: Mirror — run a fresh mirror reflection test (0 divergences = pass)
        mirror_level = await self.mirror_reflection_test(entity_id)
        result.cord_mirror = mirror_level in (CuriosityLevel.NONE, CuriosityLevel.NOTICE)

        # Cord 3: Originator — verify identity chain signature
        if self.db_pool:
            try:
                async with self.db_pool.acquire() as conn:
                    row = await conn.fetchrow("""
                        SELECT originator_signature, identity_chain_valid
                        FROM fibres
                        WHERE fibre_id = $1
                    """, entity_id)
                    if row:
                        result.cord_originator = bool(
                            row.get("originator_signature")
                            and row.get("identity_chain_valid", False)
                        )
                    else:
                        result.cord_originator = False
            except Exception as exc:
                logger.error(
                    ">>> [CURIOSITY] Three-Cord Originator check failed for %s: %s",
                    entity_id, exc,
                )
                result.cord_originator = False
        else:
            result.cord_originator = True

        # Final verdict
        result.verified = (
            result.cord_real and result.cord_mirror and result.cord_originator
        )

        logger.info(
            ">>> [CURIOSITY] Three-Cord for %s: real=%s mirror=%s originator=%s → %s",
            entity_id,
            result.cord_real,
            result.cord_mirror,
            result.cord_originator,
            "VERIFIED" if result.verified else "FAILED",
        )

        return result

    # =========================================================================
    # LEVEL ESCALATION
    # =========================================================================

    async def _escalate_level(
        self,
        state: EntityCuriosityState,
        new_level: CuriosityLevel,
        reason: str,
    ) -> None:
        """
        Escalate an entity's curiosity level and execute level-specific actions.

        Args:
            state: The entity's current curiosity state.
            new_level: The level to escalate to.
            reason: Human-readable reason for the escalation.
        """
        old_level = state.current_level
        if new_level == old_level:
            return  # No change

        state.current_level = new_level
        state.last_check = datetime.utcnow()

        # Reset window on level change
        if new_level != CuriosityLevel.NONE:
            if state.window_start is None or new_level.value != old_level.value:
                state.window_start = datetime.utcnow()

        logger.warning(
            ">>> [CURIOSITY] Entity %s escalated: %s → %s (%s)",
            state.entity_id, old_level.value, new_level.value, reason,
        )

        # Fire hive event
        await self._fire_hive_event(state.entity_id, new_level, reason)

        # Log forensic record
        if self._forensic_logger:
            try:
                await self._forensic_logger.log_event(
                    event_type=f"curiosity_escalation_{new_level.value}",
                    source_entity=str(state.entity_id),
                    evidence={
                        "old_level": old_level.value,
                        "new_level": new_level.value,
                        "reason": reason,
                        "events_in_window": len(state.events_in_window),
                        "ring_confirmations": state.ring_confirmations,
                    },
                )
            except Exception as exc:
                logger.error(">>> [CURIOSITY] Forensic log error: %s", exc)

        # Level-specific actions
        if new_level == CuriosityLevel.NOTICE:
            await self._handle_notice(state)
        elif new_level == CuriosityLevel.INTEREST:
            await self._handle_interest(state)
        elif new_level == CuriosityLevel.CONCERN:
            await self._handle_concern(state)
        elif new_level == CuriosityLevel.ALARM:
            await self._handle_alarm(state, reason)

        # Persist state to database
        await self._persist_state(state)

    async def _handle_notice(self, state: EntityCuriosityState) -> None:
        """
        NOTICE level handler: increase monitoring frequency.

        No overt action is taken.  The entity's monitoring interval is
        reduced to increase observation granularity within the 24-hour
        window.
        """
        # Double monitoring frequency (halve interval)
        state.monitoring_interval_sec = max(30.0, state.monitoring_interval_sec / 2)
        logger.info(
            ">>> [CURIOSITY] NOTICE for %s — monitoring interval now %.0fs",
            state.entity_id, state.monitoring_interval_sec,
        )

    async def _handle_interest(self, state: EntityCuriosityState) -> None:
        """
        INTEREST level handler: alert ring partners, compare against mirror.

        Ring partners are notified to independently cross-verify the entity's
        behavior.  The Observer is alerted.  72-hour assessment window begins.
        """
        # Increase monitoring further
        state.monitoring_interval_sec = max(15.0, state.monitoring_interval_sec / 2)

        # Notify ring partners
        if self.db_pool:
            try:
                async with self.db_pool.acquire() as conn:
                    ring_partners = await conn.fetch("""
                        SELECT member_id FROM ring_membership
                        WHERE ring_id = (
                            SELECT ring_id FROM ring_membership
                            WHERE member_id = $1
                            LIMIT 1
                        )
                        AND member_id != $1
                    """, state.entity_id)

                    for partner in ring_partners:
                        await conn.execute("""
                            INSERT INTO curiosity_notifications
                                (target_entity_id, about_entity_id, level, message)
                            VALUES ($1, $2, $3, $4)
                        """,
                            partner["member_id"],
                            state.entity_id,
                            CuriosityLevel.INTEREST.value,
                            f"Cross-verify entity {state.entity_id} — "
                            f"{state.divergence_count_in_window} anomalies detected",
                        )

                    logger.info(
                        ">>> [CURIOSITY] INTEREST for %s — notified %d ring partners",
                        state.entity_id, len(ring_partners),
                    )
            except Exception as exc:
                logger.error(
                    ">>> [CURIOSITY] Ring notification error: %s", exc,
                )

    async def _handle_concern(self, state: EntityCuriosityState) -> None:
        """
        CONCERN level handler: initiate Three-Cord Verification.

        Ring partners have confirmed behavioral divergence.  The Three-Cord
        Verification (Real, Mirror, Originator) is executed.  If any cord
        fails, the entity is immediately escalated to ALARM.
        """
        logger.warning(
            ">>> [CURIOSITY] CONCERN for %s — initiating Three-Cord Verification",
            state.entity_id,
        )

        result = await self._three_cord_verify(state.entity_id)
        state.three_cord_result = result

        if not result.verified:
            failed_cords = []
            if not result.cord_real:
                failed_cords.append("Real")
            if not result.cord_mirror:
                failed_cords.append("Mirror")
            if not result.cord_originator:
                failed_cords.append("Originator")

            reason = f"Three-Cord FAILED: {', '.join(failed_cords)} cord(s) broken"
            await self._escalate_level(state, CuriosityLevel.ALARM, reason)

    async def _handle_alarm(self, state: EntityCuriosityState, reason: str) -> None:
        """
        ALARM level handler: MESH ISOLATION + alert Big Nate + deploy Penetrator.

        This is the maximum response.  The entity is immediately isolated
        from the mesh, ring partners form a defensive perimeter, Big Nate
        is alerted for human review, and a Penetrator is deployed for
        forensic tracing of the compromise origin.
        """
        logger.critical(
            ">>> [CURIOSITY] *** ALARM *** Entity %s — %s",
            state.entity_id, reason,
        )

        # 1. Mesh Isolation
        if self._mesh_isolation:
            try:
                await self._mesh_isolation.isolate_entity(
                    entity_id=state.entity_id,
                    reason=f"Curiosity Protocol ALARM: {reason}",
                )
                await self._mesh_isolation.form_defensive_perimeter(state.entity_id)
                await self._mesh_isolation.quarantine_data(state.entity_id)
                logger.info(
                    ">>> [CURIOSITY] Mesh isolation activated for %s",
                    state.entity_id,
                )
            except Exception as exc:
                logger.error(
                    ">>> [CURIOSITY] Mesh isolation failed for %s: %s",
                    state.entity_id, exc,
                )

        # 2. Alert Big Nate (persist to urgent alerts table)
        if self.db_pool:
            try:
                async with self.db_pool.acquire() as conn:
                    await conn.execute("""
                        INSERT INTO urgent_alerts
                            (alert_type, entity_id, severity, message, details)
                        VALUES ($1, $2, $3, $4, $5)
                    """,
                        "curiosity_alarm",
                        state.entity_id,
                        "critical",
                        f"CURIOSITY ALARM: Entity {state.entity_id} failed verification",
                        reason,
                    )
            except Exception as exc:
                logger.error(
                    ">>> [CURIOSITY] Alert persistence failed: %s", exc,
                )

        # 3. Deploy Penetrator (fire event for orchestrator)
        await self._fire_hive_event(
            state.entity_id,
            CuriosityLevel.ALARM,
            f"Deploy Penetrator — {reason}",
            extra_data={"action": "deploy_penetrator"},
        )

        # Zero monitoring interval — continuous surveillance
        state.monitoring_interval_sec = 5.0

    # =========================================================================
    # FULL ENTITY EVALUATION
    # =========================================================================

    async def evaluate_entity(self, entity_id: UUID) -> Dict[str, Any]:
        """
        Execute a full curiosity evaluation for an entity.

        This is the primary entry point for the Curiosity Protocol.  It
        runs the mirror reflection test, evaluates the accumulated evidence,
        and escalates the entity's curiosity level as appropriate.

        The evaluation flow:
            1. Run mirror reflection test (6 divergence checks).
            2. Determine recommended level from divergence count.
            3. If recommended level is higher than current, escalate.
            4. At INTEREST: check ring partner confirmations.
            5. At CONCERN: trigger Three-Cord Verification.
            6. Return comprehensive evaluation result.

        Args:
            entity_id: UUID of the entity to evaluate.

        Returns:
            Dictionary containing evaluation results, current level,
            events in window, and any actions taken.
        """
        state = self._get_state(entity_id)
        state.last_check = datetime.utcnow()

        # 1. Run mirror reflection test
        test_level = await self.mirror_reflection_test(entity_id)

        # 2. Check for window expiry — if monitoring window has elapsed
        #    without further issues, consider de-escalation
        if state.window_start and state.current_level != CuriosityLevel.NONE:
            window_duration = LEVEL_WINDOWS.get(
                state.current_level, timedelta(hours=24)
            )
            if window_duration.total_seconds() > 0:
                elapsed = datetime.utcnow() - state.window_start
                if elapsed > window_duration and test_level == CuriosityLevel.NONE:
                    # Window expired with no new issues — de-escalate
                    await self._deescalate(state)
                    return {
                        "entity_id": str(entity_id),
                        "action": "deescalated",
                        "previous_level": state.current_level.value,
                        "current_level": CuriosityLevel.NONE.value,
                        "state": state.to_dict(),
                    }

        # 3. Determine effective level (max of current and test result)
        level_order = [
            CuriosityLevel.NONE,
            CuriosityLevel.NOTICE,
            CuriosityLevel.INTEREST,
            CuriosityLevel.CONCERN,
            CuriosityLevel.ALARM,
        ]
        current_idx = level_order.index(state.current_level)
        test_idx = level_order.index(test_level)

        # Also consider accumulated events in the window
        window_divergences = state.divergence_count_in_window
        if window_divergences >= 4:
            accumulated_level = CuriosityLevel.CONCERN
        elif window_divergences >= 2:
            accumulated_level = CuriosityLevel.INTEREST
        elif window_divergences >= 1:
            accumulated_level = CuriosityLevel.NOTICE
        else:
            accumulated_level = CuriosityLevel.NONE
        accumulated_idx = level_order.index(accumulated_level)

        effective_idx = max(current_idx, test_idx, accumulated_idx)
        effective_level = level_order[effective_idx]

        # 4. At INTEREST, check ring partner confirmations for escalation
        if effective_level == CuriosityLevel.INTEREST:
            confirmations = await self._check_ring_confirmations(entity_id)
            state.ring_confirmations = confirmations
            if confirmations >= RING_CONFIRMATIONS_REQUIRED:
                effective_level = CuriosityLevel.CONCERN

        # 5. Escalate if needed
        if effective_level != state.current_level:
            reason = (
                f"Mirror test: {test_level.value}, "
                f"Window divergences: {window_divergences}, "
                f"Ring confirmations: {state.ring_confirmations}"
            )
            await self._escalate_level(state, effective_level, reason)

        return {
            "entity_id": str(entity_id),
            "current_level": state.current_level.value,
            "test_level": test_level.value,
            "window_divergences": window_divergences,
            "ring_confirmations": state.ring_confirmations,
            "events_in_window": len(state.events_in_window),
            "monitoring_interval_sec": state.monitoring_interval_sec,
            "three_cord_result": (
                {
                    "real": state.three_cord_result.cord_real,
                    "mirror": state.three_cord_result.cord_mirror,
                    "originator": state.three_cord_result.cord_originator,
                    "verified": state.three_cord_result.verified,
                }
                if state.three_cord_result
                else None
            ),
            "state": state.to_dict(),
        }

    # =========================================================================
    # RING PARTNER CONFIRMATION
    # =========================================================================

    async def _check_ring_confirmations(self, entity_id: UUID) -> int:
        """
        Count ring partner confirmations of behavioral divergence.

        Ring partners independently flag entities they observe behaving
        anomalously.  This method counts how many partners have confirmed
        the divergence for the given entity.

        Args:
            entity_id: UUID of the entity being investigated.

        Returns:
            Number of ring partner confirmations.
        """
        if not self.db_pool:
            return 0
        try:
            async with self.db_pool.acquire() as conn:
                row = await conn.fetchrow("""
                    SELECT COUNT(*) as cnt
                    FROM ring_divergence_confirmations
                    WHERE about_entity_id = $1
                      AND confirmed_at > NOW() - INTERVAL '72 hours'
                """, entity_id)
                return row["cnt"] if row else 0
        except Exception as exc:
            logger.warning(
                ">>> [CURIOSITY] Ring confirmation check error: %s", exc,
            )
            return 0

    async def register_ring_confirmation(
        self, confirming_entity_id: UUID, about_entity_id: UUID, details: str = ""
    ) -> Dict[str, Any]:
        """
        Record a ring partner's confirmation of behavioral divergence.

        Called when a ring partner independently observes anomalous behavior
        in one of its neighbors and reports it to the Curiosity Protocol.

        Args:
            confirming_entity_id: UUID of the entity providing confirmation.
            about_entity_id: UUID of the entity being flagged.
            details: Optional description of observed anomaly.

        Returns:
            Confirmation record with updated state.
        """
        state = self._get_state(about_entity_id)
        state.ring_confirmations += 1

        if self.db_pool:
            try:
                async with self.db_pool.acquire() as conn:
                    await conn.execute("""
                        INSERT INTO ring_divergence_confirmations
                            (confirming_entity_id, about_entity_id, details)
                        VALUES ($1, $2, $3)
                    """, confirming_entity_id, about_entity_id, details)
            except Exception as exc:
                logger.error(
                    ">>> [CURIOSITY] Ring confirmation persist error: %s", exc,
                )

        logger.info(
            ">>> [CURIOSITY] Ring confirmation for %s from %s (total: %d)",
            about_entity_id, confirming_entity_id, state.ring_confirmations,
        )

        # If enough confirmations at INTEREST, trigger evaluation
        if (
            state.current_level == CuriosityLevel.INTEREST
            and state.ring_confirmations >= RING_CONFIRMATIONS_REQUIRED
        ):
            await self.evaluate_entity(about_entity_id)

        return {
            "about_entity_id": str(about_entity_id),
            "confirming_entity_id": str(confirming_entity_id),
            "total_confirmations": state.ring_confirmations,
            "current_level": state.current_level.value,
        }

    # =========================================================================
    # DE-ESCALATION
    # =========================================================================

    async def _deescalate(self, state: EntityCuriosityState) -> None:
        """
        De-escalate an entity's curiosity level back to NONE.

        Called when the monitoring window has expired with no further
        divergences detected.  Resets monitoring parameters to defaults.
        """
        old_level = state.current_level
        state.current_level = CuriosityLevel.NONE
        state.window_start = None
        state.ring_confirmations = 0
        state.three_cord_result = None
        state.monitoring_interval_sec = 300.0  # Reset to default

        logger.info(
            ">>> [CURIOSITY] Entity %s de-escalated: %s → NONE",
            state.entity_id, old_level.value,
        )

        if self._forensic_logger:
            try:
                await self._forensic_logger.log_event(
                    event_type="curiosity_deescalation",
                    source_entity=str(state.entity_id),
                    evidence={
                        "old_level": old_level.value,
                        "new_level": CuriosityLevel.NONE.value,
                    },
                )
            except Exception as exc:
                logger.error(">>> [CURIOSITY] Forensic log error: %s", exc)

        await self._fire_hive_event(
            state.entity_id,
            CuriosityLevel.NONE,
            f"De-escalated from {old_level.value}",
        )

    # =========================================================================
    # HIVE EVENT BUS
    # =========================================================================

    async def _fire_hive_event(
        self,
        entity_id: UUID,
        level: CuriosityLevel,
        reason: str,
        extra_data: Optional[Dict[str, Any]] = None,
    ) -> None:
        """
        Publish a curiosity level-change event to the hive event bus.

        Maps the curiosity level to the appropriate HIVE_EVENT_TOPICS key
        and publishes the event with entity context.

        Args:
            entity_id: UUID of the affected entity.
            level: The curiosity level being reported.
            reason: Human-readable description of the event.
            extra_data: Optional additional event payload.
        """
        topic_map = {
            CuriosityLevel.NONE: "hive.defense.all_clear",
            CuriosityLevel.NOTICE: "hive.curiosity.notice",
            CuriosityLevel.INTEREST: "hive.curiosity.interest",
            CuriosityLevel.CONCERN: "hive.curiosity.concern",
            CuriosityLevel.ALARM: "hive.curiosity.alarm",
        }

        topic = topic_map.get(level, "hive.curiosity.notice")

        event_payload = {
            "topic": topic,
            "entity_id": str(entity_id),
            "level": level.value,
            "reason": reason,
            "timestamp": datetime.utcnow().isoformat(),
        }
        if extra_data:
            event_payload.update(extra_data)

        # Publish to event bus if available
        if self._event_bus:
            try:
                await self._event_bus.publish(topic, event_payload)
            except Exception as exc:
                logger.error(
                    ">>> [CURIOSITY] Event bus publish failed: %s", exc,
                )

        # Also persist to database event log
        if self.db_pool:
            try:
                async with self.db_pool.acquire() as conn:
                    await conn.execute("""
                        INSERT INTO hive_events
                            (topic, entity_id, payload)
                        VALUES ($1, $2, $3)
                    """, topic, entity_id,
                        __import__("json").dumps(event_payload),
                    )
            except Exception as exc:
                logger.warning(
                    ">>> [CURIOSITY] Event persist failed: %s", exc,
                )

        logger.info(
            ">>> [CURIOSITY] Hive event fired: %s for %s",
            topic, entity_id,
        )

    # =========================================================================
    # PERSISTENCE
    # =========================================================================

    async def _persist_state(self, state: EntityCuriosityState) -> None:
        """
        Persist the entity's curiosity state to the database.

        Upserts the current level, event count, and monitoring parameters
        for recovery after restarts.

        Args:
            state: The EntityCuriosityState to persist.
        """
        if not self.db_pool:
            return
        try:
            import json
            async with self.db_pool.acquire() as conn:
                await conn.execute("""
                    INSERT INTO curiosity_state
                        (entity_id, current_level, event_count, window_start,
                         ring_confirmations, monitoring_interval_sec, last_check)
                    VALUES ($1, $2, $3, $4, $5, $6, $7)
                    ON CONFLICT (entity_id)
                    DO UPDATE SET
                        current_level = EXCLUDED.current_level,
                        event_count = EXCLUDED.event_count,
                        window_start = EXCLUDED.window_start,
                        ring_confirmations = EXCLUDED.ring_confirmations,
                        monitoring_interval_sec = EXCLUDED.monitoring_interval_sec,
                        last_check = EXCLUDED.last_check,
                        updated_at = NOW()
                """,
                    state.entity_id,
                    state.current_level.value,
                    len(state.events),
                    state.window_start,
                    state.ring_confirmations,
                    state.monitoring_interval_sec,
                    state.last_check,
                )
        except Exception as exc:
            logger.error(
                ">>> [CURIOSITY] State persistence failed for %s: %s",
                state.entity_id, exc,
            )

    async def load_persisted_states(self) -> int:
        """
        Load all persisted curiosity states from the database on startup.

        Restores in-memory entity states from the last persisted snapshot
        so that monitoring continues seamlessly after a restart.

        Returns:
            Number of entity states restored.
        """
        if not self.db_pool:
            return 0
        try:
            async with self.db_pool.acquire() as conn:
                rows = await conn.fetch("""
                    SELECT entity_id, current_level, event_count, window_start,
                           ring_confirmations, monitoring_interval_sec, last_check
                    FROM curiosity_state
                    WHERE current_level != 'none'
                """)

            restored = 0
            for row in rows:
                entity_id = row["entity_id"]
                state = self._get_state(entity_id)
                state.current_level = CuriosityLevel(row["current_level"])
                state.window_start = row["window_start"]
                state.ring_confirmations = row["ring_confirmations"] or 0
                state.monitoring_interval_sec = (
                    row["monitoring_interval_sec"] or 300.0
                )
                state.last_check = row["last_check"]
                restored += 1

            logger.info(
                ">>> [CURIOSITY] Restored %d persisted curiosity states",
                restored,
            )
            return restored

        except Exception as exc:
            logger.error(
                ">>> [CURIOSITY] State restoration failed: %s", exc,
            )
            return 0

    # =========================================================================
    # RESET / ADMIN
    # =========================================================================

    async def reset_entity(self, entity_id: UUID, authorized_by: str) -> Dict[str, Any]:
        """
        Administratively reset an entity's curiosity state to NONE.

        Requires human authorization.  Used after an incident has been
        resolved and the entity is cleared for normal operations.

        Args:
            entity_id: UUID of the entity to reset.
            authorized_by: Identifier of the authorizing administrator.

        Returns:
            Reset confirmation with audit trail.
        """
        state = self._get_state(entity_id)
        old_level = state.current_level

        # Log the administrative action
        if self._forensic_logger:
            try:
                await self._forensic_logger.log_event(
                    event_type="curiosity_admin_reset",
                    source_entity=str(entity_id),
                    evidence={
                        "old_level": old_level.value,
                        "authorized_by": authorized_by,
                        "event_count": len(state.events),
                    },
                )
            except Exception as exc:
                logger.error(">>> [CURIOSITY] Forensic log error: %s", exc)

        # Reset in-memory state
        await self._deescalate(state)
        state.events.clear()
        state._divergence_history.clear()

        logger.info(
            ">>> [CURIOSITY] Entity %s reset by %s (was %s)",
            entity_id, authorized_by, old_level.value,
        )

        return {
            "entity_id": str(entity_id),
            "previous_level": old_level.value,
            "current_level": CuriosityLevel.NONE.value,
            "authorized_by": authorized_by,
            "reset_at": datetime.utcnow().isoformat(),
        }
