"""
LITTLE NATE — Silence Sentinel Agent
Monitors the rhythm of Little Nate's social presence. Detects when silence
becomes disappearance vs. when silence is doing productive work (engagement
still flows inbound despite no new posts). Flags anxiety-driven posting
bursts that follow long silences.

No Azure calls — pure SQL/time math.

Stagger delay: 290s. Loop interval: 30 minutes.
"""

import asyncio
import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

logger = logging.getLogger("nate.silence_sentinel")

POLL_INTERVAL_SECONDS = 1800  # 30 minutes
STAGGER_DELAY = 290

GREEN_THRESHOLD_HOURS = 12
YELLOW_THRESHOLD_HOURS = 48
BURST_WINDOW_HOURS = 1
BURST_MIN_POSTS = 3


class SilenceSentinel:
    def __init__(self, db_pool):
        self.db_pool = db_pool
        self._task: Optional[asyncio.Task] = None
        self._running = False

    async def start(self):
        if self._task and not self._task.done():
            return
        self._running = True
        self._task = asyncio.create_task(self._run_loop())
        logger.info("SilenceSentinel started (every 30min, stagger 290s)")

    async def stop(self):
        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("SilenceSentinel stopped")

    async def _run_loop(self):
        await asyncio.sleep(STAGGER_DELAY)
        while self._running:
            try:
                await self._analyze()
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.error("SilenceSentinel tick failed: %s", e, exc_info=True)
            await asyncio.sleep(POLL_INTERVAL_SECONDS)

    async def _analyze(self):
        now = datetime.now(timezone.utc)
        async with self.db_pool.acquire() as conn:
            last_post_at = await conn.fetchval("""
                SELECT MAX(posted_at)
                FROM skyeye_content_queue
                WHERE status = 'posted' AND posted_at IS NOT NULL
            """)

            last_inbound_at = await conn.fetchval("""
                SELECT MAX(created_at)
                FROM skyeye_notifications
                WHERE created_at IS NOT NULL
            """)

            last_outbound_at = await conn.fetchval("""
                SELECT MAX(created_at)
                FROM skyeye_social_interactions
                WHERE created_at IS NOT NULL
            """)

            burst_count = await conn.fetchval("""
                SELECT COUNT(*)
                FROM skyeye_content_queue
                WHERE status = 'posted'
                  AND posted_at > $1
                  AND posted_at IS NOT NULL
            """, now - timedelta(hours=BURST_WINDOW_HOURS))

        silence_hours = self._hours_since(last_post_at, now)
        inbound_hours = self._hours_since(last_inbound_at, now)
        outbound_hours = self._hours_since(last_outbound_at, now)

        burst_detected = False
        if silence_hours is not None and silence_hours < BURST_WINDOW_HOURS:
            if burst_count and burst_count >= BURST_MIN_POSTS:
                prev_post = await self._previous_post_gap(now)
                if prev_post is not None and prev_post > GREEN_THRESHOLD_HOURS:
                    burst_detected = True

        signal, detail = self._classify(
            silence_hours, inbound_hours, outbound_hours, burst_detected,
        )

        score = {"GREEN": 1.0, "YELLOW": 0.5, "RED": 0.0}[signal]

        metadata = {
            "silence_hours": round(silence_hours, 1) if silence_hours is not None else None,
            "inbound_hours": round(inbound_hours, 1) if inbound_hours is not None else None,
            "outbound_hours": round(outbound_hours, 1) if outbound_hours is not None else None,
            "burst_detected": burst_detected,
            "burst_count": burst_count or 0,
        }

        async with self.db_pool.acquire() as conn:
            await conn.execute("""
                INSERT INTO liminal_presence_analysis
                    (agent, signal, score, detail, metadata, created_at)
                VALUES ($1, $2, $3, $4, $5, NOW())
            """, "silence_sentinel", signal, score, detail,
                json.dumps(metadata))

        logger.info("SilenceSentinel: %s — %s", signal, detail)

    def _hours_since(self, ts: Optional[datetime], now: datetime) -> Optional[float]:
        if ts is None:
            return None
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        delta = (now - ts).total_seconds() / 3600.0
        return max(delta, 0.0)

    def _classify(
        self,
        silence_h: Optional[float],
        inbound_h: Optional[float],
        outbound_h: Optional[float],
        burst: bool,
    ) -> tuple:
        if burst:
            return "YELLOW", "Anxiety-driven burst detected — multiple posts after long silence"

        if silence_h is None:
            return "YELLOW", "No posting history found — pipeline may be new"

        has_recent_inbound = inbound_h is not None and inbound_h < GREEN_THRESHOLD_HOURS

        if silence_h < GREEN_THRESHOLD_HOURS:
            return "GREEN", f"Last post {silence_h:.0f}h ago — active presence"

        if has_recent_inbound and silence_h < YELLOW_THRESHOLD_HOURS:
            return "GREEN", (
                f"Silent for {silence_h:.0f}h but engagement inbound "
                f"({inbound_h:.0f}h ago) — silence is doing work"
            )

        if silence_h < YELLOW_THRESHOLD_HOURS:
            return "YELLOW", f"Silent for {silence_h:.0f}h with declining engagement — drifting"

        if has_recent_inbound:
            return "YELLOW", (
                f"Silent for {silence_h:.0f}h but still receiving engagement — "
                f"approaching disappearance threshold"
            )

        return "RED", f"Silent for {silence_h:.0f}h with zero engagement signals — becoming disappearance"

    async def _previous_post_gap(self, now: datetime) -> Optional[float]:
        """Hours between the 2nd-most-recent post and now, to detect gap before burst."""
        async with self.db_pool.acquire() as conn:
            second_latest = await conn.fetchval("""
                SELECT posted_at
                FROM skyeye_content_queue
                WHERE status = 'posted' AND posted_at IS NOT NULL
                ORDER BY posted_at DESC
                OFFSET 3 LIMIT 1
            """)
        if second_latest is None:
            return None
        return self._hours_since(second_latest, now)

    def get_chat_context(self) -> str:
        """Synchronous stub — actual context pulled by skyeye_chat from DB."""
        return ""
