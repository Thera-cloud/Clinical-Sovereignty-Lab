"""Emit anonymized try theme counts after a verified public trial turn.

# QUANTUM-CRYSTAL-ARCH
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timezone
from typing import Any, Optional

from app.services.growth import try_theme_telemetry_enabled
from app.services.growth.try_theme_classifier import classify_try_theme

logger = logging.getLogger("nate.growth.try_theme")


def _week_bucket(d: Optional[date] = None) -> date:
    d = d or datetime.now(timezone.utc).date()
    return d.fromordinal(d.toordinal() - d.weekday())


async def emit_try_theme(db_pool, user_text: str) -> dict[str, Any]:
    """Classify then upsert. Never logs user_text. Crisis → ops_only (no write)."""
    if not try_theme_telemetry_enabled():
        return {"skipped": True, "reason": "flag_off"}
    if not db_pool:
        return {"skipped": True, "reason": "no_db"}

    theme = classify_try_theme(user_text)
    # Discard utterance reference ASAP — callers should not reuse after await.
    user_text = ""  # noqa: F841 — intentional scrub

    if theme is None:
        return {"ok": True, "theme": None, "upserted": False}
    if theme == "ops_only":
        return {"ok": True, "theme": "ops_only", "upserted": False}

    week = _week_bucket()
    try:
        async with db_pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO try_theme_weekly (theme, week_bucket, count_bucket)
                VALUES ($1, $2, 1)
                ON CONFLICT (theme, week_bucket) DO UPDATE SET
                    count_bucket = try_theme_weekly.count_bucket + 1,
                    updated_at = NOW()
                """,
                theme,
                week,
            )
        return {"ok": True, "theme": theme, "upserted": True, "week_bucket": week.isoformat()}
    except Exception as e:
        # Never include utterance in this log
        logger.warning("try_theme upsert failed theme=%s: %s", theme, e)
        return {"ok": False, "theme": theme, "error": "upsert_failed"}


async def list_try_themes(db_pool, *, weeks: int = 4, limit: int = 40) -> list:
    async with db_pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT theme, SUM(count_bucket)::int AS total, MAX(week_bucket) AS last_week
            FROM try_theme_weekly
            WHERE week_bucket >= (CURRENT_DATE - ($1::int * 7))
            GROUP BY theme
            ORDER BY total DESC
            LIMIT $2
            """,
            max(1, int(weeks)),
            min(max(limit, 1), 100),
        )
    out = []
    for r in rows:
        d = dict(r)
        if hasattr(d.get("last_week"), "isoformat"):
            d["last_week"] = d["last_week"].isoformat()
        out.append(d)
    return out
