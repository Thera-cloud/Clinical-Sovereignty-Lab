"""
QUANTUM-CRYSTAL-ARCH: Coach email + SMS for Nate session negotiation.

- HTTPS one-click links (HMAC)
- mailto: replies to approve@reply.sovereignsanctuary.net with [#neg:uuid]
- SMS short text + HTTPS links; reply APPROVE / BUSY / ALT
- Alt times always from coach_slot_engine (same as client Schedule portal)
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import os
import re
import time
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import quote

logger = logging.getLogger("nate.session_negotiation_notify")

_SECRET = (
    os.getenv("SESSION_ACTION_SECRET")
    or os.getenv("JWT_SECRET")
    or os.getenv("SECRET_KEY", "")
)
PUBLIC_API_BASE = os.getenv("PUBLIC_API_BASE", "https://api.sovereignsanctuary.net")
REPLY_TO = os.getenv(
    "SESSION_NEGOTIATION_REPLY_TO",
    "approve@reply.sovereignsanctuary.net",
)
TOKEN_TTL_SECONDS = 30 * 24 * 3600

NEG_ID_RE = re.compile(r"\[#neg:([0-9a-fA-F-]{36})\]")
NEG_DECISION_PREFIXES = ("APPROVE", "BUSY", "ALT", "DECLINE")
NEG_SYNONYMS = {
    "YES": "approve",
    "CONFIRMED": "approve",
    "CONFIRM": "approve",
    "OK": "approve",
    "NO": "busy",
    "UNAVAILABLE": "busy",
    "RESCHEDULE": "alt",
    "OTHER": "alt",
}


def make_neg_token(negotiation_id: str, action: str) -> str:
    payload = json.dumps(
        {
            "nid": negotiation_id,
            "act": action,
            "exp": int(time.time()) + TOKEN_TTL_SECONDS,
        },
        separators=(",", ":"),
    ).encode()
    body = base64.urlsafe_b64encode(payload).rstrip(b"=")
    sig = hmac.new(_SECRET.encode(), body, hashlib.sha256).hexdigest()[:32]
    return f"{body.decode()}.{sig}"


def verify_neg_token(token: str) -> Optional[Tuple[str, str]]:
    try:
        body, sig = token.rsplit(".", 1)
        expected = hmac.new(_SECRET.encode(), body.encode(), hashlib.sha256).hexdigest()[:32]
        if not hmac.compare_digest(sig, expected):
            return None
        padded = body + "=" * (-len(body) % 4)
        data = json.loads(base64.urlsafe_b64decode(padded))
        if int(data.get("exp", 0)) < time.time():
            return None
        action = (data.get("act") or "").lower()
        if action not in ("approve", "busy", "alt"):
            return None
        return str(data.get("nid", "")), action
    except Exception:
        return None


def negotiation_action_url(negotiation_id: str, action: str) -> str:
    return (
        f"{PUBLIC_API_BASE}/api/sessions-public/negotiation-action"
        f"?token={make_neg_token(negotiation_id, action)}"
    )


def mailto_action_url(negotiation_id: str, action: str, subject_base: str) -> str:
    decision = (action or "").strip().upper()
    subj = (subject_base or "Session request").strip()
    if f"[#neg:{negotiation_id}]" not in subj:
        subj = f"{subj} [#neg:{negotiation_id}]"
    if not subj.lower().startswith("re:"):
        subj = f"Re: {subj}"
    body = f"{decision}\n\n[#neg:{negotiation_id}]\n"
    return f"mailto:{REPLY_TO}?subject={quote(subj)}&body={quote(body)}"


def extract_neg_id_from_text(*parts: str) -> Optional[str]:
    blob = "\n".join(p or "" for p in parts)
    m = NEG_ID_RE.search(blob)
    return m.group(1) if m else None


def parse_neg_decision(raw: str) -> Optional[str]:
    if not raw:
        return None
    line = raw.strip().splitlines()[0].strip().upper()
    bare = re.sub(r"[^\w ]+$", "", line).strip()
    if bare in NEG_SYNONYMS:
        return NEG_SYNONYMS[bare]
    for prefix in NEG_DECISION_PREFIXES:
        if bare.startswith(prefix):
            if prefix == "DECLINE":
                return "busy"
            return prefix.lower()
    return None


async def lookup_contact(db_pool: Any, hw_or_username: str) -> Dict[str, str]:
    if not db_pool or not hw_or_username:
        return {}
    try:
        async with db_pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT username, hardware_id,
                       COALESCE(profile_data->>'email', '') AS email,
                       COALESCE(profile_data->>'phone', '') AS phone,
                       COALESCE(profile_data->>'name', username) AS name,
                       COALESCE(profile_data->>'timezone', '') AS timezone
                FROM users
                WHERE hardware_id = $1 OR username = $1
                LIMIT 1
                """,
                hw_or_username,
            )
            if not row:
                return {}
            return {
                "username": row["username"] or "",
                "hardware_id": row["hardware_id"] or "",
                "email": row["email"] or "",
                "phone": row["phone"] or "",
                "name": row["name"] or "",
                "timezone": row["timezone"] or "",
            }
    except Exception as e:
        logger.warning("session_negotiation_notify: contact lookup failed: %s", e)
        return {}


