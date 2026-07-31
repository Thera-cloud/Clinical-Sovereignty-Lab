"""Single scheduler: nightly fuel gauge + 60s serve-health while candidates live.

# QUANTUM-CRYSTAL-ARCH
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any, Optional

logger = logging.getLogger("ln7_ops_scheduler")

FUEL_HOUR_UTC = 6  # once nightly after 06:00 UTC
HEALTH_POLL_S = 60


class Ln7OpsScheduler:
    def __init__(self, db_pool=None):
        self._db_pool = db_pool
        self._running = False
        self._task: Optional[asyncio.Task] = None
        self._last_fuel_date: Optional[str] = None
        self._cycles = 0

    async def start(self):
        self._running = True
        self._task = asyncio.create_task(self._run_loop())
        logger.info("Ln7OpsScheduler started (fuel@%sUTC + health %ss)", FUEL_HOUR_UTC, HEALTH_POLL_S)

    async def stop(self):
        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("Ln7OpsScheduler stopped cycles=%s", self._cycles)

    async def _run_loop(self):
        await asyncio.sleep(90)  # stagger after boot
        while self._running:
            self._cycles += 1
            try:
                await self._tick()
            except Exception as e:
                logger.warning("Ln7OpsScheduler tick: %s", e)
            await asyncio.sleep(HEALTH_POLL_S)

    async def _tick(self):
        from app.jobs.ln7_serve_health_monitor import run_serve_health_cycle
        from app.jobs.ln7_fuel_gauge import run_fuel_gauge_cycle

        await run_serve_health_cycle(self._db_pool)
        now = datetime.now(timezone.utc)
        day = now.date().isoformat()
        if now.hour >= FUEL_HOUR_UTC and self._last_fuel_date != day:
            out = await run_fuel_gauge_cycle(self._db_pool)
            if out.get("ok"):
                self._last_fuel_date = day
                logger.info("fuel gauge digest: %s", out.get("digest"))

    def status(self) -> dict[str, Any]:
        return {
            "running": self._running,
            "cycles": self._cycles,
            "last_fuel_date": self._last_fuel_date,
        }
