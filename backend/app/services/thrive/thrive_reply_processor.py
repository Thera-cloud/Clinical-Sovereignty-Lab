"""Inbound email replies to thrive@reply.sovereignsanctuary.net. QUANTUM-CRYSTAL-ARCH.

Subjects carry a routing tag ``[#tgt:<key>]``:

* ``[#tgt:<practice_key>]`` → completion + harvest (``client_practice_log``, source=email_reply)
* ``[#tgt:goal:<uuid8>]``   → progress update (first 0–100 integer in body) + note
* ``[#tgt:recap]`` / ``[#tgt:phase]`` / untagged → reflection: completion if the
  body reads like one, otherwise stored as ``practice_key='reflection'``

Body keyword ``pause`` (alone on the first line, or "pause reminders") pushes
every active practice's ``next_due_at`` out 7 days — thrive-owned state, never
``profile_data`` (bridge-cache overwrite risk).
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Dict, Optional

from app.services.thrive import practice_catalog as pc
from app.services.thrive import practice_tracker as pt

logger = logging.getLogger(__name__)

TAG_RE = re.compile(r"\[#tgt:([a-z0-9_:\-]+)\]", re.IGNORECASE)
PAUSE_RE = re.compile(r"^\s*(pause|stop|snooze)(\s+(reminders?|for\s+(a\s+)?week))?\s*[.!]?\s*$", re.IGNORECASE)
PCT_RE = re.compile(r"(?<!\d)(100|[1-9]?\d)\s*%?(?!\d)")
REFLECTION_KEY = "reflection"


def parse_tag(subject: str) -> Optional[str]:
    m = TAG_RE.search(subject or "")
    return m.group(1).lower() if m else None


async def _resolve_user(db_pool, sender_email: str) -> Optional[str]:
    async with db_pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT username FROM users WHERE LOWER(profile_data->>'email') = LOWER($1) AND role = 'CLIENT' LIMIT 1",
            sender_email,
        )
    return row["username"] if row else None


async def _pause(db_pool, username: str) -> int:
    async with db_pool.acquire() as conn:
        res = await conn.execute(
            """
            UPDATE client_focus_areas
            SET next_due_at = GREATEST(COALESCE(next_due_at, NOW()), NOW()) + interval '7 days', updated_at = NOW()
            WHERE username = $1 AND active
            """,
            username,
        )
    try:
        return int(res.split()[-1])
    except Exception:
        return 0


async def _goal_progress(db_pool, username: str, id_prefix: str, body: str) -> Dict[str, Any]:
    async with db_pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT id::text AS id FROM nate_commitments
            WHERE user_id = $1 AND id::text LIKE $2 || '%' AND status = 'active'
            LIMIT 1
            """,
            username, id_prefix,
        )
    if not row:
        return {"ok": False, "reason": "goal_not_found"}
    first = next((ln for ln in body.splitlines() if ln.strip()), "")
    m = PCT_RE.search(first) or PCT_RE.search(body)
    if not m:
        # No number: keep the note, do not move progress.
        await pt.update_goal_progress(db_pool, row["id"], -1, note=body[:600])
        return {"ok": True, "goal_id": row["id"], "progress": None}
    pct = float(m.group(1))
    await pt.update_goal_progress(db_pool, row["id"], pct, note=body[:600])
    return {"ok": True, "goal_id": row["id"], "progress": pct}


async def _reflection(db_pool, username: str, body: str, tag: Optional[str]) -> None:
    async with db_pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO client_practice_log (username, practice_key, source, harvest, metadata)
            VALUES ($1, $2, 'email_reply', $3, $4::jsonb)
            """,
            username, REFLECTION_KEY, body[:2000], json.dumps({"tag": tag}),
        )


async def handle_thrive_reply(db_pool, sender_email: str, subject: str, body: str) -> Dict[str, Any]:
    """Dispatch one inbound reply. Never raises; returns a small result dict for logs."""
    if db_pool is None:
        return {"ok": False, "reason": "no_db"}
    try:
        username = await _resolve_user(db_pool, sender_email)
        if not username:
            return {"ok": False, "reason": "unknown_sender"}
        tag = parse_tag(subject)
        text = (body or "").strip()
        first_line = next((ln for ln in text.splitlines() if ln.strip()), "")

        if PAUSE_RE.match(first_line):
            n = await _pause(db_pool, username)
            return {"ok": True, "username": username, "action": "pause", "practices": n}

        if tag and tag.startswith("goal:"):
            res = await _goal_progress(db_pool, username, tag.split(":", 1)[1], text)
            res.update({"username": username, "action": "goal_progress"})
            return res

        if tag in pc.PRACTICES:
            await pt.log_completion(db_pool, username, tag, source="email_reply", harvest=text[:2000])
            return {"ok": True, "username": username, "action": "completion", "practice_key": tag}

        active = [a.practice_key for a in await pt.list_focus_areas(db_pool, username)]
        detected = pt.detect_completion(text, active or None)
        if detected:
            await pt.log_completion(db_pool, username, detected, source="email_reply", harvest=text[:2000])
            return {"ok": True, "username": username, "action": "completion", "practice_key": detected}

        await _reflection(db_pool, username, text, tag)
        return {"ok": True, "username": username, "action": "reflection", "tag": tag}
    except Exception as e:
        logger.warning("thrive_reply_processor: failed for %s: %s", sender_email, e)
        return {"ok": False, "reason": str(e)[:200]}
