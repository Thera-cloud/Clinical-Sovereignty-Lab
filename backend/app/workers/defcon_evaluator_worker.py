"""
HIVE DEFENSE PROTOCOL — DEFCON Evaluator Worker (Phase 8B)
Continuous threat-level assessment for the Sovereign Swarm.

Runs every 30 seconds, evaluates trigger conditions for DEFCON level
changes (escalation and de-escalation), and enforces the 4-hour
de-escalation hold requirement.

DEFCON Levels
-------------
5 — PEACE       Normal operations.
4 — ELEVATED    Anomaly detected, increased monitoring.
3 — SUBSTANTIAL Multiple anomalies or ring confirmation.
2 — SEVERE      Canary triggered, active compromise suspected.
1 — CRITICAL    Active breach, duress code, or mass compromise.

De-escalation Rule
------------------
The system must remain at an elevated DEFCON level for a minimum of
4 hours before any automatic de-escalation step.  Only one level may
be lowered per de-escalation cycle.

Patent-Pending — Claims 30-56
© 2026 Clinical Sovereignty Lab. All rights reserved.
"""

from __future__ import annotations

import asyncio
import json
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional
from uuid import UUID

import structlog

from app.models.hive_defense import DefconLevel, DefconState

logger = structlog.get_logger("hive.defcon_evaluator")


# =============================================================================
# CONSTANTS
# =============================================================================

# Evaluation interval (seconds).
DEFAULT_INTERVAL: float = 30.0

# Minimum hold time at an elevated DEFCON before de-escalation (seconds).
DEESCALATION_HOLD_SECONDS: float = 4 * 3600  # 4 hours

# Escalation trigger thresholds.
TRIGGER_THRESHOLDS: Dict[str, Dict[str, Any]] = {
    "canary_triggered": {
        "target_level": DefconLevel.SEVERE,
        "description": "Canary credential accessed",
    },
    "duress_code": {
        "target_level": DefconLevel.CRITICAL,
        "description": "Shard holder used duress code",
    },
    "mass_heartbeat_failure": {
        "target_level": DefconLevel.SUBSTANTIAL,
        "description": ">20% entities silent for >2× expected interval",
        "silent_threshold_pct": 0.20,
    },
    "curiosity_alarm": {
        "target_level": DefconLevel.SUBSTANTIAL,
        "description": "Three-Cord verification failure",
    },
    "multi_anomaly": {
        "target_level": DefconLevel.ELEVATED,
        "description": "Multiple anomaly signals within observation window",
        "min_anomalies": 3,
    },
    "sbom_drift": {
        "target_level": DefconLevel.ELEVATED,
        "description": "Supply-chain SBOM hash mismatch",
    },
    "backup_integrity_failure": {
        "target_level": DefconLevel.ELEVATED,
        "description": "Backup integrity verification failed",
    },
}

# DEFCON → heartbeat interval mapping (seconds).
DEFCON_HEARTBEAT_MAP: Dict[int, float] = {
    5: 60.0,
    4: 45.0,
    3: 30.0,
    2: 15.0,
    1: 5.0,
}

# DEFCON → mirror mode mapping.
DEFCON_MIRROR_MODE: Dict[int, str] = {
    5: "passive",
    4: "passive",
    3: "active",
    2: "active",
    1: "fortress",
}


# =============================================================================
# DEFCON EVALUATOR WORKER
# =============================================================================

