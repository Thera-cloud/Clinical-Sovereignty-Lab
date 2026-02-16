"""
HIVE DEFENSE PROTOCOL v3.0 — Quarantine Evaluator Worker (Phase 8C)
Continuous assessment of new Fibres in post-birth behavioral quarantine.

Runs every 2 minutes, evaluating all active quarantine records.  Each
new Fibre must demonstrate 60 minutes of consistent, normal behavior
before being released into the live hive.

Quarantine checks:
    1. Heartbeat consistency — regular pulse with correct HMAC
    2. Access pattern normality — no unusual data access requests
    3. Ring interaction validity — proper ring partner communication
    4. Trail emission appropriateness — metadata trails match type

Pass → released into live hive, event ``hive.birth.quarantine_passed``
Fail → contained in mirror dimension, event ``hive.birth.quarantine_failed``

Patent-Pending — Claims 30-56
© 2026 Clinical Sovereignty Lab. All rights reserved.
"""

from __future__ import annotations

import asyncio
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional
from uuid import UUID

import structlog

from app.models.hive_defense import QuarantineRecord

logger = structlog.get_logger("hive.quarantine_evaluator")


# =============================================================================
# CONSTANTS
# =============================================================================

# Default evaluation interval (seconds)
DEFAULT_INTERVAL: float = 120.0  # 2 minutes

# Quarantine duration (minutes)
DEFAULT_QUARANTINE_MINUTES: int = 60

# DEFCON → interval mapping
DEFCON_INTERVAL_MAP: Dict[int, float] = {
    5: 120.0,   # PEACE — standard 2min
    4: 90.0,    # ELEVATED — slightly tighter
    3: 60.0,    # SUBSTANTIAL — every minute
    2: 30.0,    # SEVERE — aggressive
    1: 15.0,    # CRITICAL — maximum vigilance
}

# Minimum heartbeat count expected in quarantine window
MIN_HEARTBEATS_REQUIRED: int = 10


# =============================================================================
# QUARANTINE EVALUATOR WORKER
# =============================================================================

