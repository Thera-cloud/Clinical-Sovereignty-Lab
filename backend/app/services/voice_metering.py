"""
Per-user monthly voice minute entitlement (Sovereign Voice v3.1).
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Dict, Optional, Tuple

logger = logging.getLogger("nate.voice_metering")

# Hard cap per single call (seconds) by tier — Grok Realtime + XTTS cost control.
# Maps product tiers on `users.tier` / profile_data. ADMIN still capped (safety).
TIER_MAX_SINGLE_CALL_SECONDS: Dict[str, int] = {
    "TRIAL": 300,  # 5 min
    "THRESHOLD": 300,
    "STANDARD": 900,  # 15 min
    "INNER_CHAMBER": 1800,  # 30 min
    "SOVEREIGN_CIRCLE": 3600,  # 60 min
    "COACH_ONLY": 3600,
    "ADMIN": 7200,  # 2 h safety cap
    "CLIENT": 900,
}

DEFAULT_MAX_SINGLE_CALL_SECONDS = 900

# Seconds before hard hangup when Nathan plays the wrap-up line (not shorter than call).
CALL_DURATION_WARNING_BEFORE_END_SEC = 120

VOICE_CALL_WRAP_UP_MESSAGE = (
    "We're getting close to the end of our time today. "
    "Let's wrap up with what feels most important."
)

# Minutes per calendar month by subscription tier (product sheet should match).
TIER_VOICE_MINUTES: Dict[str, Optional[float]] = {
    "TRIAL": 30.0,
    "THRESHOLD": 15.0,
    "STANDARD": 120.0,
    "INNER_CHAMBER": 120.0,
    "SOVEREIGN_CIRCLE": 600.0,
    "COACH_ONLY": 180.0,
    "ADMIN": None,
    "CLIENT": 120.0,
}


def _year_month_utc() -> str:
    now = datetime.now(timezone.utc)
    return f"{now.year:04d}-{now.month:02d}"


def tier_minute_limit(tier: Optional[str]) -> Optional[float]:
    """None = unlimited."""
    if not tier:
        return TIER_VOICE_MINUTES.get("STANDARD")
    t = tier.strip().upper()
    return TIER_VOICE_MINUTES.get(t, TIER_VOICE_MINUTES.get("STANDARD"))


def max_single_call_seconds(tier: Optional[str]) -> int:
    """Maximum duration for one Twilio media-stream call (enforced server-side)."""
    if not tier:
        return DEFAULT_MAX_SINGLE_CALL_SECONDS
    t = tier.strip().upper()
    return TIER_MAX_SINGLE_CALL_SECONDS.get(t, DEFAULT_MAX_SINGLE_CALL_SECONDS)


async def get_monthly_minutes_used(pool, user_uuid: str) -> float:
    if not pool:
        return 0.0
    ym = _year_month_utc()
    try:
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT minutes_used FROM voice_call_usage
                WHERE user_uuid = $1::uuid AND year_month = $2
                """,
                user_uuid,
                ym,
            )
        if not row:
            return 0.0
        return float(row["minutes_used"] or 0)
    except Exception as e:
        logger.warning("get_monthly_minutes_used: %s", e)
        return 0.0


async def _has_prepaid_account(pool, user_uuid: str) -> Optional[int]:
    """Check for prepaid voice account; returns balance_seconds or None."""
    try:
        async with pool.acquire() as conn:
            bal = await conn.fetchval(
                "SELECT balance_seconds FROM voice_accounts WHERE user_id = $1",
                user_uuid,
            )
        return bal
    except Exception:
        return None


async def check_voice_entitlement(pool, user_uuid: str, tier: Optional[str]) -> Tuple[bool, str]:
    """
    Returns (allowed, reason). reason is ok|no_pool|over_quota|unlimited|prepaid
    Checks prepaid voice_accounts first; falls back to tier-based monthly quota.
    """
    if not pool:
        return True, "no_pool"

    # SOVEREIGN-VOICE: check prepaid account first
    prepaid_bal = await _has_prepaid_account(pool, user_uuid)
    if prepaid_bal is not None:
        if prepaid_bal > 0:
            return True, "prepaid"
        return False, "over_quota"

    limit = tier_minute_limit(tier)
    if limit is None:
        return True, "unlimited"
    used = await get_monthly_minutes_used(pool, user_uuid)
    if used >= limit:
        return False, "over_quota"
    return True, "ok"


async def add_voice_minutes(pool, user_uuid: str, minutes: float) -> None:
    """
    Record used voice minutes. If a prepaid voice account exists,
    deduction is handled by the billing loop — just log to voice_call_usage.
    Falls back to tier-based monthly tracking otherwise.
    """
    if not pool or minutes <= 0:
        return
    ym = _year_month_utc()
    try:
        async with pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO voice_call_usage (user_uuid, year_month, minutes_used, updated_at)
                VALUES ($1::uuid, $2, $3::numeric, NOW())
                ON CONFLICT (user_uuid, year_month) DO UPDATE SET
                    minutes_used = voice_call_usage.minutes_used + EXCLUDED.minutes_used,
                    updated_at = NOW()
                """,
                user_uuid,
                ym,
                Decimal(str(round(minutes, 4))),
            )
    except Exception as e:
        logger.warning("add_voice_minutes: %s", e)
