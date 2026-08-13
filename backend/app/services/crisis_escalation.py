"""Crisis escalation stub. Flag-gated. Injection screen before any write."""

from __future__ import annotations

import os
import re
from typing import Any, Dict

from app.services.google_workspace_service import FlagOff

_INJECTION = (
    re.compile(r"ignore\s+(all\s+)?(previous|prior)\s+instructions?", re.I),
    re.compile(r"you\s+are\s+now\s+", re.I),
    re.compile(r"system\s+prompt\s*:", re.I),
    re.compile(r"<\|im_start\|>", re.I),
)


def _flag_on(name: str) -> bool:
    return os.getenv(name, "false").strip().lower() in ("1", "true", "yes")


def injection_blocked(text: str) -> bool:
    blob = text or ""
    return any(p.search(blob) for p in _INJECTION)


async def escalate(
    db_pool,
    *,
    coach_id: str,
    client_id: str,
    note: str,
) -> Dict[str, Any]:
    if not _flag_on("ENABLE_CRISIS_ESCALATION"):
        raise FlagOff("ENABLE_CRISIS_ESCALATION")
    if injection_blocked(note):
        raise ValueError("injection_blocked")
    coach_id = (coach_id or "").strip()
    client_id = (client_id or "").strip()
    if not coach_id or not client_id:
        raise ValueError("hardware_id required")
    if db_pool is None:
        return {"ok": True, "queued": False}
    async with db_pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO skyeye_activity (type, content, platform)
            VALUES ($1, $2, $3)
            """,
            "crisis_escalation",
            f"{coach_id}:{client_id}:{(note or '')[:500]}",
            "workspace",
        )
    return {"ok": True, "queued": True}
