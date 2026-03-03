"""
HIVE DEFENSE v4.0 — Tier Enforcement & Usage Metering
Server-side tier gating and atomic usage metering.

TierEnforcement: Decorator to restrict endpoints by subscription tier.
UsageMeter: Atomic check-and-increment for metered features.
"""

import functools
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set

from fastapi import HTTPException

_logger = logging.getLogger("tier_enforcement")

# ─── Tier Definitions ─────────────────────────────────────────────────────────

TIER_LEVELS = {
    "threshold": 0,       # Free trial
    "trial": 0,           # Alias
    "coach_only": 0,      # Alias
    "inner_chamber": 1,   # $49/mo
    "standard": 1,        # Alias
    "sovereign_circle": 2,  # $149/mo
    "top_tier": 2,        # Alias
    "top": 2,             # Alias
}

# Feature limits per tier (monthly)
TIER_LIMITS: Dict[str, Dict[str, Any]] = {
    "threshold": {
        "ai_session_minutes": 60,
        "coach_sessions": 0,
        "family_members": 0,
        "legacy_vault_gb": 0,
        "me2me_hours": 0,
        "night_school_mb": 50,
        "nevedal_reports": 1,
        "foresight_reports": 0,
        "voice_analysis_minutes": 10,
    },
    "inner_chamber": {
        "ai_session_minutes": 600,
        "coach_sessions": 4,
        "family_members": 0,
        "legacy_vault_gb": 5,
        "me2me_hours": 10,
        "night_school_mb": 500,
        "nevedal_reports": 10,
        "foresight_reports": 5,
        "voice_analysis_minutes": 120,
    },
    "sovereign_circle": {
        "ai_session_minutes": -1,  # unlimited
        "coach_sessions": -1,
        "family_members": 5,
        "legacy_vault_gb": 100,
        "me2me_hours": -1,
        "night_school_mb": -1,
        "nevedal_reports": -1,
        "foresight_reports": -1,
        "voice_analysis_minutes": -1,
    },
}


_TIER_LIMIT_ALIAS = {
    "standard": "inner_chamber",
    "top_tier": "sovereign_circle",
    "top": "sovereign_circle",
    "trial": "threshold",
    "coach_only": "threshold",
}


def _resolve_tier_key(tier: str) -> str:
    """Map any tier alias to its TIER_LIMITS key."""
    key = tier.lower().replace(" ", "_")
    return _TIER_LIMIT_ALIAS.get(key, key)


class TierEnforcement:
    """Server-side tier gating for API endpoints."""

    @staticmethod
    def require_tier(minimum_tier: str):
        """
        Decorator: require the user to be at least `minimum_tier`.
        Must be used on endpoints that receive `user` from Depends(get_current_user).
        """
        min_level = TIER_LEVELS.get(minimum_tier.lower().replace(" ", "_"), 0)

        def decorator(func):
            @functools.wraps(func)
            async def wrapper(*args, **kwargs):
                user = kwargs.get("user") or kwargs.get("current_user")
                if not user:
                    raise HTTPException(status_code=401, detail="Authentication required")

                user_tier = "threshold"
                if isinstance(user, dict):
                    user_tier = user.get("tier", user.get("subscription_tier", "threshold"))
                elif hasattr(user, "tier"):
                    user_tier = getattr(user, "tier", "threshold")

                user_tier = user_tier.lower().replace(" ", "_")
                user_level = TIER_LEVELS.get(user_tier, 0)

                if user_level < min_level:
                    raise HTTPException(
                        status_code=403,
                        detail=f"This feature requires {minimum_tier} tier or above",
                    )
                return await func(*args, **kwargs)
            return wrapper
        return decorator

    @staticmethod
    def get_limit(tier: str, feature: str) -> int:
        """Get the limit for a specific feature at a given tier. -1 means unlimited."""
        tier_key = _resolve_tier_key(tier)
        limits = TIER_LIMITS.get(tier_key, TIER_LIMITS["threshold"])
        return limits.get(feature, 0)


