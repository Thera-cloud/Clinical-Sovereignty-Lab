"""Docs API headings + habit checklist. vault_sync=TRUE only (AC14)."""

from __future__ import annotations

import os
from typing import Any, Dict, List, Optional

from app.services.google_workspace_service import FlagOff, VaultBlocked, client_vault_sync

DOCS_BATCH = "https://docs.googleapis.com/v1/documents/{doc_id}:batchUpdate"


def _flag_on(name: str) -> bool:
    return os.getenv(name, "false").strip().lower() in ("1", "true", "yes")


def heading_requests(title: str, checklist: Optional[List[str]] = None) -> List[Dict[str, Any]]:
    title = (title or "Habits").strip()[:200]
    lines = [title, ""] + [f"[ ] {item}" for item in (checklist or [])]
    text = "\n".join(lines) + "\n"
    return [
        {"insertText": {"location": {"index": 1}, "text": text}},
        {
            "updateParagraphStyle": {
                "range": {"startIndex": 1, "endIndex": min(len(title) + 1, 80)},
                "paragraphStyle": {"namedStyleType": "HEADING_1"},
                "fields": "namedStyleType",
            }
        },
    ]


async def format_habit_doc(
    db_pool,
    *,
    coach_id: str,
    client_id: str,
    doc_id: str,
    title: str,
    checklist: Optional[List[str]] = None,
    access_token: Optional[str] = None,
) -> Dict[str, Any]:
    if not _flag_on("ENABLE_WS_DRIVE_DELIVERY"):
        raise FlagOff("ENABLE_WS_DRIVE_DELIVERY")
    client_id = (client_id or "").strip()
    if not await client_vault_sync(db_pool, client_id):
        raise VaultBlocked("docs_formatter blocked: vault_sync=false")
    reqs = heading_requests(title, checklist)
    if not access_token or not doc_id:
        return {"ok": True, "applied": False, "requests": len(reqs), "coach_id": coach_id}
    import aiohttp

    url = DOCS_BATCH.format(doc_id=doc_id)
    async with aiohttp.ClientSession() as session:
        async with session.post(
            url,
            headers={
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json",
            },
            json={"requests": reqs},
        ) as resp:
            ok = resp.status in (200, 201)
    return {"ok": ok, "applied": ok, "requests": len(reqs), "coach_id": coach_id}
