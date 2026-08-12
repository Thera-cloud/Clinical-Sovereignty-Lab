"""
Path B: load archived Zoom transcripts for Little Nate learning context.

Reads coaching_sessions.session_data.transcript_location via blob_storage,
formats VTT as dialogue excerpts for chat / briefings / lived wisdom.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

_MAX_EXCERPT_CHARS = 3500
_CONTEXT_HEADER = "[ZOOM SESSION TRANSCRIPTS — Path B full dialogue excerpts]"


def session_id_calendar_label(session_id: str) -> Optional[str]:
    """SES_YYYYMMDD_* embeds when the meeting was first created/booked — not always live day."""
    if not session_id:
        return None
    m = re.match(r"^SES_(\d{4})(\d{2})(\d{2})(?:_|$)", session_id.strip())
    if not m:
        return None
    try:
        from datetime import date

        d = date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        return d.strftime("%b %d, %Y")
    except ValueError:
        return None


def _as_datetime(val: Any) -> Optional[Any]:
    """Coerce datetime / ISO string; returns datetime-like or None."""
    if val is None:
        return None
    if hasattr(val, "strftime"):
        return val
    if isinstance(val, str) and val.strip():
        try:
            from datetime import datetime

            return datetime.fromisoformat(val.strip().replace("Z", "+00:00"))
        except Exception:
            return None
    return None


def format_session_day_label(val: Any) -> Optional[str]:
    dt_val = _as_datetime(val)
    if dt_val is None:
        return None
    try:
        return dt_val.strftime("%b %d, %Y")
    except Exception:
        return None


def resolve_live_session_display(
    *,
    actual_start: Any = None,
    actual_end: Any = None,
    scheduled_start: Any = None,
    session_data: Any = None,
    archive_created_at: Any = None,
    session_id: str = "",
    metadata: Any = None,
) -> Dict[str, Optional[str]]:
    """
    Prefer when the live call ran over SES_* booking stamp / create day.

    Returns keys: live_label, booking_label, display_label, date_slug (YYYY-MM-DD).
    """
    sd = _session_data_dict(session_data)
    meta = metadata if isinstance(metadata, dict) else {}
    if isinstance(metadata, str) and metadata.strip():
        try:
            meta = json.loads(metadata)
        except Exception:
            meta = {}

    candidates = (
        actual_start,
        actual_end,
        meta.get("live_session_at") or meta.get("live_session_date"),
        sd.get("actual_start") or sd.get("live_started_at") or sd.get("zoom_folder_doc_placed_at"),
        scheduled_start,
        archive_created_at,
    )
    live_dt = None
    for c in candidates:
        live_dt = _as_datetime(c)
        if live_dt is not None:
            break

    live_label = format_session_day_label(live_dt) if live_dt else None
    booking_label = session_id_calendar_label(session_id or "")
    if booking_label and live_label and booking_label == live_label:
        booking_label = None

    if live_label and booking_label:
        display = f"{live_label} (live; booked {booking_label})"
    elif live_label:
        display = live_label
    elif booking_label:
        display = f"{booking_label} (booking date — live time unknown)"
    else:
        display = "recent"

    date_slug = None
    if live_dt is not None:
        try:
            date_slug = live_dt.strftime("%Y-%m-%d")
        except Exception:
            date_slug = None
    if not date_slug and session_id:
        m = re.match(r"^SES_(\d{4})(\d{2})(\d{2})(?:_|$)", session_id.strip())
        if m:
            date_slug = f"{m.group(1)}-{m.group(2)}-{m.group(3)}"

    return {
        "live_label": live_label,
        "booking_label": booking_label,
        "display_label": display,
        "date_slug": date_slug,
    }


def _session_data_dict(raw: Any) -> Dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str) and raw.strip():
        try:
            return json.loads(raw)
        except Exception:
            return {}
    return {}


def load_transcript_text(location: str, storage_kind: str = "local") -> Optional[str]:
    """Load raw VTT/TXT from blob or local path."""
    if not (location or "").strip():
        return None
    try:
        from app.services.blob_storage import download_bytes

        content_bytes = download_bytes(location=location, storage_kind=storage_kind or "local")
        if content_bytes:
            return content_bytes.decode("utf-8", errors="ignore")
    except Exception as e:
        logger.warning("load_transcript_text blob failed for %s: %s", location, e)

    try:
        from pathlib import Path

        path = Path(location)
        if path.exists():
            return path.read_text(encoding="utf-8", errors="ignore")
    except Exception as e:
        logger.debug("load_transcript_text local fallback: %s", e)
    return None


def vtt_to_dialogue_excerpt(vtt_content: str, max_chars: int = _MAX_EXCERPT_CHARS) -> str:
    """Strip WEBVTT timing; prefer VTTParser labels when available."""
    if not (vtt_content or "").strip():
        return ""

    # Strip synthetic classroom merge headers if present
    body = vtt_content
    if "[TRANSCRIPT]" in body:
        body = body.split("[TRANSCRIPT]", 1)[-1]
    if "[ZOOM AI SUMMARY]" in body and "[TRANSCRIPT]" not in vtt_content:
        body = body.split("[ZOOM AI SUMMARY]", 1)[-1]

    try:
        from app.services.classroom_analyzer import VTTParser

        entries = VTTParser.parse(body)
        if entries:
            lines: List[str] = []
            for ent in entries:
                speaker = (getattr(ent, "speaker", None) or "").strip()
                text = (getattr(ent, "text", None) or "").strip()
                if not text:
                    continue
                lines.append(f"{speaker}: {text}" if speaker else text)
            joined = "\n".join(lines)
            if joined.strip():
                if len(joined) > max_chars:
                    return joined[: max_chars - 3].rstrip() + "..."
                return joined
    except Exception as e:
        logger.debug("VTTParser excerpt fallback: %s", e)

    lines: List[str] = []
    for line in body.splitlines():
        line = line.strip()
        if not line or line == "WEBVTT" or line.startswith("NOTE"):
            continue
        if "-->" in line:
            continue
        if re.match(r"^\d+$", line):
            continue
        lines.append(line)
    joined = "\n".join(lines)
    if len(joined) > max_chars:
        return joined[: max_chars - 3].rstrip() + "..."
    return joined


async def _resolve_client_ids(db_pool, client_id: str) -> List[str]:
    """Hardware id + username aliases for coaching_sessions.client_id lookup."""
    ids: List[str] = []
    for val in (client_id,):
        if val and val not in ids:
            ids.append(val)
    try:
        from app.services.zoom_session_folder import _resolve_client_username

        username, _ = await _resolve_client_username(db_pool, client_id)
        if username and username not in ids:
            ids.append(username)
    except Exception:
        pass
    return ids


async def get_sessions_with_transcripts_pg(
    db_pool,
    client_id: str,
    limit: int = 3,
) -> List[Dict[str, Any]]:
    """Recent coaching_sessions rows that have transcript_location archived."""
    if not db_pool or not client_id:
        return []
    entity_ids = await _resolve_client_ids(db_pool, client_id)
    if not entity_ids:
        return []
    try:
        async with db_pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT session_id, client_id, client_name, zoom_meeting_id,
                       scheduled_start, actual_start, actual_end, session_data
                FROM coaching_sessions
                WHERE client_id = ANY($1::text[])
                  AND COALESCE(session_data->>'transcript_location', '') <> ''
                ORDER BY COALESCE(actual_start, actual_end, scheduled_start) DESC NULLS LAST
                LIMIT $2
                """,
                entity_ids,
                limit,
            )
        return [dict(r) for r in rows]
    except Exception as e:
        logger.warning("get_sessions_with_transcripts_pg failed: %s", e)
        return []


