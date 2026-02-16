"""
HIVE DEFENSE PROTOCOL v3.0 — Snapshot Comparison Worker (Phase 8C)
Daily behavioral snapshot capture and historical drift analysis.

Runs once daily.  For each active entity in the hive:
1. Captures a new behavioral snapshot (data access hash, communication
   graph hash, trail emission fingerprint, coherence baseline hash).
2. Compares against snapshots from 30, 60, and 90 days ago.
3. Fires ``hive.snapshot.drift_detected`` if significant divergence
   is found between current and historical behavior.

Slow, subtle compromise is the hardest to detect.  By comparing weekly
snapshots over long time horizons, we can catch gradual behavioral drift
that might indicate a compromised entity slowly expanding its footprint.

Patent-Pending — Claims 30-56
© 2026 Clinical Sovereignty Lab. All rights reserved.
"""

from __future__ import annotations

import asyncio
import hashlib
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional
from uuid import UUID, uuid4

import structlog

from app.models.hive_defense import BehavioralSnapshot

logger = structlog.get_logger("hive.snapshot_comparison")


# =============================================================================
# CONSTANTS
# =============================================================================

# Default run interval (seconds) — once daily
DEFAULT_INTERVAL: float = 86400.0  # 24 hours

# Comparison horizons (days)
COMPARISON_HORIZONS: List[int] = [30, 60, 90]

# Drift threshold — combined hash difference score above this triggers alert
DRIFT_THRESHOLD: float = 0.5

# Maximum entities to snapshot per cycle (backpressure)
MAX_ENTITIES_PER_CYCLE: int = 10000


# =============================================================================
# SNAPSHOT COMPARISON WORKER
# =============================================================================

