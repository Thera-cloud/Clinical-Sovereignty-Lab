"""Coach Command integrations hub payload. Flags default OFF until Queens."""

from __future__ import annotations

import os
from typing import Any, Dict, List

HUB_FLAGS = (
    "ENABLE_WS_OAUTH",
    "ENABLE_WS_CALENDAR_SYNC",
    "ENABLE_WS_GMAIL_DRAFTS",
    "ENABLE_WS_DRIVE_DELIVERY",
    "ENABLE_VOICE_CAMPAIGN",
    "ENABLE_CAMPAIGN_NUDGES",
    "ENABLE_AUDIO_BRIEFS",
    "ENABLE_COACH_LINKEDIN",
    "ENABLE_STUDIO_WEBHOOKS",
    "ENABLE_COACH_NEWSLETTER",
    "ENABLE_COACH_TASKS",
    "ENABLE_SUPERVISION_VIEW",
    "ENABLE_PRACTICE_LIBRARIES",
    "ENABLE_CRISIS_ESCALATION",
)


def _flag_on(name: str) -> bool:
    return os.getenv(name, "false").strip().lower() in ("1", "true", "yes")


async def hub_snapshot(db_pool, coach_id: str) -> Dict[str, Any]:
    from app.services.coach_linkedin_oauth import coach_linkedin_status
    from app.services.google_workspace_service import get_google_svc

    ws = await get_google_svc(db_pool).status(coach_id)
    li = await coach_linkedin_status(db_pool, coach_id)
    studio = {"configured": False, "fingerprint": None}
    chat_url = ""
    drafts_waiting = 0
    campaign_day_n = None
    campaign_title = None
    voice_recordings = 0
    assistants: List[Dict[str, Any]] = []
    if db_pool:
        async with db_pool.acquire() as conn:
            sec = await conn.fetchrow(
                """
                SELECT fingerprint FROM studio_webhook_secrets
                WHERE coach_id = $1 AND revoked_at IS NULL
                """,
                coach_id,
            )
            if sec:
                studio = {"configured": True, "fingerprint": sec["fingerprint"]}
            chat = await conn.fetchrow(
                """
                SELECT chat_webhook_url FROM coach_integrations_settings
                WHERE coach_id = $1
                """,
                coach_id,
            )
            if chat:
                chat_url = chat["chat_webhook_url"] or ""
            dw = await conn.fetchval(
                """
                SELECT COUNT(*) FROM email_drafts
                WHERE coach_id = $1 AND status IN ('pending', 'pushed')
                """,
                coach_id,
            )
            drafts_waiting = int(dw or 0)
            camp = await conn.fetchrow(
                """
                SELECT title, day_n FROM coach_marketing_campaigns
                WHERE coach_id = $1
                ORDER BY updated_at DESC NULLS LAST, id DESC
                LIMIT 1
                """,
                coach_id,
            )
            if camp:
                campaign_title = camp["title"]
                campaign_day_n = camp["day_n"]
            vr = await conn.fetchval(
                """
                SELECT COUNT(*) FROM coach_voice_recordings WHERE coach_id = $1
                """,
                coach_id,
            )
            voice_recordings = int(vr or 0)
            asst_rows = await conn.fetch(
                """
                SELECT ch.assistant_id,
                       u.username,
                       COALESCE(u.profile_data->>'name', u.username) AS name
                FROM coach_hierarchy ch
                LEFT JOIN users u ON u.hardware_id = ch.assistant_id
                WHERE ch.master_coach_id = $1 AND ch.status = 'active'
                ORDER BY name, u.username
                """,
                coach_id,
            )
            assistants = [
                {
                    "hardware_id": r["assistant_id"],
                    "username": r["username"] or "",
                    "name": r["name"] or r["username"] or r["assistant_id"],
                }
                for r in asst_rows
            ]
    flags = {name: _flag_on(name) for name in HUB_FLAGS}
    is_master = bool(assistants)
    supervision = {
        "is_master": is_master,
        "assistants": assistants,
        "assistant_count": len(assistants),
        "supervision_flag": flags.get("ENABLE_SUPERVISION_VIEW", False),
        "source": "coach_hierarchy",
    }
    return {
        "status": "ok",
        "coach_id": coach_id,
        "flags": flags,
        "erasure_ui": False,
        "workspace": ws,
        "linkedin": li,
        "studio": studio,
        "chat_webhook_url": chat_url,
        "drafts_waiting": drafts_waiting,
        "campaign": {"title": campaign_title, "day_n": campaign_day_n},
        "voice_recordings": voice_recordings,
        "supervision": supervision,
        "studio_hooks": {
            "base": "/api/v1/hooks",
            "paths": ["intake-analysis", "engagement", "client-digest"],
            "headers": ["X-Coach-Id", "X-Studio-Signature"],
        },
        "cards": _cards(ws, li, drafts_waiting, campaign_day_n, flags, supervision),
    }


def _cards(ws, li, drafts_waiting, day_n, flags, supervision=None) -> List[Dict[str, Any]]:
    supervision = supervision or {}
    ws_label = "Connected" if ws.get("connected") else (
        "Connect Workspace" if flags.get("ENABLE_WS_OAUTH") else "Not connected"
    )
    li_label = "Connected" if li.get("connected") else "Connect LinkedIn"
    if supervision.get("is_master"):
        master_detail = f"Master · {supervision.get('assistant_count', 0)} assistants"
    else:
        master_detail = "Not a master on coach_hierarchy"
    return [
        {"id": "workspace", "title": "Google Workspace", "detail": ws_label},
        {"id": "linkedin", "title": "LinkedIn", "detail": li_label},
        {"id": "drafts", "title": "Drafts waiting", "detail": str(drafts_waiting)},
        {
            "id": "campaign",
            "title": "Campaign day-N",
            "detail": f"Day {day_n}" if day_n is not None else "None",
        },
        {"id": "supervision", "title": "Supervision", "detail": master_detail},
    ]
