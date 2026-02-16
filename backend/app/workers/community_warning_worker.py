"""
SOVEREIGN SWARM — Community Warning Worker
Cultural signal to member match scanning.
Periodically checks for new cultural signals and processes them.
"""

from __future__ import annotations

import asyncio
from typing import Any, Optional

import structlog

logger = structlog.get_logger(__name__)


class CommunityWarningWorker:
    """Background worker: cultural signal processing and community warning generation."""

    def __init__(
        self,
        community_warning: Any,
        db_pool: Any = None,
        interval: int = 1800,  # 30 minutes
    ) -> None:
        self.community_warning = community_warning
        self.db_pool = db_pool
        self.interval = interval
        self._task: asyncio.Task | None = None
        self._running = False
        self._processed_signals: set = set()

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
                await self._process_new_signals()
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.error("community_warning_error", error=str(e))
            await asyncio.sleep(self.interval)

    async def _process_new_signals(self) -> None:
        """Check for new cultural signals and process them."""
        if not self.db_pool:
            return

        try:
            async with self.db_pool.acquire() as conn:
                rows = await conn.fetch(
                    """
                    SELECT signal_id, source_platform, signal_type,
                           description, keywords, sentiment, volume,
                           velocity, geographic_scope, confidence
                    FROM cultural_signals
                    WHERE first_detected > NOW() - INTERVAL '1 day'
                    ORDER BY first_detected DESC
                    """
                )
        except Exception as e:
            logger.warning("Cultural signal query failed: %s", e)
            return

        from app.models.solutions import CulturalSignal

        for row in rows:
            signal_id = row["signal_id"]
            if signal_id in self._processed_signals:
                continue

            signal = CulturalSignal(
                signal_id=signal_id,
                source_platform=row.get("source_platform", ""),
                signal_type=row.get("signal_type", ""),
                description=row.get("description", ""),
                keywords=row.get("keywords", []),
                sentiment=row.get("sentiment", 0.0),
                volume=row.get("volume", 0),
                velocity=row.get("velocity", 0.0),
                geographic_scope=row.get("geographic_scope", "national"),
                confidence=row.get("confidence", 0.0),
            )

            try:
                await self.community_warning.process_signal(signal)
                self._processed_signals.add(signal_id)
                logger.info(
                    "signal_processed",
                    signal_id=signal_id,
                    signal_type=signal.signal_type,
                )
            except Exception as e:
                logger.error(
                    "signal_processing_failed",
                    signal_id=signal_id,
                    error=str(e),
                )

        # Cleanup
        if len(self._processed_signals) > 10000:
            self._processed_signals.clear()
