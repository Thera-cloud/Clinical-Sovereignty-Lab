"""
SOVEREIGN SWARM — Night School Worker
Processes queued content ingestion and manages the Night School curriculum pipeline.
"""

from __future__ import annotations

import asyncio
from typing import Any, Optional

import structlog

logger = structlog.get_logger(__name__)


class NightSchoolWorker:
    """Background worker: Night School content ingestion queue processing."""

    def __init__(
        self,
        curriculum_pipeline: Any,
        db_pool: Any = None,
        interval: int = 600,
    ) -> None:
        self.curriculum_pipeline = curriculum_pipeline
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
                await self._process_queue()
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.error("night_school_worker_error", error=str(e))
            await asyncio.sleep(self.interval)

    async def _process_queue(self) -> None:
        """Process queued content ingestion requests."""
        if not self.db_pool:
            return
        try:
            async with self.db_pool.acquire() as conn:
                rows = await conn.fetch(
                    """SELECT id, source_name, content_type, raw_content, metadata
                    FROM night_school_queue
                    WHERE status = 'pending'
                    ORDER BY created_at ASC LIMIT 5"""
                )
                for row in rows:
                    try:
                        result = await self.curriculum_pipeline.ingest_content(
                            source_name=row["source_name"],
                            content_type=row["content_type"],
                            raw_content=row["raw_content"],
                            metadata=row.get("metadata"),
                        )
                        await conn.execute(
                            "UPDATE night_school_queue SET status = $1 WHERE id = $2",
                            result.get("status", "processed"), row["id"],
                        )
                        logger.info("night_school_content_processed", source=row["source_name"])
                    except Exception as e:
                        await conn.execute(
                            "UPDATE night_school_queue SET status = 'error' WHERE id = $1",
                            row["id"],
                        )
                        logger.error("content_processing_failed", error=str(e))
        except Exception as e:
            logger.warning("night_school_queue_query_failed", error=str(e))
