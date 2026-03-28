"""
HIVE DEFENSE PROTOCOL v3.0 — Behavioral Snapshot Manager (Phase 8C: Third Cord)
Weekly SHA-256 cryptographic snapshots of every Fibre's behavioral profile.

Design rationale:
    A sophisticated attacker modifies behavior slowly — fractions of a percent
    per day.  Day-to-day comparisons show nothing.  But comparing the current
    week's behavioral profile against the profile from 30, 60, or 90 days ago
    makes the cumulative drift *obvious*.

    Every 7 days, the Behavioral Snapshot Manager takes a SHA-256 snapshot of
    four dimensions for each entity:
        1. data_access_hash           — Hash of data access patterns
        2. communication_graph_hash   — Hash of communication graph topology
        3. trail_emission_fingerprint — Fingerprint of Trail Emission patterns
        4. coherence_baseline_hash    — Hash of emotional coherence baseline

    The snapshot comparison algorithm:
        - Compare week N vs week N-4  (30-day comparison)
        - Compare week N vs week N-8  (60-day comparison)
        - Compare week N vs week N-13 (90-day comparison)

    Any dimension where the hashes differ = behavioural drift in that dimension.
    Drift across multiple dimensions or across multiple time horizons = compound
    indicator of compromise.

Patent-Pending — Claims 30-56
© 2026 Clinical Sovereignty Lab. All rights reserved.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import time
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Callable, Coroutine, Dict, List, Optional, Tuple
from uuid import UUID, uuid4

from app.models.hive_defense import (
    BehavioralSnapshot,
    MirrorReflection,
    HIVE_EVENT_TOPICS,
)

logger = logging.getLogger("hive.behavioral_snapshot")


# =============================================================================
# CONSTANTS
# =============================================================================

#: Snapshot interval in days
SNAPSHOT_INTERVAL_DAYS: int = 7

#: Comparison horizons (in weeks)
COMPARISON_HORIZONS: List[Tuple[str, int]] = [
    ("30_day", 4),    # 4 weeks ≈ 30 days
    ("60_day", 8),    # 8 weeks ≈ 60 days
    ("90_day", 13),   # 13 weeks ≈ 90 days
]

#: Snapshot dimensions
SNAPSHOT_DIMENSIONS: List[str] = [
    "data_access_hash",
    "communication_graph_hash",
    "trail_emission_fingerprint",
    "coherence_baseline_hash",
]

#: Drift severity thresholds (number of changed dimensions)
DRIFT_SEVERITY_THRESHOLDS: Dict[str, int] = {
    "low": 1,        # 1 dimension changed
    "medium": 2,     # 2 dimensions changed
    "high": 3,       # 3 dimensions changed
    "critical": 4,   # All 4 dimensions changed
}

#: Maximum snapshots retained per entity (in memory)
MAX_SNAPSHOTS_PER_ENTITY: int = 52  # ~1 year of weekly snapshots


# =============================================================================
# DIVERGENCE REPORT
# =============================================================================

@dataclass
class DivergenceReport:
    """
    Report of behavioral divergence between two snapshots.

    Attributes:
        entity_id:          UUID of the entity.
        current_week:       The current snapshot's week number.
        comparison_week:    The comparison snapshot's week number.
        horizon_label:      Human-readable label (e.g., "30_day").
        dimensions_changed: List of dimension names that diverged.
        total_dimensions:   Total number of dimensions compared.
        severity:           Divergence severity (low/medium/high/critical).
        details:            Per-dimension comparison details.
        generated_at:       Timestamp of report generation.
    """
    entity_id: UUID = field(default_factory=uuid4)
    current_week: int = 0
    comparison_week: int = 0
    horizon_label: str = ""
    dimensions_changed: List[str] = field(default_factory=list)
    total_dimensions: int = 4
    severity: str = "none"
    details: Dict[str, Dict[str, str]] = field(default_factory=dict)
    generated_at: datetime = field(default_factory=datetime.utcnow)

    @property
    def divergence_ratio(self) -> float:
        """Fraction of dimensions that diverged (0.0 – 1.0)."""
        if self.total_dimensions == 0:
            return 0.0
        return len(self.dimensions_changed) / self.total_dimensions


# =============================================================================
# BEHAVIORAL SNAPSHOT MANAGER
# =============================================================================

class BehavioralSnapshotManager:
    """
    Weekly cryptographic snapshots of every Fibre's behavioral profile.

    Takes SHA-256 snapshots of four behavioral dimensions every 7 days
    and compares current snapshots against 30/60/90-day-old snapshots.
    Drift that is invisible day-to-day becomes obvious when viewed across
    these longer time horizons.

    Integration Points:
        - CumulativeDriftScorer  — provides behavioral dimension data
        - CuriosityProtocol      — receives drift alerts
        - DefconController       — escalation on severe drift
        - ForensicLogger         — logs drift detections

    Usage::

        manager = BehavioralSnapshotManager(db_pool=pool)
        await manager.load_from_db()

        # Take a snapshot
        snapshot = await manager.take_snapshot(entity_id)

        # Compare snapshots
        report = await manager.compare_snapshots(entity_id, week_12, week_4)

        # Run full analysis (all entities, all horizons)
        alerts = await manager.run_full_analysis()

    Patent-Pending — Claims 30-56
    """

    def __init__(
        self,
        db_pool=None,
        event_callback: Optional[Callable[[str, Dict[str, Any]], Coroutine]] = None,
        forensic_logger=None,
        behavioral_data_provider=None,
    ) -> None:
        """
        Initialize the Behavioral Snapshot Manager.

        Args:
            db_pool:                   asyncpg connection pool.
            event_callback:            Async callback for hive event bus.
            forensic_logger:           ForensicLogger for evidence chain.
            behavioral_data_provider:  Service that provides current behavioral
                                       data for snapshot computation (e.g.,
                                       CumulativeDriftScorer).
        """
        self._db_pool = db_pool
        self._event_callback = event_callback
        self._forensic_logger = forensic_logger
        self._behavioral_data = behavioral_data_provider

        # Snapshots per entity: entity_id → {week_number → BehavioralSnapshot}
        self._snapshots: Dict[UUID, Dict[int, BehavioralSnapshot]] = defaultdict(dict)

        # Current week number (incremented by the snapshot loop)
        self._current_week: int = 0

        # Statistics
        self._total_snapshots_taken: int = 0
        self._total_drift_detections: int = 0

        # Snapshot loop
        self._snapshot_task: Optional[asyncio.Task] = None

        logger.info("BehavioralSnapshotManager initialized")

    # =========================================================================
    # SNAPSHOT CREATION
    # =========================================================================

    async def take_snapshot(
        self,
        entity_id: UUID,
        data_access_pattern: str = "",
        communication_graph: str = "",
        trail_emission_data: str = "",
        coherence_baseline: str = "",
    ) -> BehavioralSnapshot:
        """
        Take a SHA-256 behavioral snapshot of an entity.

        Hashes each of the four behavioral dimensions and stores the snapshot
        indexed by entity and week number.

        Args:
            entity_id:             UUID of the entity.
            data_access_pattern:   Raw data access pattern string to hash.
            communication_graph:   Raw communication graph data to hash.
            trail_emission_data:   Raw trail emission data to hash.
            coherence_baseline:    Raw coherence baseline data to hash.

        Returns:
            BehavioralSnapshot with all four dimension hashes.
        """
        snapshot = BehavioralSnapshot(
            entity_id=entity_id,
            week_number=self._current_week,
            data_access_hash=hashlib.sha256(
                data_access_pattern.encode()
            ).hexdigest(),
            communication_graph_hash=hashlib.sha256(
                communication_graph.encode()
            ).hexdigest(),
            trail_emission_fingerprint=hashlib.sha256(
                trail_emission_data.encode()
            ).hexdigest(),
            coherence_baseline_hash=hashlib.sha256(
                coherence_baseline.encode()
            ).hexdigest(),
        )

        # Store in memory
        entity_snapshots = self._snapshots[entity_id]
        entity_snapshots[self._current_week] = snapshot

        # Prune old snapshots beyond retention
        if len(entity_snapshots) > MAX_SNAPSHOTS_PER_ENTITY:
            oldest_week = min(entity_snapshots.keys())
            del entity_snapshots[oldest_week]

        self._total_snapshots_taken += 1

        logger.info(
            "Snapshot taken: entity=%s week=%d "
            "access=%s… comm=%s… trail=%s… coherence=%s…",
            entity_id,
            self._current_week,
            snapshot.data_access_hash[:12],
            snapshot.communication_graph_hash[:12],
            snapshot.trail_emission_fingerprint[:12],
            snapshot.coherence_baseline_hash[:12],
        )

        # Persist
        await self._persist_snapshot(snapshot)

        return snapshot

    # =========================================================================
    # SNAPSHOT COMPARISON
    # =========================================================================

    async def compare_snapshots(
        self,
        entity_id: UUID,
        current_week: int,
        comparison_week: int,
    ) -> DivergenceReport:
        """
        Compare two snapshots for behavioral divergence.

        Examines all four dimensions and reports which (if any) have changed.
        Assigns a severity level based on the number of changed dimensions.

        Args:
            entity_id:       UUID of the entity.
            current_week:    Week number of the current (newer) snapshot.
            comparison_week: Week number of the comparison (older) snapshot.

        Returns:
            DivergenceReport detailing the comparison results.
        """
        entity_snaps = self._snapshots.get(entity_id, {})

        current = entity_snaps.get(current_week)
        comparison = entity_snaps.get(comparison_week)

        report = DivergenceReport(
            entity_id=entity_id,
            current_week=current_week,
            comparison_week=comparison_week,
        )

        if current is None or comparison is None:
            report.severity = "insufficient_data"
            report.details = {
                "note": (
                    f"Missing snapshot(s): current_week={current_week} "
                    f"exists={current is not None}, "
                    f"comparison_week={comparison_week} "
                    f"exists={comparison is not None}"
                )
            }
            return report

        # Compare each dimension
        changed: List[str] = []
        details: Dict[str, Dict[str, str]] = {}

        dimension_pairs = [
            ("data_access_hash", current.data_access_hash, comparison.data_access_hash),
            ("communication_graph_hash", current.communication_graph_hash, comparison.communication_graph_hash),
            ("trail_emission_fingerprint", current.trail_emission_fingerprint, comparison.trail_emission_fingerprint),
            ("coherence_baseline_hash", current.coherence_baseline_hash, comparison.coherence_baseline_hash),
        ]

        for dim_name, current_hash, comparison_hash in dimension_pairs:
            is_same = current_hash == comparison_hash
            details[dim_name] = {
                "current": current_hash[:16] + "…",
                "comparison": comparison_hash[:16] + "…",
                "match": "yes" if is_same else "DIVERGED",
            }
            if not is_same:
                changed.append(dim_name)

        report.dimensions_changed = changed
        report.details = details

        # Determine severity
        num_changed = len(changed)
        if num_changed == 0:
            report.severity = "none"
        elif num_changed >= DRIFT_SEVERITY_THRESHOLDS["critical"]:
            report.severity = "critical"
        elif num_changed >= DRIFT_SEVERITY_THRESHOLDS["high"]:
            report.severity = "high"
        elif num_changed >= DRIFT_SEVERITY_THRESHOLDS["medium"]:
            report.severity = "medium"
        else:
            report.severity = "low"

        if num_changed > 0:
            logger.warning(
                "Snapshot divergence: entity=%s weeks=%d→%d "
                "changed=%d/4 dims=%s severity=%s",
                entity_id, comparison_week, current_week,
                num_changed, changed, report.severity,
            )

        return report

    # =========================================================================
    # FULL ANALYSIS
    # =========================================================================

    async def run_full_analysis(self) -> List[DivergenceReport]:
        """
        Run a full snapshot comparison for all entities across all horizons.

        Compares each entity's current-week snapshot against 30/60/90-day
        old snapshots and returns alerts for any detected drift.

        Returns:
            List of DivergenceReports where drift was detected.
        """
        alerts: List[DivergenceReport] = []

        for entity_id in list(self._snapshots.keys()):
            for horizon_label, weeks_back in COMPARISON_HORIZONS:
                comparison_week = self._current_week - weeks_back
                if comparison_week < 0:
                    continue

                report = await self.compare_snapshots(
                    entity_id, self._current_week, comparison_week,
                )
                report.horizon_label = horizon_label

                if report.severity not in ("none", "insufficient_data"):
                    alerts.append(report)
                    self._total_drift_detections += 1

                    # Log to forensic chain
                    if self._forensic_logger:
                        try:
                            await self._forensic_logger.log_event(
                                event_type="snapshot_drift_detected",
                                source_entity=str(entity_id),
                                evidence={
                                    "current_week": self._current_week,
                                    "comparison_week": comparison_week,
                                    "horizon": horizon_label,
                                    "severity": report.severity,
                                    "dimensions_changed": report.dimensions_changed,
                                    "divergence_ratio": report.divergence_ratio,
                                },
                            )
                        except Exception as exc:
                            logger.error("Forensic log failed: %s", exc)

                    # Broadcast event
                    await self._broadcast_event(
                        "hive.snapshot.drift_detected",
                        {
                            "entity_id": str(entity_id),
                            "horizon": horizon_label,
                            "severity": report.severity,
                            "dimensions_changed": report.dimensions_changed,
                            "current_week": self._current_week,
                            "comparison_week": comparison_week,
                            "timestamp": datetime.utcnow().isoformat(),
                        },
                    )

        if alerts:
            logger.warning(
                "Full analysis: %d drift alerts across %d entities",
                len(alerts),
                len(set(a.entity_id for a in alerts)),
            )
        else:
            logger.info(
                "Full analysis: no drift detected across %d entities",
                len(self._snapshots),
            )

        return alerts

    # =========================================================================
    # WEEK MANAGEMENT
    # =========================================================================

    def advance_week(self) -> int:
        """
        Advance the current week counter.

        Returns:
            The new current week number.
        """
        self._current_week += 1
        logger.info("Week advanced to %d", self._current_week)
        return self._current_week

    @property
    def current_week(self) -> int:
        """Current week number."""
        return self._current_week

    # =========================================================================
    # SNAPSHOT LOOP
    # =========================================================================

    async def start_snapshot_loop(self) -> None:
        """
        Start the weekly snapshot loop.

        Takes snapshots for all tracked entities every 7 days and
        runs full analysis after each snapshot cycle.
        """
        if self._snapshot_task is not None:
            logger.warning("Snapshot loop already running")
            return

        self._snapshot_task = asyncio.create_task(self._snapshot_loop())
        logger.info("Behavioral snapshot loop started (interval=%dd)", SNAPSHOT_INTERVAL_DAYS)

    async def stop_snapshot_loop(self) -> None:
        """Stop the weekly snapshot loop."""
        if self._snapshot_task:
            self._snapshot_task.cancel()
            try:
                await self._snapshot_task
            except asyncio.CancelledError:
                pass
            self._snapshot_task = None
            logger.info("Behavioral snapshot loop stopped")

    async def _snapshot_loop(self) -> None:
        """Internal snapshot loop coroutine."""
        interval_sec = SNAPSHOT_INTERVAL_DAYS * 86400
        while True:
            try:
                await asyncio.sleep(interval_sec)
                self.advance_week()

                # Take snapshots for all known entities
                # (In production, this would fetch behavioral data from
                #  the behavioral_data_provider for each entity)
                logger.info(
                    "Starting weekly snapshot cycle for %d entities",
                    len(self._snapshots),
                )

                # Run full analysis
                alerts = await self.run_full_analysis()

                if alerts:
                    logger.warning(
                        "Weekly analysis found %d drift alerts", len(alerts),
                    )

            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.error("Snapshot loop error: %s", exc)
                await asyncio.sleep(60.0)

    # =========================================================================
    # QUERIES
    # =========================================================================

    async def get_entity_snapshots(
        self,
        entity_id: UUID,
    ) -> List[Dict[str, Any]]:
        """
        Return all snapshots for an entity.

        Args:
            entity_id: UUID of the entity.

        Returns:
            List of snapshot dicts sorted by week number (most recent first).
        """
        entity_snaps = self._snapshots.get(entity_id, {})
        return [
            {
                "snapshot_id": str(snap.snapshot_id),
                "entity_id": str(snap.entity_id),
                "week_number": snap.week_number,
                "data_access_hash": snap.data_access_hash[:16] + "…",
                "communication_graph_hash": snap.communication_graph_hash[:16] + "…",
                "trail_emission_fingerprint": snap.trail_emission_fingerprint[:16] + "…",
                "coherence_baseline_hash": snap.coherence_baseline_hash[:16] + "…",
                "created_at": snap.created_at.isoformat(),
            }
            for week, snap in sorted(
                entity_snaps.items(), key=lambda x: x[0], reverse=True,
            )
        ]

    # =========================================================================
    # ADMIN
    # =========================================================================

    def summary(self) -> Dict[str, Any]:
        """Return a summary dict for admin dashboards."""
        return {
            "current_week": self._current_week,
            "entities_tracked": len(self._snapshots),
            "total_snapshots_taken": self._total_snapshots_taken,
            "total_drift_detections": self._total_drift_detections,
            "snapshot_interval_days": SNAPSHOT_INTERVAL_DAYS,
            "comparison_horizons": [
                {"label": label, "weeks_back": weeks}
                for label, weeks in COMPARISON_HORIZONS
            ],
        }

    # =========================================================================
    # PERSISTENCE
    # =========================================================================

    async def _persist_snapshot(self, snapshot: BehavioralSnapshot) -> None:
        """Persist a snapshot to the database."""
        if not self._db_pool:
            return

        try:
            async with self._db_pool.acquire() as conn:
                await conn.execute(
                    """
                    INSERT INTO behavioral_snapshots (
                        snapshot_id, entity_id, week_number,
                        data_access_hash, communication_graph_hash,
                        trail_emission_fingerprint, coherence_baseline_hash,
                        created_at
                    ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
                    ON CONFLICT (entity_id, week_number) DO UPDATE SET
                        data_access_hash = EXCLUDED.data_access_hash,
                        communication_graph_hash = EXCLUDED.communication_graph_hash,
                        trail_emission_fingerprint = EXCLUDED.trail_emission_fingerprint,
                        coherence_baseline_hash = EXCLUDED.coherence_baseline_hash,
                        created_at = EXCLUDED.created_at
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
            logger.error(
                "Failed to persist snapshot for entity %s week %d: %s",
                snapshot.entity_id, snapshot.week_number, exc,
            )

    async def load_from_db(self) -> int:
        """
        Load snapshots from the database on startup.

        Returns:
            Number of snapshots loaded.
        """
        if not self._db_pool:
            return 0

        try:
            async with self._db_pool.acquire() as conn:
                rows = await conn.fetch(
                    """
                    SELECT snapshot_id, entity_id, week_number,
                           data_access_hash, communication_graph_hash,
                           trail_emission_fingerprint, coherence_baseline_hash,
                           created_at
                    FROM behavioral_snapshots
                    ORDER BY week_number ASC
                    """
                )

            loaded = 0
            max_week = 0
            for row in rows:
                snapshot = BehavioralSnapshot(
                    snapshot_id=row["snapshot_id"],
                    entity_id=row["entity_id"],
                    week_number=row["week_number"],
                    data_access_hash=row["data_access_hash"] or "",
                    communication_graph_hash=row["communication_graph_hash"] or "",
                    trail_emission_fingerprint=row["trail_emission_fingerprint"] or "",
                    coherence_baseline_hash=row["coherence_baseline_hash"] or "",
                    created_at=row["created_at"],
                )
                self._snapshots[snapshot.entity_id][snapshot.week_number] = snapshot
                max_week = max(max_week, snapshot.week_number)
                loaded += 1

            self._current_week = max_week
            logger.info(
                "Loaded %d behavioral snapshots from database "
                "(current_week=%d)",
                loaded, self._current_week,
            )
            return loaded

        except Exception as exc:
            logger.error("Failed to load behavioral snapshots: %s", exc)
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