async def load_session_transcript_excerpt(
    session_data: Any,
    max_chars: int = _MAX_EXCERPT_CHARS,
) -> Tuple[str, int]:
    """
    Load transcript for one session row.
    Returns (excerpt_text, raw_char_count).
    """
    sd = _session_data_dict(session_data)
    location = (sd.get("transcript_location") or "").strip()
    if not location:
        return "", 0
    storage_kind = (sd.get("transcript_storage") or "local").strip() or "local"
    raw = load_transcript_text(location, storage_kind)
    if not raw:
        return "", 0
    excerpt = vtt_to_dialogue_excerpt(raw, max_chars=max_chars)
    return excerpt, len(raw)


async def get_zoom_transcript_context_pg(
    db_pool,
    client_id: str,
    limit: int = 2,
    max_chars_per_session: int = _MAX_EXCERPT_CHARS,
) -> str:
    """
    Build Path B transcript context block for Little Nate (client chat / briefings).
    """
    rows = await get_sessions_with_transcripts_pg(db_pool, client_id, limit=limit)
    if not rows:
        return ""

    parts: List[str] = [_CONTEXT_HEADER]
    for row in rows:
        excerpt, raw_len = await load_session_transcript_excerpt(
            row.get("session_data"), max_chars=max_chars_per_session
        )
        if not excerpt.strip():
            continue
        sid = row.get("session_id") or ""
        dates = resolve_live_session_display(
            actual_start=row.get("actual_start"),
            actual_end=row.get("actual_end"),
            scheduled_start=row.get("scheduled_start"),
            session_data=row.get("session_data"),
            session_id=sid,
        )
        dt_label = dates.get("display_label") or "recent"
        parts.append(
            f"Session {dt_label} ({sid}, transcript_chars={raw_len}):\n{excerpt}"
        )

    if len(parts) <= 1:
        return ""

    parts.append(
        "Use this verified session dialogue to remember what was discussed. "
        "Do not quote long passages verbatim; reflect themes therapeutically."
    )
    return "\n\n".join(parts)


