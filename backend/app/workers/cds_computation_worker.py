"""
HIVE DEFENSE PROTOCOL — CDS Computation Worker (Phase 8B)
Periodic Cumulative Drift Score computation across all hive entities.

Runs every 10 minutes, recalculates the combined magnitude for every
entity that has drift data, and triggers curiosity evaluation when
thresholds are exceeded.

The Cumulative Drift Score (CDS) is the Euclidean magnitude of a
6-dimensional drift vector:

    CDS = sqrt(d_access² + d_comm² + d_coherence² + d_trail² + d_journal² + d_timing²)

Patent-Pending — Claims 30-56
© 2026 Clinical Sovereignty Lab. All rights reserved.
"""

from __future__ import annotations

import asyncio
import math
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from uuid import UUID

import structlog

from app.models.hive_defense import CuriosityLevel, DriftScore

logger = structlog.get_logger("hive.cds_computation")


# =============================================================================
# CONSTANTS
# =============================================================================

# Default computation interval (seconds).
DEFAULT_INTERVAL: float = 600.0  # 10 minutes

# CDS threshold: above this magnitude, curiosity evaluation is triggered.
CDS_NOTICE_THRESHOLD: float = 0.5
CDS_INTEREST_THRESHOLD: float = 0.8
CDS_CONCERN_THRESHOLD: float = 1.2

# DEFCON → interval multiplier (tighter monitoring at higher alert levels).
DEFCON_INTERVAL_MAP: Dict[int, float] = {
    5: 600.0,   # PEACE — 10 minutes
    4: 300.0,   # ELEVATED — 5 minutes
    3: 180.0,   # SUBSTANTIAL — 3 minutes
    2: 60.0,    # SEVERE — 1 minute
    1: 30.0,    # CRITICAL — 30 seconds
}


# =============================================================================
# CDS COMPUTATION WORKER
# =============================================================================

