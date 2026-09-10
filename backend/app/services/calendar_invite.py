"""Client add-to-calendar links (ICS + Google + Outlook).

Join Zoom stays a separate action. Host start URLs (/s/…?zak=) are never used
as calendar location or as the event URL.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional
from urllib.parse import quote, urlencode

logger_name = "nate.calendar_invite"

_ZOOM_HOST = re.compile(r"zoom\.us/s/|zak=", re.I)
_ZOOM_JOIN = re.compile(r"zoom\.us/(j|wc)/", re.I)
_MEETING_ID = re.compile(r"zoom\.us/(?:s|j|wc)/(\d+)", re.I)

TOKEN_TTL_SECONDS = 180 * 24 * 3600


def public_api_base() -> str:
    return (os.getenv("PUBLIC_API_BASE") or "https://api.sovereignsanctuary.net").rstrip("/")


def _secret() -> str:
    return (
        os.getenv("SESSION_ACTION_SECRET")
        or os.getenv("JWT_SECRET")
        or os.getenv("SECRET_KEY")
        or ""
    )


def safe_join_url(*candidates: Optional[str]) -> str:
    """Return the first https Zoom join URL. Drops host/start URLs."""
    for raw in candidates:
        u = (raw or "").strip()
        if not u or not u.lower().startswith("https://"):
            continue
        if _ZOOM_HOST.search(u):
            continue
        if _ZOOM_JOIN.search(u):
            return u
    return ""


def join_from_host_path(host_url: str) -> str:
    """Public /j/{id} from a host /s/{id} URL. No zak. Password unknown."""
    if not host_url:
        return ""
    m = _MEETING_ID.search(host_url)
    if not m:
        return ""
    return f"https://zoom.us/j/{m.group(1)}"


def _as_utc(value: Any) -> Optional[datetime]:
    if value is None:
        return None
    if isinstance(value, datetime):
        dt = value
    else:
        text = str(value).strip()
        if not text:
            return None
        try:
            dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _fmt_ics(dt: datetime) -> str:
    return dt.strftime("%Y%m%dT%H%M%SZ")


def _fold(line: str) -> str:
    if len(line) <= 75:
        return line
    out = [line[:75]]
    rest = line[75:]
    while rest:
        out.append(" " + rest[:74])
        rest = rest[74:]
    return "\r\n".join(out)


def _esc_ics(text: str) -> str:
    return (
        (text or "")
        .replace("\\", "\\\\")
        .replace(";", "\\;")
        .replace(",", "\\,")
        .replace("\r\n", "\\n")
        .replace("\n", "\\n")
    )


@dataclass(frozen=True)
class CalendarInvite:
    google_url: str
    outlook_url: str
    ics_url: str
    ics_bytes: bytes
    join_url: str
    summary: str


def sign_ics_token(*, session_id: str, client_id: str, ttl: int = TOKEN_TTL_SECONDS) -> str:
    secret = _secret()
    if not secret or not session_id:
        return ""
    payload = {
        "sid": session_id,
        "cid": client_id or "",
        "exp": int(datetime.now(timezone.utc).timestamp()) + int(ttl),
    }
    body = base64.urlsafe_b64encode(json.dumps(payload, separators=(",", ":")).encode()).decode()
    sig = hmac.new(secret.encode(), body.encode(), hashlib.sha256).hexdigest()
    return f"{body}.{sig}"


def verify_ics_token(token: str) -> Optional[Dict[str, str]]:
    secret = _secret()
    if not secret or not token or "." not in token:
        return None
    body, sig = token.rsplit(".", 1)
    expect = hmac.new(secret.encode(), body.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expect, sig):
        return None
    try:
        pad = "=" * (-len(body) % 4)
        payload = json.loads(base64.urlsafe_b64decode(body + pad))
    except Exception:
        return None
    exp = int(payload.get("exp") or 0)
    if exp < int(datetime.now(timezone.utc).timestamp()):
        return None
    sid = str(payload.get("sid") or "").strip()
    if not sid:
        return None
    return {"session_id": sid, "client_id": str(payload.get("cid") or "")}


def build_ics(
    *,
    session_id: str,
    summary: str,
    start: datetime,
    end: datetime,
    description: str,
    join_url: str = "",
) -> bytes:
    uid = f"sanctuary-{session_id}@sovereignsanctuary.net"
    stamp = _fmt_ics(datetime.now(timezone.utc))
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//Sovereign Sanctuary//Session Invite//EN",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        "BEGIN:VEVENT",
        f"UID:{uid}",
        f"DTSTAMP:{stamp}",
        f"DTSTART:{_fmt_ics(start)}",
        f"DTEND:{_fmt_ics(end)}",
        _fold(f"SUMMARY:{_esc_ics(summary)}"),
        _fold(f"DESCRIPTION:{_esc_ics(description)}"),
        "LOCATION:Sovereign Sanctuary session",
    ]
    if join_url:
        lines.append(_fold(f"URL:{join_url}"))
    lines.extend(["END:VEVENT", "END:VCALENDAR", ""])
    return "\r\n".join(lines).encode("utf-8")


def google_template_url(*, summary: str, start: datetime, end: datetime, details: str) -> str:
    dates = f"{_fmt_ics(start)}/{_fmt_ics(end)}"
    q = urlencode(
        {
            "action": "TEMPLATE",
            "text": summary,
            "dates": dates,
            "details": details,
            "location": "Sovereign Sanctuary session",
        }
    )
    return f"https://calendar.google.com/calendar/render?{q}"


def outlook_template_url(*, summary: str, start: datetime, end: datetime, details: str) -> str:
    q = urlencode(
        {
            "subject": summary,
            "startdt": start.isoformat().replace("+00:00", "Z"),
            "enddt": end.isoformat().replace("+00:00", "Z"),
            "body": details,
            "location": "Sovereign Sanctuary session",
            "path": "/calendar/action/compose",
            "rru": "addevent",
        }
    )
    return f"https://outlook.live.com/calendar/0/deeplink/compose?{q}"


def build_invite(
    *,
    session_id: str,
    coach_name: str,
    scheduled_start: Any,
    scheduled_end: Any = None,
    join_url: str = "",
    zoom_link: str = "",
    zoom_host_url: str = "",
    client_id: str = "",
    duration_minutes: int = 50,
) -> Optional[CalendarInvite]:
    start = _as_utc(scheduled_start)
    if not start:
        return None
    end = _as_utc(scheduled_end)
    if not end or end <= start:
        end = start + timedelta(minutes=max(5, int(duration_minutes or 50)))

    join = safe_join_url(join_url, zoom_link)
    if not join and zoom_host_url:
        join = join_from_host_path(zoom_host_url)

    coach = (coach_name or "your coach").strip() or "your coach"
    summary = f"Sanctuary session with {coach}"
    details = (
        f"Coaching session with {coach}.\n"
        "Add this event to your calendar. Do not use this link to start Zoom."
    )
    if join:
        details += f"\n\nJoin Zoom at session time:\n{join}"

    ics = build_ics(
        session_id=session_id or "session",
        summary=summary,
        start=start,
        end=end,
        description=details,
        join_url=join,
    )
    token = sign_ics_token(session_id=session_id or "", client_id=client_id)
    ics_url = f"{public_api_base()}/api/sessions-public/calendar.ics?t={quote(token)}" if token else ""
    return CalendarInvite(
        google_url=google_template_url(summary=summary, start=start, end=end, details=details),
        outlook_url=outlook_template_url(summary=summary, start=start, end=end, details=details),
        ics_url=ics_url,
        ics_bytes=ics,
        join_url=join,
        summary=summary,
    )


def email_context(invite: Optional[CalendarInvite]) -> Dict[str, Any]:
    if not invite:
        return {
            "google_cal_url": "",
            "outlook_cal_url": "",
            "ics_url": "",
            "ics_bytes": None,
        }
    return {
        "google_cal_url": invite.google_url,
        "outlook_cal_url": invite.outlook_url,
        "ics_url": invite.ics_url,
        "ics_bytes": invite.ics_bytes,
    }


def html_cta_fragment(invite: Optional[CalendarInvite], *, include_join: bool = False) -> str:
    if not invite:
        return ""
    parts = [
        '<p style="margin-top:20px;color:#9A9A9A;">'
        "Add this appointment to your calendar. These links save the event — they do not start Zoom."
        "</p>"
    ]
    if invite.google_url:
        parts.append(
            f'<p><a href="{invite.google_url}" style="color:#C9A962;">Add to Google Calendar</a></p>'
        )
    if invite.outlook_url:
        parts.append(
            f'<p><a href="{invite.outlook_url}" style="color:#C9A962;">Add to Outlook</a></p>'
        )
    if invite.ics_url:
        parts.append(
            f'<p><a href="{invite.ics_url}" style="color:#C9A962;">Apple Calendar / ICS</a></p>'
        )
    if include_join and invite.join_url:
        parts.append(
            f'<p style="margin-top:16px;"><a href="{invite.join_url}" style="color:#4ECDC4;">Join Zoom at session time</a></p>'
        )
    return "\n".join(parts)


def invite_from_session(session: Dict[str, Any], *, coach_name: str = "") -> Optional[CalendarInvite]:
    if not session:
        return None
    return build_invite(
        session_id=str(session.get("session_id") or session.get("id") or ""),
        coach_name=coach_name or str(session.get("coach_name") or "your coach"),
        scheduled_start=session.get("scheduled_start") or session.get("scheduled_at"),
        scheduled_end=session.get("scheduled_end"),
        join_url=str(session.get("join_url") or ""),
        zoom_link=str(session.get("zoom_link") or ""),
        zoom_host_url=str(session.get("zoom_host_url") or ""),
        client_id=str(session.get("client_id") or ""),
        duration_minutes=int(session.get("duration_minutes") or 50) if str(session.get("duration_minutes") or "").strip() else 50,
    )
