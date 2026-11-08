"""Tap-to-confirm tokens for upcoming coaching sessions.

48h email carries a signed link. Tapping records client_confirmed_at.
Charge at 24h still runs whether or not they tap; unpaid + failed charge
still cancels. This is attendance confirmation, not payment.
"""

from __future__ import annotations

import hashlib
import html
import logging
import os
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

logger = logging.getLogger("nate.session_confirm")


def _salt() -> str:
    return (
        os.getenv("SESSION_CONFIRM_TOKEN_SALT")
        or os.getenv("JWT_SECRET")
        or "session-confirm"
    )


def hash_confirm_token(raw: str) -> str:
    return hashlib.sha256(f"{_salt()}:{raw}".encode()).hexdigest()


def mint_raw_token() -> str:
    return secrets.token_urlsafe(32)


def confirm_url(raw: str) -> str:
    base = os.getenv("API_PUBLIC_BASE", "https://api.sovereignsanctuary.net").rstrip("/")
    return f"{base}/api/billing/session-confirm?t={raw}"


def confirm_html(*, ok: bool, when: str = "", already: bool = False, expired: bool = False) -> str:
    if ok and already:
        title, body, color = "Already confirmed", "This appointment was already confirmed. You are set.", "#C9A962"
    elif ok:
        title, body, color = "Appointment confirmed", f"You confirmed your session{(' on <strong>' + html.escape(when) + '</strong>') if when else ''}.", "#C9A962"
    elif expired:
        title, body, color = "Link expired", "This confirm link is no longer valid. Open Schedule in the app if you still plan to attend.", "#EF4444"
    else:
        title, body, color = "Link not valid", "This confirm link was already used or does not match an upcoming session.", "#EF4444"
    return (
        "<!DOCTYPE html><html><head><meta charset='utf-8'><meta name='viewport' "
        "content='width=device-width,initial-scale=1'><title>Sovereign Sanctuary</title></head>"
        "<body style='font-family:sans-serif;background:#050505;color:#e5e5e5;padding:24px;'>"
        "<div style='max-width:520px;margin:auto;background:#111;border:1px solid "
        f"{color};border-radius:8px;padding:28px;'>"
        f"<h2 style='color:{color};margin-top:0;'>{title}</h2>"
        f"<p>{body}</p>"
        "<p style='color:#64748b;font-size:13px;'>Your card on file is still charged about "
        "24 hours before the session. Cancel from Schedule 24 hours or more before start "
        "to void the invoice.</p>"
        "<p><a href='https://app.sovereignsanctuary.net' style='color:#C9A962;'>Open Sovereign Sanctuary</a></p>"
        "</div></body></html>"
    )


def _as_utc(value: Any) -> Optional[datetime]:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    raw = str(value).strip().replace("Z", "+00:00")
    if not raw:
        return None
    try:
        dt = datetime.fromisoformat(raw)
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


async def issue_confirm_token(conn, session_id, scheduled_at=None) -> Optional[str]:
    """Mint a new hash, store it, return the raw token for the email URL."""
    if not session_id:
        return None
    row = await conn.fetchrow(
        """SELECT client_confirmed_at, status
           FROM coaching_sessions WHERE id = $1""",
        session_id,
    )
    if not row:
        return None
    if str(row["status"] or "").upper() in (
        "CANCELLED", "CANCELED", "RESCHEDULED", "CANCELLED_BY_GOOGLE",
    ):
        return None
    if row["client_confirmed_at"]:
        return None
    raw = mint_raw_token()
    start = _as_utc(scheduled_at) or (datetime.now(timezone.utc) + timedelta(hours=72))
    await conn.execute(
        """UPDATE coaching_sessions
              SET confirm_token_hash = $2,
                  confirm_token_expires_at = $3,
                  updated_at = NOW()
            WHERE id = $1""",
        session_id,
        hash_confirm_token(raw),
        start,
    )
    return raw