class CdsComputationWorker:
    """Background worker: periodic Cumulative Drift Score recomputation.

    Iterates over all entities with drift data (from the ``hive_drift_scores``
    table or in-memory registry), recomputes the combined CDS magnitude,
    and escalates entities whose score exceeds graduated thresholds to the
    :class:`CuriosityProtocol` for further evaluation.

    Parameters
    ----------
    db_pool : Any, optional
        asyncpg connection pool for reading/writing drift scores.
    curiosity_protocol : Any, optional
        Reference to :class:`CuriosityProtocol` for anomaly escalation.
    defcon_provider : callable, optional
        Async callable returning the current DEFCON level (int 1-5).
    base_interval : float
        Default computation interval in seconds.
    """

    def __init__(
        self,
        db_pool: Any = None,
        curiosity_protocol: Any = None,
        defcon_provider: Optional[Any] = None,
        base_interval: float = DEFAULT_INTERVAL,
    ) -> None:
        self.db_pool = db_pool
        self.curiosity_protocol = curiosity_protocol
        self.defcon_provider = defcon_provider
        self.base_interval = base_interval

        self._task: Optional[asyncio.Task] = None
        self._running: bool = False

        # Cumulative metrics
        self._total_cycles: int = 0
        self._total_entities_computed: int = 0
        self._total_escalations: int = 0

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Start the CDS computation loop."""
        self._running = True
        self._task = asyncio.create_task(self._run_loop())
        logger.info("worker_started", worker="CdsComputationWorker")

    async def stop(self) -> None:
        """Gracefully stop the computation loop."""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info(
            "worker_stopped",
            worker="CdsComputationWorker",
            total_cycles=self._total_cycles,
            total_computed=self._total_entities_computed,
            total_escalations=self._total_escalations,
        )

    # ------------------------------------------------------------------
    # Main loop
    # ------------------------------------------------------------------

    async def _run_loop(self) -> None:
        """Primary loop: recompute CDS at the DEFCON-adjusted interval."""
        while self._running:
            cycle_start = time.monotonic()
            try:
                await self._compute_all_drift_scores()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.error(
                    "cds_computation_error",
                    error=str(exc),
                    exc_info=True,
                )

            interval = await self._current_interval()
            elapsed = time.monotonic() - cycle_start
            sleep_time = max(0.0, interval - elapsed)
            await asyncio.sleep(sleep_time)

    # ------------------------------------------------------------------
    # Core computation
    # ------------------------------------------------------------------

    async def _compute_all_drift_scores(self) -> None:
        """Recompute CDS magnitude for all entities with drift data.

        Steps:
        1. Fetch all drift-score rows from the database.
        2. Recompute ``combined_magnitude`` using Euclidean distance.
        3. Persist the updated magnitude.
        4. Escalate entities exceeding thresholds to CuriosityProtocol.
        """
        entities = await self._fetch_drift_entities()
        if not entities:
            return

        escalation_targets: List[Dict[str, Any]] = []
        computed = 0

        for entity in entities:
            entity_id = entity["entity_id"]

            # Recompute magnitude
            magnitude = math.sqrt(
                entity.get("data_access", 0.0) ** 2
                + entity.get("communication", 0.0) ** 2
                + entity.get("coherence", 0.0) ** 2
                + entity.get("trail_emission", 0.0) ** 2
                + entity.get("journal_trajectory", 0.0) ** 2
                + entity.get("timing_pattern", 0.0) ** 2
            )

            # Persist updated magnitude
            await self._update_magnitude(entity_id, magnitude)
            computed += 1

            # Check thresholds
            if magnitude >= CDS_CONCERN_THRESHOLD:
                escalation_targets.append({
                    "entity_id": entity_id,
                    "magnitude": magnitude,
                    "level": CuriosityLevel.CONCERN,
                    "reason": f"CDS magnitude {magnitude:.3f} exceeds CONCERN threshold ({CDS_CONCERN_THRESHOLD})",
                })
            elif magnitude >= CDS_INTEREST_THRESHOLD:
                escalation_targets.append({
                    "entity_id": entity_id,
                    "magnitude": magnitude,
                    "level": CuriosityLevel.INTEREST,
                    "reason": f"CDS magnitude {magnitude:.3f} exceeds INTEREST threshold ({CDS_INTEREST_THRESHOLD})",
                })
            elif magnitude >= CDS_NOTICE_THRESHOLD:
                escalation_targets.append({
                    "entity_id": entity_id,
                    "magnitude": magnitude,
                    "level": CuriosityLevel.NOTICE,
                    "reason": f"CDS magnitude {magnitude:.3f} exceeds NOTICE threshold ({CDS_NOTICE_THRESHOLD})",
                })

        # Escalate
        for target in escalation_targets:
            await self._escalate_to_curiosity(target)

        # Update metrics
        self._total_cycles += 1
        self._total_entities_computed += computed
        self._total_escalations += len(escalation_targets)

        # Persist cycle metrics
        await self._persist_cycle_metrics(computed, len(escalation_targets))

        logger.info(
            "cds_computation_complete",
            cycle=self._total_cycles,
            entities_computed=computed,
            escalations=len(escalation_targets),
        )

    # ------------------------------------------------------------------
    # Data access
    # ------------------------------------------------------------------

    async def _fetch_drift_entities(self) -> List[Dict[str, Any]]:
        """Fetch all entities with drift data from the database."""
        if not self.db_pool:
            return []

        try:
            async with self.db_pool.acquire() as conn:
                rows = await conn.fetch("""
                    SELECT entity_id, data_access, communication, coherence,
                           trail_emission, journal_trajectory, timing_pattern,
                           combined_magnitude, last_updated
                    FROM hive_drift_scores
                    WHERE active = true
                    ORDER BY last_updated ASC
                """)
                return [dict(r) for r in rows]
        except Exception as exc:
            logger.warning("drift_fetch_failed", error=str(exc))
            return []

    async def _update_magnitude(self, entity_id: UUID, magnitude: float) -> None:
        """Persist the recomputed CDS magnitude for an entity."""
        if not self.db_pool:
            return

        try:
            async with self.db_pool.acquire() as conn:
                await conn.execute(
                    """
                    UPDATE hive_drift_scores
                    SET combined_magnitude = $2, last_updated = NOW()
                    WHERE entity_id = $1
                    """,
                    entity_id, magnitude,
                )
        except Exception as exc:
            logger.debug("magnitude_update_failed", entity_id=str(entity_id), error=str(exc))

    # ------------------------------------------------------------------
    # Curiosity escalation
    # ------------------------------------------------------------------

    async def _escalate_to_curiosity(self, target: Dict[str, Any]) -> None:
        """Forward an entity with elevated CDS to the CuriosityProtocol."""
        try:
            if self.curiosity_protocol and hasattr(self.curiosity_protocol, "evaluate_entity"):
                await self.curiosity_protocol.evaluate_entity(
                    entity_id=target["entity_id"],
                    trigger_reason="cds_threshold_exceeded",
                    context={
                        "magnitude": target["magnitude"],
                        "curiosity_level": target["level"].value if hasattr(target["level"], "value") else str(target["level"]),
                        "reason": target["reason"],
                    },
                )
                logger.info(
                    "cds_curiosity_escalation",
                    entity_id=str(target["entity_id"]),
                    magnitude=round(target["magnitude"], 4),
                    level=str(target["level"]),
                )
        except Exception as exc:
            logger.error(
                "cds_curiosity_escalation_failed",
                entity_id=str(target.get("entity_id")),
                error=str(exc),
            )

    # ------------------------------------------------------------------
    # DEFCON-aware interval
    # ------------------------------------------------------------------

    async def _current_interval(self) -> float:
        """Return the computation interval adjusted for the current DEFCON level."""
        if self.defcon_provider:
            try:
                level = await self.defcon_provider()
                level_int = int(level.value) if hasattr(level, "value") else int(level)
                return DEFCON_INTERVAL_MAP.get(level_int, self.base_interval)
            except Exception:
                pass
        return self.base_interval

    # ------------------------------------------------------------------
    # Metrics persistence
    # ------------------------------------------------------------------

    async def _persist_cycle_metrics(
        self, entities_computed: int, escalations: int,
    ) -> None:
        """Write cycle metrics to the database for dashboard consumption."""
        if not self.db_pool:
            return

        try:
            async with self.db_pool.acquire() as conn:
                await conn.execute(
                    """
                    INSERT INTO hive_cds_metrics
                        (cycle_number, entities_computed, escalations, computed_at)
                    VALUES ($1, $2, $3, NOW())
                    """,
                    self._total_cycles,
                    entities_computed,
                    escalations,
                )
        except Exception as exc:
            logger.debug("cds_metrics_persist_failed", error=str(exc))

    # ------------------------------------------------------------------
    # Diagnostics
    # ------------------------------------------------------------------

    @property
    def stats(self) -> Dict[str, Any]:
        """Diagnostic statistics for monitoring."""
        return {
            "running": self._running,
            "total_cycles": self._total_cycles,
            "total_entities_computed": self._total_entities_computed,
            "total_escalations": self._total_escalations,
        }

    def __repr__(self) -> str:
        return (
            f"<CdsComputationWorker "
            f"cycles={self._total_cycles} "
            f"computed={self._total_entities_computed} "
            f"escalations={self._total_escalations}>"
        )
