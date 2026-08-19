"""S5 screener autoscale — hint + background agent. QUANTUM-CRYSTAL-ARCH"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict, Optional

logger = logging.getLogger("studio_screener_autoscale")


def scale_hint(waiting: int) -> Dict[str, Any]:
    n = max(0, int(waiting or 0))
    workers = 1
    if n >= 20:
        workers = 4
    elif n >= 10:
        workers = 3
    elif n >= 4:
        workers = 2
    return {"ok": True, "waiting": n, "workers": workers, "autoscale": True}


async def waiting_count(db_pool, show_id: str) -> int:
    if not db_pool or not show_id:
        return 0
    async with db_pool.acquire() as conn:
        n = await conn.fetchval(
            """
            SELECT COUNT(*) FROM show_callers
            WHERE show_id = $1::uuid AND risk_flag = FALSE AND opted_in = TRUE
              AND created_at > NOW() - INTERVAL '2 hours'
            """,
            show_id,
        )
    return int(n or 0)


class StudioScreenerAutoscaleAgent:
    """Background hint loop. Not an email auditor. QUANTUM-CRYSTAL-ARCH"""

    def __init__(self, db_pool=None):
        self.db_pool = db_pool
        self._task: Optional[asyncio.Task] = None
        self._running = False
        self.last_hint: Dict[str, Any] = scale_hint(0)

    async def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._loop(), name="studio_screener_autoscale")

    async def stop(self) -> None:
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):
                pass
            self._task = None

    async def _loop(self) -> None:
        while self._running:
            try:
                await self._cycle()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.warning("studio screener autoscale cycle: %s", exc)
            await asyncio.sleep(300)

    async def _cycle(self) -> None:
        waiting = 0
        if self.db_pool:
            try:
                async with self.db_pool.acquire() as conn:
                    waiting = int(
                        await conn.fetchval(
                            """
                            SELECT COUNT(*) FROM show_callers
                            WHERE risk_flag = FALSE AND opted_in = TRUE
                              AND created_at > NOW() - INTERVAL '2 hours'
                            """
                        )
                        or 0
                    )
            except Exception as exc:
                logger.warning("studio screener autoscale count: %s", exc)
        self.last_hint = scale_hint(waiting)
        logger.info(
            "studio screener autoscale waiting=%s workers=%s",
            self.last_hint.get("waiting"),
            self.last_hint.get("workers"),
        )
