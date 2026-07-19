"""Aggregated Dispatch topic signals (never raw clinical transcripts).

# QUANTUM-CRYSTAL-ARCH — Little Nate Dispatch
"""
from __future__ import annotations

import logging
import re
from datetime import date, datetime, timezone
from typing import Optional

logger = logging.getLogger("nate.newsletter_signals")

_THEME_RE = re.compile(r"[^a-z0-9 _-]{1,}", re.I)


def _normalize_theme(theme: str) -> str:
    t = _THEME_RE.sub(" ", (theme or "").strip().lower())
    t = re.sub(r"\s+", " ", t).strip()[:120]
    return t or "steadiness"


async def record_theme_signal(
    db_pool,
    theme: str,
    *,
    source: str = "feedback",
    week: Optional[date] = None,
) -> bool:
    """Upsert weekly theme bucket. Sources: feedback | library | forecast | hive."""
    if not db_pool:
        return False
    theme_n = _normalize_theme(theme)
    if len(theme_n) < 3:
        return False
    week_bucket = week or date.fromtimestamp(
        datetime.now(timezone.utc).timestamp()
    )
    # Monday of ISO week
    week_bucket = week_bucket.fromordinal(week_bucket.toordinal() - week_bucket.weekday())
    try:
        async with db_pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO newsletter_chat_signals (theme, week_bucket, count_bucket)
                VALUES ($1, $2, 1)
                ON CONFLICT (theme, week_bucket) DO UPDATE SET
                    count_bucket = newsletter_chat_signals.count_bucket + 1,
                    updated_at = NOW()
                """,
                theme_n,
                week_bucket,
            )
        return True
    except Exception as e:
        logger.warning("record_theme_signal (%s): %s", source, e)
        return False


async def bump_growth_ledger(
    db_pool,
    channel: str,
    *,
    subscribers_gained: int = 0,
    invites_sent: int = 0,
    conversions: int = 0,
) -> None:
    if not db_pool or not channel:
        return
    day = datetime.now(timezone.utc).date()
    try:
        async with db_pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO newsletter_growth_ledger
                    (day, channel, subscribers_gained, invites_sent, conversions)
                VALUES ($1, $2, $3, $4, $5)
                ON CONFLICT (day, channel) DO UPDATE SET
                    subscribers_gained = newsletter_growth_ledger.subscribers_gained + EXCLUDED.subscribers_gained,
                    invites_sent = newsletter_growth_ledger.invites_sent + EXCLUDED.invites_sent,
                    conversions = newsletter_growth_ledger.conversions + EXCLUDED.conversions
                """,
                day,
                channel[:64],
                max(0, subscribers_gained),
                max(0, invites_sent),
                max(0, conversions),
            )
    except Exception as e:
        logger.warning("bump_growth_ledger: %s", e)


async def upsert_topic_forecast(
    db_pool,
    topic_key: str,
    *,
    seasonal_label: Optional[str] = None,
    foresight_score: float = 0.5,
    news_velocity: float = 0.0,
) -> None:
    if not db_pool or not topic_key:
        return
    from datetime import timedelta

    target = datetime.now(timezone.utc).date() + timedelta(days=7)
    try:
        async with db_pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO newsletter_topic_forecast
                    (topic_key, seasonal_label, target_week, news_velocity, foresight_score)
                VALUES ($1, $2, $3, $4, $5)
                """,
                topic_key[:64],
                seasonal_label,
                target,
                float(news_velocity),
                float(foresight_score),
            )
    except Exception as e:
        logger.warning("upsert_topic_forecast: %s", e)
