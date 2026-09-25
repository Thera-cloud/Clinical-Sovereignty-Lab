"""Main-chat working session: one live session at a time. QUANTUM-CRYSTAL-ARCH"""

from __future__ import annotations

import logging
import os
import re
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional

logger = logging.getLogger("chat.session_focus")

_HELD: Dict[str, Dict[str, str]] = {}

_SESSION = re.compile(
    r"\b(?:sessions?|last time|that (?:call|meeting)|our (?:call|meeting)|zoom)\b",
    re.I,
)
_LEAVE = re.compile(
    r"\b(?:something else|different (?:topic|question)|forget the session|"
    r"leave the session|not about the session|anyway)\b",
    re.I,
)
_LATEST = re.compile(r"\b(?:last|latest|most recent)\b", re.I)
_PREV = re.compile(r"\b(?:the one before|previous|before that|the earlier one)\b", re.I)
_CORRECT = re.compile(r"\b(?:no[, ]+i mean|i mean|i meant|not that one|that'?s not)\b", re.I)
_MONTHS = {
    "january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6,
    "july": 7, "august": 8, "september": 9, "october": 10, "november": 11, "december": 12,
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "jun": 6, "jul": 7, "aug": 8,
    "sep": 9, "sept": 9, "oct": 10, "nov": 11, "dec": 12,
}


def focus_enabled() -> bool:
    return os.getenv("ENABLE_CHAT_SESSION_FOCUS", "true").strip().lower() in (
        "1", "true", "yes", "on",
    )


def _today() -> date:
    return datetime.utcnow().date()


def parse_day(text: str, today: Optional[date] = None) -> Optional[date]:
    today = today or _today()
    low = (text or "").lower()
    if re.search(r"\byesterday\b", low):
        return today - timedelta(days=1)
    if re.search(r"\btoday\b", low):
        return today
    iso = re.search(r"\b(20\d{2})-(\d{2})-(\d{2})\b", low)
    if iso:
        try:
            return date(int(iso.group(1)), int(iso.group(2)), int(iso.group(3)))
        except ValueError:
            return None
    for name, month in _MONTHS.items():
        hit = re.search(rf"\b{name}\.?\s+(\d{{1,2}})\b", low)
        if not hit:
            continue
        day = int(hit.group(1))
        year = today.year
        try:
            found = date(year, month, day)
        except ValueError:
            return None
        if found > today + timedelta(days=2):
            found = date(year - 1, month, day)
        return found
    return None


def choose_session(
    held: Optional[Dict[str, str]],
    sessions: List[Dict[str, str]],
    text: str,
) -> Dict[str, Any]:
    """Return move: ignore | leave | clarify | bind | missing."""
    blob = (text or "").strip()
    low = blob.lower()
    held = held or {}
    if _LEAVE.search(low):
        return {"move": "leave"}
    named = parse_day(blob)
    talking = bool(_SESSION.search(low) or named or _PREV.search(low) or _CORRECT.search(low))
    if held.get("session_id") and not talking and not _LEAVE.search(low):
        if len(blob.split()) <= 24:
            return {"move": "bind", "session_id": held["session_id"]}
        return {"move": "leave"}
    if not talking:
        return {"move": "ignore"}
    if not sessions:
        return {"move": "missing"}
    if _PREV.search(low):
        pick = sessions[1] if len(sessions) > 1 else None
        if not pick:
            return {"move": "missing"}
        return {"move": "bind", "session_id": pick["session_id"]}
    if named:
        hits = [s for s in sessions if s.get("date_slug") == named.isoformat()]
        if len(hits) == 1:
            return {"move": "bind", "session_id": hits[0]["session_id"]}
        if len(hits) > 1:
            return {"move": "clarify", "options": hits[:2]}
        return {"move": "missing", "asked": named.isoformat()}
    if _LATEST.search(low) or re.search(r"\blast time\b", low):
        return {"move": "bind", "session_id": sessions[0]["session_id"]}
    if held.get("session_id") and not _CORRECT.search(low):
        return {"move": "bind", "session_id": held["session_id"]}
    if len(sessions) == 1:
        return {"move": "bind", "session_id": sessions[0]["session_id"]}
    return {"move": "clarify", "options": sessions[:2]}


def _hold_key(client_id: str) -> str:
    return (client_id or "").strip()


def read_held(client_id: str) -> Dict[str, str]:
    return dict(_HELD.get(_hold_key(client_id)) or {})


