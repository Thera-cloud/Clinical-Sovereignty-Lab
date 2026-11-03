"""Repair Zoom join/host URLs for coaching sessions.

Used by REST ensure, ICS/calendar-links, and reminder email so clients of every
account type receive a live /j/ URL instead of a deleted meeting or host ZAK.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Tuple

from app.services.calendar_invite import ics_sequence_from_session, safe_join_url
from app.services.zoom_client import ZoomClient, parse_zoom_meeting_id

logger = logging.getLogger("session_zoom_repair")


def _as_dt(value: Any) -> Optional[datetime]:
    if value is None:
        return None
    if isinstance(value, datetime):
        dtv = value
        if dtv.tzinfo is None:
            dtv = dtv.replace(tzinfo=timezone.utc)
        return dtv.astimezone(timezone.utc)
    text = str(value).strip()
    if not text:
        return None
    try:
        dtv = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if dtv.tzinfo is None:
        dtv = dtv.replace(tzinfo=timezone.utc)
    return dtv.astimezone(timezone.utc)


def _iso_z(dtv: datetime) -> str:
    return dtv.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def user_can_access_session(user: Dict[str, Any], session: dict) -> bool:
    role = str((user or {}).get("role") or "").upper()
    if role == "ADMIN":
        return True
    ids = {
        str((user or {}).get("hardware_id") or ""),
        str((user or {}).get("username") or ""),
        str((user or {}).get("id") or ""),
        str((user or {}).get("user_id") or ""),
    }
    ids.discard("")
    targets = {
        str((session or {}).get("client_id") or ""),
        str((session or {}).get("coach_id") or ""),
    }
    if ids & targets:
        return True
    sess_fam = str((session or {}).get("family_id") or "").strip()
    if not sess_fam:
        return False
    user_fam = str((user or {}).get("family_id") or "").strip()
    if not user_fam:
        pd = (user or {}).get("profile_data") or {}
        if isinstance(pd, str):
            try:
                pd = json.loads(pd)
            except Exception:
                pd = {}
        if isinstance(pd, dict):
            user_fam = str(pd.get("family_id") or "").strip()
    return bool(user_fam and sess_fam == user_fam)


def session_is_host(user: Dict[str, Any], session: dict) -> bool:
    role = str((user or {}).get("role") or "").upper()
    if role == "ADMIN":
        return True
    ids = {
        str((user or {}).get("hardware_id") or ""),
        str((user or {}).get("username") or ""),
        str((user or {}).get("id") or ""),
        str((user or {}).get("user_id") or ""),
    }
    ids.discard("")
    return str((session or {}).get("coach_id") or "") in ids


def zoom_meeting_id_from_session(session: dict) -> str:
    mid = str((session or {}).get("zoom_meeting_id") or "").strip()
    if mid:
        return mid
    return parse_zoom_meeting_id(
        (session or {}).get("zoom_link") or "",
        (session or {}).get("zoom_host_url") or "",
        (session or {}).get("join_url") or "",
        (session or {}).get("meeting_url") or "",
    )


def zoom_start_and_duration(session: dict) -> Tuple[str, int]:
    st = _as_dt((session or {}).get("scheduled_start") or (session or {}).get("scheduled_at"))
    en = _as_dt((session or {}).get("scheduled_end"))
    now = datetime.now(timezone.utc)
    dur_min = 50
    try:
        if st and en and en > st:
            dur_min = max(5, int((en - st).total_seconds() / 60))
        if en and en > now:
            dur_min = max(dur_min, int((en - now).total_seconds() / 60))
        dur_min = max(int(dur_min or 50), 60)
    except Exception:
        dur_min = 60
    if st and st >= now:
        start_iso = _iso_z(st)
    else:
        start_iso = _iso_z(now)
    return start_iso, dur_min


def apply_zoom_result(session: dict, zoom_resp: dict) -> bool:
    """Mutate session with join/host/id. Bump ICS sequence when meeting is recreated."""
    recreated = bool((zoom_resp or {}).get("recreated"))
    join_url = str((zoom_resp or {}).get("join_url") or "")
    start_url = str((zoom_resp or {}).get("start_url") or "")
    new_mid = str((zoom_resp or {}).get("id") or "")
    if join_url:
        session["zoom_link"] = join_url
        session["join_url"] = join_url
    if start_url:
        session["zoom_host_url"] = start_url
    if new_mid:
        session["zoom_meeting_id"] = new_mid
    if recreated:
        seq = ics_sequence_from_session(session) + 1
        sd = session.get("session_data")
        if not isinstance(sd, dict):
            sd = {}
        else:
            sd = dict(sd)
        sd["ics_sequence"] = seq
        session["session_data"] = sd
        session["ics_sequence"] = seq
    return recreated


def client_join_url(session: dict) -> str:
    return safe_join_url(
        (session or {}).get("zoom_link"),
        (session or {}).get("join_url"),
        (session or {}).get("zoom_join_url"),
    )


def session_dict_from_row(row: Any, *, client_name: str = "") -> Dict[str, Any]:
    d = dict(row) if not isinstance(row, dict) else dict(row)
    sd = d.get("session_data")
    if isinstance(sd, str):
        try:
            sd = json.loads(sd)
        except Exception:
            sd = {}
    if not isinstance(sd, dict):
        sd = {}
    sid = str(d.get("session_id") or "")
    return {
        "session_id": sid,
        "id": sid,
        "client_id": d.get("client_id") or "",
        "coach_id": d.get("coach_id") or "",
        "scheduled_start": d.get("scheduled_start") or d.get("scheduled_at"),
        "scheduled_end": d.get("scheduled_end"),
        "zoom_link": d.get("zoom_link") or "",
        "zoom_host_url": d.get("zoom_host_url") or "",
        "zoom_meeting_id": d.get("zoom_meeting_id") or "",
        "session_data": sd,
        "client_name": client_name or d.get("client_name") or "",
        "notes": d.get("notes") or "",
        "family_id": d.get("family_id") or "",
        "status": d.get("status") or "scheduled",
        "consultation_email": d.get("consultation_email") or "",
    }


async def mint_session_zoom(
    session: dict,
    client: Optional[ZoomClient] = None,
) -> Tuple[dict, bool]:
    zc = client or ZoomClient.from_env()
    mid = zoom_meeting_id_from_session(session)
    start_iso, dur_min = zoom_start_and_duration(session)
    client_name = str((session or {}).get("client_name") or "").strip() or "Client"
    topic = f"Coaching Session — {client_name}"
    zoom_resp = await zc.ensure_scheduled_meeting(
        meeting_id=mid,
        topic=topic,
        start_time_iso=start_iso,
        duration_minutes=dur_min,
        agenda=str((session or {}).get("notes") or ""),
    )
    recreated = apply_zoom_result(session, zoom_resp)
    return session, recreated


async def mint_and_persist(
    db_pool,
    session: dict,
    *,
    zoom_client: Optional[ZoomClient] = None,
) -> Tuple[dict, bool]:
    session, recreated = await mint_session_zoom(session, zoom_client)
    if db_pool is not None:
        try:
            from app.services.pg_data_helpers import upsert_session_pg

            await upsert_session_pg(db_pool, session)
        except Exception as e:
            logger.warning("mint_and_persist upsert failed: %s", e)
    return session, recreated
