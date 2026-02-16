"""
SOVEREIGN SWARM — Ingestion Safety Worker
Periodic crisis pattern scanning during Me-2-Me data ingestion.
"""

from __future__ import annotations

import asyncio
from typing import Any

import structlog

logger = structlog.get_logger(__name__)


class IngestionSafetyWorker:
    """Background worker: scans recent imprints for crisis content."""

    def __init__(
        self,
        ingestion_safety: Any,
        db_pool: Any = None,
        interval: int = 3600,  # Hourly
    ) -> None:
        self.ingestion_safety = ingestion_safety
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
                await self._scan_recent_imprints()
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.error("ingestion_safety_error", error=str(e))
            await asyncio.sleep(self.interval)

    async def _scan_recent_imprints(self) -> None:
        """Scan recent unscanned imprints for crisis content."""
        if not self.db_pool:
            return
        try:
            async with self.db_pool.acquire() as conn:
                rows = await conn.fetch(
                    """SELECT entry_id, user_id, content_hash, source
                    FROM me2me_imprint_entries
                    WHERE captured_at > NOW() - INTERVAL '2 hours'
                    AND processed = FALSE
                    LIMIT 100"""
                )
                flagged = 0
                for row in rows:
                    result = await self.ingestion_safety.scan_content(
                        user_id=row["user_id"],
                        content=row.get("content_hash", ""),
                        source=row.get("source", ""),
                    )
                    if not result.get("safe", True):
                        flagged += 1
                if flagged:
                    logger.warning("ingestion_safety_scan", flagged=flagged, total=len(rows))
        except Exception as e:
            logger.warning("ingestion_safety_scan_failed", error=str(e))
