"""Dormant daily aggregator for the research schema (Slice 5).

This service is NOT registered in ``_service_checks`` and NOT wired into
``main.py`` — it lands as pure infrastructure. A future slice will schedule
``run_daily_aggregation`` from the maintenance loop once the schema and
pseudonym key have been validated in production.

Contract when flag on
---------------------
- Reads ``public.nevedal_metrics`` for a single UTC day.
- Groups by user_id, computes count/avg/min/max C_emo and CEE window count.
- Writes each aggregate row to ``research.metrics_daily`` with the user's
  HMAC pseudonym. UNIQUE(pseudonym, day, domain_tag) makes retries safe.
- Aggregates ``public.nate_intelligence_crystals`` for the same day into
  ``research.crystal_stats_daily`` by domain (no pseudonym).
- Every run — success, skip, or error — writes a row to
  ``research.aggregation_log``.

Contract when flag off
----------------------
- ``is_enabled()`` returns False, ``run_daily_aggregation`` is a no-op.
- No queries against ``public``. No writes anywhere.
"""

from __future__ import annotations

import logging
import os
from datetime import date, datetime, timedelta, timezone
from typing import Optional

from app.services.research_pseudonym import (
    ResearchKeyMissing,
    pseudonymize,
)

logger = logging.getLogger(__name__)

_ENV_FLAG = "ENABLE_RESEARCH_AGGREGATION"


def is_enabled() -> bool:
    return os.getenv(_ENV_FLAG, "").strip().lower() in ("1", "true", "yes", "on")


def _yesterday_utc() -> date:
    return (datetime.now(timezone.utc) - timedelta(days=1)).date()


async def _log_run(
    db_pool,
    day: date,
    dataset: str,
    rows: int,
    status: str,
    detail: str = "",
) -> None:
    try:
        async with db_pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO research.aggregation_log
                    (day_processed, dataset, rows_written, status, detail)
                VALUES ($1, $2, $3, $4, $5)
                """,
                day,
                dataset,
                rows,
                status,
                detail[:2000],
            )
    except Exception as e:  # pragma: no cover
        logger.warning("research_aggregator: log write failed: %s", e)


async def _aggregate_metrics_daily(db_pool, day: date) -> int:
    async with db_pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT user_id::text AS uid,
                   COUNT(*)::int AS n,
                   AVG(c_emo)::numeric(6,5) AS c_emo_avg,
                   MIN(c_emo)::numeric(6,5) AS c_emo_min,
                   MAX(c_emo)::numeric(6,5) AS c_emo_max,
                   SUM(CASE WHEN cee_window THEN 1 ELSE 0 END)::int AS cee_n
            FROM nevedal_metrics
            WHERE recorded_at >= $1::date
              AND recorded_at <  ($1::date + INTERVAL '1 day')
              AND user_id IS NOT NULL
            GROUP BY user_id
            """,
            day,
        )
    written = 0
    for r in rows:
        pseud = pseudonymize(r["uid"])
        if not pseud:
            continue
        async with db_pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO research.metrics_daily
                    (pseudonym, day, sample_count, c_emo_avg, c_emo_min,
                     c_emo_max, cee_windows, domain_tag)
                VALUES ($1, $2, $3, $4, $5, $6, $7, 'general')
                ON CONFLICT (pseudonym, day, domain_tag) DO UPDATE SET
                    sample_count = EXCLUDED.sample_count,
                    c_emo_avg    = EXCLUDED.c_emo_avg,
                    c_emo_min    = EXCLUDED.c_emo_min,
                    c_emo_max    = EXCLUDED.c_emo_max,
                    cee_windows  = EXCLUDED.cee_windows
                """,
                pseud,
                day,
                r["n"],
                r["c_emo_avg"],
                r["c_emo_min"],
                r["c_emo_max"],
                r["cee_n"],
            )
        written += 1
    return written


async def _aggregate_crystal_stats_daily(db_pool, day: date) -> int:
    async with db_pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT COALESCE(domain, 'general') AS domain,
                   COUNT(*)::int AS created,
                   SUM(CASE WHEN superseded_by IS NOT NULL THEN 1 ELSE 0 END)::int AS superseded,
                   AVG(confidence)::numeric(6,5) AS avg_conf
            FROM nate_intelligence_crystals
            WHERE created_at >= $1::date
              AND created_at <  ($1::date + INTERVAL '1 day')
            GROUP BY COALESCE(domain, 'general')
            """,
            day,
        )
    written = 0
    for r in rows:
        async with db_pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO research.crystal_stats_daily
                    (day, domain, crystals_created, crystals_superseded, avg_confidence)
                VALUES ($1, $2, $3, $4, $5)
                ON CONFLICT (day, domain) DO UPDATE SET
                    crystals_created    = EXCLUDED.crystals_created,
                    crystals_superseded = EXCLUDED.crystals_superseded,
                    avg_confidence      = EXCLUDED.avg_confidence
                """,
                day,
                r["domain"],
                r["created"],
                r["superseded"],
                r["avg_conf"],
            )
        written += 1
    return written


async def run_daily_aggregation(db_pool, day: Optional[date] = None) -> dict:
    """Aggregate one UTC day into ``research.*``. Idempotent.

    Returns a small dict describing what was written. Never raises — errors
    are logged both to ``research.aggregation_log`` and the module logger.
    """
    if not is_enabled():
        return {"status": "skipped", "reason": "flag off"}
    if db_pool is None:
        return {"status": "skipped", "reason": "no db_pool"}

    day = day or _yesterday_utc()
    result = {"day": day.isoformat(), "metrics_rows": 0, "crystal_rows": 0}

    try:
        result["metrics_rows"] = await _aggregate_metrics_daily(db_pool, day)
        await _log_run(db_pool, day, "metrics_daily", result["metrics_rows"], "ok")
    except ResearchKeyMissing as e:
        await _log_run(db_pool, day, "metrics_daily", 0, "skipped", str(e))
        result["metrics_status"] = "skipped_no_key"
    except Exception as e:
        logger.exception("research_aggregator: metrics_daily failed")
        await _log_run(db_pool, day, "metrics_daily", 0, "error", str(e))
        result["metrics_status"] = f"error: {e}"

    try:
        result["crystal_rows"] = await _aggregate_crystal_stats_daily(db_pool, day)
        await _log_run(db_pool, day, "crystal_stats_daily", result["crystal_rows"], "ok")
    except Exception as e:
        logger.exception("research_aggregator: crystal_stats_daily failed")
        await _log_run(db_pool, day, "crystal_stats_daily", 0, "error", str(e))
        result["crystal_status"] = f"error: {e}"

    result.setdefault("status", "ok")
    return result