class DefconEvaluatorWorker:
    """Background worker: continuous DEFCON threat-level evaluation.

    Responsibilities
    ----------------
    * Poll trigger sources (DB events, canary state, heartbeat metrics)
      every 30 seconds.
    * Escalate the DEFCON level when trigger conditions are met.
    * Manage the 4-hour de-escalation hold timer — never de-escalate
      before the hold period expires, and only step down one level at a time.
    * Persist all DEFCON transitions for forensic audit.

    Parameters
    ----------
    db_pool : Any, optional
        asyncpg connection pool.
    forensic_logger : Any, optional
        :class:`ForensicLogger` for immutable evidence.
    canary_manager : Any, optional
        :class:`CanaryCredentialManager` for canary state checks.
    base_interval : float
        Evaluation interval in seconds.
    """

    def __init__(
        self,
        db_pool: Any = None,
        forensic_logger: Any = None,
        canary_manager: Any = None,
        base_interval: float = DEFAULT_INTERVAL,
    ) -> None:
        self.db_pool = db_pool
        self.forensic_logger = forensic_logger
        self.canary_manager = canary_manager
        self.base_interval = base_interval

        # Current DEFCON state
        self._state = DefconState(
            level=DefconLevel.PEACE,
            triggered_at=datetime.now(tz=timezone.utc),
        )

        self._task: Optional[asyncio.Task] = None
        self._running: bool = False

        # Transition history (in-memory ring buffer)
        self._transition_history: List[Dict[str, Any]] = []
        self._max_history: int = 200

        # Cumulative metrics
        self._total_evaluations: int = 0
        self._total_escalations: int = 0
        self._total_deescalations: int = 0

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Start the DEFCON evaluation loop."""
        self._running = True
        await self._load_state_from_db()
        self._task = asyncio.create_task(self._run_loop())
        logger.info(
            "worker_started",
            worker="DefconEvaluatorWorker",
            current_level=self._state.level.value,
        )

    async def stop(self) -> None:
        """Gracefully stop the evaluation loop."""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info(
            "worker_stopped",
            worker="DefconEvaluatorWorker",
            total_evaluations=self._total_evaluations,
            total_escalations=self._total_escalations,
            total_deescalations=self._total_deescalations,
        )

    # ------------------------------------------------------------------
    # Public: state access
    # ------------------------------------------------------------------

    @property
    def current_state(self) -> DefconState:
        """Return the current DEFCON state."""
        return self._state

    @property
    def current_level(self) -> DefconLevel:
        """Return the current DEFCON level."""
        return self._state.level

    async def get_current_level(self) -> DefconLevel:
        """Async accessor for the current DEFCON level (usable as defcon_provider)."""
        return self._state.level

    # ------------------------------------------------------------------
    # Public: manual escalation
    # ------------------------------------------------------------------

    async def escalate(
        self,
        target_level: DefconLevel,
        reason: str,
        triggered_by: str = "manual",
    ) -> Dict[str, Any]:
        """Manually escalate to a specific DEFCON level.

        Parameters
        ----------
        target_level : DefconLevel
            The DEFCON level to escalate to.
        reason : str
            Human-readable reason for the escalation.
        triggered_by : str
            Identifier of the entity that triggered the escalation.

        Returns
        -------
        dict
            Transition record.
        """
        return await self._transition(
            target_level=target_level,
            reason=reason,
            triggered_by=triggered_by,
            direction="escalation",
        )

    # ------------------------------------------------------------------
    # Main loop
    # ------------------------------------------------------------------

    async def _run_loop(self) -> None:
        """Primary loop: evaluate threat conditions every interval."""
        while self._running:
            cycle_start = time.monotonic()
            try:
                await self._evaluate_conditions()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.error(
                    "defcon_evaluation_error",
                    error=str(exc),
                    exc_info=True,
                )

            elapsed = time.monotonic() - cycle_start
            sleep_time = max(0.0, self.base_interval - elapsed)
            await asyncio.sleep(sleep_time)

    # ------------------------------------------------------------------
    # Evaluation logic
    # ------------------------------------------------------------------

    async def _evaluate_conditions(self) -> None:
        """Check all trigger conditions and adjust DEFCON accordingly.

        Evaluation proceeds in two phases:
        1. **Escalation check** — scan for conditions that warrant raising
           the DEFCON level.  Escalation is immediate; no hold time.
        2. **De-escalation check** — if no escalation occurred and the
           hold period has elapsed, attempt to step down one level.
        """
        self._total_evaluations += 1
        now = datetime.now(tz=timezone.utc)
        current_level = self._state.level

        # Phase 1: Escalation
        escalation_needed = False
        max_target = current_level  # highest (lowest number) target seen

        triggers = await self._collect_triggers()

        for trigger in triggers:
            target = trigger["target_level"]
            # Escalate only if target is more severe (lower number)
            if target.value < max_target.value:
                max_target = target
                escalation_needed = True

        if escalation_needed and max_target.value < current_level.value:
            reason_parts = [
                t["reason"] for t in triggers
                if t["target_level"].value <= max_target.value
            ]
            await self._transition(
                target_level=max_target,
                reason="; ".join(reason_parts),
                triggered_by="defcon_evaluator",
                direction="escalation",
            )
            return

        # Phase 2: De-escalation
        if current_level != DefconLevel.PEACE:
            await self._attempt_deescalation(now)

    async def _collect_triggers(self) -> List[Dict[str, Any]]:
        """Collect all active escalation triggers from various sources.

        Returns a list of trigger dicts with ``target_level`` and ``reason``.
        """
        triggers: List[Dict[str, Any]] = []

        # --- Canary triggers ---
        if self.canary_manager:
            try:
                canary_events = await self.canary_manager.check_all_canaries()
                if canary_events:
                    triggers.append({
                        "target_level": DefconLevel.SEVERE,
                        "reason": f"Canary triggered: {len(canary_events)} access event(s)",
                        "source": "canary_manager",
                    })
            except Exception as exc:
                logger.debug("canary_trigger_check_failed", error=str(exc))

        # --- Database event triggers ---
        if self.db_pool:
            try:
                async with self.db_pool.acquire() as conn:
                    # Check for unprocessed DEFCON trigger events
                    rows = await conn.fetch("""
                        SELECT trigger_type, severity, details, created_at
                        FROM hive_defcon_triggers
                        WHERE processed = false
                        ORDER BY created_at ASC
                    """)
                    for row in rows:
                        trigger_type = row["trigger_type"]
                        trigger_def = TRIGGER_THRESHOLDS.get(trigger_type, {})
                        target = trigger_def.get("target_level", DefconLevel.ELEVATED)

                        triggers.append({
                            "target_level": target,
                            "reason": f"{trigger_type}: {row['details'] or trigger_def.get('description', '')}",
                            "source": "db_trigger",
                        })

                        # Mark as processed
                        await conn.execute(
                            """
                            UPDATE hive_defcon_triggers
                            SET processed = true, processed_at = NOW()
                            WHERE trigger_type = $1 AND created_at = $2
                            """,
                            trigger_type, row["created_at"],
                        )

                    # Check mass heartbeat failure
                    hb_stats = await conn.fetchrow("""
                        SELECT total_checked, silent
                        FROM hive_heartbeat_metrics
                        ORDER BY swept_at DESC
                        LIMIT 1
                    """)
                    if hb_stats and hb_stats["total_checked"] > 0:
                        silent_pct = hb_stats["silent"] / hb_stats["total_checked"]
                        threshold = TRIGGER_THRESHOLDS["mass_heartbeat_failure"]["silent_threshold_pct"]
                        if silent_pct >= threshold:
                            triggers.append({
                                "target_level": DefconLevel.SUBSTANTIAL,
                                "reason": (
                                    f"Mass heartbeat failure: {silent_pct:.0%} silent "
                                    f"({hb_stats['silent']}/{hb_stats['total_checked']})"
                                ),
                                "source": "heartbeat_metrics",
                            })

            except Exception as exc:
                logger.debug("db_trigger_collection_failed", error=str(exc))

        return triggers

    # ------------------------------------------------------------------
    # De-escalation
    # ------------------------------------------------------------------

    async def _attempt_deescalation(self, now: datetime) -> None:
        """Attempt to de-escalate one DEFCON level if the hold period has elapsed.

        Rules:
        - Must have been at current level for >= 4 hours.
        - Only step down one level at a time.
        - Cannot de-escalate below PEACE (5).
        """
        last_change = self._state.last_escalation or self._state.triggered_at
        if last_change.tzinfo is None:
            last_change = last_change.replace(tzinfo=timezone.utc)

        hold_elapsed = (now - last_change).total_seconds()

        if hold_elapsed < DEESCALATION_HOLD_SECONDS:
            return  # Hold period not met

        current_value = self._state.level.value
        target_value = min(current_value + 1, 5)  # Step down one level

        if target_value == current_value:
            return  # Already at PEACE

        target_level = DefconLevel(target_value)
        await self._transition(
            target_level=target_level,
            reason=f"Automatic de-escalation after {hold_elapsed / 3600:.1f}h hold",
            triggered_by="defcon_evaluator_deescalation",
            direction="deescalation",
        )

    # ------------------------------------------------------------------
    # State transition
    # ------------------------------------------------------------------

    async def _transition(
        self,
        target_level: DefconLevel,
        reason: str,
        triggered_by: str,
        direction: str = "escalation",
    ) -> Dict[str, Any]:
        """Execute a DEFCON level transition.

        Persists the transition to the database and forensic log, and
        updates the in-memory state with associated parameters (heartbeat
        interval, mirror mode, etc.).
        """
        old_level = self._state.level
        now = datetime.now(tz=timezone.utc)

        # Update state
        self._state.level = target_level
        self._state.triggered_at = now
        self._state.trigger_reason = reason
        self._state.heartbeat_interval_sec = DEFCON_HEARTBEAT_MAP.get(target_level.value, 60.0)
        self._state.mirror_mode = DEFCON_MIRROR_MODE.get(target_level.value, "passive")

        if direction == "escalation":
            self._state.last_escalation = now
            self._total_escalations += 1
        else:
            self._state.last_deescalation = now
            self._total_deescalations += 1

        transition_record = {
            "from_level": old_level.value,
            "to_level": target_level.value,
            "direction": direction,
            "reason": reason,
            "triggered_by": triggered_by,
            "timestamp": now.isoformat(),
            "heartbeat_interval": self._state.heartbeat_interval_sec,
            "mirror_mode": self._state.mirror_mode,
        }

        # Ring-buffer history
        self._transition_history.append(transition_record)
        if len(self._transition_history) > self._max_history:
            self._transition_history = self._transition_history[-self._max_history:]

        # Persist to database
        await self._persist_transition(transition_record)

        # Forensic evidence
        if self.forensic_logger:
            try:
                await self.forensic_logger.log_event(
                    event_type=f"hive.defcon.{direction}",
                    source_entity=triggered_by,
                    evidence=transition_record,
                )
            except Exception as exc:
                logger.debug("forensic_log_failed", error=str(exc))

        log_fn = logger.critical if target_level.value <= 2 else logger.warning
        log_fn(
            f"DEFCON_{direction.upper()}",
            from_level=old_level.value,
            to_level=target_level.value,
            reason=reason,
            triggered_by=triggered_by,
        )

        return transition_record

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    async def _persist_transition(self, record: Dict[str, Any]) -> None:
        """Persist a DEFCON transition to the database."""
        if not self.db_pool:
            return

        try:
            async with self.db_pool.acquire() as conn:
                await conn.execute(
                    """
                    INSERT INTO hive_defcon_transitions
                        (from_level, to_level, direction, reason,
                         triggered_by, transitioned_at)
                    VALUES ($1, $2, $3, $4, $5, NOW())
                    """,
                    record["from_level"],
                    record["to_level"],
                    record["direction"],
                    record["reason"],
                    record["triggered_by"],
                )
                # Also update the current state row
                await conn.execute(
                    """
                    INSERT INTO hive_defcon_state
                        (id, level, trigger_reason, heartbeat_interval_sec,
                         mirror_mode, updated_at)
                    VALUES (1, $1, $2, $3, $4, NOW())
                    ON CONFLICT (id) DO UPDATE
                    SET level = $1, trigger_reason = $2,
                        heartbeat_interval_sec = $3, mirror_mode = $4,
                        updated_at = NOW()
                    """,
                    record["to_level"],
                    record["reason"],
                    record.get("heartbeat_interval", 60.0),
                    record.get("mirror_mode", "passive"),
                )
        except Exception as exc:
            logger.debug("defcon_transition_persist_failed", error=str(exc))

    async def _load_state_from_db(self) -> None:
        """Load the persisted DEFCON state from the database on startup."""
        if not self.db_pool:
            return

        try:
            async with self.db_pool.acquire() as conn:
                row = await conn.fetchrow("""
                    SELECT level, trigger_reason, heartbeat_interval_sec,
                           mirror_mode, updated_at
                    FROM hive_defcon_state
                    WHERE id = 1
                """)
                if row:
                    self._state.level = DefconLevel(row["level"])
                    self._state.trigger_reason = row["trigger_reason"] or ""
                    self._state.heartbeat_interval_sec = float(row["heartbeat_interval_sec"] or 60.0)
                    self._state.mirror_mode = row["mirror_mode"] or "passive"
                    if row["updated_at"]:
                        updated = row["updated_at"]
                        if updated.tzinfo is None:
                            updated = updated.replace(tzinfo=timezone.utc)
                        self._state.triggered_at = updated
                        self._state.last_escalation = updated

                    logger.info(
                        "defcon_state_loaded",
                        level=self._state.level.value,
                        reason=self._state.trigger_reason,
                    )
        except Exception as exc:
            logger.debug("defcon_state_load_failed", error=str(exc))

    # ------------------------------------------------------------------
    # Diagnostics
    # ------------------------------------------------------------------

    @property
    def stats(self) -> Dict[str, Any]:
        """Diagnostic statistics for monitoring."""
        return {
            "running": self._running,
            "current_level": self._state.level.value,
            "mirror_mode": self._state.mirror_mode,
            "heartbeat_interval": self._state.heartbeat_interval_sec,
            "total_evaluations": self._total_evaluations,
            "total_escalations": self._total_escalations,
            "total_deescalations": self._total_deescalations,
            "transition_history_size": len(self._transition_history),
        }

    def __repr__(self) -> str:
        return (
            f"<DefconEvaluatorWorker "
            f"level={self._state.level.value} "
            f"evals={self._total_evaluations} "
            f"escalations={self._total_escalations}>"
        )
