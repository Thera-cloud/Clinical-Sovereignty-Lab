"""LearningLoopAgent — intelligence growth from admin interactions (2h cycle). Stub — full implementation pending"""

import asyncio
import logging

logger = logging.getLogger(__name__)


class LearningLoopAgent:
    """Stub — full implementation pending"""

    def __init__(self, db_pool=None):
        self.db_pool = db_pool
        self._task = None
        self._running = False

    async def start(self):
        self._running = True
        logger.info("LearningLoopAgent started (stub)")

    async def stop(self):
        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()
        logger.info("LearningLoopAgent stopped (stub)")
