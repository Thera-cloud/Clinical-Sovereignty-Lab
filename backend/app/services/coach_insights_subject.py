"""Coach Insights subject resolution — no heavy imports."""

from __future__ import annotations

import re
from typing import Any, Dict, Optional


def resolve_coach_focus_client_id(
    ctx: Dict[str, Any], user_message: str = ""
) -> Optional[str]:
    """Resolve hardware_id / username for zoom learning + briefing injection.

    Context client_id is honored only when the coach locked a subject
    (saved therapeutic override or explicit subject_locked). Dropdown
    preselection alone must not invent a focus client.
    """
    msg = (user_message or "").lower()

    def _match_roster(message: str) -> Optional[str]:
        if not message:
            return None
        for entry in ctx.get("client_names") or []:
            if not isinstance(entry, dict):
                continue
            cid = entry.get("id") or entry.get("hardware_id") or ""
            name = (entry.get("name") or "").lower()
            username = (entry.get("username") or "").lower()
            if not cid:
                continue
            if name and name in message:
                return str(cid)
            for part in name.split():
                if len(part) >= 3 and part in message:
                    return str(cid)
            if username and username in message:
                return str(cid)
            user_stem = re.sub(r"[0-9@._-]+", "", username)
            if len(user_stem) >= 3 and user_stem in message:
                return str(cid)
            if "zack" in message and "zachary" in name:
                return str(cid)
        return None

    from_msg = _match_roster(msg)
    if from_msg:
        return from_msg

    override_active = bool(ctx.get("override_active"))
    subject_locked = bool(ctx.get("subject_locked")) or override_active
    if not subject_locked:
        return None

    for key in ("client_id", "focused_client_id"):
        val = (
            (ctx.get(key) or "").strip()
            if isinstance(ctx.get(key), str)
            else ctx.get(key)
        )
        if val:
            return str(val)
    briefing = ctx.get("briefing_data") or {}
    if isinstance(briefing, dict):
        cid = briefing.get("client_id")
        client = briefing.get("client")
        if not cid and isinstance(client, dict):
            cid = client.get("id")
        if cid:
            return str(cid)
    return None
