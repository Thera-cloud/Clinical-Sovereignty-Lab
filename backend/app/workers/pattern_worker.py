"""
SOVEREIGN SWARM — Transgenerational Pattern Worker
Client history scanning, pattern activation detection, clinical team notifications.
"""

from __future__ import annotations

import asyncio
from typing import Any, Dict, List
from uuid import UUID, uuid4

import structlog

from app.models.foresight import PatternActivation

logger = structlog.get_logger(__name__)


class PatternWorker:
    """
    Background worker for transgenerational pattern detection:
    scan client histories, generate PatternActivation alerts, notify clinical teams.
    """

    def __init__(
        self,
        pattern_engine: Any,
        db_pool: Any,
        interval: int = 3600,
    ) -> None:
        self.pattern_engine = pattern_engine
        self.db_pool = db_pool
        self.interval = interval
        self._task: asyncio.Task | None = None
        self._running = False

    async def start(self) -> None:
        self._running = True
        self._task = asyncio.create_task(self._run_loop())
        logger.info("worker_started", worker=self.__class__.__name__)

    async def stop(self) -> None:
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("worker_stopped", worker=self.__class__.__name__)

    async def _run_loop(self) -> None:
        while self._running:
            try:
                await self._tick()
            except Exception as e:
                logger.error(
                    "worker_error",
                    worker=self.__class__.__name__,
                    error=str(e),
                )
            await asyncio.sleep(self.interval)

    async def _tick(self) -> None:
        # 1. Get families with sufficient data
        family_ids: List[Any] = []
        try:
            async with self.db_pool.acquire() as conn:
                rows = await conn.fetch("""
                    SELECT DISTINCT family_id FROM users
                    WHERE family_id IS NOT NULL
                """)
                family_ids = [r["family_id"] for r in rows if r["family_id"]]
        except Exception as e:
            logger.warning("pattern_families_query_failed", error=str(e))
            return

        activations: List[PatternActivation] = []

        for family_id in family_ids:
            try:
                # 2. Run full pattern analysis
                analysis = await self.pattern_engine.full_analysis(family_id)

                # 3. Extract trigger patterns and convert to PatternActivation
                trigger_data = analysis.get("trigger_patterns", {}) or {}
                correlated = trigger_data.get("correlated_triggers", [])

                for item in correlated[:5]:  # limit to top 5 per family
                    activation = PatternActivation(
                        family_id=UUID(str(family_id)) if family_id else None,
                        pattern_name="correlated_stress_spike",
                        pattern_description="Temporal correlation of stress events across family members",
                        trigger_circumstances=[str(item)],
                        trigger_match_score=0.7,
                        therapeutic_preparations=[
                            "Consider family session to address shared stressors",
                        ],
                        recommended_modalities=["family_systems", "relational"],
                    )
                    activations.append(activation)

                # 4. Check coping inheritance for inherited patterns
                coping_data = analysis.get("coping_inheritance", {}) or {}
                inherited = coping_data.get("inherited_mechanisms", {})

                for pattern_name, holder_ids in list(inherited.items())[:3]:
                    activation = PatternActivation(
                        family_id=UUID(str(family_id)) if family_id else None,
                        pattern_name=pattern_name,
                        pattern_description=f"Inherited coping mechanism shared by {len(holder_ids)} members",
                        inherited_from="family_system",
                        transmission_rate=len(holder_ids) / max(len(inherited) or 1, 1),
                        trigger_match_score=0.6,
                        therapeutic_preparations=[
                            "Explore origin and appropriateness of inherited pattern",
                        ],
                    )
                    activations.append(activation)

            except Exception as e:
                logger.debug(
                    "pattern_analysis_family_skipped",
                    family_id=str(family_id),
                    error=str(e),
                )

        # 5. Log activations and notify (log insight for clinical visibility)
        for act in activations:
            logger.info(
                "pattern_activation",
                activation_id=str(act.activation_id),
                pattern_name=act.pattern_name,
                family_id=str(act.family_id) if act.family_id else None,
            )

        # Store via strategic memory if available
        try:
            from app.services.strategic_memory import StrategicMemoryService
            memory = StrategicMemoryService(self.db_pool)
            for act in activations[:10]:  # limit stored per tick
                await memory.log_insight(
                    title=f"Pattern: {act.pattern_name}",
                    body=act.pattern_description,
                    domain="transgenerational",
                    confidence=act.trigger_match_score,
                    tags=["pattern_activation", act.pattern_name],
                    metadata={"activation_id": str(act.activation_id)},
                )
        except Exception as e:
            logger.debug("pattern_insight_store_skipped", error=str(e))

        logger.info(
            "pattern_tick_complete",
            families_analyzed=len(family_ids),
            activations_found=len(activations),
        )