class UsageMeter:
    """Atomic usage metering backed by PostgreSQL."""

    def __init__(self, db_pool):
        self._db = db_pool

    async def check_and_increment(
        self, user_id: str, feature: str, quantity: float = 1.0, tier: str = "threshold"
    ) -> Dict[str, Any]:
        """
        Atomically check and increment usage for a feature.
        Returns {"allowed": bool, "current": float, "limit": float, "remaining": float}.
        """
        limit = TierEnforcement.get_limit(tier, feature)
        billing_month = datetime.now(timezone.utc).strftime("%Y-%m")

        if limit == -1:
            # Unlimited — just record usage
            await self._increment(user_id, feature, billing_month, quantity, None)
            return {"allowed": True, "current": quantity, "limit": -1, "remaining": -1}

        if limit == 0:
            return {"allowed": False, "current": 0, "limit": 0, "remaining": 0}

        # Atomic check-and-increment using PostgreSQL
        try:
            row = await self._db.fetchrow(
                """
                INSERT INTO usage_meters (user_id, feature, billing_month, current_usage, max_limit, updated_at)
                VALUES ($1, $2, $3, $4, $5, NOW())
                ON CONFLICT (user_id, feature, billing_month)
                DO UPDATE SET
                    current_usage = usage_meters.current_usage + $4,
                    max_limit = GREATEST(usage_meters.max_limit, $5),
                    updated_at = NOW()
                WHERE usage_meters.current_usage + $4 <= $5
                RETURNING current_usage, max_limit
                """,
                user_id, feature, billing_month, quantity, float(limit),
            )

            if row is None:
                # Usage would exceed limit — fetch current
                current_row = await self._db.fetchrow(
                    "SELECT current_usage FROM usage_meters WHERE user_id=$1 AND feature=$2 AND billing_month=$3",
                    user_id, feature, billing_month,
                )
                current = current_row["current_usage"] if current_row else 0
                return {
                    "allowed": False,
                    "current": current,
                    "limit": float(limit),
                    "remaining": max(0, float(limit) - current),
                }

            return {
                "allowed": True,
                "current": row["current_usage"],
                "limit": row["max_limit"],
                "remaining": max(0, row["max_limit"] - row["current_usage"]),
            }
        except Exception as exc:
            _logger.error("UsageMeter error: %s", exc)
            # Fail open but log — don't block users on meter failure
            return {"allowed": True, "current": 0, "limit": float(limit), "remaining": float(limit), "error": str(exc)}

    async def _increment(
        self, user_id: str, feature: str, billing_month: str,
        quantity: float, max_limit: Optional[float],
    ) -> None:
        """Increment usage without a limit check."""
        try:
            await self._db.execute(
                """
                INSERT INTO usage_meters (user_id, feature, billing_month, current_usage, max_limit, updated_at)
                VALUES ($1, $2, $3, $4, $5, NOW())
                ON CONFLICT (user_id, feature, billing_month)
                DO UPDATE SET current_usage = usage_meters.current_usage + $4, updated_at = NOW()
                """,
                user_id, feature, billing_month, quantity, max_limit,
            )
        except Exception as exc:
            _logger.error("Usage increment failed: %s", exc)

    async def get_usage(self, user_id: str, feature: str) -> Dict[str, Any]:
        """Get current usage for a feature."""
        billing_month = datetime.now(timezone.utc).strftime("%Y-%m")
        try:
            row = await self._db.fetchrow(
                "SELECT current_usage, max_limit FROM usage_meters WHERE user_id=$1 AND feature=$2 AND billing_month=$3",
                user_id, feature, billing_month,
            )
            if row:
                return {"current": row["current_usage"], "limit": row["max_limit"] or 0}
            return {"current": 0, "limit": 0}
        except Exception:
            return {"current": 0, "limit": 0}

    async def reset_monthly(self, user_id: str) -> None:
        """Reset all usage for a user at billing period boundary."""
        billing_month = datetime.now(timezone.utc).strftime("%Y-%m")
        try:
            await self._db.execute(
                "UPDATE usage_meters SET current_usage = 0, updated_at = NOW() WHERE user_id=$1 AND billing_month=$2",
                user_id, billing_month,
            )
        except Exception as exc:
            _logger.error("Usage reset failed: %s", exc)
