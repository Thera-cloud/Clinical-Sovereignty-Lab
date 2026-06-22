"""
Coach schedule link hide + calendar reference flags (QUANTUM-CRYSTAL-ARCH).

Soft-hide removes actionable Schedule cards while keeping calendar dots.
Syncs PG coaching_sessions, backend sessions.json, and coach vault schedule.json.
"""

from __future__ import annotations

import json
import logging
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger("session_schedule_link")

ACTIVE_ACTION_STATUSES = frozenset({"scheduled", "active", "pending_approval"})


def _safe_id(raw_id: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_\-]", "", str(raw_id or ""))


def vault_root() -> Path:
    return Path(os.environ.get("BRIDGE_DATA_DIR", "/app/bridge_data")) / "Vaults"


def coach_schedule_path(coach_id: str) -> Path:
    return vault_root() / "Coaches" / _safe_id(coach_id) / "schedule.json"


def session_data_dict(session: Dict[str, Any]) -> Dict[str, Any]:
    sd = session.get("session_data")
    if sd is None:
        sd = {}
    if isinstance(sd, str):
        try:
            sd = json.loads(sd) if sd else {}
        except Exception:
            sd = {}
    if not isinstance(sd, dict):
        sd = {}
    merged = dict(sd)
    for key in (
        "transcript_location",
        "transcript_archived_at",
        "schedule_link_hidden",
        "schedule_link_removed_at",
        "zoom_folder_doc_placed",
        "zoom_folder_file_id",
    ):
        if key in session and session.get(key) not in (None, ""):
            merged[key] = session[key]
    return merged


def has_archived_transcript(session: Dict[str, Any]) -> bool:
    sd = session_data_dict(session)
    return bool(
        str(sd.get("transcript_location") or "").strip()
        or str(sd.get("transcript_archived_at") or "").strip()
    )


def is_schedule_link_hidden(session: Dict[str, Any]) -> bool:
    sd = session_data_dict(session)
    v = sd.get("schedule_link_hidden", session.get("schedule_link_hidden"))
    if v is True:
        return True
    return str(v or "").lower() in ("true", "1", "yes")


def _parse_start_utc(session: Dict[str, Any]) -> Optional[datetime]:
    raw = (
        session.get("scheduled_start")
        or session.get("scheduled_time")
        or ""
    )
    if not raw and session.get("date"):
        t = (session.get("time") or "09:00").strip()
        raw = f"{session.get('date')}T{t}"
    if not raw:
        return None
    try:
        s = str(raw).replace("Z", "+00:00")
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        return None


def archive_required_before_hide(session: Dict[str, Any]) -> bool:
    """Past sessions require archived transcript before removing schedule link."""
    st = _parse_start_utc(session)
    if not st:
        return False
    return st < datetime.now(timezone.utc)


def show_in_action_list(item: Dict[str, Any]) -> bool:
    if is_schedule_link_hidden(item):
        return False
    status = (item.get("status") or "scheduled").lower()
    return status in ACTIVE_ACTION_STATUSES


def annotate_calendar_item(item: Dict[str, Any]) -> Dict[str, Any]:
    out = dict(item)
    actionable = show_in_action_list(out)
    out["show_in_action_list"] = actionable
    out["calendar_reference_only"] = not actionable
    return out


def annotate_calendar_schedule(schedule: List[Any]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for raw in schedule or []:
        if not isinstance(raw, dict):
            continue
        out.append(annotate_calendar_item(dict(raw)))
    return out


def _patch_coach_schedule_json(coach_id: str, session_id: str, patch: Dict[str, Any]) -> None:
    path = coach_schedule_path(coach_id)
    if not path.parent.exists():
        return
    schedule: List[Dict[str, Any]] = []
    if path.exists():
        try:
            with open(path, "r", encoding="utf-8") as f:
                loaded = json.load(f)
            if isinstance(loaded, list):
                schedule = loaded
        except Exception as e:
            logger.warning("schedule.json read failed coach=%s: %s", coach_id, e)
            return

    sid = str(session_id or "").strip()
    matched = False
    for entry in schedule:
        if not isinstance(entry, dict):
            continue
        eid = str(entry.get("id") or entry.get("session_id") or "").strip()
        if eid == sid:
            entry.update(patch)
            entry["status"] = patch.get("status", entry.get("status", "completed"))
            matched = True
            break

    if not matched and patch.get("calendar_reference_stub"):
        schedule.append(patch["calendar_reference_stub"])

    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(schedule, f, indent=2)
        try:
            path.chmod(0o644)
        except Exception:
            pass
    except Exception as e:
        logger.warning("schedule.json write failed coach=%s: %s", coach_id, e)


async def hide_session_schedule_link(
    db_pool,
    session: Dict[str, Any],
    sessions_list: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """
    Soft-hide session from coach action list; retain calendar reference.
    Updates PG, optional JSON session list, and coach vault schedule.json.
    """
    session_id = str(session.get("session_id") or session.get("id") or "").strip()
    coach_id = str(session.get("coach_id") or "").strip()
    if not session_id or not coach_id:
        raise ValueError("session_id and coach_id required")

    now_iso = datetime.now(timezone.utc).isoformat()
    patch = {
        "schedule_link_hidden": True,
        "schedule_link_removed_at": now_iso,
        "calendar_reference_only": True,
    }

    session = dict(session)
    session["status"] = "completed"
    session["schedule_link_hidden"] = True
    session["schedule_link_removed_at"] = now_iso
    session["calendar_reference_only"] = True
    sd = session_data_dict(session)
    sd.update(patch)
    session["session_data"] = sd

    if db_pool:
        try:
            async with db_pool.acquire() as conn:
                await conn.execute(
                    """
                    UPDATE coaching_sessions
                    SET status = 'completed',
                        session_data = COALESCE(session_data, '{}'::jsonb) || $2::jsonb,
                        updated_at = NOW()
                    WHERE session_id = $1
                    """,
                    session_id,
                    json.dumps(patch, default=str),
                )
        except Exception as e:
            logger.warning("hide_session_schedule_link PG failed %s: %s", session_id, e)
            raise

    if sessions_list is not None:
        for s in sessions_list:
            if str(s.get("session_id") or "") == session_id:
                s["status"] = "completed"
                s.update(patch)
                if isinstance(s.get("session_data"), dict):
                    s["session_data"].update(patch)
                else:
                    s["session_data"] = {**session_data_dict(s), **patch}
                break

    stub = {
        "id": session_id,
        "session_id": session_id,
        "coach_id": coach_id,
        "client_id": session.get("client_id") or "",
        "client_name": session.get("client_name") or "",
        "date": (session.get("date") or "")[:10]
        or (_parse_start_utc(session).date().isoformat() if _parse_start_utc(session) else ""),
        "time": session.get("time") or "",
        "scheduled_start": session.get("scheduled_start") or "",
        "status": "completed",
        **patch,
    }
    _patch_coach_schedule_json(
        coach_id,
        session_id,
        {
            **patch,
            "status": "completed",
            "calendar_reference_stub": stub,
        },
    )

    return annotate_calendar_item(session)
