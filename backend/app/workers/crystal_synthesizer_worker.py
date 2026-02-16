"""
SOVEREIGN SWARM — Crystal Synthesizer Worker
Monthly identity crystal synthesis for all eligible users.
"""

from __future__ import annotations

import asyncio
from typing import Any

import structlog

logger = structlog.get_logger(__name__)


class CrystalSynthesizerWorker:
    """Background worker: monthly identity crystal synthesis."""

    def __init__(
        self,
        crystallizer: Any,
        consent_service: Any = None,
        db_pool: Any = None,
        interval: int = 86400,  # Daily check
    ) -> None:
        self.crystallizer = crystallizer
        self.consent_service = consent_service
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
                await self._synthesize_eligible_users()
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.error("crystal_worker_error", error=str(e))
            await asyncio.sleep(self.interval)

    async def _synthesize_eligible_users(self) -> None:
        """Find users due for crystal synthesis and process them."""
        if not self.db_pool:
            return

        try:
            async with self.db_pool.acquire() as conn:
                # Users with PRESERVE consent who haven't had a crystal in 30+ days
                rows = await conn.fetch(
                    """SELECT c.user_id FROM me2me_consent_records c
                    LEFT JOIN me2me_identity_crystals ic ON ic.user_id = c.user_id
                    WHERE c.status = 'active' AND c.level IN ('preserve', 'interact')
                    GROUP BY c.user_id
                    HAVING MAX(ic.synthesized_at) < NOW() - INTERVAL '30 days'
                       OR MAX(ic.synthesized_at) IS NULL"""
                )

                for row in rows:
                    user_id = row["user_id"]
                    try:
                        crystal = await self.crystallizer.synthesize(user_id)
                        if crystal:
                            logger.info("crystal_synthesized", user_id=user_id, version=crystal.crystal_version)
                    except Exception as e:
                        logger.error("crystal_synthesis_failed", user_id=user_id, error=str(e))
        except Exception as e:
            logger.warning("eligible_users_query_failed", error=str(e))
