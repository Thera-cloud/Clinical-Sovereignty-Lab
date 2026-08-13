"""SendGrid drip markers on post_nudges. Does not send Gmail. Does not call LinkedIn."""

from __future__ import annotations

import os
from typing import Any, Dict

from app.services.google_workspace_service import FlagOff


def _flag_on(name: str) -> bool:
    return os.getenv(name, "false").strip().lower() in ("1", "true", "yes")


async def enqueue_drip_marker(
    db_pool,
    *,
    coach_id: str,
    content_id: int,
    campaign_id: str = "",
) -> Dict[str, Any]:
    if not _flag_on("ENABLE_CAMPAIGN_NUDGES"):
        raise FlagOff("ENABLE_CAMPAIGN_NUDGES")
    async with db_pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO post_nudges (coach_id, content_id, channel, scheduled_at)
            VALUES ($1, $2, 'sendgrid', NOW())
            RETURNING id
            """,
            coach_id,
            int(content_id),
        )
    return {
        "ok": True,
        "nudge_id": int(row["id"]) if row else None,
        "channel": "sendgrid",
        "campaign_id": campaign_id,
        "sent": False,
    }
