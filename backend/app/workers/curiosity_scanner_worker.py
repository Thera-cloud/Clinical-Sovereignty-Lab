"""
HIVE DEFENSE PROTOCOL — Curiosity Scanner Worker (Phase 8A)
Periodic mirror reflection tests on a sampled subset of hive entities.

Entities at higher curiosity levels are tested more frequently via weighted
random selection.  Each selected entity undergoes a full
``CuriosityProtocol.evaluate_entity()`` pass.  Scan cadence and sensitivity
adapt to the current DEFCON level.

Patent-Pending — Claims 30-56
© 2026 Clinical Sovereignty Lab. All rights reserved.
"""

from __future__ import annotations

import asyncio
import random
import time
from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import UUID

import structlog

logger = structlog.get_logger("hive.curiosity_scanner")


# ---------------------------------------------------------------------------
# Curiosity-level → sampling weight (higher = tested more often)
# ---------------------------------------------------------------------------
CURIOSITY_SAMPLING_WEIGHTS: Dict[str, float] = {
    "none": 0.05,      # Rare random spot-checks
    "notice": 0.25,    # Quarterly inclusion
    "interest": 0.50,  # Every other cycle
    "concern": 0.80,   # Almost every cycle
    "alarm": 1.00,     # Every cycle without exception
}

# ---------------------------------------------------------------------------
# DEFCON → scan multiplier (how many entities per cycle relative to base)
# ---------------------------------------------------------------------------
DEFCON_SCAN_MULTIPLIER: Dict[int, float] = {
    5: 1.0,    # PEACE — standard sampling
    4: 1.5,    # ELEVATED — 50% more scans
    3: 2.0,    # SUBSTANTIAL — double scans
    2: 3.0,    # SEVERE — triple
    1: 5.0,    # CRITICAL — full sweep bias
}

# DEFCON → cycle interval override (seconds)
DEFCON_INTERVAL_MAP: Dict[int, float] = {
    5: 300.0,  # PEACE — every 5 min
    4: 180.0,  # ELEVATED — every 3 min
    3: 120.0,  # SUBSTANTIAL — every 2 min
    2: 60.0,   # SEVERE — every 1 min
    1: 30.0,   # CRITICAL — every 30s
}

# Base number of entities sampled per cycle at DEFCON 5
BASE_SAMPLE_SIZE: int = 10