async def send_coach_negotiation_notify(
    db_pool: Any,
    negotiation: Dict[str, Any],
    session: Optional[Dict[str, Any]] = None,
) -> Dict[str, bool]:
    """Email + SMS coach with HTTPS + mailto actions. Returns channel flags."""
    out = {"email": False, "sms": False}
    if not db_pool or not negotiation:
        return out
    neg_id = str(negotiation.get("id") or "")
    coach_id = negotiation.get("coach_id") or ""
    if not neg_id or not coach_id:
        return out

    coach = await lookup_contact(db_pool, coach_id)
    client_name = (
        (session or {}).get("client_name")
        or (negotiation.get("metadata") or {}).get("client_name")
        or "Client"
    )
    when = negotiation.get("proposed_start") or (session or {}).get("scheduled_start") or "requested time"
    try:
        from app.services.session_approval import format_session_time

        when_fmt = format_session_time(
            {"scheduled_start": when},
            {"timezone": coach.get("timezone")},
        )
    except Exception:
        when_fmt = str(when)

    approve_url = negotiation_action_url(neg_id, "approve")
    busy_url = negotiation_action_url(neg_id, "busy")
    alt_url = negotiation_action_url(neg_id, "alt")
    subject_base = f"Session request from {client_name} — {when_fmt}"
    mailto_approve = mailto_action_url(neg_id, "approve", subject_base)
    mailto_busy = mailto_action_url(neg_id, "busy", subject_base)
    mailto_alt = mailto_action_url(neg_id, "alt", subject_base)

    if coach.get("email"):
        try:
            from app.services.notifications_service import EmailService

            out["email"] = bool(
                await EmailService().send_email(
                    to_email=coach["email"],
                    template_name="session_negotiation_coach",
                    context={
                        "client_name": client_name,
                        "session_time": when_fmt,
                        "approve_url": approve_url,
                        "busy_url": busy_url,
                        "alt_url": alt_url,
                        "mailto_approve": mailto_approve,
                        "mailto_busy": mailto_busy,
                        "mailto_alt": mailto_alt,
                        "neg_token": f"[#neg:{neg_id}]",
                    },
                )
            )
        except Exception as e:
            logger.warning("session_negotiation_notify: email failed: %s", e)

    phone = (coach.get("phone") or "").strip()
    if phone:
        try:
            from app.websocket.notification_system import NotificationSystem

            body = (
                f"Session request: {client_name} wants {when_fmt}. "
                f"Reply APPROVE, BUSY, or ALT (alts from your Schedule). "
                f"Or tap Approve {approve_url} · Busy {busy_url} · Alt {alt_url}"
            )
            ns = NotificationSystem(
                data_dir=os.environ.get("DATA_DIR", "/app/data"),
                sendgrid_key=os.environ.get("SENDGRID_API_KEY"),
            )
            out["sms"] = bool(await ns.send_sms(phone, body[:1500]))
        except Exception as e:
            logger.warning("session_negotiation_notify: SMS failed: %s", e)

    return out


async def send_client_negotiation_update_email(
    db_pool: Any,
    negotiation: Dict[str, Any],
    *,
    nate_message: str = "",
) -> bool:
    client_id = negotiation.get("client_id") or ""
    client = await lookup_contact(db_pool, client_id)
    if not client.get("email"):
        return False
    alts: List[Dict[str, Any]] = negotiation.get("alt_slots") or []
    alt_lines = []
    for i, slot in enumerate(alts[:5], 1):
        start = slot.get("start") if isinstance(slot, dict) else slot
        alt_lines.append(f"{i}. {start}")
    try:
        from app.services.notifications_service import EmailService

        coach = await lookup_contact(db_pool, negotiation.get("coach_id") or "")
        return bool(
            await EmailService().send_email(
                to_email=client["email"],
                template_name="session_negotiation_client",
                context={
                    "coach_name": coach.get("name") or "your coach",
                    "nate_message": nate_message or "Your coach responded about the session.",
                    "alt_slots_text": "\n".join(alt_lines) if alt_lines else "",
                    "status": negotiation.get("status") or "",
                },
            )
        )
    except Exception as e:
        logger.warning("session_negotiation_notify: client email failed: %s", e)
        return False