async def verify_path_b_transcript_for_client(
    db_pool,
    client_id: str,
) -> Dict[str, Any]:
    """Diagnostic: confirm transcript archive + LN context load for a client."""
    rows = await get_sessions_with_transcripts_pg(db_pool, client_id, limit=5)
    sessions_out: List[Dict[str, Any]] = []
    context = await get_zoom_transcript_context_pg(db_pool, client_id, limit=2)

    for row in rows:
        sd = _session_data_dict(row.get("session_data"))
        excerpt, raw_len = await load_session_transcript_excerpt(row.get("session_data"))
        classroom_ok = False
        try:
            async with db_pool.acquire() as conn:
                csa = await conn.fetchrow(
                    """
                    SELECT status, therapeutic_presence_score, analyzed_at
                    FROM classroom_session_analyses
                    WHERE session_id = $1
                    LIMIT 1
                    """,
                    row.get("session_id"),
                )
            if csa:
                classroom_ok = (csa["status"] or "") == "completed"
        except Exception:
            pass

        sessions_out.append(
            {
                "session_id": row.get("session_id"),
                "zoom_meeting_id": row.get("zoom_meeting_id"),
                "transcript_location": sd.get("transcript_location"),
                "transcript_source": sd.get("transcript_source"),
                "classroom_analysis_available": sd.get("classroom_analysis_available"),
                "nate_read_transcript_at": sd.get("nate_read_transcript_at"),
                "raw_transcript_chars": raw_len,
                "excerpt_chars": len(excerpt),
                "classroom_pg_completed": classroom_ok,
            }
        )

    return {
        "client_id": client_id,
        "sessions_with_transcript": len(rows),
        "ln_context_chars": len(context),
        "ln_context_preview": (context or "")[:500],
        "path_b_pull_ok": bool(context.strip()) and any(
            s.get("excerpt_chars", 0) > 100 for s in sessions_out
        ),
        "sessions": sessions_out,
    }
