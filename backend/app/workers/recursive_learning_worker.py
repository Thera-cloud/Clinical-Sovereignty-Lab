"""
HIVE DEFENSE PROTOCOL — Recursive Learning Worker (Phase 8E)
Model improvement worker for Projected Helix deployments.

Runs every 5 minutes.  For each active projection, triggers a deeper
model refinement pass using all accumulated interactions.  Tracks
accuracy progression and fires alerts when models reach high convergence
(>=0.95 accuracy).

Patent-Pending — Claims 53-56
© 2026 Clinical Sovereignty Lab. All rights reserved.
"""

from __future__ import annotations

import asyncio
import time
from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import UUID

import structlog

logger = structlog.get_logger("hive.recursive_learning")


# ---------------------------------------------------------------------------
# Tunables
# ---------------------------------------------------------------------------

# Default refinement cycle interval (seconds).
DEFAULT_INTERVAL: float = 300.0  # 5 minutes

# Accuracy threshold for high-convergence alerts.
HIGH_CONVERGENCE_ACCURACY: float = 0.95

# How often to persist accuracy history to the database (cycles).
PERSISTENCE_EVERY_N_CYCLES: int = 3


class RecursiveLearningWorker:
    """
    Background worker: model improvement for Projected Helix deployments.

    Responsibilities
    ----------------
    * Enumerate all active Projected Helix deployments that have a
      recursive projection engine.
    * For each deployment, trigger a deeper model refinement pass using
      the ``refine_model()`` method on the :class:`RecursiveProjection`.
    * Track model accuracy progression over time.
    * Alert when a model reaches high convergence (accuracy >= 0.95),
      indicating the mirror can anticipate attacker commands.
    * Persist accuracy history for forensic and audit purposes.

    Parameters
    ----------
    projection_registry : Any
        Service that manages live ``ProjectedHelix`` instances.
        Expected interface:
        - ``get_active_projections() -> list[dict]``
        - ``get_recursive_projection(deployment_id) -> RecursiveProjection``
    event_bus : Any, optional
        Hive event bus for publishing learning events.
    db_pool : Any, optional
        asyncpg connection pool for metrics and history persistence.
    interval : float
        Refinement cycle interval in seconds (default: 300.0 = 5 min).
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
        self._total_refinements: int = 0
        self._total_patterns_discovered: int = 0
        self._convergence_alerts_fired: int = 0

        # Accuracy history per deployment for trend analysis
        self._accuracy_history: Dict[str, List[Dict[str, Any]]] = {}

        # Track which deployments we've already alerted for convergence
        self._convergence_alerted: set = set()

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Start the recursive learning loop."""
        self._running = True
        self._task = asyncio.create_task(self._run_loop())
        logger.info("worker_started", worker=self.__class__.__name__)

    async def stop(self) -> None:
        """Gracefully stop the learning loop and do a final persist."""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

        # Best-effort final persistence
        try:
            await self._persist_accuracy_history()
        except Exception:
            pass

        logger.info(
            "worker_stopped",
            worker=self.__class__.__name__,
            total_cycles=self._total_cycles,
            total_refinements=self._total_refinements,
            total_patterns_discovered=self._total_patterns_discovered,
            convergence_alerts=self._convergence_alerts_fired,
        )

    # ------------------------------------------------------------------
    # Main loop
    # ------------------------------------------------------------------

    async def _run_loop(self) -> None:
        """Primary loop — refines models at the configured interval."""
        while self._running:
            cycle_start = time.monotonic()
            try:
                await self._refinement_cycle()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.error(
                    "recursive_learning_error",
                    error=str(exc),
                    exc_info=True,
                )

            elapsed = time.monotonic() - cycle_start
            sleep_time = max(0.0, self.interval - elapsed)
            await asyncio.sleep(sleep_time)

    # ------------------------------------------------------------------
    # Refinement cycle
    # ------------------------------------------------------------------

    async def _refinement_cycle(self) -> None:
        """
        Execute a single refinement pass over all active projections.

        For each projection:
        1. Retrieve its RecursiveProjection engine.
        2. Trigger ``refine_model()`` for deeper pattern analysis.
        3. Record accuracy progression.
        4. Fire convergence alert if threshold is reached for the first time.
        """
        projections = await self._get_active_projections()
        if not projections:
            self._total_cycles += 1
            return

        cycle_refinements: int = 0
        cycle_patterns: int = 0
        cycle_convergence_alerts: int = 0

        for proj in projections:
            deployment_id = proj.get("deployment_id") or proj.get("id")
            deployment_id_str = str(deployment_id)

            try:
                result = await self._refine_deployment(deployment_id, proj)

                if result and result.get("refined"):
                    cycle_refinements += 1
                    new_patterns = result.get("new_protocol_patterns", 0)
                    cycle_patterns += new_patterns

                    accuracy = result.get("accuracy", 0.0)

                    # Track accuracy history
                    self._record_accuracy(deployment_id_str, accuracy, result)

                    # Convergence alert (once per deployment)
                    if (
                        accuracy >= HIGH_CONVERGENCE_ACCURACY
                        and deployment_id_str not in self._convergence_alerted
                    ):
                        await self._fire_convergence_alert(
                            deployment_id, accuracy, result
                        )
                        self._convergence_alerted.add(deployment_id_str)
                        cycle_convergence_alerts += 1

            except Exception as exc:
                logger.error(
                    "deployment_refinement_failed",
                    deployment_id=deployment_id_str,
                    error=str(exc),
                    exc_info=True,
                )

        # Update cumulative metrics
        self._total_cycles += 1
        self._total_refinements += cycle_refinements
        self._total_patterns_discovered += cycle_patterns
        self._convergence_alerts_fired += cycle_convergence_alerts

        # Periodic persistence
        if self._total_cycles % PERSISTENCE_EVERY_N_CYCLES == 0:
            await self._persist_accuracy_history()

        # Persist cycle metrics
        await self._persist_cycle_metrics(
            refinements=cycle_refinements,
            patterns_discovered=cycle_patterns,
            convergence_alerts=cycle_convergence_alerts,
        )

        logger.info(
            "recursive_learning_cycle_complete",
            cycle_number=self._total_cycles,
            projections_processed=len(projections),
            refinements=cycle_refinements,
            patterns_discovered=cycle_patterns,
            convergence_alerts=cycle_convergence_alerts,
        )

    # ------------------------------------------------------------------
    # Individual deployment refinement
    # ------------------------------------------------------------------

    async def _refine_deployment(
        self,
        deployment_id: UUID,
        projection: Dict[str, Any],
    ) -> Optional[Dict[str, Any]]:
        """
        Trigger model refinement for a single deployment.

        Parameters
        ----------
        deployment_id : UUID
            The deployment to refine.
        projection : dict
            Projection state from the registry.

        Returns
        -------
        dict or None
            Refinement result from ``RecursiveProjection.refine_model()``.
        """
        # Get the RecursiveProjection instance
        recursive_proj = await self._get_recursive_projection(deployment_id)
        if recursive_proj is None:
            logger.debug(
                "no_recursive_projection",
                deployment_id=str(deployment_id),
            )
            return None

        # Trigger refinement
        result = await recursive_proj.refine_model()

        if result and result.get("refined"):
            logger.debug(
                "deployment_refined",
                deployment_id=str(deployment_id),
                accuracy=result.get("accuracy", 0.0),
                model_version=result.get("model_version", 0),
                interactions_analyzed=result.get("interactions_analyzed", 0),
                new_patterns=result.get("new_protocol_patterns", 0),
            )

        return result

    # ------------------------------------------------------------------
    # Projection retrieval
    # ------------------------------------------------------------------

    async def _get_active_projections(self) -> List[Dict[str, Any]]:
        """Retrieve all active Projected Helix deployments."""
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
                    SELECT deployment_id, status, mirror_accuracy,
                           interactions_mirrored, commands_intercepted,
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

    async def _get_recursive_projection(
        self,
        deployment_id: UUID,
    ) -> Any:
        """
        Retrieve the RecursiveProjection engine for a deployment.

        Parameters
        ----------
        deployment_id : UUID
            The deployment to get the engine for.

        Returns
        -------
        RecursiveProjection or None
        """
        if hasattr(self.projection_registry, "get_recursive_projection"):
            result = self.projection_registry.get_recursive_projection(
                deployment_id
            )
            if asyncio.iscoroutine(result):
                return await result
            return result
        return None

    # ------------------------------------------------------------------
    # Accuracy tracking
    # ------------------------------------------------------------------

    def _record_accuracy(
        self,
        deployment_id_str: str,
        accuracy: float,
        result: Dict[str, Any],
    ) -> None:
        """
        Record accuracy measurement for trend analysis.

        Parameters
        ----------
        deployment_id_str : str
            The deployment ID as a string.
        accuracy : float
            The current model accuracy.
        result : dict
            The full refinement result.
        """
        if deployment_id_str not in self._accuracy_history:
            self._accuracy_history[deployment_id_str] = []

        entry = {
            "accuracy": round(accuracy, 4),
            "model_version": result.get("model_version", 0),
            "interactions_analyzed": result.get("interactions_analyzed", 0),
            "total_protocol_patterns": result.get(
                "total_protocol_patterns", 0
            ),
            "temporal_patterns": result.get("temporal_patterns", 0),
            "cycle_number": self._total_cycles,
            "timestamp": datetime.utcnow().isoformat(),
        }
        self._accuracy_history[deployment_id_str].append(entry)

        # Cap history per deployment
        max_history = 1000
        if len(self._accuracy_history[deployment_id_str]) > max_history:
            self._accuracy_history[deployment_id_str] = (
                self._accuracy_history[deployment_id_str][-max_history:]
            )

    def get_accuracy_trend(
        self,
        deployment_id: UUID,
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        """
        Retrieve accuracy history for a deployment.

        Parameters
        ----------
        deployment_id : UUID
            The deployment to get the trend for.
        limit : int
            Maximum entries to return.

        Returns
        -------
        list[dict]
            Accuracy history entries, newest first.
        """
        history = self._accuracy_history.get(str(deployment_id), [])
        return list(reversed(history[-limit:]))

    # ------------------------------------------------------------------
    # Convergence alerts
    # ------------------------------------------------------------------

    async def _fire_convergence_alert(
        self,
        deployment_id: UUID,
        accuracy: float,
        result: Dict[str, Any],
    ) -> None:
        """
        Fire an alert when a model reaches high convergence.

        This is a significant event — the mirror can now anticipate
        attacker commands before they're sent.

        Parameters
        ----------
        deployment_id : UUID
            The converged deployment.
        accuracy : float
            The accuracy that triggered the alert.
        result : dict
            The refinement result.
        """
        await self._fire_event(
            topic="hive.projection.model_highly_converged",
            payload={
                "deployment_id": str(deployment_id),
                "accuracy": round(accuracy, 4),
                "model_version": result.get("model_version", 0),
                "interactions_analyzed": result.get(
                    "interactions_analyzed", 0
                ),
                "total_patterns": result.get("total_protocol_patterns", 0),
                "timestamp": datetime.utcnow().isoformat(),
                "significance": (
                    "Mirror can now anticipate attacker commands. "
                    "Prediction reliability is high."
                ),
            },
        )

        logger.warning(
            "MODEL HIGHLY CONVERGED: deployment=%s accuracy=%.4f "
            "version=%d — mirror can anticipate attacker commands",
            deployment_id,
            accuracy,
            result.get("model_version", 0),
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
                "learning_event_publish_failed",
                topic=topic,
                error=str(exc),
            )

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    async def _persist_accuracy_history(self) -> None:
        """
        Persist accuracy history to the database for all tracked deployments.
        """
        if not self.db_pool:
            return

        try:
            async with self.db_pool.acquire() as conn:
                for did_str, history in self._accuracy_history.items():
                    if not history:
                        continue
                    latest = history[-1]
                    await conn.execute(
                        """
                        INSERT INTO hive_projection_accuracy_history
                            (deployment_id, accuracy, model_version,
                             interactions_analyzed, cycle_number,
                             recorded_at)
                        VALUES ($1::uuid, $2, $3, $4, $5, NOW())
                        """,
                        did_str,
                        latest.get("accuracy", 0.0),
                        latest.get("model_version", 0),
                        latest.get("interactions_analyzed", 0),
                        latest.get("cycle_number", 0),
                    )
            logger.debug(
                "accuracy_history_persisted",
                deployments=len(self._accuracy_history),
                cycle=self._total_cycles,
            )
        except Exception as exc:
            logger.warning(
                "accuracy_history_persist_failed", error=str(exc)
            )

    async def _persist_cycle_metrics(
        self,
        refinements: int,
        patterns_discovered: int,
        convergence_alerts: int,
    ) -> None:
        """Write learning metrics to the database (best-effort)."""
        if not self.db_pool:
            return
        try:
            async with self.db_pool.acquire() as conn:
                await conn.execute(
                    """
                    INSERT INTO hive_recursive_learning_metrics
                        (cycle_number, refinements, patterns_discovered,
                         convergence_alerts, processed_at)
                    VALUES ($1, $2, $3, $4, NOW())
                    """,
                    self._total_cycles,
                    refinements,
                    patterns_discovered,
                    convergence_alerts,
                )
        except Exception as exc:
            logger.debug(
                "learning_metrics_persist_failed", error=str(exc)
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
            "total_refinements": self._total_refinements,
            "total_patterns_discovered": self._total_patterns_discovered,
            "convergence_alerts_fired": self._convergence_alerts_fired,
            "deployments_tracked": len(self._accuracy_history),
            "deployments_converged": len(self._convergence_alerted),
        }

    def __repr__(self) -> str:
        return (
            f"<RecursiveLearningWorker running={self._running} "
            f"cycles={self._total_cycles} "
            f"refinements={self._total_refinements} "
            f"interval={self.interval}s>"
        )
