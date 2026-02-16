"""
HIVE DEFENSE PROTOCOL — Heartbeat Monitor Worker (Phase 8A)
Continuous heartbeat verification across all registered hive entities.

Runs at a configurable interval (default 60s, adjusts with DEFCON level)
and verifies pulse continuity for every entity in the HeartbeatRegistry.
Silent or anomalous entities are escalated to the CuriosityProtocol for
graduated evaluation.

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

logger = structlog.get_logger("hive.heartbeat_monitor")


# ---------------------------------------------------------------------------
# DEFCON → interval mapping (seconds)
# ---------------------------------------------------------------------------
DEFCON_INTERVAL_MAP: Dict[int, float] = {
    5: 60.0,   # PEACE — standard 60s sweep
    4: 45.0,   # ELEVATED — tighter monitoring
    3: 30.0,   # SUBSTANTIAL — aggressive checks
    2: 15.0,   # SEVERE — near real-time
    1: 5.0,    # CRITICAL — maximum vigilance
}

# An entity is "silent" if no heartbeat arrives within this multiplier of the
# expected interval.
SILENCE_MULTIPLIER: float = 2.0


class HeartbeatMonitorWorker:
    """Background worker: continuous heartbeat verification for all hive entities.

    Responsibilities
    ----------------
    * Iterate over all entities registered in the ``HeartbeatRegistry``.
    * Flag entities whose last pulse exceeds ``SILENCE_MULTIPLIER × expected_interval``.
    * Invoke ``CuriosityProtocol.evaluate_entity()`` for silent or anomalous pulses.
    * Emit structured metrics after every sweep cycle.
    * Dynamically adjust sweep interval based on the current DEFCON level.

    Parameters
    ----------
    heartbeat_registry : Any
        Reference to the ``HeartbeatRegistry`` service that tracks entity pulses.
    curiosity_protocol : Any
        Reference to the ``CuriosityProtocol`` service for anomaly escalation.
    db_pool : Any, optional
        asyncpg connection pool for persistence and metric storage.
    base_interval : float
        Default sweep interval in seconds (overridden by DEFCON mapping).
    defcon_provider : callable, optional
        Async callable that returns the current ``DefconLevel`` value (int 1-5).
        If *None*, the worker uses ``base_interval`` without adjustment.
    """

    def __init__(
        self,
        heartbeat_registry: Any,
        curiosity_protocol: Any,
        db_pool: Any = None,
        base_interval: float = 60.0,
        defcon_provider: Optional[Any] = None,
    ) -> None:
        self.heartbeat_registry = heartbeat_registry
        self.curiosity_protocol = curiosity_protocol
        self.db_pool = db_pool
        self.base_interval = base_interval
        self.defcon_provider = defcon_provider

        self._task: Optional[asyncio.Task] = None
        self._running: bool = False

        # Cumulative metrics
        self._total_sweeps: int = 0
        self._total_checked: int = 0
        self._total_silent: int = 0
        self._total_anomalous: int = 0

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Start the heartbeat monitoring loop."""
        self._running = True
        self._task = asyncio.create_task(self._run_loop())
        logger.info("worker_started", worker=self.__class__.__name__)

    async def stop(self) -> None:
        """Gracefully stop the monitoring loop."""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info(
            "worker_stopped",
            worker=self.__class__.__name__,
            total_sweeps=self._total_sweeps,
            total_checked=self._total_checked,
            total_silent=self._total_silent,
            total_anomalous=self._total_anomalous,
        )

    # ------------------------------------------------------------------
    # Main loop
    # ------------------------------------------------------------------

    async def _run_loop(self) -> None:
        """Primary loop — sweeps heartbeats at the current DEFCON-adjusted interval."""
        while self._running:
            cycle_start = time.monotonic()
            try:
                await self._sweep_heartbeats()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.error(
                    "heartbeat_sweep_error",
                    error=str(exc),
                    exc_info=True,
                )

            interval = await self._current_interval()
            elapsed = time.monotonic() - cycle_start
            sleep_time = max(0.0, interval - elapsed)
            await asyncio.sleep(sleep_time)

    # ------------------------------------------------------------------
    # Sweep logic
    # ------------------------------------------------------------------

    async def _sweep_heartbeats(self) -> None:
        """Check every registered entity's heartbeat for continuity.

        Metrics emitted per sweep
        -------------------------
        - ``total_checked`` — number of entities examined
        - ``healthy`` — entities with an on-time pulse
        - ``silent`` — entities with no pulse within the expected window
        - ``anomalous`` — entities whose pulse data failed integrity checks
        """
        entities = await self._get_registered_entities()
        if not entities:
            return

        now = datetime.utcnow()
        expected_interval = await self._current_interval()
        silence_threshold = timedelta(seconds=expected_interval * SILENCE_MULTIPLIER)

        healthy: int = 0
        silent: int = 0
        anomalous: int = 0
        escalation_targets: List[Dict[str, Any]] = []

        for entity in entities:
            entity_id: UUID = entity.get("entity_id") or entity.get("id")
            last_pulse_time: Optional[datetime] = entity.get("last_pulse_at")

            # --- Silent detection ---
            if last_pulse_time is None or (now - last_pulse_time) > silence_threshold:
                silent += 1
                escalation_targets.append({
                    "entity_id": entity_id,
                    "reason": "heartbeat_silence",
                    "last_pulse_at": last_pulse_time,
                    "silence_duration_sec": (
                        (now - last_pulse_time).total_seconds()
                        if last_pulse_time
                        else None
                    ),
                })
                continue

            # --- Anomaly detection (pulse integrity) ---
            if await self._pulse_is_anomalous(entity):
                anomalous += 1
                escalation_targets.append({
                    "entity_id": entity_id,
                    "reason": "heartbeat_anomaly",
                    "last_pulse_at": last_pulse_time,
                    "details": entity.get("anomaly_details", ""),
                })
                continue

            healthy += 1

        # --- Escalate silent / anomalous entities ---
        for target in escalation_targets:
            await self._escalate_to_curiosity(target)

        # --- Persist sweep metrics ---
        self._total_sweeps += 1
        self._total_checked += len(entities)
        self._total_silent += silent
        self._total_anomalous += anomalous

        await self._persist_sweep_metrics(
            total_checked=len(entities),
            healthy=healthy,
            silent=silent,
            anomalous=anomalous,
        )

        logger.info(
            "heartbeat_sweep_complete",
            sweep_number=self._total_sweeps,
            total_checked=len(entities),
            healthy=healthy,
            silent=silent,
            anomalous=anomalous,
        )

    # ------------------------------------------------------------------
    # Entity retrieval
    # ------------------------------------------------------------------

    async def _get_registered_entities(self) -> List[Dict[str, Any]]:
        """Retrieve all entities registered in the heartbeat registry.

        Delegates to ``heartbeat_registry.get_all_entities()`` if available,
        otherwise falls back to a direct DB query.
        """
        if hasattr(self.heartbeat_registry, "get_all_entities"):
            return await self.heartbeat_registry.get_all_entities()

        if not self.db_pool:
            return []

        try:
            async with self.db_pool.acquire() as conn:
                rows = await conn.fetch(
                    """
                    SELECT entity_id, last_pulse_at, birth_coherence_hash,
                           monotonic_counter, pulse_data
                    FROM hive_heartbeats
                    WHERE active = true
                    ORDER BY last_pulse_at ASC NULLS FIRST
                    """
                )
                return [dict(r) for r in rows]
        except Exception as exc:
            logger.warning("heartbeat_entity_fetch_failed", error=str(exc))
            return []

    # ------------------------------------------------------------------
    # Anomaly checks
    # ------------------------------------------------------------------

    async def _pulse_is_anomalous(self, entity: Dict[str, Any]) -> bool:
        """Determine whether an entity's latest pulse is anomalous.

        Checks performed:
        1. Monotonic counter should be strictly increasing.
        2. Pulse HMAC should pass integrity verification via the registry.
        3. Birth coherence hash must match the original registration.
        """
        if hasattr(self.heartbeat_registry, "verify_pulse_integrity"):
            result = await self.heartbeat_registry.verify_pulse_integrity(
                entity_id=entity.get("entity_id") or entity.get("id"),
                pulse_data=entity.get("pulse_data", ""),
                monotonic_counter=entity.get("monotonic_counter", 0),
            )
            if not result.get("valid", True):
                entity["anomaly_details"] = result.get("reason", "integrity_check_failed")
                return True
        return False

    # ------------------------------------------------------------------
    # Curiosity escalation
    # ------------------------------------------------------------------

    async def _escalate_to_curiosity(self, target: Dict[str, Any]) -> None:
        """Forward a silent or anomalous entity to the CuriosityProtocol.

        Parameters
        ----------
        target : dict
            Must contain ``entity_id``, ``reason``, and optionally additional
            context fields (``silence_duration_sec``, ``details``, etc.).
        """
        try:
            if hasattr(self.curiosity_protocol, "evaluate_entity"):
                await self.curiosity_protocol.evaluate_entity(
                    entity_id=target["entity_id"],
                    trigger_reason=target["reason"],
                    context=target,
                )
                logger.info(
                    "heartbeat_curiosity_escalation",
                    entity_id=str(target["entity_id"]),
                    reason=target["reason"],
                )
        except Exception as exc:
            logger.error(
                "heartbeat_curiosity_escalation_failed",
                entity_id=str(target.get("entity_id")),
                error=str(exc),
            )

    # ------------------------------------------------------------------
    # DEFCON-aware interval
    # ------------------------------------------------------------------

    async def _current_interval(self) -> float:
        """Return the sweep interval adjusted for the current DEFCON level."""
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

    async def _persist_sweep_metrics(
        self,
        total_checked: int,
        healthy: int,
        silent: int,
        anomalous: int,
    ) -> None:
        """Write sweep metrics to the database for dashboard consumption.

        Silently no-ops if ``db_pool`` is unavailable.
        """
        if not self.db_pool:
            return
        try:
            async with self.db_pool.acquire() as conn:
                await conn.execute(
                    """
                    INSERT INTO hive_heartbeat_metrics
                        (sweep_number, total_checked, healthy, silent, anomalous, swept_at)
                    VALUES ($1, $2, $3, $4, $5, NOW())
                    """,
                    self._total_sweeps,
                    total_checked,
                    healthy,
                    silent,
                    anomalous,
                )
        except Exception as exc:
            # Metrics persistence is best-effort; never crash the sweep loop.
            logger.debug("heartbeat_metrics_persist_failed", error=str(exc))