async def resolve_coach_open_negotiation(
    db_pool: Any,
    *,
    email: str = "",
    phone_digits: str = "",
    negotiation_id: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """Find active negotiation for a coach identified by email/phone or explicit id."""
    if not db_pool:
        return None
    try:
        from app.services.session_negotiation_service import ACTIVE_STATUSES, _row_to_dict

        async with db_pool.acquire() as conn:
            if negotiation_id:
                row = await conn.fetchrow(
                    """
                    SELECT * FROM session_negotiations
                    WHERE id = $1::uuid AND status = ANY($2::text[])
                    """,
                    negotiation_id,
                    list(ACTIVE_STATUSES),
                )
                return _row_to_dict(row) if row else None

            coach_hw = None
            if email:
                coach_hw = await conn.fetchval(
                    """
                    SELECT hardware_id FROM users
                    WHERE LOWER(profile_data->>'email') = LOWER($1)
                      AND role IN ('COACH', 'ADMIN')
                    LIMIT 1
                    """,
                    email,
                )
            if not coach_hw and phone_digits:
                digits = re.sub(r"\D", "", phone_digits)[-10:]
                if digits:
                    coach_hw = await conn.fetchval(
                        """
                        SELECT hardware_id FROM users
                        WHERE role IN ('COACH', 'ADMIN')
                          AND regexp_replace(
                                COALESCE(profile_data->>'phone', ''), '[^0-9]', '', 'g'
                              ) LIKE '%' || $1
                        LIMIT 1
                        """,
                        digits,
                    )
            if not coach_hw:
                return None
            row = await conn.fetchrow(
                """
                SELECT * FROM session_negotiations
                WHERE coach_id = $1 AND status = ANY($2::text[])
                ORDER BY updated_at DESC LIMIT 1
                """,
                coach_hw,
                list(ACTIVE_STATUSES),
            )
            return _row_to_dict(row) if row else None
    except Exception as e:
        logger.warning("session_negotiation_notify: resolve open failed: %s", e)
        return None


async def apply_coach_channel_decision(
    db_pool: Any,
    *,
    decision: str,
    negotiation_id: Optional[str] = None,
    coach_email: str = "",
    coach_phone: str = "",
) -> Dict[str, Any]:
    """
    Apply approve|busy|alt from email click, mailto inbound, or SMS.
    Mutates negotiation + coaching session JSON/PG when possible.
    """
    from app.services.session_negotiation_service import coach_decide, negotiation_enabled

    if not negotiation_enabled():
        return {"ok": False, "error": "flag_off"}

    neg = await resolve_coach_open_negotiation(
        db_pool,
        email=coach_email,
        phone_digits=coach_phone,
        negotiation_id=negotiation_id,
    )
    if not neg:
        return {"ok": False, "error": "negotiation_not_found"}

    result = await coach_decide(
        db_pool,
        coach_id=neg["coach_id"],
        negotiation_id=neg["id"],
        decision=decision,
    )
    if not result.get("ok"):
        return result

    # Persist session status changes (mirror booking-action / bridge adapter)
    try:
        from pathlib import Path
        from app.config import settings as _settings
        from app.services.pg_data_helpers import upsert_session_pg

        data_dir = Path(_settings.DATA_DIR)
        sessions_path = data_dir / "sessions.json"
        sessions: List[Dict[str, Any]] = []
        if sessions_path.exists():
            try:
                sessions = json.loads(sessions_path.read_text()) or []
            except Exception:
                sessions = []

        action = result.get("bridge_action") or "none"
        sid = result.get("session_id") or neg.get("session_id")
        found = None
        for s in sessions:
            if s.get("session_id") != sid:
                continue
            found = s
            if action == "approve_session":
                s["status"] = "scheduled"
                s["approved_via"] = "negotiation_channel"
            elif action == "decline_session":
                s["status"] = "declined"
                s["declined_via"] = "negotiation_channel"
            elif action == "reschedule_and_approve":
                s["status"] = "scheduled"
                if result.get("new_start"):
                    s["scheduled_start"] = result["new_start"]
                if result.get("new_end"):
                    s["scheduled_end"] = result["new_end"]
                s["approved_via"] = "negotiation_channel"
            break

        if found:
            try:
                sessions_path.write_text(json.dumps(sessions, indent=2, default=str))
            except Exception as e:
                logger.warning("session_negotiation_notify: sessions.json write failed: %s", e)
            try:
                await upsert_session_pg(db_pool, found)
            except Exception as e:
                logger.warning("session_negotiation_notify: PG session upsert failed: %s", e)

        # Client email with alts (slot-engine sourced)
        client_msg = result.get("client_nate_text") or ""
        await send_client_negotiation_update_email(
            db_pool,
            result.get("negotiation") or neg,
            nate_message=client_msg,
        )
    except Exception as e:
        logger.warning("session_negotiation_notify: finalize side effects failed: %s", e)

    result["via"] = "channel"
    return result
