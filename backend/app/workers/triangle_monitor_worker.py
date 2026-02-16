"""
HIVE DEFENSE PROTOCOL v3.1 — Triangle Monitor Worker (Phase 8D)
Background worker that monitors all active triangular mirror inversion
spaces for activity, engagement patterns, and lifecycle events.

Runs every 30 seconds and:
    1. Enumerates all active InvertedSpaces.
    2. Checks each space for recent activity (interactions).
    3. Identifies inactive spaces (attacker gave up / disengaged).
    4. Fires events on key milestones:
       - First interaction in a space.
       - 100th interaction milestone.
       - Attacker disengaged (no activity within timeout).
    5. Persists space state snapshots to the database.
    6. Logs operational metrics for the admin dashboard.

Patent-Pending — Claims 50-51
© 2026 Clinical Sovereignty Lab. All rights reserved.
"""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Set
from uuid import UUID

logger = logging.getLogger("hive.triangle_monitor_worker")


# =============================================================================
# TUNABLES
# =============================================================================

# Default monitoring interval (seconds)
DEFAULT_INTERVAL: float = 30.0

# If an attacker has not interacted for this duration, consider disengaged
DISENGAGE_TIMEOUT: timedelta = timedelta(minutes=30)

# Interaction milestones that trigger events
INTERACTION_MILESTONES: Set[int] = {1, 10, 50, 100, 500, 1000}

# How often to persist full state snapshots (every N cycles)
PERSIST_EVERY_N_CYCLES: int = 5


# =============================================================================
# TRIANGLE MONITOR WORKER
# =============================================================================

