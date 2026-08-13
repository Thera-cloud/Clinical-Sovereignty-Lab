"""Per-campaign Sheet row on campaign_engagements insert (AC12). drive.file only."""

from __future__ import annotations

import os
from typing import Any, Dict, Optional

from app.services.google_workspace_service import FlagOff

SHEETS_APPEND = (
    "https://sheets.googleapis.com/v4/spreadsheets/{sid}/values/{range}:append"
)


def _flag_on(name: str) -> bool:
    return os.getenv(name, "false").strip().lower() in ("1", "true", "yes")


def engagement_row(payload: Dict[str, Any]) -> list:
    return [
        str(payload.get("campaign_id") or ""),
        str(payload.get("source") or ""),
        str(payload.get("actor_handle") or ""),
        str(payload.get("created_at") or ""),
    ]


async def append_engagement(
    *,
    spreadsheet_id: str,
    payload: Dict[str, Any],
    access_token: Optional[str] = None,
) -> Dict[str, Any]:
    if not _flag_on("ENABLE_WS_DRIVE_DELIVERY"):
        raise FlagOff("ENABLE_WS_DRIVE_DELIVERY")
    row = engagement_row(payload)
    if not access_token or not spreadsheet_id:
        return {"ok": True, "appended": False, "row": row}
    import aiohttp

    url = SHEETS_APPEND.format(sid=spreadsheet_id, range="Engagements!A:D")
    async with aiohttp.ClientSession() as session:
        async with session.post(
            url,
            headers={
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json",
            },
            params={"valueInputOption": "RAW", "insertDataOption": "INSERT_ROWS"},
            json={"values": [row]},
        ) as resp:
            ok = resp.status in (200, 201)
    return {"ok": ok, "appended": ok, "row": row}