class SnapshotComparisonWorker:
    """Background worker: daily behavioral snapshot capture and drift analysis.

    Responsibilities
    ----------------
    * Capture a new behavioral snapshot for every active hive entity.
    * Compare current snapshots against 30-day, 60-day, and 90-day
      historical baselines.
    * Calculate drift scores across four behavioral dimensions.
    * Fire ``hive.snapshot.drift_detected`` events when drift exceeds
      thresholds.
    * Persist all snapshots and comparison results.

    Parameters
    ----------
    db_pool : Any, optional
        asyncpg connection pool.
    event_callback : callable, optional
        Async callback ``(topic: str, payload: dict) -> None``.
    defcon_provider : callable, optional
        Async callable returning the current DEFCON level.
    base_interval : float
        Default run interval in seconds (24h default).
    """

    def __init__(
        self,
        db_pool: Any = None,
        event_callback: Optional[Any] = None,
        defcon_provider: Optional[Any] = None,
        base_interval: float = DEFAULT_INTERVAL,
    ) -> None:
        self.db_pool = db_pool
        self.event_callback = event_callback
        self.defcon_provider = defcon_provider
        self.base_interval = base_interval

        self._task: Optional[asyncio.Task] = None
        self._running: bool = False

        # Cumulative metrics
        self._total_runs: int = 0
        self._total_snapshots_taken: int = 0
        self._total_comparisons: int = 0
        self._total_drifts_detected: int = 0
        self._last_run_at: Optional[datetime] = None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Start the snapshot comparison loop."""
        self._running = True
        self._task = asyncio.create_task(self._run_loop())
        logger.info("worker_started", worker="SnapshotComparisonWorker")

    async def stop(self) -> None:
        """Gracefully stop the loop."""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info(
            "worker_stopped",
            worker="SnapshotComparisonWorker",
            total_runs=self._total_runs,
            total_snapshots=self._total_snapshots_taken,
            total_drifts=self._total_drifts_detected,
        )

    # ------------------------------------------------------------------
    # Main Loop
    # ------------------------------------------------------------------

    async def _run_loop(self) -> None:
        """Primary loop: run snapshot cycle daily."""
        while self._running:
            cycle_start = time.monotonic()
            try:
                await self._run_snapshot_cycle()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.error(
                    "snapshot_cycle_error",
                    error=str(exc),
                    exc_info=True,
                )

            elapsed = time.monotonic() - cycle_start
            sleep_time = max(0.0, self.base_interval - elapsed)
            await asyncio.sleep(sleep_time)

    # ------------------------------------------------------------------
    # Snapshot Cycle
    # ------------------------------------------------------------------

    async def _run_snapshot_cycle(self) -> None:
        """Execute one full snapshot capture and comparison cycle.

        Steps:
        1. Fetch all active entities.
        2. For each entity, capture a new behavioral snapshot.
        3. For each comparison horizon (30/60/90 days), load the
           historical snapshot and compute drift.
        4. Fire drift events where thresholds are exceeded.
        5. Persist all new snapshots and comparison results.
        """
        self._total_runs += 1
        self._last_run_at = datetime.now(timezone.utc)
        now = self._last_run_at

        logger.info(
            "snapshot_cycle_started",
            run_number=self._total_runs,
        )

        # Step 1: Fetch active entities
        entities = await self._fetch_active_entities()
        if not entities:
            logger.info("snapshot_cycle_skipped reason=no_active_entities")
            return

        entity_count = min(len(entities), MAX_ENTITIES_PER_CYCLE)
        snapshots_taken = 0
        drifts_detected = 0

        # Step 2-4: Process each entity
        for entity in entities[:entity_count]:
            entity_id = entity.get("entity_id")
            if not entity_id:
                continue

            # Capture new snapshot
            snapshot = await self._capture_snapshot(entity_id, entity)
            if snapshot:
                snapshots_taken += 1
                await self._persist_snapshot(snapshot)

                # Compare against historical horizons
                for horizon_days in COMPARISON_HORIZONS:
                    historical = await self._load_historical_snapshot(
                        entity_id, horizon_days
                    )
                    if historical:
                        drift = self._compute_drift(snapshot, historical)
                        self._total_comparisons += 1

                        if drift["drift_score"] > DRIFT_THRESHOLD:
                            drifts_detected += 1
                            self._total_drifts_detected += 1
                            await self._fire_drift_event(
                                entity_id, drift, horizon_days
                            )

                        # Persist comparison result
                        await self._persist_comparison(
                            entity_id, snapshot, historical,
                            drift, horizon_days
                        )

        self._total_snapshots_taken += snapshots_taken

        logger.info(
            "snapshot_cycle_complete",
            run_number=self._total_runs,
            entities_processed=entity_count,
            snapshots_taken=snapshots_taken,
            drifts_detected=drifts_detected,
        )

    # ------------------------------------------------------------------
    # Snapshot Capture
    # ------------------------------------------------------------------

    async def _capture_snapshot(
        self,
        entity_id: Any,
        entity_data: Dict[str, Any],
    ) -> Optional[BehavioralSnapshot]:
        """
        Capture a behavioral snapshot for a single entity.

        Computes cryptographic hashes of the entity's current behavioral
        profile across four dimensions.

        Returns
        -------
        BehavioralSnapshot or None
            The snapshot, or None if capture failed.
        """
        try:
            now = datetime.now(timezone.utc)
            week_number = now.isocalendar()[1]

            # Fetch behavioral data for hashing
            behavioral_data = await self._fetch_behavioral_data(entity_id)

            data_access_hash = hashlib.sha256(
                str(behavioral_data.get("data_access_pattern", "")).encode()
            ).hexdigest()

            communication_hash = hashlib.sha256(
                str(behavioral_data.get("communication_graph", "")).encode()
            ).hexdigest()

            trail_fingerprint = hashlib.sha256(
                str(behavioral_data.get("trail_emissions", "")).encode()
            ).hexdigest()

            coherence_hash = hashlib.sha256(
                str(behavioral_data.get("coherence_baseline", "")).encode()
            ).hexdigest()

            snapshot = BehavioralSnapshot(
                entity_id=entity_id,
                week_number=week_number,
                data_access_hash=data_access_hash,
                communication_graph_hash=communication_hash,
                trail_emission_fingerprint=trail_fingerprint,
                coherence_baseline_hash=coherence_hash,
            )

            return snapshot

        except Exception as exc:
            logger.warning(
                "snapshot_capture_failed",
                entity_id=str(entity_id),
                error=str(exc),
            )
            return None

    # ------------------------------------------------------------------
    # Drift Computation
    # ------------------------------------------------------------------

    def _compute_drift(
        self,
        current: BehavioralSnapshot,
        historical: BehavioralSnapshot,
    ) -> Dict[str, Any]:
        """
        Compute behavioral drift between current and historical snapshots.

        Compares hashes across four dimensions.  Each dimension contributes
        0.0 (identical) or 1.0 (different) to the drift score.  The
        overall drift score is the average across all dimensions.

        Returns
        -------
        dict
            Drift analysis with per-dimension results and overall score.
        """
        dimensions = {
            "data_access": (
                current.data_access_hash,
                historical.data_access_hash,
            ),
            "communication": (
                current.communication_graph_hash,
                historical.communication_graph_hash,
            ),
            "trail_emission": (
                current.trail_emission_fingerprint,
                historical.trail_emission_fingerprint,
            ),
            "coherence": (
                current.coherence_baseline_hash,
                historical.coherence_baseline_hash,
            ),
        }

        dimension_drifts: Dict[str, float] = {}
        changed_dimensions: List[str] = []

        for dim_name, (current_hash, historical_hash) in dimensions.items():
            if current_hash != historical_hash:
                dimension_drifts[dim_name] = 1.0
                changed_dimensions.append(dim_name)
            else:
                dimension_drifts[dim_name] = 0.0

        total_drift = sum(dimension_drifts.values())
        drift_score = total_drift / len(dimensions) if dimensions else 0.0

        return {
            "drift_score": drift_score,
            "dimension_drifts": dimension_drifts,
            "changed_dimensions": changed_dimensions,
            "dimensions_changed": len(changed_dimensions),
            "total_dimensions": len(dimensions),
        }

    # ------------------------------------------------------------------
    # Drift Events
    # ------------------------------------------------------------------

    async def _fire_drift_event(
        self,
        entity_id: Any,
        drift: Dict[str, Any],
        horizon_days: int,
    ) -> None:
        """Fire a hive.snapshot.drift_detected event."""
        payload = {
            "entity_id": str(entity_id),
            "horizon_days": horizon_days,
            "drift_score": drift["drift_score"],
            "changed_dimensions": drift["changed_dimensions"],
            "threshold": DRIFT_THRESHOLD,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

        logger.warning(
            "SNAPSHOT_DRIFT_DETECTED",
            entity_id=str(entity_id),
            horizon_days=horizon_days,
            drift_score=drift["drift_score"],
            changed=drift["changed_dimensions"],
        )

        if self.event_callback:
            try:
                await self.event_callback("hive.snapshot.drift_detected", payload)
            except Exception as exc:
                logger.error("drift_event_failed", error=str(exc))

    # ------------------------------------------------------------------
    # Data Fetching
    # ------------------------------------------------------------------

    async def _fetch_active_entities(self) -> List[Dict[str, Any]]:
        """Fetch all active entities in the hive."""
        if not self.db_pool:
            return []

        try:
            async with self.db_pool.acquire() as conn:
                rows = await conn.fetch(
                    """
                    SELECT entity_id, fibre_type, ring_region
                    FROM hive_heartbeats
                    WHERE active = true
                    ORDER BY entity_id
                    LIMIT $1
                    """,
                    MAX_ENTITIES_PER_CYCLE,
                )
                return [dict(r) for r in rows]
        except Exception as exc:
            logger.debug("entity_fetch_failed", error=str(exc))
            return []

    async def _fetch_behavioral_data(
        self,
        entity_id: Any,
    ) -> Dict[str, Any]:
        """Fetch current behavioral data for snapshot hashing."""
        data: Dict[str, Any] = {}

        if not self.db_pool:
            return data

        try:
            async with self.db_pool.acquire() as conn:
                # Data access pattern
                access_rows = await conn.fetch(
                    """
                    SELECT resource_type, COUNT(*) as cnt
                    FROM hive_access_log
                    WHERE entity_id = $1
                      AND accessed_at >= NOW() - INTERVAL '7 days'
                    GROUP BY resource_type
                    ORDER BY resource_type
                    """,
                    entity_id,
                )
                data["data_access_pattern"] = [dict(r) for r in access_rows]

                # Communication graph (recent partners)
                comm_rows = await conn.fetch(
                    """
                    SELECT partner_id, COUNT(*) as interactions
                    FROM hive_ring_interactions
                    WHERE entity_id = $1
                      AND interacted_at >= NOW() - INTERVAL '7 days'
                    GROUP BY partner_id
                    ORDER BY partner_id
                    """,
                    entity_id,
                )
                data["communication_graph"] = [dict(r) for r in comm_rows]

                # Trail emissions
                trail_rows = await conn.fetch(
                    """
                    SELECT trail_type, COUNT(*) as cnt
                    FROM hive_trail_emissions
                    WHERE entity_id = $1
                      AND emitted_at >= NOW() - INTERVAL '7 days'
                    GROUP BY trail_type
                    ORDER BY trail_type
                    """,
                    entity_id,
                )
                data["trail_emissions"] = [dict(r) for r in trail_rows]

                # Coherence baseline
                coherence = await conn.fetchrow(
                    """
                    SELECT AVG(coherence_score) as avg_score,
                           STDDEV(coherence_score) as std_score
                    FROM hive_coherence_readings
                    WHERE entity_id = $1
                      AND measured_at >= NOW() - INTERVAL '7 days'
                    """,
                    entity_id,
                )
                data["coherence_baseline"] = dict(coherence) if coherence else {}

        except Exception as exc:
            logger.debug(
                "behavioral_data_fetch_failed",
                entity_id=str(entity_id),
                error=str(exc),
            )

        return data

    async def _load_historical_snapshot(
        self,
        entity_id: Any,
        days_ago: int,
    ) -> Optional[BehavioralSnapshot]:
        """Load a historical snapshot from *days_ago* days back."""
        if not self.db_pool:
            return None

        target_date = datetime.now(timezone.utc) - timedelta(days=days_ago)
        # Allow ±3 day window for finding the nearest snapshot
        window_start = target_date - timedelta(days=3)
        window_end = target_date + timedelta(days=3)

        try:
            async with self.db_pool.acquire() as conn:
                row = await conn.fetchrow(
                    """
                    SELECT snapshot_id, entity_id, week_number,
                           data_access_hash, communication_graph_hash,
                           trail_emission_fingerprint, coherence_baseline_hash,
                           created_at
                    FROM hive_behavioral_snapshots
                    WHERE entity_id = $1
                      AND created_at BETWEEN $2 AND $3
                    ORDER BY ABS(EXTRACT(EPOCH FROM (created_at - $4)))
                    LIMIT 1
                    """,
                    entity_id,
                    window_start,
                    window_end,
                    target_date,
                )

                if row:
                    return BehavioralSnapshot(
                        snapshot_id=row["snapshot_id"],
                        entity_id=row["entity_id"],
                        week_number=row["week_number"],
                        data_access_hash=row["data_access_hash"],
                        communication_graph_hash=row["communication_graph_hash"],
                        trail_emission_fingerprint=row["trail_emission_fingerprint"],
                        coherence_baseline_hash=row["coherence_baseline_hash"],
                        created_at=row["created_at"],
                    )

        except Exception as exc:
            logger.debug(
                "historical_snapshot_load_failed",
                entity_id=str(entity_id),
                days_ago=days_ago,
                error=str(exc),
            )

        return None

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    async def _persist_snapshot(self, snapshot: BehavioralSnapshot) -> None:
        """Persist a new behavioral snapshot to the database."""
        if not self.db_pool:
            return

        try:
            async with self.db_pool.acquire() as conn:
                await conn.execute(
                    """
                    INSERT INTO hive_behavioral_snapshots (
                        snapshot_id, entity_id, week_number,
                        data_access_hash, communication_graph_hash,
                        trail_emission_fingerprint, coherence_baseline_hash,
                        created_at
                    ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
                    """,
                    snapshot.snapshot_id,
                    snapshot.entity_id,
                    snapshot.week_number,
                    snapshot.data_access_hash,
                    snapshot.communication_graph_hash,
                    snapshot.trail_emission_fingerprint,
                    snapshot.coherence_baseline_hash,
                    snapshot.created_at,
                )
        except Exception as exc:
            logger.debug("snapshot_persist_failed", error=str(exc))

    async def _persist_comparison(
        self,
        entity_id: Any,
        current: BehavioralSnapshot,
        historical: BehavioralSnapshot,
        drift: Dict[str, Any],
        horizon_days: int,
    ) -> None:
        """Persist a snapshot comparison result."""
        if not self.db_pool:
            return

        try:
            async with self.db_pool.acquire() as conn:
                await conn.execute(
                    """
                    INSERT INTO hive_snapshot_comparisons (
                        entity_id, current_snapshot_id, historical_snapshot_id,
                        horizon_days, drift_score, dimensions_changed,
                        changed_dimensions, compared_at
                    ) VALUES ($1, $2, $3, $4, $5, $6, $7, NOW())
                    """,
                    entity_id,
                    current.snapshot_id,
                    historical.snapshot_id,
                    horizon_days,
                    drift["drift_score"],
                    drift["dimensions_changed"],
                    drift["changed_dimensions"],
                )
        except Exception as exc:
            logger.debug("comparison_persist_failed", error=str(exc))

    # ------------------------------------------------------------------
    # Diagnostics
    # ------------------------------------------------------------------

    @property
    def stats(self) -> Dict[str, Any]:
        """Diagnostic statistics."""
        return {
            "running": self._running,
            "total_runs": self._total_runs,
            "total_snapshots_taken": self._total_snapshots_taken,
            "total_comparisons": self._total_comparisons,
            "total_drifts_detected": self._total_drifts_detected,
            "last_run_at": (
                self._last_run_at.isoformat() if self._last_run_at else None
            ),
        }

    def __repr__(self) -> str:
        return (
            f"<SnapshotComparisonWorker "
            f"runs={self._total_runs} "
            f"snapshots={self._total_snapshots_taken} "
            f"drifts={self._total_drifts_detected}>"
        )
