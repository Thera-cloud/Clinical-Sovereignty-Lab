"""Gmail History poll → campaign_engagements + optional warm draft. No Pub/Sub."""

from __future__ import annotations

import logging
import os
from typing import Any, Dict, Optional

from app.services.google_workspace_service import FlagOff

logger = logging.getLogger("gmail_reply_listener")

HISTORY_URL = "https://gmail.googleapis.com/gmail/v1/users/me/history"


def _flag_on(name: str) -> bool:
    return os.getenv(name, "false").strip().lower() in ("1", "true", "yes")


async def fetch_history(access_token: str, start_history_id: str) -> Dict[str, Any]:
    import aiohttp

    params = {"startHistoryId": start_history_id, "historyTypes": "messageAdded"}
    async with aiohttp.ClientSession() as session:
        async with session.get(
            HISTORY_URL,
            headers={"Authorization": f"Bearer {access_token}"},
            params=params,
        ) as resp:
            text = await resp.text()
            if resp.status != 200:
                logger.warning("Gmail history poll failed: %d %s", resp.status, text[:200])
                return {"history": []}
            import json
            return json.loads(text) if text else {"history": []}


async def poll_and_record(
    db_pool,
    *,
    coach_id: str,
    access_token: str,
    start_history_id: str,
    campaign_id: Optional[str] = None,
) -> Dict[str, Any]:
    """History.list only."""
    if not _flag_on("ENABLE_WS_GMAIL_DRAFTS"):
        raise FlagOff("ENABLE_WS_GMAIL_DRAFTS")
    payload = await fetch_history(access_token, start_history_id)
    history = payload.get("history") or []
    n = 0
    if db_pool:
        async with db_pool.acquire() as conn:
            for item in history:
                for added in item.get("messagesAdded") or []:
                    msg = added.get("message") or {}
                    hid = str(msg.get("id") or item.get("id") or "")
                    await conn.execute(
                        """
                        INSERT INTO campaign_engagements (coach_id, campaign_id, source, actor_handle)
                        VALUES ($1, $2, 'gmail_history', $3)
                        """,
                        coach_id,
                        campaign_id,
                        hid[:200],
                    )
                    n += 1
            if payload.get("historyId"):
                await conn.execute(
                    """
                    UPDATE google_workspace_connection
                    SET gmail_history_id = $1, updated_at = NOW()
                    WHERE hardware_id = $2 AND revoked_at IS NULL
                    """,
                    str(payload["historyId"]),
                    coach_id,
                )
    return {"ok": True, "engagements": n, "historyId": payload.get("historyId")}


async def warm_reply_draft(
    db_pool,
    coach_id: str,
    payload: Dict[str, Any],
) -> Dict[str, Any]:
    from app.services.gmail_draft_service import create_coach_draft

    return await create_coach_draft(db_pool, coach_id, payload)
