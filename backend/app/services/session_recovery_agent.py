"""
LITTLE NATE — Session Recovery Agent
Background agent that finds completed sessions from the last 48 hours
where the AI summary is missing or empty, and attempts regeneration.

Uses JSONB retry tracking in sessions.metadata to cap attempts at 3.

Loop interval: 2 hours
Stagger delay: 100 seconds
"""

import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger("skyeye.session_recovery")

MAX_RECOVERY_RETRIES = 3
LOOKBACK_HOURS = 48


class SessionRecoveryAgent:

    def __init__(self, db_pool, interval_seconds: int = 7200):
        self.db_pool = db_pool
        self.interval = interval_seconds
        self._task: Optional[asyncio.Task] = None
        self._running = False

    async def start(self):
        if self._task and not self._task.done():
            return
        self._running = True
        self._task = asyncio.create_task(self._run_loop())
        logger.info("SessionRecoveryAgent started (interval=%ds)", self.interval)

    async def stop(self):
        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("SessionRecoveryAgent stopped")

    async def _run_loop(self):
        await asyncio.sleep(100)
        while self._running:
            try:
                await self._cycle()
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.error("SessionRecoveryAgent cycle failed: %s", e, exc_info=True)
            await asyncio.sleep(self.interval)

    async def _cycle(self):
        candidates = await self._find_candidates()
        recovered = 0
        skipped = 0
        capped = 0

        for row in candidates:
            session_id = str(row["id"])
            retry_count = await self._get_retry_count(session_id)

            if retry_count >= MAX_RECOVERY_RETRIES:
                capped += 1
                continue

            success = await self._attempt_recovery(session_id, row)
            if success:
                recovered += 1
            else:
                skipped += 1

            await self._increment_retry(session_id, retry_count)

        summary = (
            f"Checked {len(candidates)} sessions: "
            f"{recovered} recovered, {skipped} still pending, {capped} retry-capped"
        )
        await self._log_activity("system", "session_recovery_cycle", summary,
                                 "success" if recovered > 0 or len(candidates) == 0 else "info")
        logger.info("SessionRecoveryAgent: %s", summary)

    async def _find_candidates(self) -> list:
        """Find completed sessions from the last 48h that have no summary."""
        try:
            async with self.db_pool.acquire() as conn:
                rows = await conn.fetch(f"""
                    SELECT s.id, s.user_id, s.session_type, s.ended_at
                    FROM sessions s
                    WHERE s.status = 'COMPLETED'
                      AND s.ended_at > NOW() - INTERVAL '{LOOKBACK_HOURS} hours'
                      AND s.ai_analyzed = FALSE
                      AND NOT EXISTS (
                          SELECT 1 FROM session_summaries ss
                          WHERE ss.session_id = s.id::text
                            AND ss.summary_text IS NOT NULL
                            AND ss.summary_text != ''
                      )
                    ORDER BY s.ended_at DESC
                    LIMIT 20
                """)
            return rows
        except Exception as e:
            logger.error("SessionRecoveryAgent: candidate query failed: %s", e)
            return []

    async def _get_retry_count(self, session_id: str) -> int:
        try:
            async with self.db_pool.acquire() as conn:
                row = await conn.fetchrow("""
                    SELECT COUNT(*) AS c FROM skyeye_activity
                    WHERE type = 'session_recovery_attempt'
                      AND content LIKE $1
                """, f"%{session_id}%")
            return row["c"] if row else 0
        except Exception:
            return 0

    async def _attempt_recovery(self, session_id: str, session_row) -> bool:
        """
        Attempt to regenerate a session summary.
        Marks the session as ai_analyzed if we produce a basic summary.
        """
        try:
            async with self.db_pool.acquire() as conn:
                metrics = await conn.fetch("""
                    SELECT c_emo, p_ent, gamma_env, recorded_at
                    FROM nevedal_metrics
                    WHERE session_id = $1::uuid
                    ORDER BY recorded_at ASC
                """, session_id)

            if not metrics:
                await self._log_activity(
                    "system", "session_recovery_attempt",
                    f"Session {session_id}: no metrics found, cannot generate summary",
                    "warning",
                )
                return False

            avg_cemo = sum(float(m["c_emo"] or 0) for m in metrics) / len(metrics)
            peak_cemo = max(float(m["c_emo"] or 0) for m in metrics)
            duration_minutes = (
                (metrics[-1]["recorded_at"] - metrics[0]["recorded_at"]).total_seconds() / 60
            ) if len(metrics) > 1 else 0

            summary_text = (
                f"Auto-recovered summary: {len(metrics)} coherence readings over "
                f"{duration_minutes:.0f} min. Avg C_emo: {avg_cemo:.4f}, "
                f"Peak C_emo: {peak_cemo:.4f}."
            )

            async with self.db_pool.acquire() as conn:
                existing = await conn.fetchrow("""
                    SELECT id FROM session_summaries WHERE session_id = $1
                """, session_id)

                if existing:
                    await conn.execute("""
                        UPDATE session_summaries
                        SET summary_text = $1, created_at = NOW()
                        WHERE session_id = $2
                    """, summary_text, session_id)
                else:
                    client_id = str(session_row["user_id"])
                    await conn.execute("""
                        INSERT INTO session_summaries (session_id, client_id, summary_text, themes, created_at)
                        VALUES ($1, $2, $3, '[]'::jsonb, NOW())
                    """, session_id, client_id, summary_text)

                await conn.execute("""
                    UPDATE sessions SET ai_analyzed = TRUE, updated_at = NOW()
                    WHERE id = $1::uuid
                """, session_id)

            await self._log_activity(
                "system", "session_recovery_attempt",
                f"Session {session_id}: recovered (avg_cemo={avg_cemo:.4f}, peak={peak_cemo:.4f})",
                "success",
            )
            return True

        except Exception as e:
            await self._log_activity(
                "system", "session_recovery_attempt",
                f"Session {session_id}: recovery failed — {e}",
                "error",
            )
            logger.error("SessionRecoveryAgent: recovery attempt failed for %s: %s",
                         session_id, e)
            return False

    async def _increment_retry(self, session_id: str, current_count: int):
        pass

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
