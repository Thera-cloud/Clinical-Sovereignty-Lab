"""
Background agent: callback queue processor + outreach jitter batching (Sovereign Voice v3.1).
Single service registration in main.py to avoid inflating service health denominator.
"""

from __future__ import annotations

import asyncio
import logging
import os
import random
from datetime import datetime, timedelta, timezone
from typing import Optional

logger = logging.getLogger("nate.voice_call_center")

CALLBACK_TICK_SEC = int(os.getenv("VOICE_CALLBACK_TICK_SEC", "60"))
OUTREACH_CYCLE_SEC = int(os.getenv("VOICE_OUTREACH_CYCLE_SEC", str(6 * 3600)))
STAGGER_SEC = int(os.getenv("VOICE_CALL_CENTER_STAGGER", "275"))


class VoiceCallCenterAgent:
    def __init__(self, db_pool, app_state=None):
        self.db_pool = db_pool
        self.app_state = app_state
        self._task: Optional[asyncio.Task] = None
        self._running = False
        self._last_outreach = datetime.now(timezone.utc) - timedelta(hours=24)

    async def start(self):
        if self._task and not self._task.done():
            return
        self._running = True
        self._task = asyncio.create_task(self._run_loop())
        logger.info(
            "VoiceCallCenterAgent started (callback every %ss, outreach cycle %ss)",
            CALLBACK_TICK_SEC,
            OUTREACH_CYCLE_SEC,
        )

    async def stop(self):
        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("VoiceCallCenterAgent stopped")

    async def _run_loop(self):
        await asyncio.sleep(STAGGER_SEC)
        while self._running:
            try:
                await self._tick_callback_queue()
                await self._maybe_outreach_jitter()
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.error("VoiceCallCenterAgent tick failed: %s", e, exc_info=True)
            await asyncio.sleep(CALLBACK_TICK_SEC)

    async def _tick_callback_queue(self):
        if not self.db_pool:
            return
        from app.services.voice_capacity import XTTS_CONCURRENCY_LIMIT, get_active_voice_count

        active = await get_active_voice_count()
        if active >= XTTS_CONCURRENCY_LIMIT:
            return

        row = None
        try:
            async with self.db_pool.acquire() as conn:
                row = await conn.fetchrow(
                    """
                    SELECT id, user_uuid, priority, reason
                    FROM callback_queue
                    WHERE status = 'pending'
                      AND (scheduled_for IS NULL OR scheduled_for <= NOW())
                    ORDER BY priority ASC, scheduled_for ASC NULLS LAST, id ASC
                    LIMIT 1
                    FOR UPDATE SKIP LOCKED
                    """
                )
                if not row:
                    return
                await conn.execute(
                    "UPDATE callback_queue SET status = 'in_progress', updated_at = NOW() WHERE id = $1",
                    row["id"],
                )
        except Exception as e:
            logger.debug("callback dequeue skipped: %s", e)
            return

        # Placeholder: real implementation dials via Twilio REST with context params.
        logger.info(
            "callback_queue would dial user_uuid=%s id=%s reason=%s (Twilio wiring in ops)",
            row["user_uuid"],
            row["id"],
            (row["reason"] or "")[:80],
        )
        try:
            async with self.db_pool.acquire() as conn:
                await conn.execute(
                    """
                    UPDATE callback_queue SET status = 'completed', updated_at = NOW()
                    WHERE id = $1
                    """,
                    row["id"],
                )
        except Exception as e:
            logger.warning("callback_queue update failed: %s", e)

    async def _maybe_outreach_jitter(self):
        now = datetime.now(timezone.utc)
        if (now - self._last_outreach).total_seconds() < OUTREACH_CYCLE_SEC:
            return
        self._last_outreach = now
        if not self.db_pool:
            return
        # Jittered synthetic batch: log + optional future enqueue when outreach engine is populated
        try:
            n = random.randint(0, 3)
            for i in range(n):
                delay = 6 * (i + 1) + random.randint(0, 2)
                logger.debug("outreach_jitter placeholder spacing=%ss", delay)
            async with self.db_pool.acquire() as conn:
                await conn.execute(
                    """
                    INSERT INTO outreach_events (user_uuid, event_type, payload)
                    VALUES (NULL, 'jitter_cycle', $1::jsonb)
                    """,
                    '{"cycle": true, "queued_stub": true}',
                )
        except Exception as e:
            logger.debug("outreach jitter skipped: %s", e)