async def consume_confirm_token(conn, raw: str) -> Dict[str, Any]:
    """Mark the session confirmed. Returns {ok, already, expired, when, session_id, ...}."""
    out: Dict[str, Any] = {
        "ok": False, "already": False, "expired": False,
        "when": "", "session_id": "", "client_id": "", "coach_id": "",
        "client_name": "", "coach_email": "", "coach_name": "",
    }
    token = (raw or "").strip()
    if len(token) < 16 or len(token) > 128:
        return out
    th = hash_confirm_token(token)
    row = await conn.fetchrow(
        f"""SELECT cs.id, cs.session_id, cs.client_id, cs.coach_id, cs.client_name,
                  cs.client_confirmed_at, cs.confirm_token_expires_at, cs.status,
                  COALESCE(cs.scheduled_start, cs.scheduled_at) AS scheduled_at,
                  cu.profile_data->>'email' AS coach_email,
                  cu.profile_data->>'name' AS coach_name
           FROM coaching_sessions cs
           LEFT JOIN users cu ON cu.id::text = cs.coach_id::text
              OR cu.hardware_id = cs.coach_id::text
           WHERE cs.confirm_token_hash = $1
           LIMIT 1""",
        th,
    )
    if not row:
        return out
    status = str(row["status"] or "").upper()
    if status in ("CANCELLED", "CANCELED", "RESCHEDULED", "CANCELLED_BY_GOOGLE"):
        return out
    exp = row["confirm_token_expires_at"]
    now = datetime.now(timezone.utc)
    if exp is not None:
        exp_dt = exp if getattr(exp, "tzinfo", None) else _as_utc(exp)
        if exp_dt and exp_dt < now:
            out["expired"] = True
            return out
    already = bool(row["client_confirmed_at"])
    await conn.execute(
        """UPDATE coaching_sessions
              SET client_confirmed_at = COALESCE(client_confirmed_at, NOW()),
                  confirm_token_hash = NULL,
                  confirm_token_expires_at = NULL,
                  session_data = COALESCE(session_data, '{}'::jsonb)
                    || jsonb_build_object('client_confirmed_at', NOW()::text),
                  updated_at = NOW()
            WHERE id = $1""",
        row["id"],
    )
    try:
        await conn.execute(
            """INSERT INTO session_notifications
                   (session_id, notification_type, channel, recipient_id)
               VALUES ($1, 'client_confirmed', 'email', $2)
               ON CONFLICT DO NOTHING""",
            row["id"], row["client_id"],
        )
    except Exception as e:
        logger.warning("session_confirm notify log: %s", e)
    when = ""
    start = row["scheduled_at"]
    if start:
        when = str(start)
    out.update({
        "ok": True,
        "already": already,
        "when": when,
        "session_id": row["session_id"] or "",
        "client_id": row["client_id"] or "",
        "coach_id": row["coach_id"] or "",
        "client_name": row["client_name"] or "",
        "coach_email": row["coach_email"] or "",
        "coach_name": row["coach_name"] or "",
        "session_uuid": row["id"],
    })
    return out


async def confirm_session_for_user(
    conn,
    session_id: str,
    *,
    username: str = "",
    hardware_id: str = "",
) -> Dict[str, Any]:
    """Authenticated in-app confirm. Matches client_id to login identity, not the email token."""
    out: Dict[str, Any] = {
        "ok": False, "already": False, "expired": False,
        "when": "", "session_id": "", "client_id": "", "coach_id": "",
        "client_name": "", "coach_email": "", "coach_name": "",
    }
    sid = (session_id or "").strip()
    if not sid:
        return out
    ids = [i for i in (username, hardware_id) if i]
    if not ids:
        return out
    row = await conn.fetchrow(
        """SELECT cs.id, cs.session_id, cs.client_id, cs.coach_id, cs.client_name,
                  cs.client_confirmed_at, cs.status,
                  COALESCE(cs.scheduled_start, cs.scheduled_at) AS scheduled_at,
                  cu.profile_data->>'email' AS coach_email,
                  cu.profile_data->>'name' AS coach_name
           FROM coaching_sessions cs
           LEFT JOIN users cu ON cu.id::text = cs.coach_id::text
              OR cu.hardware_id = cs.coach_id::text
           WHERE cs.session_id = $1
           LIMIT 1""",
        sid,
    )
    if not row:
        return out
    client_id = str(row["client_id"] or "")
    if client_id not in ids:
        aliases = await conn.fetch(
            """SELECT hardware_id, username FROM users
               WHERE hardware_id = ANY($1::text[]) OR username = ANY($1::text[])""",
            ids,
        )
        allowed = set(ids)
        for a in aliases:
            if a["hardware_id"]:
                allowed.add(a["hardware_id"])
            if a["username"]:
                allowed.add(a["username"])
        if client_id not in allowed:
            return out
    status = str(row["status"] or "").upper()
    if status in ("CANCELLED", "CANCELED", "RESCHEDULED", "CANCELLED_BY_GOOGLE"):
        return out
    already = bool(row["client_confirmed_at"])
    await conn.execute(
        """UPDATE coaching_sessions
              SET client_confirmed_at = COALESCE(client_confirmed_at, NOW()),
                  session_data = COALESCE(session_data, '{}'::jsonb)
                    || jsonb_build_object('client_confirmed_at', NOW()::text),
                  updated_at = NOW()
            WHERE id = $1""",
        row["id"],
    )
    when = str(row["scheduled_at"] or "")
    out.update({
        "ok": True,
        "already": already,
        "when": when,
        "session_id": row["session_id"] or "",
        "client_id": row["client_id"] or "",
        "coach_id": row["coach_id"] or "",
        "client_name": row["client_name"] or "",
        "coach_email": row["coach_email"] or "",
        "coach_name": row["coach_name"] or "",
        "session_uuid": row["id"],
    })
    return out
