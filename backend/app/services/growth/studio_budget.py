"""Studio media budget gate for growth factory (wraps SSE studio daily cost).

Text-only blog drafts always allowed. Media generation requires remaining budget.

# QUANTUM-CRYSTAL-ARCH
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

logger = logging.getLogger("nate.growth.studio_budget")


async def studio_budget_status(redis=None) -> Dict[str, Any]:
    try:
        from app.sse.studio_service import get_daily_cost

        return await get_daily_cost(redis)
    except Exception as e:
        logger.warning("studio_budget_status failed: %s", e)
        return {
            "spent_cents": 0,
            "cap_cents": 0,
            "remaining_cents": 0,
            "error": str(e),
            "unconfigured": True,
        }


async def allow_media_spend(
    estimated_cents: int,
    *,
    redis=None,
    mode: str = "text_only",
) -> tuple[bool, str, Dict[str, Any]]:
    """Gate media generation. mode=text_only → always deny media (factory stays text)."""
    status = await studio_budget_status(redis)
    if mode == "text_only":
        return False, "text_only_mode", status
    if status.get("unconfigured"):
        return False, "studio_budget_unconfigured", status
    remaining = int(status.get("remaining_cents") or 0)
    if estimated_cents > remaining:
        return False, "budget_exhausted", status
    return True, "ok", status


async def factory_generation_mode(db_pool, redis=None) -> Dict[str, Any]:
    """Read growth_config.studio_media_mode + live budget."""
    mode = "text_only"
    allow_when_ok = True
    if db_pool is not None:
        try:
            async with db_pool.acquire() as conn:
                row = await conn.fetchrow(
                    "SELECT value FROM growth_config WHERE key = 'studio_media_mode'"
                )
            if row and isinstance(row["value"], dict):
                mode = str(row["value"].get("mode") or "text_only")
                allow_when_ok = bool(
                    row["value"].get("allow_media_when_budget_ok", True)
                )
        except Exception as e:
            logger.warning("factory_generation_mode config read: %s", e)
    status = await studio_budget_status(redis)
    media_ok = False
    reason = "text_only_mode"
    if mode != "text_only" and allow_when_ok:
        media_ok, reason, status = await allow_media_spend(
            100, redis=redis, mode=mode
        )
    return {
        "mode": mode,
        "media_allowed": media_ok,
        "reason": reason,
        "budget": status,
    }