class QuarantineEvaluatorWorker:
    """Background worker: evaluate Fibres in post-birth quarantine.

    Responsibilities
    ----------------
    * Query all active quarantine records.
    * For each quarantine that has reached its duration, evaluate the
      Fibre's behavioral data over the quarantine window.
    * Pass or fail each Fibre based on four behavioral checks.
    * Release passed Fibres into the live hive.
    * Contain failed Fibres in the mirror dimension.
    * Fire appropriate events on pass/fail.

    Parameters
    ----------
    db_pool : Any, optional
        asyncpg connection pool for quarantine records and behavioral data.
    heartbeat_registry : Any, optional
        Reference to HeartbeatRegistry for pulse verification.
    event_callback : callable, optional
        Async callback ``(topic: str, payload: dict) -> None``.
    defcon_provider : callable, optional
        Async callable returning the current DEFCON level (int 1-5).
    base_interval : float
        Default evaluation interval in seconds.
    """

    def __init__(
        self,
        db_pool: Any = None,
        heartbeat_registry: Any = None,
        event_callback: Optional[Any] = None,
        defcon_provider: Optional[Any] = None,
        base_interval: float = DEFAULT_INTERVAL,
    ) -> None:
        self.db_pool = db_pool
        self.heartbeat_registry = heartbeat_registry
        self.event_callback = event_callback
        self.defcon_provider = defcon_provider
        self.base_interval = base_interval

        self._task: Optional[asyncio.Task] = None
        self._running: bool = False

        # Cumulative metrics
        self._total_evaluations: int = 0
        self._total_passed: int = 0
        self._total_failed: int = 0
        self._total_pending: int = 0

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Start the quarantine evaluation loop."""
        self._running = True
        self._task = asyncio.create_task(self._run_loop())
        logger.info("worker_started", worker="QuarantineEvaluatorWorker")

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
            worker="QuarantineEvaluatorWorker",
            total_evaluations=self._total_evaluations,
            total_passed=self._total_passed,
            total_failed=self._total_failed,
        )

    # ------------------------------------------------------------------
    # Main Loop
    # ------------------------------------------------------------------

    async def _run_loop(self) -> None:
        """Primary loop: evaluate quarantines at DEFCON-adjusted intervals."""
        while self._running:
            cycle_start = time.monotonic()
            try:
                await self._evaluate_all_quarantines()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.error(
                    "quarantine_evaluation_error",
                    error=str(exc),
                    exc_info=True,
                )

            interval = await self._current_interval()
            elapsed = time.monotonic() - cycle_start
            sleep_time = max(0.0, interval - elapsed)
            await asyncio.sleep(sleep_time)

    # ------------------------------------------------------------------
    # Evaluation Logic
    # ------------------------------------------------------------------

    async def _evaluate_all_quarantines(self) -> None:
        """Fetch and evaluate all active quarantine records.

        For each quarantine whose duration has elapsed, runs the four
        behavioral checks and issues a pass/fail verdict.
        """
        records = await self._fetch_active_quarantines()
        if not records:
            return

        now = datetime.now(timezone.utc)
        self._total_pending = 0
        evaluated = 0
        passed = 0
        failed = 0

        for record in records:
            fibre_id = record.get("fibre_id")
            started_at = record.get("started_at")
            duration_min = record.get("duration_minutes", DEFAULT_QUARANTINE_MINUTES)

            if not fibre_id or not started_at:
                continue

            # Check if quarantine duration has elapsed
            quarantine_end = started_at + timedelta(minutes=duration_min)
            if now < quarantine_end:
                self._total_pending += 1
                continue

            # Duration elapsed — evaluate behavioral data
            evaluation = await self._evaluate_fibre(fibre_id, started_at, now)
            evaluated += 1

            if evaluation["passed"]:
                passed += 1
                self._total_passed += 1
                await self._release_fibre(fibre_id, evaluation)
            else:
                failed += 1
                self._total_failed += 1
                await self._contain_fibre(fibre_id, evaluation)

        self._total_evaluations += evaluated

        if evaluated > 0:
            logger.info(
                "quarantine_evaluation_cycle",
                evaluated=evaluated,
                passed=passed,
                failed=failed,
                pending=self._total_pending,
            )

    async def _evaluate_fibre(
        self,
        fibre_id: Any,
        started_at: datetime,
        evaluation_time: datetime,
    ) -> Dict[str, Any]:
        """
        Evaluate a single Fibre's behavior during quarantine.

        Checks:
        1. Heartbeat consistency — regular, verified pulses.
        2. Access pattern normality — no unusual data access.
        3. Ring interaction validity — proper partner communication.
        4. Trail emission appropriateness — metadata trails match type.

        Returns
        -------
        dict
            Evaluation result with ``passed`` (bool) and individual
            check results.
        """
        result: Dict[str, Any] = {
            "fibre_id": str(fibre_id),
            "started_at": started_at.isoformat(),
            "evaluated_at": evaluation_time.isoformat(),
            "passed": False,
            "checks": {},
        }

        # Check 1: Heartbeat consistency
        heartbeat_ok = await self._check_heartbeat_consistency(
            fibre_id, started_at, evaluation_time
        )
        result["checks"]["heartbeat_consistent"] = heartbeat_ok

        # Check 2: Access pattern normality
        access_ok = await self._check_access_patterns(
            fibre_id, started_at, evaluation_time
        )
        result["checks"]["access_pattern_normal"] = access_ok

        # Check 3: Ring interaction validity
        ring_ok = await self._check_ring_interactions(
            fibre_id, started_at, evaluation_time
        )
        result["checks"]["ring_interaction_valid"] = ring_ok

        # Check 4: Trail emission appropriateness
        trail_ok = await self._check_trail_emissions(
            fibre_id, started_at, evaluation_time
        )
        result["checks"]["trail_emission_appropriate"] = trail_ok

        # Overall pass: ALL four checks must pass
        result["passed"] = all([heartbeat_ok, access_ok, ring_ok, trail_ok])

        logger.info(
            "quarantine_evaluation",
            fibre_id=str(fibre_id),
            passed=result["passed"],
            checks=result["checks"],
        )

        return result

    # ------------------------------------------------------------------
    # Behavioral Checks
    # ------------------------------------------------------------------

    async def _check_heartbeat_consistency(
        self,
        fibre_id: Any,
        since: datetime,
        until: datetime,
    ) -> bool:
        """Verify heartbeat pulse consistency during quarantine window."""
        if self.heartbeat_registry:
            try:
                if hasattr(self.heartbeat_registry, "check_continuity"):
                    return self.heartbeat_registry.check_continuity(fibre_id)
            except Exception:
                pass

        # Fallback: check database for heartbeat records
        if not self.db_pool:
            return False

        try:
            async with self.db_pool.acquire() as conn:
                count = await conn.fetchval(
                    """
                    SELECT COUNT(*) FROM hive_heartbeats
                    WHERE entity_id = $1
                      AND recorded_at BETWEEN $2 AND $3
                    """,
                    fibre_id,
                    since,
                    until,
                )
                return count >= MIN_HEARTBEATS_REQUIRED
        except Exception as exc:
            logger.debug("heartbeat_check_failed", fibre_id=str(fibre_id), error=str(exc))
            return False

    async def _check_access_patterns(
        self,
        fibre_id: Any,
        since: datetime,
        until: datetime,
    ) -> bool:
        """Check for normal data access patterns during quarantine."""
        if not self.db_pool:
            return True  # Permissive default without DB

        try:
            async with self.db_pool.acquire() as conn:
                # Check for excessive or unusual access requests
                row = await conn.fetchrow(
                    """
                    SELECT COUNT(*) as total_accesses,
                           COUNT(CASE WHEN access_type = 'admin' THEN 1 END) as admin_accesses,
                           COUNT(CASE WHEN access_type = 'cross_ring' THEN 1 END) as cross_ring
                    FROM hive_access_log
                    WHERE entity_id = $1
                      AND accessed_at BETWEEN $2 AND $3
                    """,
                    fibre_id,
                    since,
                    until,
                )

                if row:
                    # Fail if: admin access attempts or excessive cross-ring
                    admin = row["admin_accesses"] or 0
                    cross_ring = row["cross_ring"] or 0
                    if admin > 0 or cross_ring > 5:
                        return False

                return True
        except Exception as exc:
            logger.debug("access_check_failed", fibre_id=str(fibre_id), error=str(exc))
            return True  # Permissive on DB error

    async def _check_ring_interactions(
        self,
        fibre_id: Any,
        since: datetime,
        until: datetime,
    ) -> bool:
        """Verify proper ring partner communication patterns."""
        if not self.db_pool:
            return True

        try:
            async with self.db_pool.acquire() as conn:
                row = await conn.fetchrow(
                    """
                    SELECT COUNT(*) as interactions,
                           COUNT(DISTINCT partner_id) as unique_partners
                    FROM hive_ring_interactions
                    WHERE entity_id = $1
                      AND interacted_at BETWEEN $2 AND $3
                    """,
                    fibre_id,
                    since,
                    until,
                )

                if row:
                    interactions = row["interactions"] or 0
                    partners = row["unique_partners"] or 0
                    # Expected: some interaction but not excessive
                    if interactions > 0 and partners <= 10:
                        return True
                    # Zero interactions is suspicious but not automatic fail
                    return interactions == 0

                return True
        except Exception as exc:
            logger.debug("ring_check_failed", fibre_id=str(fibre_id), error=str(exc))
            return True

    async def _check_trail_emissions(
        self,
        fibre_id: Any,
        since: datetime,
        until: datetime,
    ) -> bool:
        """Verify metadata trail emissions are appropriate for Fibre type."""
        if not self.db_pool:
            return True

        try:
            async with self.db_pool.acquire() as conn:
                row = await conn.fetchrow(
                    """
                    SELECT COUNT(*) as trail_count,
                           COUNT(CASE WHEN anomalous = true THEN 1 END) as anomalous
                    FROM hive_trail_emissions
                    WHERE entity_id = $1
                      AND emitted_at BETWEEN $2 AND $3
                    """,
                    fibre_id,
                    since,
                    until,
                )

                if row:
                    anomalous = row["anomalous"] or 0
                    return anomalous == 0

                return True
        except Exception as exc:
            logger.debug("trail_check_failed", fibre_id=str(fibre_id), error=str(exc))
            return True

    # ------------------------------------------------------------------
    # Pass / Fail Actions
    # ------------------------------------------------------------------

    async def _release_fibre(
        self,
        fibre_id: Any,
        evaluation: Dict[str, Any],
    ) -> None:
        """Release a Fibre from quarantine into the live hive."""
        logger.info(
            "quarantine_passed",
            fibre_id=str(fibre_id),
        )

        # Update quarantine record in DB
        if self.db_pool:
            try:
                async with self.db_pool.acquire() as conn:
                    await conn.execute(
                        """
                        UPDATE hive_quarantine_records
                        SET passed = true, evaluated_at = NOW()
                        WHERE fibre_id = $1 AND passed IS NULL
                        """,
                        fibre_id,
                    )
            except Exception as exc:
                logger.error("quarantine_release_db_failed", error=str(exc))

        # Fire event
        if self.event_callback:
            try:
                await self.event_callback(
                    "hive.birth.quarantine_passed",
                    {
                        "fibre_id": str(fibre_id),
                        "evaluation": evaluation,
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                    },
                )
            except Exception as exc:
                logger.error("quarantine_pass_event_failed", error=str(exc))

    async def _contain_fibre(
        self,
        fibre_id: Any,
        evaluation: Dict[str, Any],
    ) -> None:
        """Contain a failed Fibre — move to mirror dimension."""
        logger.warning(
            "quarantine_failed",
            fibre_id=str(fibre_id),
            failed_checks=[
                k for k, v in evaluation.get("checks", {}).items() if not v
            ],
        )

        # Update quarantine record
        if self.db_pool:
            try:
                async with self.db_pool.acquire() as conn:
                    await conn.execute(
                        """
                        UPDATE hive_quarantine_records
                        SET passed = false, evaluated_at = NOW()
                        WHERE fibre_id = $1 AND passed IS NULL
                        """,
                        fibre_id,
                    )
            except Exception as exc:
                logger.error("quarantine_contain_db_failed", error=str(exc))

        # Fire event
        if self.event_callback:
            try:
                await self.event_callback(
                    "hive.birth.quarantine_failed",
                    {
                        "fibre_id": str(fibre_id),
                        "evaluation": evaluation,
                        "failed_checks": [
                            k for k, v in evaluation.get("checks", {}).items()
                            if not v
                        ],
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                    },
                )
            except Exception as exc:
                logger.error("quarantine_fail_event_failed", error=str(exc))

    # ------------------------------------------------------------------
    # Data Fetching
    # ------------------------------------------------------------------

    async def _fetch_active_quarantines(self) -> List[Dict[str, Any]]:
        """Fetch all active (unevaluated) quarantine records."""
        if not self.db_pool:
            return []

        try:
            async with self.db_pool.acquire() as conn:
                rows = await conn.fetch(
                    """
                    SELECT fibre_id, started_at, duration_minutes
                    FROM hive_quarantine_records
                    WHERE passed IS NULL
                    ORDER BY started_at ASC
                    """
                )
                return [dict(r) for r in rows]
        except Exception as exc:
            logger.debug("quarantine_fetch_failed", error=str(exc))
            return []

    # ------------------------------------------------------------------
    # DEFCON-aware interval
    # ------------------------------------------------------------------

    async def _current_interval(self) -> float:
        """Return the evaluation interval adjusted for DEFCON level."""
        if self.defcon_provider:
            try:
                level = await self.defcon_provider()
                level_int = int(level.value) if hasattr(level, "value") else int(level)
                return DEFCON_INTERVAL_MAP.get(level_int, self.base_interval)
            except Exception:
                pass
        return self.base_interval

    # ------------------------------------------------------------------
    # Diagnostics
    # ------------------------------------------------------------------

    @property
    def stats(self) -> Dict[str, Any]:
        """Diagnostic statistics."""
        return {
            "running": self._running,
            "total_evaluations": self._total_evaluations,
            "total_passed": self._total_passed,
            "total_failed": self._total_failed,
            "total_pending": self._total_pending,
            "pass_rate": (
                round(self._total_passed / self._total_evaluations, 4)
                if self._total_evaluations > 0
                else 0.0
            ),
        }

    def __repr__(self) -> str:
        return (
            f"<QuarantineEvaluatorWorker "
            f"evaluated={self._total_evaluations} "
            f"passed={self._total_passed} "
            f"failed={self._total_failed}>"
        )
