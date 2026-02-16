"""
HIVE DEFENSE PROTOCOL — Trap Monitor Worker (Phase 8A)
Active management of InfiniteMirrorTrap instances.

Monitors all deployed traps, checks whether attackers are still engaging,
marks stale traps as disengaged, fires hive events, persists trap state,
and logs operational metrics.

Patent-Pending — Claims 30-56
© 2026 Clinical Sovereignty Lab. All rights reserved.
"""

from __future__ import annotations

import asyncio
import time
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional
from uuid import UUID

import structlog

logger = structlog.get_logger("hive.trap_monitor")


# ---------------------------------------------------------------------------
# Tunables
# ---------------------------------------------------------------------------

# If an attacker has not interacted with a trap for this long, consider them
# disengaged and mark the trap accordingly.
DISENGAGE_TIMEOUT = timedelta(hours=1)

# Default monitoring cycle interval (seconds).
DEFAULT_INTERVAL: float = 120.0

# How often to persist full trap state snapshots to the database (cycles).
PERSISTENCE_EVERY_N_CYCLES: int = 5


class TrapMonitorWorker:
    """Background worker: active monitoring of InfiniteMirrorTrap instances.

    Responsibilities
    ----------------
    * Enumerate all active trap instances from the trap registry.
    * For each trap, verify the attacker is still interacting (based on
      last interaction timestamp).
    * If an attacker has been silent for longer than ``DISENGAGE_TIMEOUT``,
      transition the trap to ``attacker_disengaged`` state and fire the
      ``hive.trap.attacker_disengaged`` event.
    * Track and log operational metrics: active traps, total interactions,
      longest running trap duration.
    * Periodically persist trap state snapshots to the database for
      forensic durability.

    Parameters
    ----------
    trap_registry : Any
        Service that manages live ``InfiniteMirrorTrap`` instances.
        Expected interface:
        - ``get_active_traps() -> list[dict]``
        - ``mark_disengaged(trap_id) -> None``
    event_bus : Any, optional
        Hive event bus for firing ``hive.trap.*`` events.
        Expected interface: ``publish(topic: str, payload: dict) -> None``
    db_pool : Any, optional
        asyncpg connection pool for state persistence and metrics.
    interval : float
        Monitoring cycle interval in seconds.
    """

    def __init__(
        self,
        trap_registry: Any,
        event_bus: Any = None,
        db_pool: Any = None,
        interval: float = DEFAULT_INTERVAL,
    ) -> None:
        self.trap_registry = trap_registry
        self.event_bus = event_bus
        self.db_pool = db_pool
        self.interval = interval

        self._task: Optional[asyncio.Task] = None
        self._running: bool = False

        # Cumulative metrics
        self._total_cycles: int = 0
        self._total_disengagements: int = 0
        self._total_interactions_observed: int = 0

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Start the trap monitoring loop."""
        self._running = True
        self._task = asyncio.create_task(self._run_loop())
        logger.info("worker_started", worker=self.__class__.__name__)

    async def stop(self) -> None:
        """Gracefully stop the monitoring loop and perform a final persist."""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

        # Best-effort final state persistence on shutdown
        try:
            await self._persist_trap_states()
        except Exception:
            pass

        logger.info(
            "worker_stopped",
            worker=self.__class__.__name__,
            total_cycles=self._total_cycles,
            total_disengagements=self._total_disengagements,
            total_interactions_observed=self._total_interactions_observed,
        )

    # ------------------------------------------------------------------
    # Main loop
    # ------------------------------------------------------------------

    async def _run_loop(self) -> None:
        """Primary loop — monitors traps at the configured interval."""
        while self._running:
            cycle_start = time.monotonic()
            try:
                await self._monitor_cycle()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.error(
                    "trap_monitor_error",
                    error=str(exc),
                    exc_info=True,
                )

            elapsed = time.monotonic() - cycle_start
            sleep_time = max(0.0, self.interval - elapsed)
            await asyncio.sleep(sleep_time)

    # ------------------------------------------------------------------
    # Monitor cycle
    # ------------------------------------------------------------------

    async def _monitor_cycle(self) -> None:
        """Execute a single monitoring pass over all active traps.

        For each trap the worker checks:
        1. Is the attacker still interacting? (last interaction within timeout)
        2. Trap health: is the containment shell stable?
        3. Accumulated metrics (interaction count, duration).

        Stale traps are transitioned and the ``hive.trap.attacker_disengaged``
        event is emitted.
        """
        traps = await self._get_active_traps()
        if not traps:
            self._total_cycles += 1
            return

        now = datetime.utcnow()
        active_count: int = 0
        cycle_interactions: int = 0
        longest_duration: float = 0.0
        disengagements_this_cycle: int = 0

        for trap in traps:
            trap_id: UUID = trap.get("trap_id") or trap.get("id")
            last_interaction: Optional[datetime] = trap.get("last_interaction_at")
            deployed_at: Optional[datetime] = trap.get("deployed_at")
            interaction_count: int = trap.get("interaction_count", 0)

            # --- Duration tracking ---
            if deployed_at:
                duration_sec = (now - deployed_at).total_seconds()
                longest_duration = max(longest_duration, duration_sec)

            cycle_interactions += interaction_count

            # --- Disengage check ---
            if self._is_disengaged(last_interaction, now):
                await self._handle_disengagement(trap_id, trap)
                disengagements_this_cycle += 1
                continue

            # --- Trap health check ---
            await self._check_trap_health(trap_id, trap)
            active_count += 1

        # --- Periodic persistence ---
        self._total_cycles += 1
        self._total_disengagements += disengagements_this_cycle
        self._total_interactions_observed += cycle_interactions

        if self._total_cycles % PERSISTENCE_EVERY_N_CYCLES == 0:
            await self._persist_trap_states()

        # --- Metrics persistence ---
        await self._persist_cycle_metrics(
            active_traps=active_count,
            total_interactions=cycle_interactions,
            longest_trap_duration_sec=longest_duration,
            disengagements=disengagements_this_cycle,
        )

        logger.info(
            "trap_monitor_cycle_complete",
            cycle_number=self._total_cycles,
            active_traps=active_count,
            total_interactions=cycle_interactions,
            longest_trap_duration_sec=round(longest_duration, 1),
            disengagements=disengagements_this_cycle,
        )

    # ------------------------------------------------------------------
    # Trap retrieval
    # ------------------------------------------------------------------

    async def _get_active_traps(self) -> List[Dict[str, Any]]:
        """Retrieve all currently active trap instances.

        Tries the trap registry first, falls back to DB.
        """
        if hasattr(self.trap_registry, "get_active_traps"):
            return await self.trap_registry.get_active_traps()

        if not self.db_pool:
            return []

        try:
            async with self.db_pool.acquire() as conn:
                rows = await conn.fetch(
                    """
                    SELECT trap_id, deployed_at, last_interaction_at,
                           interaction_count, status, attacker_profile_id,
                           containment_zone
                    FROM hive_infinite_mirror_traps
                    WHERE status = 'active'
                    ORDER BY deployed_at ASC
                    """
                )
                return [dict(r) for r in rows]
        except Exception as exc:
            logger.warning("trap_fetch_failed", error=str(exc))
            return []

    # ------------------------------------------------------------------
    # Disengage detection
    # ------------------------------------------------------------------

    @staticmethod
    def _is_disengaged(
        last_interaction: Optional[datetime],
        now: datetime,
    ) -> bool:
        """Return True if the attacker has been silent past the timeout.

        Parameters
        ----------
        last_interaction : datetime or None
            Timestamp of the last recorded attacker interaction.  If *None*,
            the trap has never seen an interaction — treat as disengaged.
        now : datetime
            Current UTC time.
        """
        if last_interaction is None:
            return True
        return (now - last_interaction) > DISENGAGE_TIMEOUT

    # ------------------------------------------------------------------
    # Disengagement handling
    # ------------------------------------------------------------------

    async def _handle_disengagement(
        self,
        trap_id: UUID,
        trap: Dict[str, Any],
    ) -> None:
        """Mark a trap as disengaged and fire the hive event.

        Parameters
        ----------
        trap_id : UUID
            Unique identifier of the trap.
        trap : dict
            Full trap state dictionary.
        """
        # 1. Mark disengaged in the registry
        if hasattr(self.trap_registry, "mark_disengaged"):
            try:
                await self.trap_registry.mark_disengaged(trap_id)
            except Exception as exc:
                logger.error(
                    "trap_mark_disengaged_failed",
                    trap_id=str(trap_id),
                    error=str(exc),
                )

        # 2. Update DB status
        if self.db_pool:
            try:
                async with self.db_pool.acquire() as conn:
                    await conn.execute(
                        """
                        UPDATE hive_infinite_mirror_traps
                        SET status = 'attacker_disengaged',
                            disengaged_at = NOW()
                        WHERE trap_id = $1
                        """,
                        trap_id,
                    )
            except Exception as exc:
                logger.warning(
                    "trap_db_disengage_failed",
                    trap_id=str(trap_id),
                    error=str(exc),
                )

        # 3. Fire hive event
        await self._fire_event(
            topic="hive.trap.attacker_disengaged",
            payload={
                "trap_id": str(trap_id),
                "attacker_profile_id": str(trap.get("attacker_profile_id", "")),
                "containment_zone": trap.get("containment_zone", ""),
                "interaction_count": trap.get("interaction_count", 0),
                "deployed_at": (
                    trap["deployed_at"].isoformat()
                    if trap.get("deployed_at")
                    else None
                ),
                "last_interaction_at": (
                    trap["last_interaction_at"].isoformat()
                    if trap.get("last_interaction_at")
                    else None
                ),
                "disengaged_at": datetime.utcnow().isoformat(),
            },
        )

        logger.warning(
            "trap_attacker_disengaged",
            trap_id=str(trap_id),
            attacker_profile_id=str(trap.get("attacker_profile_id", "")),
            interaction_count=trap.get("interaction_count", 0),
        )

    # ------------------------------------------------------------------
    # Trap health
    # ------------------------------------------------------------------

    async def _check_trap_health(
        self,
        trap_id: UUID,
        trap: Dict[str, Any],
    ) -> None:
        """Verify the containment shell of an active trap is still operational.

        Checks delegated to the trap registry's ``check_health()`` method when
        available; otherwise this is a no-op (the trap is assumed healthy).
        """
        if hasattr(self.trap_registry, "check_health"):
            try:
                health = await self.trap_registry.check_health(trap_id)
                if isinstance(health, dict) and not health.get("healthy", True):
                    logger.warning(
                        "trap_health_degraded",
                        trap_id=str(trap_id),
                        reason=health.get("reason", "unknown"),
                    )
            except Exception as exc:
                logger.error(
                    "trap_health_check_failed",
                    trap_id=str(trap_id),
                    error=str(exc),
                )

    # ------------------------------------------------------------------
    # Event bus
    # ------------------------------------------------------------------

    async def _fire_event(self, topic: str, payload: Dict[str, Any]) -> None:
        """Publish a hive event.  No-ops gracefully if no event bus is configured."""
        if not self.event_bus:
            return
        try:
            if asyncio.iscoroutinefunction(getattr(self.event_bus, "publish", None)):
                await self.event_bus.publish(topic, payload)
            elif hasattr(self.event_bus, "publish"):
                self.event_bus.publish(topic, payload)
        except Exception as exc:
            logger.error("trap_event_publish_failed", topic=topic, error=str(exc))

    # ------------------------------------------------------------------
    # State persistence
    # ------------------------------------------------------------------

    async def _persist_trap_states(self) -> None:
        """Snapshot all active trap states into the database.

        Called every ``PERSISTENCE_EVERY_N_CYCLES`` cycles and on worker shutdown.
        Existing snapshots are upserted by ``trap_id``.
        """
        if not self.db_pool:
            return

        traps = await self._get_active_traps()
        if not traps:
            return

        try:
            async with self.db_pool.acquire() as conn:
                for trap in traps:
                    trap_id = trap.get("trap_id") or trap.get("id")
                    await conn.execute(
                        """
                        INSERT INTO hive_trap_state_snapshots
                            (trap_id, interaction_count, status,
                             last_interaction_at, snapshot_at)
                        VALUES ($1, $2, $3, $4, NOW())
                        ON CONFLICT (trap_id)
                        DO UPDATE SET
                            interaction_count = EXCLUDED.interaction_count,
                            status = EXCLUDED.status,
                            last_interaction_at = EXCLUDED.last_interaction_at,
                            snapshot_at = NOW()
                        """,
                        trap_id,
                        trap.get("interaction_count", 0),
                        trap.get("status", "active"),
                        trap.get("last_interaction_at"),
                    )
            logger.debug(
                "trap_states_persisted",
                trap_count=len(traps),
                cycle=self._total_cycles,
            )
        except Exception as exc:
            logger.warning("trap_state_persist_failed", error=str(exc))

    # ------------------------------------------------------------------
    # Metrics persistence
    # ------------------------------------------------------------------

    async def _persist_cycle_metrics(
        self,
        active_traps: int,
        total_interactions: int,
        longest_trap_duration_sec: float,
        disengagements: int,
    ) -> None:
        """Write trap monitoring metrics to the database.

        Best-effort — a persistence failure never crashes the monitor loop.
        """
        if not self.db_pool:
            return
        try:
            async with self.db_pool.acquire() as conn:
                await conn.execute(
                    """
                    INSERT INTO hive_trap_monitor_metrics
                        (cycle_number, active_traps, total_interactions,
                         longest_trap_duration_sec, disengagements, monitored_at)
                    VALUES ($1, $2, $3, $4, $5, NOW())
                    """,
                    self._total_cycles,
                    active_traps,
                    total_interactions,
                    longest_trap_duration_sec,
                    disengagements,
                )
        except Exception as exc:
            logger.debug("trap_metrics_persist_failed", error=str(exc))
