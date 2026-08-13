"""Google Chat incoming webhook notifier (AC13). No Sanctuary data in T4 Studio."""

from __future__ import annotations

import os
from typing import Any, Dict, Optional

from app.services.google_workspace_service import FlagOff

import aiohttp


def _flag_on(name: str) -> bool:
    return os.getenv(name, "false").strip().lower() in ("1", "true", "yes")


async def load_chat_webhook(db_pool, coach_id: str) -> Optional[str]:
    if not db_pool:
        return None
    async with db_pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT chat_webhook_url FROM coach_integrations_settings
            WHERE coach_id = $1
            """,
            coach_id,
        )
    url = (row["chat_webhook_url"] if row else None) or ""
    return url.strip() or None


async def notify_coach(
    db_pool,
    coach_id: str,
    text: str,
    *,
    webhook_url: Optional[str] = None,
) -> Dict[str, Any]:
    """Post a short Chat card. Never include client PII."""
    if not _flag_on("ENABLE_CAMPAIGN_NUDGES") and not _flag_on("ENABLE_CRISIS_ESCALATION"):
        raise FlagOff("ENABLE_CAMPAIGN_NUDGES")
    url = webhook_url or await load_chat_webhook(db_pool, coach_id)
    body = {"text": (text or "").strip()[:400]}
    if not url:
        return {"ok": False, "reason": "no_webhook"}
    async with aiohttp.ClientSession() as session:
        async with session.post(url, json=body) as resp:
            return {"ok": resp.status in (200, 201), "status": resp.status}