def _set_held(client_id: str, row: Optional[Dict[str, str]]) -> None:
    key = _hold_key(client_id)
    if not key:
        return
    if not row:
        _HELD.pop(key, None)
        return
    _HELD[key] = {
        "session_id": row.get("session_id") or "",
        "label": row.get("label") or "",
        "date_slug": row.get("date_slug") or "",
    }


async def _list_sessions(db_pool, client_id: str) -> List[Dict[str, str]]:
    from app.services.zoom_transcript_context import (
        get_sessions_with_transcripts_pg,
        resolve_live_session_display,
    )

    rows = await get_sessions_with_transcripts_pg(db_pool, client_id, limit=8)
    out: List[Dict[str, str]] = []
    for row in rows:
        dates = resolve_live_session_display(
            actual_start=row.get("actual_start"),
            actual_end=row.get("actual_end"),
            scheduled_start=row.get("scheduled_start"),
            session_data=row.get("session_data"),
            session_id=row.get("session_id") or "",
        )
        out.append({
            "session_id": row.get("session_id") or "",
            "label": dates.get("display_label") or "recent",
            "date_slug": dates.get("date_slug") or "",
        })
    return [s for s in out if s["session_id"]]


async def _folder_preview(db_pool, session_id: str) -> str:
    if not db_pool or not session_id:
        return ""
    try:
        async with db_pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT metadata
                FROM coach_folder_files
                WHERE file_type = 'session_summary'
                  AND metadata->>'session_id' = $1
                ORDER BY created_at DESC
                LIMIT 1
                """,
                session_id,
            )
    except Exception as exc:
        logger.warning("chat session focus folder skipped: %s", exc)
        return ""
    if not row:
        return ""
    meta = row["metadata"]
    if isinstance(meta, str):
        import json
        try:
            meta = json.loads(meta)
        except Exception:
            meta = {}
    if not isinstance(meta, dict):
        return ""
    return (meta.get("summary_preview") or meta.get("markdown") or "")[:1200]


async def session_focus_block(db_pool, client_id: str, user_text: str) -> str:
    """Prompt block for the one session under discussion. Empty means leave the usual context."""
    if not focus_enabled() or not db_pool or not (client_id or "").strip():
        return ""
    sessions = await _list_sessions(db_pool, client_id)
    choice = choose_session(read_held(client_id), sessions, user_text or "")
    move = choice.get("move")
    if move == "ignore":
        return ""
    if move == "leave":
        _set_held(client_id, None)
        return ""
    by_id = {s["session_id"]: s for s in sessions}
    if move == "clarify":
        opts = choice.get("options") or []
        labels = " or ".join(s.get("label") or "a recent session" for s in opts[:2])
        return (
            "SESSION FOCUS: The client is asking about a live session and more than one could fit. "
            f"Name these dates and ask which one: {labels}. "
            "Do not summarize either session until they pick."
        )
    if move == "missing":
        asked = choice.get("asked") or "that day"
        return (
            f"SESSION FOCUS: The client asked about a live session ({asked}). "
            "You do not have that session in the recent archive. Say so. Do not describe a different day."
        )
    sid = choice.get("session_id") or ""
    row = by_id.get(sid)
    if not row:
        _set_held(client_id, None)
        return ""
    _set_held(client_id, row)
    from app.services.zoom_transcript_context import (
        get_sessions_with_transcripts_pg,
        load_session_transcript_excerpt,
    )

    excerpt = ""
    rows = await get_sessions_with_transcripts_pg(db_pool, client_id, limit=8)
    for item in rows:
        if (item.get("session_id") or "") == sid:
            excerpt, _raw = await load_session_transcript_excerpt(item.get("session_data"))
            break
    preview = await _folder_preview(db_pool, sid)
    parts = [
        f"SESSION FOCUS: Stay on the live session of {row['label']} ({sid}).",
        "This is the only session in view. Do not bring in another day.",
        "If they correct the day, follow the correction. If a word points at this session, keep it.",
        "Talk about what they asked. Do not read the transcript aloud.",
    ]
    if preview:
        parts.append("Coach-folder summary:\n" + preview)
    if excerpt:
        parts.append("Zoom transcript excerpt:\n" + excerpt[:3500])
    if not preview and not excerpt:
        parts.append("The date is known. The summary and transcript are not loaded. Say you cannot open the notes.")
    return "\n".join(parts)