class TriangleMonitorWorker:
    """
    Background worker monitoring active triangular mirror inversion spaces.

    Responsibilities:
        - Detect attacker disengagement and deactivate stale spaces.
        - Fire hive events on key interaction milestones.
        - Persist space state for forensic durability.
        - Track operational metrics for admin visibility.

    Parameters
    ----------
    triangular_inversion : object
        The ``TriangularMirrorInversion`` service managing live spaces.
    inversion_forensic_logger : object, optional
        The ``InversionForensicLogger`` for accessing interaction data.
    event_bus : object, optional
        Hive event bus for publishing space lifecycle events.
    db_pool : object, optional
        asyncpg connection pool for state persistence.
    interval : float
        Monitoring cycle interval in seconds (default 30s).

    Usage
    -----
    ::

        worker = TriangleMonitorWorker(
            triangular_inversion=inversion_service,
            event_bus=bus,
        )
        await worker.start()
        # ... monitors continuously ...
        await worker.stop()
    """

    def __init__(
        self,
        triangular_inversion=None,
        inversion_forensic_logger=None,
        event_bus=None,
        db_pool=None,
        interval: float = DEFAULT_INTERVAL,
    ) -> None:
        self._inversion = triangular_inversion
        self._forensic_logger = inversion_forensic_logger
        self._event_bus = event_bus
        self._db_pool = db_pool
        self._interval: float = interval

        # Worker state
        self._task: Optional[asyncio.Task] = None
        self._running: bool = False

        # Tracking — which milestones have been fired for each space
        self._milestones_fired: Dict[UUID, Set[int]] = {}

        # Previous interaction counts (for detecting new activity)
        self._previous_counts: Dict[UUID, int] = {}

        # Metrics
        self._total_cycles: int = 0
        self._total_disengagements: int = 0
        self._total_milestones_fired: int = 0
        self._started_at: Optional[datetime] = None

    # ─── Lifecycle ───────────────────────────────────────────────────────

    async def start(self) -> None:
        """Start the triangle monitoring loop."""
        if self._running:
            logger.warning(
                ">>> [TRIANGLE_MONITOR] Already running — ignoring start()"
            )
            return

        self._running = True
        self._started_at = datetime.utcnow()
        self._task = asyncio.create_task(
            self._run_loop(),
            name="triangle_monitor_worker",
        )
        logger.info(
            ">>> [TRIANGLE_MONITOR] Started — interval=%.0fs",
            self._interval,
        )

    async def stop(self) -> None:
        """Gracefully stop the monitoring loop."""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

        # Final persist
        await self._persist_all_states()

        logger.info(
            ">>> [TRIANGLE_MONITOR] Stopped — %d cycles, "
            "%d disengagements, %d milestones",
            self._total_cycles,
            self._total_disengagements,
            self._total_milestones_fired,
        )

    # ─── Main Loop ───────────────────────────────────────────────────────

    async def _run_loop(self) -> None:
        """Primary monitoring loop — runs at the configured interval."""
        while self._running:
            cycle_start = time.monotonic()

            try:
                await self._monitor_cycle()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.error(
                    ">>> [TRIANGLE_MONITOR] Cycle error: %s",
                    exc,
                    exc_info=True,
                )

            elapsed = time.monotonic() - cycle_start
            sleep_time = max(0.0, self._interval - elapsed)

            try:
                await asyncio.sleep(sleep_time)
            except asyncio.CancelledError:
                raise

    # ─── Monitor Cycle ───────────────────────────────────────────────────

    async def _monitor_cycle(self) -> None:
        """
        Execute a single monitoring pass over all active inversion spaces.

        Steps:
            1. Get all active spaces.
            2. For each space, check for activity and milestones.
            3. Detect disengaged spaces.
            4. Periodic persistence.
            5. Log cycle metrics.
        """
        if not self._inversion:
            self._total_cycles += 1
            return

        active_spaces = self._inversion.get_active_spaces()
        if not active_spaces:
            self._total_cycles += 1
            return

        now = datetime.utcnow()
        active_count: int = 0
        cycle_interactions: int = 0
        disengagements: int = 0

        for space in active_spaces:
            space_id = space.space_id
            interaction_count = space.interaction_count
            cycle_interactions += interaction_count

            # Check for new activity since last cycle
            prev_count = self._previous_counts.get(space_id, 0)
            new_interactions = interaction_count - prev_count
            self._previous_counts[space_id] = interaction_count

            # Check milestones
            await self._check_milestones(space_id, interaction_count)

            # Check for disengagement
            is_inactive = await self._check_disengagement(space, now)
            if is_inactive:
                disengagements += 1
                await self._handle_disengagement(space)
                continue

            active_count += 1

        # Update metrics
        self._total_cycles += 1
        self._total_disengagements += disengagements

        # Periodic persistence
        if self._total_cycles % PERSIST_EVERY_N_CYCLES == 0:
            await self._persist_all_states()

        # Persist cycle metrics
        await self._persist_cycle_metrics(
            active_spaces=active_count,
            total_interactions=cycle_interactions,
            disengagements=disengagements,
        )

        logger.info(
            ">>> [TRIANGLE_MONITOR] Cycle #%d — %d active spaces, "
            "%d total interactions, %d disengagements",
            self._total_cycles,
            active_count,
            cycle_interactions,
            disengagements,
        )

    # ─── Milestone Detection ─────────────────────────────────────────────

    async def _check_milestones(
        self,
        space_id: UUID,
        interaction_count: int,
    ) -> None:
        """
        Check and fire milestone events for a space.

        Milestones: 1st interaction, 10th, 50th, 100th, 500th, 1000th.
        """
        if space_id not in self._milestones_fired:
            self._milestones_fired[space_id] = set()

        fired = self._milestones_fired[space_id]

        for milestone in INTERACTION_MILESTONES:
            if interaction_count >= milestone and milestone not in fired:
                fired.add(milestone)
                self._total_milestones_fired += 1

                # Determine event topic based on milestone
                if milestone == 1:
                    topic = "hive.triangle.first_interaction"
                elif milestone >= 100:
                    topic = "hive.triangle.high_engagement"
                else:
                    topic = "hive.triangle.milestone"

                await self._fire_event(
                    topic=topic,
                    payload={
                        "space_id": str(space_id),
                        "milestone": milestone,
                        "interaction_count": interaction_count,
                        "timestamp": datetime.utcnow().isoformat(),
                    },
                )

                logger.info(
                    ">>> [TRIANGLE_MONITOR] Milestone: space %s reached "
                    "%d interactions",
                    space_id,
                    milestone,
                )

    # ─── Disengagement Detection ─────────────────────────────────────────

    async def _check_disengagement(
        self,
        space: Any,
        now: datetime,
    ) -> bool:
        """
        Check if an attacker has disengaged from an inversion space.

        Uses the interaction history from the forensic logger or
        falls back to the space's entry time.
        """
        # Try to get last interaction time from forensic logger
        last_interaction_time: Optional[datetime] = None

        if self._forensic_logger:
            try:
                chains = getattr(
                    self._forensic_logger, "_space_chains", {}
                )
                chain = chains.get(space.space_id, [])
                if chain:
                    last_interaction_time = chain[-1].timestamp
            except Exception:
                pass

        if last_interaction_time is None:
            # No interactions at all — use entry time
            last_interaction_time = space.entry_time

        # Check if timeout has elapsed
        return (now - last_interaction_time) > DISENGAGE_TIMEOUT

    async def _handle_disengagement(self, space: Any) -> None:
        """
        Handle an attacker disengagement — deactivate space and fire event.
        """
        space_id = space.space_id

        # Deactivate via the inversion service
        if self._inversion:
            try:
                await self._inversion.deactivate_space(space_id)
            except Exception as exc:
                logger.error(
                    ">>> [TRIANGLE_MONITOR] Deactivation failed for %s: %s",
                    space_id,
                    exc,
                )

        # Get final report if available
        report: Optional[Dict[str, Any]] = None
        if self._forensic_logger:
            try:
                report = await self._forensic_logger.get_space_report(space_id)
            except Exception:
                pass

        # Fire disengagement event
        await self._fire_event(
            topic="hive.triangle.attacker_disengaged",
            payload={
                "space_id": str(space_id),
                "entry_gate": space.entry_gate,
                "total_interactions": space.interaction_count,
                "tripwires_triggered": space.tripwires_triggered,
                "entry_time": space.entry_time.isoformat(),
                "disengaged_at": datetime.utcnow().isoformat(),
                "forensic_summary": (
                    {
                        "chain_integrity": report.get("chain_integrity"),
                        "duration_seconds": report.get("duration_seconds"),
                        "behavioral_strategies": (
                            report.get("behavioral_model", {})
                            .get("detected_strategies", [])
                            if report.get("behavioral_model")
                            else []
                        ),
                    }
                    if report
                    else None
                ),
            },
        )

        logger.warning(
            ">>> [TRIANGLE_MONITOR] Attacker disengaged from space %s — "
            "%d interactions, %d tripwires",
            space_id,
            space.interaction_count,
            space.tripwires_triggered,
        )

        # Clean up tracking
        self._milestones_fired.pop(space_id, None)
        self._previous_counts.pop(space_id, None)

    # ─── Event Bus ───────────────────────────────────────────────────────

    async def _fire_event(
        self, topic: str, payload: Dict[str, Any]
    ) -> None:
        """Publish a hive event (no-ops gracefully)."""
        if not self._event_bus:
            return
        try:
            if asyncio.iscoroutinefunction(
                getattr(self._event_bus, "publish", None)
            ):
                await self._event_bus.publish(topic, payload)
            elif hasattr(self._event_bus, "publish"):
                self._event_bus.publish(topic, payload)
        except Exception as exc:
            logger.error(
                ">>> [TRIANGLE_MONITOR] Event publish failed: topic=%s %s",
                topic,
                exc,
            )

    # ─── State Persistence ───────────────────────────────────────────────

    async def _persist_all_states(self) -> None:
        """
        Persist all active space states to the database.

        Delegates to the TriangularMirrorInversion service's internal
        persistence where available.
        """
        if not self._inversion or not self._db_pool:
            return

        try:
            active = self._inversion.get_active_spaces()
            for space in active:
                await self._persist_space_snapshot(space)

            logger.debug(
                ">>> [TRIANGLE_MONITOR] Persisted %d space states",
                len(active),
            )
        except Exception as exc:
            logger.warning(
                ">>> [TRIANGLE_MONITOR] State persistence failed: %s", exc
            )

    async def _persist_space_snapshot(self, space: Any) -> None:
        """Persist a single space snapshot to the database."""
        if not self._db_pool:
            return

        try:
            import json
            async with self._db_pool.acquire() as conn:
                await conn.execute(
                    """
                    INSERT INTO hive_triangle_monitor_snapshots
                        (space_id, interaction_count, tripwires_triggered,
                         is_active, entry_gate, snapshot_at)
                    VALUES ($1, $2, $3, $4, $5, NOW())
                    ON CONFLICT (space_id)
                    DO UPDATE SET
                        interaction_count = EXCLUDED.interaction_count,
                        tripwires_triggered = EXCLUDED.tripwires_triggered,
                        is_active = EXCLUDED.is_active,
                        snapshot_at = NOW()
                    """,
                    space.space_id,
                    space.interaction_count,
                    space.tripwires_triggered,
                    space.is_active,
                    space.entry_gate,
                )
        except Exception as exc:
            logger.debug(
                ">>> [TRIANGLE_MONITOR] Snapshot persist failed: %s", exc
            )

    # ─── Metrics Persistence ─────────────────────────────────────────────

    async def _persist_cycle_metrics(
        self,
        active_spaces: int,
        total_interactions: int,
        disengagements: int,
    ) -> None:
        """Write monitoring metrics to the database (best effort)."""
        if not self._db_pool:
            return

        try:
            async with self._db_pool.acquire() as conn:
                await conn.execute(
                    """
                    INSERT INTO hive_triangle_monitor_metrics
                        (cycle_number, active_spaces, total_interactions,
                         disengagements, monitored_at)
                    VALUES ($1, $2, $3, $4, NOW())
                    """,
                    self._total_cycles,
                    active_spaces,
                    total_interactions,
                    disengagements,
                )
        except Exception as exc:
            logger.debug(
                ">>> [TRIANGLE_MONITOR] Metrics persist failed: %s", exc
            )

    # ─── Diagnostics ─────────────────────────────────────────────────────

    @property
    def stats(self) -> Dict[str, Any]:
        """Worker diagnostic metrics."""
        uptime = None
        if self._started_at:
            uptime = (datetime.utcnow() - self._started_at).total_seconds()

        return {
            "running": self._running,
            "total_cycles": self._total_cycles,
            "total_disengagements": self._total_disengagements,
            "total_milestones_fired": self._total_milestones_fired,
            "interval_sec": self._interval,
            "tracked_spaces": len(self._previous_counts),
            "uptime_seconds": round(uptime, 1) if uptime else None,
        }

    def __repr__(self) -> str:
        return (
            f"<TriangleMonitorWorker "
            f"running={self._running} "
            f"cycles={self._total_cycles} "
            f"disengagements={self._total_disengagements}>"
        )