class CuriosityScannerWorker:
    """Background worker: periodic mirror reflection testing on hive entities.

    Responsibilities
    ----------------
    * Sample a weighted subset of entities — higher curiosity levels get
      higher selection probability.
    * Invoke ``curiosity_protocol.evaluate_entity()`` for each sample.
    * Track cumulative metrics: scans performed, anomalies found, escalations.
    * Respect DEFCON level for both scan frequency and sample size.
    * Log structured metrics after every scan cycle.

    Parameters
    ----------
    curiosity_protocol : Any
        Reference to the ``CuriosityProtocol`` service.
    heartbeat_registry : Any
        Provides the entity population and their current curiosity levels.
    db_pool : Any, optional
        asyncpg connection pool for persistence and metric storage.
    base_interval : float
        Default scan cycle interval in seconds (adjusted by DEFCON).
    defcon_provider : callable, optional
        Async callable returning the current DEFCON level (int 1-5).
    """

    def __init__(
        self,
        curiosity_protocol: Any,
        heartbeat_registry: Any,
        db_pool: Any = None,
        base_interval: float = 300.0,
        defcon_provider: Optional[Any] = None,
    ) -> None:
        self.curiosity_protocol = curiosity_protocol
        self.heartbeat_registry = heartbeat_registry
        self.db_pool = db_pool
        self.base_interval = base_interval
        self.defcon_provider = defcon_provider

        self._task: Optional[asyncio.Task] = None
        self._running: bool = False

        # Cumulative metrics
        self._total_cycles: int = 0
        self._scans_performed: int = 0
        self._anomalies_found: int = 0
        self._escalations_triggered: int = 0

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Start the curiosity scanning loop."""
        self._running = True
        self._task = asyncio.create_task(self._run_loop())
        logger.info("worker_started", worker=self.__class__.__name__)

    async def stop(self) -> None:
        """Gracefully stop the scanning loop."""
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
            total_cycles=self._total_cycles,
            scans_performed=self._scans_performed,
            anomalies_found=self._anomalies_found,
            escalations_triggered=self._escalations_triggered,
        )

    # ------------------------------------------------------------------
    # Main loop
    # ------------------------------------------------------------------

    async def _run_loop(self) -> None:
        """Primary loop — scans entities at the DEFCON-adjusted interval."""
        while self._running:
            cycle_start = time.monotonic()
            try:
                await self._scan_cycle()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.error(
                    "curiosity_scan_error",
                    error=str(exc),
                    exc_info=True,
                )

            interval = await self._current_interval()
            elapsed = time.monotonic() - cycle_start
            sleep_time = max(0.0, interval - elapsed)
            await asyncio.sleep(sleep_time)

    # ------------------------------------------------------------------
    # Scan cycle
    # ------------------------------------------------------------------

    async def _scan_cycle(self) -> None:
        """Execute a single scan cycle.

        Steps
        -----
        1. Fetch all active entities and their curiosity levels.
        2. Determine sample size (base × DEFCON multiplier).
        3. Weighted random selection using curiosity-level weights.
        4. Evaluate each selected entity via ``CuriosityProtocol``.
        5. Collect and persist cycle metrics.
        """
        entities = await self._get_entities_with_curiosity()
        if not entities:
            return

        sample_size = await self._compute_sample_size(len(entities))
        selected = self._weighted_sample(entities, sample_size)

        cycle_anomalies: int = 0
        cycle_escalations: int = 0

        for entity in selected:
            entity_id: UUID = entity.get("entity_id") or entity.get("id")
            current_level: str = entity.get("curiosity_level", "none")

            try:
                result = await self.curiosity_protocol.evaluate_entity(
                    entity_id=entity_id,
                    trigger_reason="mirror_reflection_test",
                    context={
                        "scan_type": "periodic_mirror_reflection",
                        "prior_curiosity_level": current_level,
                        "cycle_number": self._total_cycles + 1,
                    },
                )
                self._scans_performed += 1

                # Track anomalies and escalations from the evaluation result
                if isinstance(result, dict):
                    if result.get("anomaly_detected", False):
                        cycle_anomalies += 1
                    if result.get("escalated", False):
                        cycle_escalations += 1
                        logger.warning(
                            "curiosity_escalation",
                            entity_id=str(entity_id),
                            from_level=current_level,
                            new_level=result.get("new_level", "unknown"),
                        )
            except Exception as exc:
                logger.error(
                    "curiosity_entity_scan_failed",
                    entity_id=str(entity_id),
                    error=str(exc),
                )

        # --- Update cumulative metrics ---
        self._total_cycles += 1
        self._anomalies_found += cycle_anomalies
        self._escalations_triggered += cycle_escalations

        await self._persist_cycle_metrics(
            entities_sampled=len(selected),
            anomalies_found=cycle_anomalies,
            escalations_triggered=cycle_escalations,
        )

        logger.info(
            "curiosity_scan_cycle_complete",
            cycle_number=self._total_cycles,
            population_size=len(entities),
            entities_sampled=len(selected),
            anomalies_found=cycle_anomalies,
            escalations_triggered=cycle_escalations,
        )

    # ------------------------------------------------------------------
    # Entity retrieval
    # ------------------------------------------------------------------

    async def _get_entities_with_curiosity(self) -> List[Dict[str, Any]]:
        """Fetch all active entities along with their current curiosity level.

        Tries the registry first, falls back to a direct DB query.
        """
        if hasattr(self.heartbeat_registry, "get_all_entities_with_curiosity"):
            return await self.heartbeat_registry.get_all_entities_with_curiosity()

        if hasattr(self.heartbeat_registry, "get_all_entities"):
            entities = await self.heartbeat_registry.get_all_entities()
            # Attach curiosity level if not present
            for e in entities:
                if "curiosity_level" not in e:
                    e["curiosity_level"] = "none"
            return entities

        if not self.db_pool:
            return []

        try:
            async with self.db_pool.acquire() as conn:
                rows = await conn.fetch(
                    """
                    SELECT h.entity_id, h.last_pulse_at,
                           COALESCE(c.level, 'none') AS curiosity_level
                    FROM hive_heartbeats h
                    LEFT JOIN hive_curiosity_state c
                        ON h.entity_id = c.entity_id
                    WHERE h.active = true
                    """
                )
                return [dict(r) for r in rows]
        except Exception as exc:
            logger.warning("curiosity_entity_fetch_failed", error=str(exc))
            return []

    # ------------------------------------------------------------------
    # Weighted sampling
    # ------------------------------------------------------------------

    def _weighted_sample(
        self,
        entities: List[Dict[str, Any]],
        sample_size: int,
    ) -> List[Dict[str, Any]]:
        """Select entities via weighted random sampling without replacement.

        Higher curiosity levels produce higher sampling weights, ensuring
        entities under investigation are tested more frequently.

        Parameters
        ----------
        entities : list of dict
            Each entity must have a ``curiosity_level`` key.
        sample_size : int
            Maximum number of entities to select.

        Returns
        -------
        list of dict
            The selected subset.
        """
        if not entities:
            return []

        sample_size = min(sample_size, len(entities))

        weights = [
            CURIOSITY_SAMPLING_WEIGHTS.get(
                e.get("curiosity_level", "none"), 0.05
            )
            for e in entities
        ]

        # Ensure at least a minimal weight so every entity has *some* chance
        weights = [max(w, 0.01) for w in weights]

        try:
            selected_indices = []
            remaining_indices = list(range(len(entities)))
            remaining_weights = list(weights)

            for _ in range(sample_size):
                if not remaining_indices:
                    break
                chosen = random.choices(
                    remaining_indices,
                    weights=remaining_weights,
                    k=1,
                )[0]
                selected_indices.append(chosen)
                idx = remaining_indices.index(chosen)
                remaining_indices.pop(idx)
                remaining_weights.pop(idx)

            return [entities[i] for i in selected_indices]
        except Exception:
            # Fallback to uniform random if weighted sampling fails
            return random.sample(entities, sample_size)

    # ------------------------------------------------------------------
    # DEFCON-aware parameters
    # ------------------------------------------------------------------

    async def _current_interval(self) -> float:
        """Return the scan interval adjusted for the current DEFCON level."""
        if self.defcon_provider:
            try:
                level = await self.defcon_provider()
                level_int = int(level.value) if hasattr(level, "value") else int(level)
                return DEFCON_INTERVAL_MAP.get(level_int, self.base_interval)
            except Exception:
                pass
        return self.base_interval

    async def _compute_sample_size(self, population: int) -> int:
        """Compute how many entities to scan this cycle.

        Uses ``BASE_SAMPLE_SIZE × DEFCON_SCAN_MULTIPLIER``, capped at the
        total population.
        """
        multiplier = 1.0
        if self.defcon_provider:
            try:
                level = await self.defcon_provider()
                level_int = int(level.value) if hasattr(level, "value") else int(level)
                multiplier = DEFCON_SCAN_MULTIPLIER.get(level_int, 1.0)
            except Exception:
                pass
        return min(int(BASE_SAMPLE_SIZE * multiplier), population)

    # ------------------------------------------------------------------
    # Metrics persistence
    # ------------------------------------------------------------------

    async def _persist_cycle_metrics(
        self,
        entities_sampled: int,
        anomalies_found: int,
        escalations_triggered: int,
    ) -> None:
        """Write scan cycle metrics to the database.

        Best-effort — a persistence failure never crashes the scan loop.
        """
        if not self.db_pool:
            return
        try:
            async with self.db_pool.acquire() as conn:
                await conn.execute(
                    """
                    INSERT INTO hive_curiosity_scan_metrics
                        (cycle_number, entities_sampled, anomalies_found,
                         escalations_triggered, scanned_at)
                    VALUES ($1, $2, $3, $4, NOW())
                    """,
                    self._total_cycles,
                    entities_sampled,
                    anomalies_found,
                    escalations_triggered,
                )
        except Exception as exc:
            logger.debug("curiosity_metrics_persist_failed", error=str(exc))
