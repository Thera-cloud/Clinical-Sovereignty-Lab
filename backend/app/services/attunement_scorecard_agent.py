"""Nightly attunement scorecard — computed from existing stores only.

QUANTUM-CRYSTAL-ARCH — clinical. SOVEREIGN-STANDARD.
CEO: Nathaniel James Nevedal. Risk: RED (aggregates only, no transcripts).
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger("nate.attunement_scorecard")

_INTERVAL_S = 6 * 3600
_NIGHT_HOUR = 4


class AttunementScorecardAgent:
    def __init__(self, db_pool, app_state=None):
        self.db_pool = db_pool
        self._app_state = app_state
        self._task: Optional[asyncio.Task] = None
        self._running = False
        self._last_date = ""

    async def start(self):
        if self._task and not self._task.done():
            return
        self._running = True
        self._task = asyncio.create_task(self._run_loop())
        logger.info("AttunementScorecardAgent started (nightly 04:00 UTC + 6h tick)")

    async def stop(self):
        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("AttunementScorecardAgent stopped")

    async def _run_loop(self):
        await asyncio.sleep(20)
        try:
            await self.run_cycle(reason="boot")
        except Exception as e:
            logger.warning("AttunementScorecardAgent boot cycle: %s", e)
        while self._running:
            try:
                now = datetime.now(timezone.utc)
                day = now.date().isoformat()
                if now.hour == _NIGHT_HOUR and self._last_date != day:
                    await self.run_cycle(reason="nightly")
                    self._last_date = day
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.error("AttunementScorecardAgent tick failed: %s", e)
            await asyncio.sleep(60)

    async def run_cycle(self, reason: str = "manual") -> dict:
        if not self.db_pool:
            logger.warning("AttunementScorecardAgent: no db_pool — skip")
            return {"ok": False, "reason": "no_db"}
        metrics = await self._compute()
        content = json.dumps({
            "reason": reason,
            "computed_at": datetime.now(timezone.utc).isoformat(),
            **metrics,
        })
        try:
            async with self.db_pool.acquire() as conn:
                await conn.execute(
                    "INSERT INTO skyeye_activity (platform, type, content, severity, created_at) "
                    "VALUES ($1, $2, $3, $4, NOW())",
                    "system", "attunement_scorecard", content[:4000], "info",
                )
        except Exception as e:
            logger.warning("AttunementScorecardAgent write failed: %s", e)
        logger.info("AttunementScorecardAgent wrote scorecard reason=%s", reason)
        return metrics

    async def _compute(self) -> dict:
        sql = """
        WITH recent AS (
            SELECT user_id, user_text, ai_text, session_id, metadata, created_at
            FROM conversation_history
            WHERE created_at > NOW() - INTERVAL '7 days'
              AND LENGTH(COALESCE(user_text, '')) > 0
        )
        SELECT
            COUNT(*)::int AS turns,
            COUNT(*) FILTER (
                WHERE LENGTH(user_text) >= 80 AND LENGTH(COALESCE(ai_text, '')) <= 20
            )::int AS collapse_n,
            AVG(NULLIF((metadata->'attunement'->>'hold_cover')::float, 0)) AS hold_mean,
            AVG(
                CASE WHEN LENGTH(user_text) > 0
                     THEN LENGTH(COALESCE(ai_text, ''))::float / LENGTH(user_text)
                     ELSE NULL END
            ) AS tempo_ratio,
            COUNT(*) FILTER (
                WHERE ai_text ~* '(i hear you|that sounds really hard|what.?s coming up for you)'
            )::int AS boiler_n,
            COUNT(*) FILTER (
                WHERE ai_text ~* '^(hi|hey|hello|welcome back)'
            )::int AS greeting_n,
            COUNT(*) FILTER (
                WHERE ai_text ~* '(i remember|last time you said|you told me)'
                  AND COALESCE(jsonb_array_length(metadata->'crystal_ids'), 0) = 0
            )::int AS memory_claim_n,
            COUNT(*) FILTER (
                WHERE metadata->'attunement'->>'acked_turn_id' IS NOT NULL
            )::int AS acked_n
        FROM recent
        """
        try:
            async with self.db_pool.acquire() as conn:
                row = await conn.fetchrow(sql)
        except Exception as e:
            logger.warning("AttunementScorecardAgent compute: %s", e)
            return {"turns": 0, "error": str(e)[:120]}
        turns = int(row["turns"] or 0)
        collapse_n = int(row["collapse_n"] or 0)
        boiler_n = int(row["boiler_n"] or 0)
        return {
            "turns": turns,
            "collapse_rate": round(collapse_n / turns, 4) if turns else 0.0,
            "hold_cover_mean": round(float(row["hold_mean"] or 0.0), 4),
            "tempo_ratio": round(float(row["tempo_ratio"] or 0.0), 4),
            "boilerplate_per_100": round((boiler_n / turns) * 100, 2) if turns else 0.0,
            "greeting_on_open": int(row["greeting_n"] or 0),
            "memory_claim_violations": int(row["memory_claim_n"] or 0),
            "acked_repairs": int(row["acked_n"] or 0),
        }
