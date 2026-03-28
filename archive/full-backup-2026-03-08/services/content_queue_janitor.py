"""
LITTLE NATE — Content Queue Janitor
Background agent that keeps the skyeye_content_queue clean and actionable.

Runs every 6 hours and:
  1. Archives posts that have exhausted their retry budget (retry_count >= 3).
  2. Detects repeated identical errors across platforms (root cause patterns).
  3. Logs a cycle summary to skyeye_activity for dashboard visibility.

This prevents the failed-post table from growing unboundedly and surfaces
the real reasons posts keep failing (permissions, billing, API limitations).
"""

import asyncio
import logging
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger("skyeye.content_queue_janitor")

MAX_RETRIES = 3
PATTERN_THRESHOLD = 10


class ContentQueueJanitor:

    def __init__(self, db_pool, interval_seconds: int = 21600):
        self.db_pool = db_pool
        self.interval = interval_seconds
        self._task: Optional[asyncio.Task] = None
        self._running = False

    async def start(self):
        if self._task and not self._task.done():
            return
        self._running = True
        self._task = asyncio.create_task(self._run_loop())
        logger.info("ContentQueueJanitor started (interval=%ds)", self.interval)

    async def stop(self):
        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("ContentQueueJanitor stopped")

    async def _run_loop(self):
        await asyncio.sleep(70)
        while self._running:
            try:
                await self._cycle()
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.error("ContentQueueJanitor cycle failed: %s", e, exc_info=True)
            await asyncio.sleep(self.interval)

    async def _cycle(self):
        archived = await self._archive_exhausted()
        patterns = await self._detect_error_patterns()
        stats = await self._queue_stats()

        summary_parts = [f"Archived {archived} exhausted posts"]
        if patterns:
            summary_parts.append(f"{len(patterns)} recurring error pattern(s) detected")
        summary_parts.append(
            f"Queue: {stats.get('failed', 0)} failed, "
            f"{stats.get('approved', 0)} approved, "
            f"{stats.get('posted', 0)} posted, "
            f"{stats.get('archived', 0)} archived"
        )
        summary = "; ".join(summary_parts)

        await self._log_activity("system", "janitor_cycle", summary, "success" if archived == 0 and not patterns else "info")
        logger.info("ContentQueueJanitor: %s", summary)

    async def _archive_exhausted(self) -> int:
        try:
            async with self.db_pool.acquire() as conn:
                result = await conn.execute("""
                    UPDATE skyeye_content_queue
                    SET status = 'archived', updated_at = NOW()
                    WHERE status = 'failed'
                      AND COALESCE((cross_thread_refs->>'retry_count')::int, 0) >= $1
                """, MAX_RETRIES)
            return int(result.split()[-1]) if result else 0
        except Exception as e:
            logger.error("ContentQueueJanitor: archive query failed: %s", e)
            return 0

    async def _detect_error_patterns(self) -> list:
        try:
            async with self.db_pool.acquire() as conn:
                rows = await conn.fetch("""
                    SELECT platform, LEFT(error_message, 80) AS error_pattern, COUNT(*) AS cnt
                    FROM skyeye_content_queue
                    WHERE status = 'failed'
                      AND error_message IS NOT NULL
                      AND updated_at > NOW() - INTERVAL '7 days'
                    GROUP BY platform, LEFT(error_message, 80)
                    HAVING COUNT(*) >= $1
                    ORDER BY cnt DESC
                    LIMIT 10
                """, PATTERN_THRESHOLD)

            patterns = []
            for row in rows:
                patterns.append({
                    "platform": row["platform"],
                    "error": row["error_pattern"],
                    "count": row["cnt"],
                })
                await self._log_activity(
                    row["platform"], "platform_health_alert",
                    f"Recurring failure ({row['cnt']}x in 7d): {row['error_pattern']}",
                    severity="warning",
                )
            return patterns
        except Exception as e:
            logger.error("ContentQueueJanitor: pattern detection failed: %s", e)
            return []

    async def _queue_stats(self) -> dict:
        try:
            async with self.db_pool.acquire() as conn:
                rows = await conn.fetch("""
                    SELECT status, COUNT(*) AS cnt
                    FROM skyeye_content_queue
                    GROUP BY status
                """)
            return {r["status"]: r["cnt"] for r in rows}
        except Exception:
            return {}

    async def _log_activity(self, platform: str, activity_type: str,
                            content: str, severity: str = "info"):
        try:
            async with self.db_pool.acquire() as conn:
                await conn.execute("""
                    INSERT INTO skyeye_activity (platform, type, content, severity, created_at)
                    VALUES ($1, $2, $3, $4, NOW())
                """, platform, activity_type, content, severity)
        except Exception:
            pass
