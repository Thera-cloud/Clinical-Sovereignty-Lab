"""Weekly BWAS rollup from lead_events × growth_config.bwas_stage_weights.

# QUANTUM-CRYSTAL-ARCH
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Dict, List, Optional

from app.services.growth import bwas_enabled

logger = logging.getLogger("nate.growth.bwas")

_DEFAULT_WEIGHTS = {
    "impression": 0.05,
    "engage": 0.10,
    "click": 0.15,
    "quiz_start": 0.20,
    "quiz_complete": 0.25,
    "signup": 0.40,
    "active_client": 1.0,
}


class BwasWorker:
    def __init__(self, db_pool, *, interval_s: int = 3600):
        self.db_pool = db_pool
        self.interval_s = interval_s
        self._task: Optional[asyncio.Task] = None
        self._running = False
        self.last_run: Dict[str, Any] = {"status": "init"}

    async def start(self) -> None:
        if not bwas_enabled():
            logger.info("BwasWorker not started (ENABLE_BWAS=false)")
            return
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._loop())
        logger.info("BwasWorker started (interval=%ss)", self.interval_s)

    async def stop(self) -> None:
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

    async def _loop(self) -> None:
        while self._running:
            try:
                self.last_run = await self.tick()
            except Exception as e:
                logger.warning("BwasWorker tick failed: %s", e)
                self.last_run = {"status": "error", "error": str(e)[:200]}
            await asyncio.sleep(self.interval_s)

    async def _weights(self, conn) -> Dict[str, float]:
        row = await conn.fetchrow(
            "SELECT value FROM growth_config WHERE key = 'bwas_stage_weights'"
        )
        w = dict(_DEFAULT_WEIGHTS)
        if row and isinstance(row["value"], dict):
            for k, v in row["value"].items():
                try:
                    w[str(k)] = float(v)
                except (TypeError, ValueError):
                    pass
        return w

    async def tick(self, *, weeks: int = 1) -> Dict[str, Any]:
        if not bwas_enabled():
            return {"skipped": True}
        now = datetime.now(timezone.utc).date()
        # Monday-start week bucket
        week_start = now - timedelta(days=now.weekday())
        buckets = [week_start - timedelta(days=7 * i) for i in range(max(1, weeks))]
        upserted = 0
        async with self.db_pool.acquire() as conn:
            weights = await self._weights(conn)
            for bucket in buckets:
                bucket_end = bucket + timedelta(days=7)
                rows = await conn.fetch(
                    """
                    SELECT
                        COALESCE(audience, 'general') AS audience,
                        COALESCE(content_kind, 'marketing') AS content_kind,
                        COALESCE(content_id, 0) AS content_id,
                        stage,
                        COUNT(*)::int AS n
                    FROM lead_events
                    WHERE created_at >= $1::date
                      AND created_at < $2::date
                      AND content_id IS NOT NULL
                    GROUP BY 1, 2, 3, stage
                    """,
                    bucket,
                    bucket_end,
                )
                # group by audience/kind/id
                groups: Dict[tuple, Dict[str, int]] = {}
                for r in rows:
                    key = (r["audience"], r["content_kind"], int(r["content_id"]))
                    groups.setdefault(key, {})[r["stage"]] = int(r["n"])
                for (audience, kind, cid), counts in groups.items():
                    score = 0.0
                    for stage, n in counts.items():
                        score += float(weights.get(stage, 0)) * n
                    await conn.execute(
                        """
                        INSERT INTO bwas_weekly (
                            week_bucket, audience, content_kind, content_id,
                            score, stage_counts, updated_at
                        ) VALUES ($1,$2,$3,$4,$5,$6::jsonb, NOW())
                        ON CONFLICT (week_bucket, audience, content_kind, content_id)
                        DO UPDATE SET
                            score = EXCLUDED.score,
                            stage_counts = EXCLUDED.stage_counts,
                            updated_at = NOW()
                        """,
                        bucket,
                        audience,
                        kind,
                        cid,
                        score,
                        json.dumps(counts),
                    )
                    upserted += 1
        result = {
            "status": "ok",
            "upserted": upserted,
            "week_bucket": week_start.isoformat(),
        }
        self.last_run = result
        return result


async def list_bwas(
    db_pool, *, weeks: int = 4, limit: int = 50
) -> List[Dict[str, Any]]:
    async with db_pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT * FROM bwas_weekly
            WHERE week_bucket >= (CURRENT_DATE - ($1::text || ' weeks')::interval)::date
            ORDER BY score DESC, week_bucket DESC
            LIMIT $2
            """,
            str(max(1, weeks)),
            min(max(limit, 1), 200),
        )
    out = []
    for r in rows:
        d = dict(r)
        for k, v in list(d.items()):
            if isinstance(v, Decimal):
                d[k] = float(v)
            elif isinstance(v, date):
                d[k] = v.isoformat()
            elif hasattr(v, "isoformat"):
                d[k] = v.isoformat()
        out.append(d)
    return out


async def funnel_ranked(db_pool, *, weeks: int = 4, limit: int = 40) -> List[Dict[str, Any]]:
    """Aggregate BWAS score across recent weeks per content."""
    async with db_pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT content_kind, content_id, audience,
                   SUM(score)::float AS total_score,
                   COUNT(*)::int AS week_count
            FROM bwas_weekly
            WHERE week_bucket >= (CURRENT_DATE - ($1::text || ' weeks')::interval)::date
            GROUP BY content_kind, content_id, audience
            ORDER BY total_score DESC
            LIMIT $2
            """,
            str(max(1, weeks)),
            min(max(limit, 1), 200),
        )
    return [dict(r) for r in rows]
