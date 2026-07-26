"""
PGSDHeartbeatAgent — nightly baseline snapshots.  # QUANTUM-CRYSTAL-ARCH

Primary-only (Redis leader lock). Skips audit_* and battery users.
Gated by PGSD_ENABLED + ENABLE_PGSD_HEARTBEAT.
"""

from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime, timezone
from typing import Any, Optional

logger = logging.getLogger(__name__)

POLL_INTERVAL_SECONDS = 3600  # check hourly; act once per UTC day
STAGGER_DELAY = 180
LEADER_KEY = "pgsd:heartbeat:leader"
LEADER_TTL = 3500


def _env_true(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in ("1", "true", "yes", "on")


class PGSDHeartbeatAgent:
    def __init__(
        self,
        db_pool: Any = None,
        redis_client: Any = None,
        app_state: Any = None,
    ):
        self.db_pool = db_pool
        self.redis = redis_client
        self.app_state = app_state
        self._task: Optional[asyncio.Task] = None
        self._running = False
        self._last_run_date: Optional[str] = None

    async def start(self):
        if not _env_true("PGSD_ENABLED") or not _env_true("ENABLE_PGSD_HEARTBEAT"):
            logger.info("PGSDHeartbeatAgent not started (flags off)")
            return
        if self._task and not self._task.done():
            return
        self._running = True
        self._task = asyncio.create_task(self._run_loop())
        logger.info("PGSDHeartbeatAgent started (stagger %ds)", STAGGER_DELAY)

    async def stop(self):
        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("PGSDHeartbeatAgent stopped")

    async def _is_leader(self) -> bool:
        # Prefer explicit primary role when set.
        node_role = os.environ.get("NODE_ROLE", "").strip().lower()
        if node_role and node_role not in ("primary", "green", ""):
            if node_role in ("clone", "secondary"):
                return False
        if self.redis is None:
            # No Redis → allow only when NODE_ROLE=primary or unset (single-node).
            return node_role in ("", "primary", "green")
        try:
            # SET NX EX — acquire leader
            ok = await self.redis.set(LEADER_KEY, "1", nx=True, ex=LEADER_TTL)
            if ok:
                return True
            # Refresh if we already hold it (best-effort: use GET)
            val = await self.redis.get(LEADER_KEY)
            if val in (b"1", "1"):
                await self.redis.expire(LEADER_KEY, LEADER_TTL)
                return True
            return False
        except Exception as e:
            logger.warning("PGSDHeartbeatAgent leader check failed: %s", e)
            return node_role in ("", "primary", "green")

    async def _run_loop(self):
        await asyncio.sleep(STAGGER_DELAY)
        while self._running:
            try:
                if await self._is_leader():
                    await self._tick()
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.error("PGSDHeartbeatAgent tick failed: %s", e, exc_info=True)
            await asyncio.sleep(POLL_INTERVAL_SECONDS)

    async def _tick(self):
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        if self._last_run_date == today:
            return
        if self.db_pool is None:
            return

        from app.services.pgsd_triggers import notify_user_async

        async with self.db_pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT DISTINCT u.hardware_id, u.username
                FROM users u
                WHERE u.role = 'CLIENT'
                  AND u.subscription_status IN ('ACTIVE', 'TRIAL_ACTIVE')
                  AND u.hardware_id IS NOT NULL
                  AND u.hardware_id != ''
                  AND LOWER(u.username) NOT LIKE 'audit\\_%'
                  AND COALESCE(u.profile_data->>'six_quotient_battery', '') NOT IN ('1', 'true', 'active')
                  AND (
                    EXISTS (
                        SELECT 1 FROM conversation_history ch
                        WHERE ch.user_id = u.username
                          AND ch.created_at > NOW() - INTERVAL '7 days'
                    )
                    OR EXISTS (
                        SELECT 1 FROM pgsd_snapshots s
                        WHERE s.user_id = u.hardware_id
                          AND s.computed_at > NOW() - INTERVAL '7 days'
                    )
                  )
                LIMIT 500
                """
            )

        scheduled = 0
        for row in rows:
            hw = row["hardware_id"]
            if await notify_user_async(self.db_pool, hw, source="nightly"):
                scheduled += 1
            await asyncio.sleep(0.05)  # soft rate limit

        self._last_run_date = today
        logger.info(
            "PGSDHeartbeatAgent: nightly pass date=%s candidates=%d scheduled=%d",
            today, len(rows), scheduled,
        )
