"""
HIVE DEFENSE PROTOCOL v3.0 — Post-Birth Quarantine (Phase 8C: Third Cord)
60-minute behavioral quarantine for every newly born Fibre.

Design rationale:
    Even when a Fibre is born from a valid certificate, signed by the Originator,
    and assigned to a Cosmic Ring, it could still be compromised — born from a
    stolen key.  A compromised Fibre WILL behave anomalously within minutes
    because the attacker doesn't know the expected behavioral norms.

    The Post-Birth Quarantine places every new Fibre in a 60-minute observation
    period at DEFCON-2 sensitivity (the most sensitive non-lockdown level).
    During this period, the Fibre must demonstrate:

        1. Consistent heartbeat     — Regular, valid pulse emissions
        2. Appropriate data access  — Only accessing data relevant to its role
        3. Valid ring interaction    — Communicating within its Cosmic Ring
        4. Appropriate Trail Emissions — Coherence data matching expected patterns

    A Fibre born from a stolen key will fail at least one of these checks
    because the attacker cannot perfectly replicate legitimate behavior
    from birth. Most compromised Fibres are caught within the first 10-15
    minutes.

Patent-Pending — Claims 30-56
© 2026 Clinical Sovereignty Lab. All rights reserved.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Callable, Coroutine, Dict, List, Optional, Set
from uuid import UUID, uuid4

from app.models.hive_defense import (
    DefconLevel,
    QuarantineRecord,
    HIVE_EVENT_TOPICS,
)

logger = logging.getLogger("hive.post_birth_quarantine")


# =============================================================================
# CONSTANTS
# =============================================================================

#: Default quarantine duration in minutes
QUARANTINE_DURATION_MINUTES: int = 60

#: Minimum heartbeats expected during quarantine
MIN_HEARTBEATS_REQUIRED: int = 10

#: Maximum allowed data access anomaly events during quarantine
MAX_DATA_ACCESS_ANOMALIES: int = 2

#: Maximum allowed ring interaction violations during quarantine
MAX_RING_VIOLATIONS: int = 1

#: Maximum allowed trail emission anomalies during quarantine
MAX_TRAIL_ANOMALIES: int = 3

#: Evaluation frequency (how often to check quarantined Fibres)
EVALUATION_INTERVAL_SEC: float = 30.0


# =============================================================================
# QUARANTINE TRACKING STATE
# =============================================================================

@dataclass
class QuarantineState:
    """
    Internal tracking state for a Fibre in quarantine.

    Extends the QuarantineRecord model with detailed behavioral counters
    used during the evaluation period.

    Attributes:
        record:                The Pydantic QuarantineRecord.
        heartbeat_count:       Number of valid heartbeats received.
        heartbeat_failures:    Number of heartbeat failures (missed/invalid).
        data_access_events:    List of data access events for pattern analysis.
        data_access_anomalies: Count of anomalous data access patterns.
        ring_interactions:     Count of valid ring interactions.
        ring_violations:       Count of invalid ring interactions.
        trail_emissions:       Count of trail emissions received.
        trail_anomalies:       Count of anomalous trail emissions.
        last_heartbeat_at:     Timestamp of last valid heartbeat.
        evaluation_log:        Running log of evaluation checkpoints.
    """
    record: QuarantineRecord
    heartbeat_count: int = 0
    heartbeat_failures: int = 0
    data_access_events: List[Dict[str, Any]] = field(default_factory=list)
    data_access_anomalies: int = 0
    ring_interactions: int = 0
    ring_violations: int = 0
    trail_emissions: int = 0
    trail_anomalies: int = 0
    last_heartbeat_at: Optional[datetime] = None
    evaluation_log: List[Dict[str, Any]] = field(default_factory=list)


# =============================================================================
# POST-BIRTH QUARANTINE
# =============================================================================

class PostBirthQuarantine:
    """
    60-minute behavioral quarantine for every newly born Fibre.

    Every Fibre enters quarantine immediately at birth and must demonstrate
    consistent, appropriate behavior before being released into the hive.
    The quarantine operates at DEFCON-2 sensitivity, meaning the behavioral
    thresholds are tighter than normal operations.

    A Fibre born from a stolen key will behave anomalously within minutes
    because the attacker cannot replicate the expected behavioral norms.
    The quarantine catches these compromised Fibres before they can cause
    damage.

    Integration Points:
        - HeartbeatRegistry        — provides heartbeat events
        - RingMembershipValidator  — validates ring interactions
        - CumulativeDriftScorer    — provides drift analysis
        - DefconController         — escalates on quarantine failures
        - ForensicLogger           — logs quarantine events

    Usage::

        quarantine = PostBirthQuarantine(db_pool=pool)

        # Start quarantine for a new Fibre
        record = await quarantine.start_quarantine(fibre_id)

        # Report behavioral events during quarantine
        await quarantine.report_heartbeat(fibre_id, valid=True)
        await quarantine.report_data_access(fibre_id, event_data)
        await quarantine.report_ring_interaction(fibre_id, valid=True)
        await quarantine.report_trail_emission(fibre_id, is_anomalous=False)

        # Evaluate quarantine (called periodically or on-demand)
        result = await quarantine.evaluate_quarantine(fibre_id)

    Patent-Pending — Claims 30-56
    """

    def __init__(
        self,
        db_pool=None,
        event_callback: Optional[Callable[[str, Dict[str, Any]], Coroutine]] = None,
        forensic_logger=None,
        defcon_controller=None,
    ) -> None:
        """
        Initialize the Post-Birth Quarantine system.

        Args:
            db_pool:            asyncpg connection pool for persistence.
            event_callback:     Async callback for hive event bus.
            forensic_logger:    ForensicLogger for immutable evidence chain.
            defcon_controller:  DefconController for escalation.
        """
        self._db_pool = db_pool
        self._event_callback = event_callback
        self._forensic_logger = forensic_logger
        self._defcon_controller = defcon_controller

        # Active quarantines: fibre_id → QuarantineState
        self._active: Dict[UUID, QuarantineState] = {}

        # Completed quarantines (recent history)
        self._completed: List[QuarantineState] = []
        self._max_completed_history: int = 500

        # Statistics
        self._total_quarantines: int = 0
        self._total_passed: int = 0
        self._total_failed: int = 0

        # Evaluation loop
        self._evaluation_task: Optional[asyncio.Task] = None

        logger.info("PostBirthQuarantine initialized")

    # =========================================================================
    # QUARANTINE LIFECYCLE
    # =========================================================================

    async def start_quarantine(self, fibre_id: UUID) -> QuarantineRecord:
        """
        Start a 60-minute quarantine for a newly born Fibre.

        The Fibre enters quarantine at DEFCON-2 sensitivity and must
        demonstrate consistent, appropriate behavior before release.

        Args:
            fibre_id: UUID of the Fibre to quarantine.

        Returns:
            QuarantineRecord with the quarantine parameters.

        Raises:
            ValueError: If the Fibre is already in quarantine.
        """
        if fibre_id in self._active:
            raise ValueError(
                f"Fibre {fibre_id} is already in quarantine"
            )

        record = QuarantineRecord(
            fibre_id=fibre_id,
            duration_minutes=QUARANTINE_DURATION_MINUTES,
        )

        state = QuarantineState(record=record)
        self._active[fibre_id] = state
        self._total_quarantines += 1

        logger.info(
            "Quarantine started: fibre=%s duration=%dmin (DEFCON-2 sensitivity)",
            fibre_id, QUARANTINE_DURATION_MINUTES,
        )

        # Persist to database
        await self._persist_quarantine_start(record)

        # Broadcast event
        await self._broadcast_event(
            "hive.birth.quarantine_started",
            {
                "fibre_id": str(fibre_id),
                "duration_minutes": QUARANTINE_DURATION_MINUTES,
                "sensitivity": "DEFCON-2",
                "timestamp": datetime.utcnow().isoformat(),
            },
        )

        return record

    async def evaluate_quarantine(self, fibre_id: UUID) -> Optional[str]:
        """
        Evaluate whether a quarantined Fibre has passed or failed.

        Evaluation criteria (at DEFCON-2 sensitivity):
            1. Consistent heartbeat: >= MIN_HEARTBEATS_REQUIRED valid beats
            2. Appropriate data access: <= MAX_DATA_ACCESS_ANOMALIES anomalies
            3. Valid ring interaction: <= MAX_RING_VIOLATIONS violations
            4. Appropriate trail emissions: <= MAX_TRAIL_ANOMALIES anomalies

        If the quarantine period has not elapsed, checks for early failure
        (i.e., the Fibre has already exceeded anomaly thresholds).

        Args:
            fibre_id: UUID of the Fibre to evaluate.

        Returns:
            "passed" — Fibre cleared quarantine, released to hive.
            "failed" — Fibre failed quarantine, remains contained.
            None     — Quarantine still in progress, not yet evaluable.
        """
        state = self._active.get(fibre_id)
        if state is None:
            logger.warning(
                "Evaluate called for fibre %s not in active quarantine",
                fibre_id,
            )
            return None

        record = state.record
        now = datetime.utcnow()
        elapsed = (now - record.started_at).total_seconds()
        quarantine_sec = record.duration_minutes * 60

        # ── Check for early failure (threshold exceeded before time runs out) ──
        early_fail_reasons: List[str] = []

        if state.data_access_anomalies > MAX_DATA_ACCESS_ANOMALIES:
            early_fail_reasons.append(
                f"data_access_anomalies={state.data_access_anomalies} "
                f"(max={MAX_DATA_ACCESS_ANOMALIES})"
            )

        if state.ring_violations > MAX_RING_VIOLATIONS:
            early_fail_reasons.append(
                f"ring_violations={state.ring_violations} "
                f"(max={MAX_RING_VIOLATIONS})"
            )

        if state.trail_anomalies > MAX_TRAIL_ANOMALIES:
            early_fail_reasons.append(
                f"trail_anomalies={state.trail_anomalies} "
                f"(max={MAX_TRAIL_ANOMALIES})"
            )

        if state.heartbeat_failures > 5:
            early_fail_reasons.append(
                f"heartbeat_failures={state.heartbeat_failures} (max=5)"
            )

        if early_fail_reasons:
            return await self._complete_quarantine(
                fibre_id, passed=False,
                reasons=early_fail_reasons,
            )

        # ── If quarantine period has not elapsed, still in progress ──
        if elapsed < quarantine_sec:
            # Log evaluation checkpoint
            state.evaluation_log.append({
                "elapsed_sec": elapsed,
                "heartbeat_count": state.heartbeat_count,
                "anomalies": {
                    "data_access": state.data_access_anomalies,
                    "ring": state.ring_violations,
                    "trail": state.trail_anomalies,
                    "heartbeat_failures": state.heartbeat_failures,
                },
                "timestamp": now.isoformat(),
            })
            return None

        # ── Quarantine period elapsed — final evaluation ──
        pass_reasons: List[str] = []
        fail_reasons: List[str] = []

        # 1. Heartbeat consistency
        if state.heartbeat_count >= MIN_HEARTBEATS_REQUIRED:
            record.heartbeat_consistent = True
            pass_reasons.append(
                f"heartbeats={state.heartbeat_count} (min={MIN_HEARTBEATS_REQUIRED})"
            )
        else:
            fail_reasons.append(
                f"heartbeats={state.heartbeat_count} "
                f"(min={MIN_HEARTBEATS_REQUIRED})"
            )

        # 2. Data access pattern
        if state.data_access_anomalies <= MAX_DATA_ACCESS_ANOMALIES:
            record.access_pattern_normal = True
            pass_reasons.append(
                f"data_access_anomalies={state.data_access_anomalies}"
            )
        else:
            fail_reasons.append(
                f"data_access_anomalies={state.data_access_anomalies}"
            )

        # 3. Ring interaction
        if state.ring_violations <= MAX_RING_VIOLATIONS:
            record.ring_interaction_valid = True
            pass_reasons.append(
                f"ring_violations={state.ring_violations}"
            )
        else:
            fail_reasons.append(
                f"ring_violations={state.ring_violations}"
            )

        # 4. Trail emissions
        if state.trail_anomalies <= MAX_TRAIL_ANOMALIES:
            record.trail_emission_appropriate = True
            pass_reasons.append(
                f"trail_anomalies={state.trail_anomalies}"
            )
        else:
            fail_reasons.append(
                f"trail_anomalies={state.trail_anomalies}"
            )

        # Determine final result
        passed = len(fail_reasons) == 0
        all_reasons = fail_reasons if not passed else pass_reasons

        return await self._complete_quarantine(
            fibre_id, passed=passed, reasons=all_reasons,
        )

    # =========================================================================
    # BEHAVIORAL EVENT REPORTING
    # =========================================================================

    async def report_heartbeat(
        self,
        fibre_id: UUID,
        valid: bool,
    ) -> None:
        """
        Report a heartbeat event for a quarantined Fibre.

        Args:
            fibre_id: UUID of the Fibre.
            valid:    Whether the heartbeat was valid.
        """
        state = self._active.get(fibre_id)
        if state is None:
            return

        if valid:
            state.heartbeat_count += 1
            state.last_heartbeat_at = datetime.utcnow()
        else:
            state.heartbeat_failures += 1
            logger.debug(
                "Quarantine heartbeat failure: fibre=%s failures=%d",
                fibre_id, state.heartbeat_failures,
            )

    async def report_data_access(
        self,
        fibre_id: UUID,
        event_data: Dict[str, Any],
        is_anomalous: bool = False,
    ) -> None:
        """
        Report a data access event for a quarantined Fibre.

        Args:
            fibre_id:     UUID of the Fibre.
            event_data:   Details of the data access event.
            is_anomalous: Whether this access pattern is anomalous.
        """
        state = self._active.get(fibre_id)
        if state is None:
            return

        state.data_access_events.append({
            **event_data,
            "is_anomalous": is_anomalous,
            "timestamp": datetime.utcnow().isoformat(),
        })

        if is_anomalous:
            state.data_access_anomalies += 1
            logger.warning(
                "Quarantine data access anomaly: fibre=%s count=%d event=%s",
                fibre_id, state.data_access_anomalies, event_data,
            )

    async def report_ring_interaction(
        self,
        fibre_id: UUID,
        valid: bool,
    ) -> None:
        """
        Report a ring interaction event for a quarantined Fibre.

        Args:
            fibre_id: UUID of the Fibre.
            valid:    Whether the ring interaction was valid.
        """
        state = self._active.get(fibre_id)
        if state is None:
            return

        if valid:
            state.ring_interactions += 1
        else:
            state.ring_violations += 1
            logger.warning(
                "Quarantine ring violation: fibre=%s violations=%d",
                fibre_id, state.ring_violations,
            )

    async def report_trail_emission(
        self,
        fibre_id: UUID,
        is_anomalous: bool = False,
    ) -> None:
        """
        Report a trail emission event for a quarantined Fibre.

        Args:
            fibre_id:     UUID of the Fibre.
            is_anomalous: Whether the trail emission was anomalous.
        """
        state = self._active.get(fibre_id)
        if state is None:
            return

        state.trail_emissions += 1

        if is_anomalous:
            state.trail_anomalies += 1
            logger.warning(
                "Quarantine trail anomaly: fibre=%s anomalies=%d",
                fibre_id, state.trail_anomalies,
            )

    # =========================================================================
    # QUARANTINE QUERIES
    # =========================================================================

    def is_quarantined(self, fibre_id: UUID) -> bool:
        """Check if a Fibre is currently in quarantine."""
        return fibre_id in self._active

    def get_active_quarantines(self) -> List[Dict[str, Any]]:
        """Return summary information for all active quarantines."""
        now = datetime.utcnow()
        return [
            {
                "fibre_id": str(fid),
                "started_at": state.record.started_at.isoformat(),
                "elapsed_minutes": (now - state.record.started_at).total_seconds() / 60,
                "heartbeats": state.heartbeat_count,
                "anomalies": {
                    "data_access": state.data_access_anomalies,
                    "ring": state.ring_violations,
                    "trail": state.trail_anomalies,
                    "heartbeat_failures": state.heartbeat_failures,
                },
            }
            for fid, state in self._active.items()
        ]

    # =========================================================================
    # EVALUATION LOOP
    # =========================================================================

    async def start_evaluation_loop(self) -> None:
        """Start the periodic quarantine evaluation loop."""
        if self._evaluation_task is not None:
            logger.warning("Evaluation loop already running")
            return

        self._evaluation_task = asyncio.create_task(self._evaluation_loop())
        logger.info(
            "Quarantine evaluation loop started (interval=%.0fs)",
            EVALUATION_INTERVAL_SEC,
        )

    async def stop_evaluation_loop(self) -> None:
        """Stop the periodic quarantine evaluation loop."""
        if self._evaluation_task:
            self._evaluation_task.cancel()
            try:
                await self._evaluation_task
            except asyncio.CancelledError:
                pass
            self._evaluation_task = None
            logger.info("Quarantine evaluation loop stopped")

    async def _evaluation_loop(self) -> None:
        """Internal evaluation loop coroutine."""
        while True:
            try:
                await asyncio.sleep(EVALUATION_INTERVAL_SEC)

                # Evaluate all active quarantines
                for fibre_id in list(self._active.keys()):
                    await self.evaluate_quarantine(fibre_id)

            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.error("Quarantine evaluation loop error: %s", exc)
                await asyncio.sleep(5.0)

    # =========================================================================
    # INTERNAL COMPLETION
    # =========================================================================

    async def _complete_quarantine(
        self,
        fibre_id: UUID,
        passed: bool,
        reasons: List[str],
    ) -> str:
        """
        Complete a quarantine with a pass/fail result.

        Args:
            fibre_id: UUID of the Fibre.
            passed:   Whether the Fibre passed quarantine.
            reasons:  List of reasons for the result.

        Returns:
            "passed" or "failed".
        """
        state = self._active.pop(fibre_id, None)
        if state is None:
            return "failed"

        record = state.record
        record.passed = passed
        record.evaluated_at = datetime.utcnow()

        result = "passed" if passed else "failed"

        # Track statistics
        if passed:
            self._total_passed += 1
        else:
            self._total_failed += 1

        # Add to completed history
        self._completed.append(state)
        if len(self._completed) > self._max_completed_history:
            self._completed = self._completed[-self._max_completed_history:]

        log_fn = logger.info if passed else logger.warning
        log_fn(
            "Quarantine %s: fibre=%s reasons=[%s] "
            "(heartbeats=%d, anomalies: data=%d ring=%d trail=%d)",
            result, fibre_id, "; ".join(reasons),
            state.heartbeat_count,
            state.data_access_anomalies,
            state.ring_violations,
            state.trail_anomalies,
        )

        # Forensic log
        if self._forensic_logger:
            try:
                await self._forensic_logger.log_event(
                    event_type=f"quarantine_{result}",
                    source_entity=str(fibre_id),
                    evidence={
                        "result": result,
                        "reasons": reasons,
                        "heartbeat_count": state.heartbeat_count,
                        "heartbeat_failures": state.heartbeat_failures,
                        "data_access_anomalies": state.data_access_anomalies,
                        "ring_violations": state.ring_violations,
                        "trail_anomalies": state.trail_anomalies,
                        "duration_sec": (
                            record.evaluated_at - record.started_at
                        ).total_seconds(),
                    },
                )
            except Exception as exc:
                logger.error("Forensic log failed: %s", exc)

        # Escalate on failure
        if not passed and self._defcon_controller:
            try:
                await self._defcon_controller.escalate(
                    DefconLevel.SUBSTANTIAL,
                    f"Fibre {fibre_id} failed post-birth quarantine: "
                    + "; ".join(reasons),
                )
            except Exception as exc:
                logger.error("DEFCON escalation failed: %s", exc)

        # Persist result
        await self._persist_quarantine_result(record)

        # Broadcast event
        event_topic = (
            "hive.birth.quarantine_passed"
            if passed
            else "hive.birth.quarantine_failed"
        )
        await self._broadcast_event(
            event_topic,
            {
                "fibre_id": str(fibre_id),
                "result": result,
                "reasons": reasons,
                "duration_minutes": record.duration_minutes,
                "timestamp": datetime.utcnow().isoformat(),
            },
        )

        return result

    # =========================================================================
    # ADMIN
    # =========================================================================

    def summary(self) -> Dict[str, Any]:
        """Return a summary dict for admin dashboards."""
        return {
            "active_quarantines": len(self._active),
            "total_quarantines": self._total_quarantines,
            "total_passed": self._total_passed,
            "total_failed": self._total_failed,
            "pass_rate": (
                f"{self._total_passed / self._total_quarantines * 100:.1f}%"
                if self._total_quarantines > 0
                else "N/A"
            ),
            "active_details": self.get_active_quarantines(),
        }

    # =========================================================================
    # PERSISTENCE
    # =========================================================================

    async def _persist_quarantine_start(self, record: QuarantineRecord) -> None:
        """Persist a quarantine start to the database."""
        if not self._db_pool:
            return

        try:
            async with self._db_pool.acquire() as conn:
                await conn.execute(
                    """
                    INSERT INTO quarantine_records (
                        fibre_id, started_at, duration_minutes, passed
                    ) VALUES ($1, $2, $3, NULL)
                    """,
                    record.fibre_id,
                    record.started_at,
                    record.duration_minutes,
                )
        except Exception as exc:
            logger.error(
                "Failed to persist quarantine start for %s: %s",
                record.fibre_id, exc,
            )

    async def _persist_quarantine_result(self, record: QuarantineRecord) -> None:
        """Persist a quarantine result to the database."""
        if not self._db_pool:
            return

        try:
            async with self._db_pool.acquire() as conn:
                await conn.execute(
                    """
                    UPDATE quarantine_records SET
                        passed = $2,
                        heartbeat_consistent = $3,
                        access_pattern_normal = $4,
                        ring_interaction_valid = $5,
                        trail_emission_appropriate = $6,
                        evaluated_at = $7
                    WHERE fibre_id = $1 AND evaluated_at IS NULL
                    """,
                    record.fibre_id,
                    record.passed,
                    record.heartbeat_consistent,
                    record.access_pattern_normal,
                    record.ring_interaction_valid,
                    record.trail_emission_appropriate,
                    record.evaluated_at,
                )
        except Exception as exc:
            logger.error(
                "Failed to persist quarantine result for %s: %s",
                record.fibre_id, exc,
            )

    async def load_from_db(self) -> int:
        """
        Load active quarantine records from the database on startup.

        Returns:
            Number of active quarantine records loaded.
        """
        if not self._db_pool:
            return 0

        try:
            async with self._db_pool.acquire() as conn:
                rows = await conn.fetch(
                    """
                    SELECT fibre_id, started_at, duration_minutes
                    FROM quarantine_records
                    WHERE evaluated_at IS NULL
                    """
                )

            loaded = 0
            for row in rows:
                record = QuarantineRecord(
                    fibre_id=row["fibre_id"],
                    started_at=row["started_at"],
                    duration_minutes=row["duration_minutes"],
                )
                self._active[record.fibre_id] = QuarantineState(record=record)
                loaded += 1

            logger.info("Loaded %d active quarantine records", loaded)
            return loaded

        except Exception as exc:
            logger.error("Failed to load quarantine records: %s", exc)
            return 0

    # =========================================================================
    # EVENT BUS
    # =========================================================================

    async def _broadcast_event(
        self,
        topic: str,
        payload: Dict[str, Any],
    ) -> None:
        """Broadcast an event via the registered callback."""
        if self._event_callback:
            try:
                await self._event_callback(topic, payload)
            except Exception as exc:
                logger.error(
                    "Event callback failed for topic %s: %s", topic, exc,
                )
