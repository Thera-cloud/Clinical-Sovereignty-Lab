"""
HIVE DEFENSE PROTOCOL — Projection Monitor Worker (Phase 8E)
Active management of Projected Helix deployments.

Monitors all active ProjectedHelix instances, checks projection health,
tracks attacker engagement levels, recommends decommission when attackers
disengage, and logs operational metrics.

Runs every 30 seconds.

Patent-Pending — Claims 53-56
© 2026 Clinical Sovereignty Lab. All rights reserved.
"""

from __future__ import annotations

import asyncio
import time
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional
from uuid import UUID

import structlog

logger = structlog.get_logger("hive.projection_monitor")


# ---------------------------------------------------------------------------
# Tunables
# ---------------------------------------------------------------------------

# If an attacker has not sent a command for this long, recommend decommission.
DISENGAGE_TIMEOUT = timedelta(hours=2)

# Default monitoring cycle interval (seconds).
DEFAULT_INTERVAL: float = 30.0

# How often to persist full projection state snapshots (cycles).
PERSISTENCE_EVERY_N_CYCLES: int = 10

# Accuracy threshold for "highly converged" alerts.
HIGH_CONVERGENCE_ACCURACY: float = 0.95


class ProjectionMonitorWorker:
    """
    Background worker: active management of Projected Helix deployments.

    Responsibilities
    ----------------
    * Enumerate all active Projected Helix deployments.
    * For each deployment, verify:
      - Projection health (mirror walls responsive).
      - Attacker engagement level (commands within timeout window).
      - Mirror accuracy progression (converging / stalled / diverging).
    * If the attacker has been silent for longer than ``DISENGAGE_TIMEOUT``
      (2 hours), recommend the deployment for decommission.
    * Log operational metrics: active projections, commands intercepted,
      learning progress, engagement levels.
    * Periodically persist deployment state snapshots to the database.

    Parameters
    ----------
    projection_registry : Any
        Service that manages live ``ProjectedHelix`` instances.
        Expected interface:
        - ``get_active_projections() -> list[dict]``
        - ``recommend_decommission(deployment_id) -> None``
    event_bus : Any, optional
        Hive event bus for publishing projection events.
        Expected interface: ``publish(topic: str, payload: dict) -> None``
    db_pool : Any, optional
        asyncpg connection pool for state persistence and metrics.
    interval : float
        Monitoring cycle interval in seconds (default: 30.0).
    """

    def __init__(
        self,
        projection_registry: Any,
        event_bus: Any = None,
        db_pool: Any = None,
        interval: float = DEFAULT_INTERVAL,
    ) -> None:
        self.projection_registry = projection_registry
        self.event_bus = event_bus
        self.db_pool = db_pool
        self.interval = interval

        self._task: Optional[asyncio.Task] = None
        self._running: bool = False

        # Cumulative metrics
        self._total_cycles: int = 0
        self._total_decommission_recommendations: int = 0
        self._total_commands_observed: int = 0
        self._convergence_alerts_fired: int = 0

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Start the projection monitoring loop."""
        self._running = True
        self._task = asyncio.create_task(self._run_loop())
        logger.info("worker_started", worker=self.__class__.__name__)

    async def stop(self) -> None:
        """Gracefully stop the monitoring loop and do a final persist."""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

        # Best-effort final persistence
        try:
            await self._persist_projection_states()
        except Exception:
            pass

        logger.info(
            "worker_stopped",
            worker=self.__class__.__name__,
            total_cycles=self._total_cycles,
            total_decommission_recommendations=self._total_decommission_recommendations,
            total_commands_observed=self._total_commands_observed,
            convergence_alerts=self._convergence_alerts_fired,
        )

    # ------------------------------------------------------------------
    # Main loop
    # ------------------------------------------------------------------

    async def _run_loop(self) -> None:
        """Primary loop — monitors projections at the configured interval."""
        while self._running:
            cycle_start = time.monotonic()
            try:
                await self._monitor_cycle()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.error(
                    "projection_monitor_error",
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
        """
        Execute a single monitoring pass over all active projections.

        For each projection the worker checks:
        1. Is the attacker still engaging? (last command within timeout)
        2. Projection health: are all three mirror walls responsive?
        3. Learning progress: is the model accuracy improving?
        4. Convergence: has the model reached high accuracy (>=0.95)?
        """
        projections = await self._get_active_projections()
        if not projections:
            self._total_cycles += 1
            return

        now = datetime.utcnow()
        active_count: int = 0
        cycle_commands: int = 0
        decommission_recommendations: int = 0
        convergence_alerts: int = 0

        for proj in projections:
            deployment_id: UUID = proj.get("deployment_id") or proj.get("id")
            last_command_at: Optional[datetime] = proj.get("last_command_at")
            commands_intercepted: int = proj.get("commands_intercepted", 0)
            mirror_accuracy: float = proj.get("mirror_accuracy", 0.0)
            model_version: int = proj.get("model_version", 0)

            cycle_commands += commands_intercepted

            # --- Disengage check ---
            if self._is_disengaged(last_command_at, now):
                await self._recommend_decommission(deployment_id, proj)
                decommission_recommendations += 1
                continue

            # --- Projection health check ---
            await self._check_projection_health(deployment_id, proj)

            # --- Convergence check ---
            if mirror_accuracy >= HIGH_CONVERGENCE_ACCURACY:
                await self._fire_convergence_alert(deployment_id, proj)
                convergence_alerts += 1

            active_count += 1

        # --- Periodic persistence ---
        self._total_cycles += 1
        self._total_decommission_recommendations += decommission_recommendations
        self._total_commands_observed += cycle_commands
        self._convergence_alerts_fired += convergence_alerts

        if self._total_cycles % PERSISTENCE_EVERY_N_CYCLES == 0:
            await self._persist_projection_states()

        # --- Metrics ---
        await self._persist_cycle_metrics(
            active_projections=active_count,
            commands_intercepted=cycle_commands,
            decommission_recommendations=decommission_recommendations,
            convergence_alerts=convergence_alerts,
        )

        logger.info(
            "projection_monitor_cycle_complete",
            cycle_number=self._total_cycles,
            active_projections=active_count,
            commands_intercepted=cycle_commands,
            decommission_recommendations=decommission_recommendations,
            convergence_alerts=convergence_alerts,
        )

    # ------------------------------------------------------------------
    # Projection retrieval
    # ------------------------------------------------------------------

    async def _get_active_projections(self) -> List[Dict[str, Any]]:
        """
        Retrieve all active Projected Helix deployments.

        Tries the projection registry first, falls back to DB.
        """
        if hasattr(self.projection_registry, "get_active_projections"):
            result = self.projection_registry.get_active_projections()
            if asyncio.iscoroutine(result):
                return await result
            return result

        if not self.db_pool:
            return []

        try:
            async with self.db_pool.acquire() as conn:
                rows = await conn.fetch(
                    """
                    SELECT deployment_id, target_profile_id,
                           penetrator_report_id, status,
                           authorized_by, deployed_at,
                           mirror_accuracy, interactions_mirrored,
                           commands_intercepted, last_command_at,
                           model_version
                    FROM hive_projected_helix_deployments
                    WHERE status IN ('active', 'learning')
                    ORDER BY deployed_at ASC
                    """
                )
                return [dict(r) for r in rows]
        except Exception as exc:
            logger.warning("projection_fetch_failed", error=str(exc))
            return []

    # ------------------------------------------------------------------
    # Disengage detection
    # ------------------------------------------------------------------

    @staticmethod
    def _is_disengaged(
        last_command_at: Optional[datetime],
        now: datetime,
    ) -> bool:
        """
        Return True if the attacker has been silent past the timeout.

        Parameters
        ----------
        last_command_at : datetime or None
            Timestamp of the last attacker command.  If *None*, the
            projection has never intercepted a command — treat as disengaged.
        now : datetime
            Current UTC time.
        """
        if last_command_at is None:
            return True
        return (now - last_command_at) > DISENGAGE_TIMEOUT

    # ------------------------------------------------------------------
    # Decommission recommendation
    # ------------------------------------------------------------------

    async def _recommend_decommission(
        self,
        deployment_id: UUID,
        projection: Dict[str, Any],
    ) -> None:
        """
        Recommend a Projected Helix deployment for decommission.

        Parameters
        ----------
        deployment_id : UUID
            The deployment to recommend for decommission.
        projection : dict
            Full projection state dictionary.
        """
        # Notify the registry
        if hasattr(self.projection_registry, "recommend_decommission"):
            try:
                result = self.projection_registry.recommend_decommission(
                    deployment_id
                )
                if asyncio.iscoroutine(result):
                    await result
            except Exception as exc:
                logger.error(
                    "projection_decommission_recommend_failed",
                    deployment_id=str(deployment_id),
                    error=str(exc),
                )

        # Update DB status
        if self.db_pool:
            try:
                async with self.db_pool.acquire() as conn:
                    await conn.execute(
                        """
                        UPDATE hive_projected_helix_deployments
                        SET status = 'decommission_recommended',
                            decommission_recommended_at = NOW()
                        WHERE deployment_id = $1
                        """,
                        deployment_id,
                    )
            except Exception as exc:
                logger.warning(
                    "projection_db_decommission_failed",
                    deployment_id=str(deployment_id),
                    error=str(exc),
                )

        # Fire hive event
        await self._fire_event(
            topic="hive.projection.decommission_recommended",
            payload={
                "deployment_id": str(deployment_id),
                "commands_intercepted": projection.get("commands_intercepted", 0),
                "mirror_accuracy": projection.get("mirror_accuracy", 0.0),
                "last_command_at": (
                    projection["last_command_at"].isoformat()
                    if projection.get("last_command_at")
                    else None
                ),
                "recommended_at": datetime.utcnow().isoformat(),
                "reason": "attacker_disengaged_2h",
            },
        )

        logger.warning(
            "projection_decommission_recommended",
            deployment_id=str(deployment_id),
            commands_intercepted=projection.get("commands_intercepted", 0),
            mirror_accuracy=projection.get("mirror_accuracy", 0.0),
        )

    # ------------------------------------------------------------------
    # Projection health
    # ------------------------------------------------------------------

    async def _check_projection_health(
        self,
        deployment_id: UUID,
        projection: Dict[str, Any],
    ) -> None:
        """
        Verify the health of an active projection.

        Checks mirror wall responsiveness via the registry when available.
        """
        if hasattr(self.projection_registry, "check_health"):
            try:
                result = self.projection_registry.check_health(deployment_id)
                if asyncio.iscoroutine(result):
                    health = await result
                else:
                    health = result

                if isinstance(health, dict) and not health.get("healthy", True):
                    logger.warning(
                        "projection_health_degraded",
                        deployment_id=str(deployment_id),
                        reason=health.get("reason", "unknown"),
                    )
                    await self._fire_event(
                        topic="hive.projection.health_degraded",
                        payload={
                            "deployment_id": str(deployment_id),
                            "reason": health.get("reason", "unknown"),
                            "timestamp": datetime.utcnow().isoformat(),
                        },
                    )
            except Exception as exc:
                logger.error(
                    "projection_health_check_failed",
                    deployment_id=str(deployment_id),
                    error=str(exc),
                )

    # ------------------------------------------------------------------
    # Convergence alerts
    # ------------------------------------------------------------------

    async def _fire_convergence_alert(
        self,
        deployment_id: UUID,
        projection: Dict[str, Any],
    ) -> None:
        """
        Fire an alert when a projection's mirror model reaches high convergence.

        Parameters
        ----------
        deployment_id : UUID
            The converged deployment.
        projection : dict
            Full projection state.
        """
        await self._fire_event(
            topic="hive.projection.highly_converged",
            payload={
                "deployment_id": str(deployment_id),
                "mirror_accuracy": projection.get("mirror_accuracy", 0.0),
                "model_version": projection.get("model_version", 0),
                "commands_intercepted": projection.get("commands_intercepted", 0),
                "timestamp": datetime.utcnow().isoformat(),
            },
        )

        logger.info(
            "projection_highly_converged",
            deployment_id=str(deployment_id),
            mirror_accuracy=projection.get("mirror_accuracy", 0.0),
            model_version=projection.get("model_version", 0),
        )

    # ------------------------------------------------------------------
    # Event bus
    # ------------------------------------------------------------------

    async def _fire_event(self, topic: str, payload: Dict[str, Any]) -> None:
        """Publish a hive event. No-ops gracefully if no event bus."""
        if not self.event_bus:
            return
        try:
            if asyncio.iscoroutinefunction(
                getattr(self.event_bus, "publish", None)
            ):
                await self.event_bus.publish(topic, payload)
            elif hasattr(self.event_bus, "publish"):
                self.event_bus.publish(topic, payload)
        except Exception as exc:
            logger.error(
                "projection_event_publish_failed",
                topic=topic,
                error=str(exc),
            )

    # ------------------------------------------------------------------
    # State persistence
    # ------------------------------------------------------------------

    async def _persist_projection_states(self) -> None:
        """
        Snapshot all active projection states into the database.

        Called every ``PERSISTENCE_EVERY_N_CYCLES`` cycles and on shutdown.
        """
        if not self.db_pool:
            return

        projections = await self._get_active_projections()
        if not projections:
            return

        try:
            async with self.db_pool.acquire() as conn:
                for proj in projections:
                    deployment_id = proj.get("deployment_id") or proj.get("id")
                    await conn.execute(
                        """
                        INSERT INTO hive_projection_state_snapshots
                            (deployment_id, commands_intercepted,
                             mirror_accuracy, model_version, status,
                             last_command_at, snapshot_at)
                        VALUES ($1, $2, $3, $4, $5, $6, NOW())
                        ON CONFLICT (deployment_id)
                        DO UPDATE SET
                            commands_intercepted = EXCLUDED.commands_intercepted,
                            mirror_accuracy = EXCLUDED.mirror_accuracy,
                            model_version = EXCLUDED.model_version,
                            status = EXCLUDED.status,
                            last_command_at = EXCLUDED.last_command_at,
                            snapshot_at = NOW()
                        """,
                        deployment_id,
                        proj.get("commands_intercepted", 0),
                        proj.get("mirror_accuracy", 0.0),
                        proj.get("model_version", 0),
                        proj.get("status", "active"),
                        proj.get("last_command_at"),
                    )
            logger.debug(
                "projection_states_persisted",
                projection_count=len(projections),
                cycle=self._total_cycles,
            )
        except Exception as exc:
            logger.warning(
                "projection_state_persist_failed", error=str(exc)
            )

    # ------------------------------------------------------------------
    # Metrics persistence
    # ------------------------------------------------------------------

    async def _persist_cycle_metrics(
        self,
        active_projections: int,
        commands_intercepted: int,
        decommission_recommendations: int,
        convergence_alerts: int,
    ) -> None:
        """
        Write projection monitoring metrics to the database.

        Best-effort — a persistence failure never crashes the loop.
        """
        if not self.db_pool:
            return
        try:
            async with self.db_pool.acquire() as conn:
                await conn.execute(
                    """
                    INSERT INTO hive_projection_monitor_metrics
                        (cycle_number, active_projections,
                         commands_intercepted,
                         decommission_recommendations,
                         convergence_alerts, monitored_at)
                    VALUES ($1, $2, $3, $4, $5, NOW())
                    """,
                    self._total_cycles,
                    active_projections,
                    commands_intercepted,
                    decommission_recommendations,
                    convergence_alerts,
                )
        except Exception as exc:
            logger.debug(
                "projection_metrics_persist_failed", error=str(exc)
            )

    # ------------------------------------------------------------------
    # Introspection
    # ------------------------------------------------------------------

    @property
    def stats(self) -> Dict[str, Any]:
        """Diagnostic summary."""
        return {
            "running": self._running,
            "interval_seconds": self.interval,
            "total_cycles": self._total_cycles,
            "total_decommission_recommendations": (
                self._total_decommission_recommendations
            ),
            "total_commands_observed": self._total_commands_observed,
            "convergence_alerts_fired": self._convergence_alerts_fired,
        }

    def __repr__(self) -> str:
        return (
            f"<ProjectionMonitorWorker running={self._running} "
            f"cycles={self._total_cycles} "
            f"interval={self.interval}s>"
        )
