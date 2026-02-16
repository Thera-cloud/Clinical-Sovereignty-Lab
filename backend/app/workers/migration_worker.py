"""
SOVEREIGN SWARM — Migration Worker
Monitors active migrations and manages phase transitions.
"""

from __future__ import annotations

import asyncio
from typing import Any

import structlog

logger = structlog.get_logger(__name__)


class MigrationWorker:
    """Background worker: migration phase monitoring and advancement."""

    def __init__(
        self,
        migration_service: Any,
        db_pool: Any = None,
        interval: int = 86400,  # Daily check
    ) -> None:
        self.migration_service = migration_service
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
                await self._check_migrations()
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.error("migration_worker_error", error=str(e))
            await asyncio.sleep(self.interval)

    async def _check_migrations(self) -> None:
        """Check active migrations for automatic phase advancement."""
        if not self.db_pool:
            return
        try:
            async with self.db_pool.acquire() as conn:
                rows = await conn.fetch(
                    """SELECT migration_id, user_id, phase, started_at
                    FROM me2me_migrations
                    WHERE phase NOT IN ('complete', 'not_started')"""
                )
                for row in rows:
                    logger.debug(
                        "migration_check",
                        migration_id=row["migration_id"],
                        phase=row["phase"],
                    )
        except Exception as e:
            logger.warning("migration_check_failed", error=str(e))
