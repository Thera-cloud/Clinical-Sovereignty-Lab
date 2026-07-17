"""
QUANTUM-CRYSTAL-ARCH: Coach/client email + SMS for Nate session negotiation.

- HTTPS one-click links (HMAC) — staging uses STAGING_PUBLIC_API_BASE when set
- mailto: replies to approve@reply.sovereignsanctuary.net with [#neg:uuid]
- SMS short text + HTTPS links; reply APPROVE / BUSY / ALT
- Client accept_alt / reject_alt links when alts are offered
- Channel approve mirrors booking-action: Zoom + ledger + GCal + Redis WS fanout
- Alt times always from coach_slot_engine (same as client Schedule portal)
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import json
import logging
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import quote

logger = logging.getLogger("nate.session_negotiation_notify")

_SECRET = (
    os.getenv("SESSION_ACTION_SECRET")
    or os.getenv("JWT_SECRET")
    or os.getenv("SECRET_KEY", "")
)
REPLY_TO = os.getenv(
    "SESSION_NEGOTIATION_REPLY_TO",
    "approve@reply.sovereignsanctuary.net",
)
TOKEN_TTL_SECONDS = 30 * 24 * 3600
SESSION_NEGOTIATION_CHANNEL = "nate:session_negotiation"
_COACH_ACTIONS = frozenset({"approve", "busy", "alt"})
_CLIENT_ACTIONS = frozenset({"accept_alt", "reject_alt"})
_ALL_ACTIONS = _COACH_ACTIONS | _CLIENT_ACTIONS

NEG_ID_RE = re.compile(r"\[#neg:([0-9a-fA-F-]{36})\]")
NEG_DECISION_PREFIXES = ("APPROVE", "BUSY", "ALT", "DECLINE", "ACCEPT", "REJECT")
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


def _runtime_env() -> str:
    return (os.getenv("ENVIRONMENT") or "production").strip().lower() or "production"


def _public_api_base() -> str:
    """
    Staging emails must use a phone-reachable host. Loopback STAGING_PUBLIC_API_BASE
    is ignored in favor of PUBLIC_API_BASE so prod negotiation-action can fall back
    to the staging DB when ENABLE_STAGING_NEGOTIATION_INBOUND_FALLBACK is on.
    """
    prod_default = (os.getenv("PUBLIC_API_BASE") or "https://api.sovereignsanctuary.net").rstrip("/")
    if _runtime_env() == "staging":
        staged = (
            os.getenv("STAGING_PUBLIC_API_BASE")
            or os.getenv("PUBLIC_API_BASE_STAGING")
            or ""
        ).strip().rstrip("/")
        if staged and "127.0.0.1" not in staged and "localhost" not in staged:
            return staged
        return prod_default
    return prod_default


def staging_inbound_fallback_enabled() -> bool:
    return os.getenv("ENABLE_STAGING_NEGOTIATION_INBOUND_FALLBACK", "false").strip().lower() in (
        "1",
        "true",
        "yes",
    )


_staging_pool: Any = None


async def _get_staging_pool() -> Any:
    """Lazy pool to little_nate_staging for prod inbound/HTTPS fallback."""
    global _staging_pool
    url = (os.getenv("STAGING_NEGOTIATION_DATABASE_URL") or "").strip()
    if not url:
        return None
    if _staging_pool is not None:
        return _staging_pool
    try:
        import asyncpg

        _staging_pool = await asyncpg.create_pool(url, min_size=1, max_size=2, command_timeout=30)
        return _staging_pool
    except Exception as e:
        logger.warning("session_negotiation_notify: staging pool failed: %s", e)
        return None


def make_neg_token(negotiation_id: str, action: str, slot: str = "") -> str:
    payload = json.dumps(
        {
            "nid": negotiation_id,
            "act": action,
            "slot": slot or "",
            "exp": int(time.time()) + TOKEN_TTL_SECONDS,
        },
        separators=(",", ":"),
    ).encode()
    body = base64.urlsafe_b64encode(payload).rstrip(b"=")
    sig = hmac.new(_SECRET.encode(), body, hashlib.sha256).hexdigest()[:32]
    return f"{body.decode()}.{sig}"


def verify_neg_token(token: str) -> Optional[Tuple[str, str, str]]:
    """Return (negotiation_id, action, slot) or None."""
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
        if action not in _ALL_ACTIONS:
            return None
        return str(data.get("nid", "")), action, str(data.get("slot") or "")
    except Exception:
        return None


def negotiation_action_url(negotiation_id: str, action: str, slot: str = "") -> str:
    return (
        f"{_public_api_base()}/api/sessions-public/negotiation-action"
        f"?token={make_neg_token(negotiation_id, action, slot=slot)}"
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
            if prefix == "ACCEPT":
                return "accept_alt"
            if prefix == "REJECT":
                return "reject_alt"
            return prefix.lower()
    return None


def parse_accept_slot_index(raw: str) -> Optional[int]:
    """0-based index from 'ACCEPT 2' / 'ACCEPT #1' (1-based in text)."""
    if not raw:
        return None
    line = raw.strip().splitlines()[0].strip().upper()
    m = re.match(r"ACCEPT\s*[#:]?\s*(\d+)", line)
    if not m:
        return None
    n = int(m.group(1))
    if n < 1:
        return None
    return n - 1


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
    neg_id = str(negotiation.get("id") or "")
    alts: List[Dict[str, Any]] = negotiation.get("alt_slots") or []
    alt_lines = []
    accept_links_html = []
    for i, slot in enumerate(alts[:5], 1):
        start = slot.get("start") if isinstance(slot, dict) else slot
        alt_lines.append(f"{i}. {start}")
        if neg_id and start:
            url = negotiation_action_url(neg_id, "accept_alt", slot=str(start))
            accept_links_html.append(
                f'<a href="{url}" style="display:inline-block;background:#4ECDC4;color:#050505;'
                f'font-weight:bold;padding:10px 16px;border-radius:6px;text-decoration:none;margin:4px;">'
                f"Accept option {i}</a>"
            )
    reject_url = negotiation_action_url(neg_id, "reject_alt") if neg_id else ""
    # Prefer ACCEPT 1 in mailto body when multiple alts (slot picker via index).
    mailto_accept = (
        mailto_action_url(neg_id, "accept 1", f"Session alts [#neg:{neg_id}]") if neg_id else ""
    )
    mailto_reject = (
        mailto_action_url(neg_id, "reject", f"Session alts [#neg:{neg_id}]") if neg_id else ""
    )
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
                    "accept_links_html": " ".join(accept_links_html),
                    "reject_url": reject_url,
                    "mailto_accept": mailto_accept,
                    "mailto_reject": mailto_reject,
                    "status": negotiation.get("status") or "",
                    "neg_token": f"[#neg:{neg_id}]" if neg_id else "",
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


def _sessions_json_paths() -> List[Path]:
    """DATA_DIR plus optional BRIDGE_DATA_DIR (staging split-brain fix)."""
    paths: List[Path] = []
    try:
        from app.config import settings as _settings

        paths.append(Path(_settings.DATA_DIR) / "sessions.json")
    except Exception:
        paths.append(Path(os.environ.get("DATA_DIR", "/app/data")) / "sessions.json")
    bridge = (os.getenv("BRIDGE_DATA_DIR") or "").strip()
    if bridge:
        p = Path(bridge) / "sessions.json"
        if p not in paths:
            paths.append(p)
    return paths


def _load_sessions_list() -> List[Dict[str, Any]]:
    for path in _sessions_json_paths():
        if path.exists():
            try:
                data = json.loads(path.read_text()) or []
                if isinstance(data, list):
                    return data
            except Exception:
                continue
    return []


def _write_sessions_list(sessions: List[Dict[str, Any]]) -> None:
    blob = json.dumps(sessions, indent=2, default=str)
    for path in _sessions_json_paths():
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(blob)
        except Exception as e:
            logger.warning("session_negotiation_notify: write %s failed: %s", path, e)


def _iso_to_zoom_start(iso_str: str) -> str:
    s = (iso_str or "").strip()
    if not s:
        return ""
    try:
        dtv = datetime.fromisoformat(s.replace("Z", "+00:00"))
        if dtv.tzinfo is None:
            dtv = dtv.replace(tzinfo=timezone.utc)
        return dtv.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    except Exception:
        return s


async def _attach_zoom_if_needed(session: Dict[str, Any]) -> None:
    from app.config import settings as _settings

    if not getattr(_settings, "ENABLE_ZOOM", False):
        return
    if (session.get("zoom_link") or "").strip():
        return
    try:
        from app.services.zoom_client import ZoomClient

        dur_min = 50
        st_s = session.get("scheduled_start", "")
        en_s = session.get("scheduled_end", "")
        try:
            st = datetime.fromisoformat(str(st_s).replace("Z", "+00:00"))
            en = datetime.fromisoformat(str(en_s).replace("Z", "+00:00"))
            if st.tzinfo is None:
                st = st.replace(tzinfo=timezone.utc)
            if en.tzinfo is None:
                en = en.replace(tzinfo=timezone.utc)
            if en > st:
                dur_min = max(5, int((en - st).total_seconds() / 60))
        except Exception:
            pass
        zoom_resp = await ZoomClient.from_env().create_meeting(
            topic=f"Session: {session.get('client_name', 'Client')}",
            start_time_iso=_iso_to_zoom_start(str(st_s)) or "",
            duration_minutes=dur_min,
        )
        if zoom_resp.get("join_url"):
            session["zoom_link"] = zoom_resp["join_url"]
            session["zoom_meeting_id"] = str(zoom_resp.get("id", ""))
            session["zoom_host_url"] = zoom_resp.get("start_url", "")
    except Exception as e:
        logger.warning("session_negotiation_notify: Zoom create failed: %s", e)


async def _apply_coach_ledger(db_pool: Any, session: Dict[str, Any]) -> None:
    if not db_pool:
        return
    try:
        from app.services.session_approval import apply_coach_ledger_txn

        async with db_pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT username, profile_data FROM users WHERE hardware_id = $1 AND role = 'COACH'",
                session.get("coach_id", ""),
            )
            if not row:
                return
            profile = row["profile_data"]
            if isinstance(profile, str):
                profile = json.loads(profile)
            profile = profile or {}
            apply_coach_ledger_txn(profile, session)
            await conn.execute(
                "UPDATE users SET profile_data = $2::jsonb WHERE username = $1",
                row["username"],
                json.dumps(profile),
            )
    except Exception as e:
        logger.warning("session_negotiation_notify: ledger failed: %s", e)


async def _gcal_sync_session(db_pool: Any, session: Dict[str, Any], *, action: str) -> None:
    if not db_pool:
        return
    try:
        from app.services.google_calendar_session_sync import sync_session_for_participants

        asyncio.create_task(sync_session_for_participants(db_pool, session, action=action))
    except Exception as e:
        logger.warning("session_negotiation_notify: gcal sync skipped: %s", e)


async def publish_negotiation_fanout(
    payload: Dict[str, Any],
    *,
    environment: Optional[str] = None,
) -> None:
    """Bridge listens on nate:session_negotiation; filters by payload environment."""
    try:
        import redis.asyncio as aioredis

        body = dict(payload)
        body["environment"] = (environment or _runtime_env()).strip().lower()
        url = os.getenv("REDIS_URL") or ""
        if not url:
            host = os.getenv("REDIS_HOST", "redis")
            port = os.getenv("REDIS_PORT", "6379")
            pw = os.getenv("REDIS_PASSWORD", "")
            url = f"redis://:{pw}@{host}:{port}" if pw else f"redis://{host}:{port}"
        client = aioredis.from_url(url, decode_responses=True)
        try:
            await client.publish(SESSION_NEGOTIATION_CHANNEL, json.dumps(body, default=str))
        finally:
            await client.aclose()
    except Exception as e:
        logger.warning("session_negotiation_notify: Redis fanout failed: %s", e)


async def enrich_approved_session(
    db_pool: Any,
    session: Dict[str, Any],
    *,
    action: str = "approve_session",
) -> Dict[str, Any]:
    """Zoom + ledger + GCal for WS/chat approve path (shared with channel finalize)."""
    if action in ("approve_session", "reschedule_and_approve"):
        await _attach_zoom_if_needed(session)
        await _apply_coach_ledger(db_pool, session)
        await _gcal_sync_session(
            db_pool, session, action="update" if session.get("google_event_id") else "create"
        )
        try:
            from app.services.session_approval import send_booking_decision_email

            asyncio.create_task(send_booking_decision_email(db_pool, session, "approved"))
        except Exception:
            pass
    elif action == "decline_session":
        await _gcal_sync_session(db_pool, session, action="delete")
        try:
            from app.services.session_approval import send_booking_decision_email

            asyncio.create_task(send_booking_decision_email(db_pool, session, "declined"))
        except Exception:
            pass
    return session


async def _finalize_session_from_result(
    db_pool: Any,
    result: Dict[str, Any],
    neg: Dict[str, Any],
    *,
    skip_local_json: bool = False,
    fanout_environment: Optional[str] = None,
    session_hint: Optional[Dict[str, Any]] = None,
) -> Optional[Dict[str, Any]]:
    """Mutate sessions (JSON+PG), Zoom/ledger/GCal on approve, Redis WS fanout."""
    from app.services.pg_data_helpers import upsert_session_pg

    action = result.get("bridge_action") or "none"
    sid = result.get("session_id") or neg.get("session_id")
    found = None
    sessions: List[Dict[str, Any]] = []

    if not skip_local_json:
        sessions = _load_sessions_list()
        for s in sessions:
            if s.get("session_id") != sid:
                continue
            found = s
            break

    if found is None and session_hint and session_hint.get("session_id") == sid:
        found = dict(session_hint)
    if found is None and sid:
        found = {
            "session_id": sid,
            "client_id": neg.get("client_id"),
            "coach_id": neg.get("coach_id"),
            "client_name": (neg.get("metadata") or {}).get("client_name"),
            "scheduled_start": neg.get("proposed_start"),
            "scheduled_end": neg.get("proposed_end"),
            "status": "pending_approval",
        }

    if found:
        if action == "approve_session":
            found["status"] = "scheduled"
            found["approved_at"] = str(datetime.now())
            found["approved_via"] = "negotiation_channel"
        elif action == "decline_session":
            found["status"] = "declined"
            found["declined_at"] = str(datetime.now())
            found["declined_via"] = "negotiation_channel"
        elif action == "reschedule_and_approve":
            found["status"] = "scheduled"
            found["approved_at"] = str(datetime.now())
            found["approved_via"] = "negotiation_channel"
            if result.get("new_start"):
                found["scheduled_start"] = result["new_start"]
            if result.get("new_end"):
                found["scheduled_end"] = result["new_end"]

        await enrich_approved_session(db_pool, found, action=action)

        if not skip_local_json:
            replaced = False
            for i, s in enumerate(sessions):
                if s.get("session_id") == sid:
                    sessions[i] = found
                    replaced = True
                    break
            if not replaced:
                sessions.append(found)
            _write_sessions_list(sessions)
        try:
            await upsert_session_pg(db_pool, found)
        except Exception as e:
            logger.warning("session_negotiation_notify: PG session upsert failed: %s", e)

    fanout = {
        "client_id": neg.get("client_id") or (found or {}).get("client_id") or "",
        "coach_id": neg.get("coach_id") or (found or {}).get("coach_id") or "",
        "session": found,
        "client_notify": result.get("client_notify"),
        "coach_notify": result.get("coach_notify"),
        "booking_status_update": (
            {
                "type": "booking_status_update",
                "session": found,
                "status": found.get("status"),
            }
            if found
            else None
        ),
        "session_negotiation_update": {
            "type": "session_negotiation_update",
            "negotiation": result.get("negotiation") or neg,
            "ok": True,
        },
    }
    await publish_negotiation_fanout(fanout, environment=fanout_environment)
    return found


async def _apply_coach_on_pool(
    db_pool: Any,
    *,
    decision: str,
    negotiation_id: Optional[str],
    coach_email: str,
    coach_phone: str,
    force: bool,
    staging_fallback: bool,
) -> Dict[str, Any]:
    from app.services.session_negotiation_service import coach_decide, negotiation_enabled

    if not force and not negotiation_enabled():
        return {"ok": False, "error": "flag_off"}
    decision = (decision or "").strip().lower()
    if decision not in _COACH_ACTIONS:
        return {"ok": False, "error": "invalid_decision"}

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
        force=force,
    )
    if not result.get("ok"):
        return result

    try:
        await _finalize_session_from_result(
            db_pool,
            result,
            neg,
            skip_local_json=staging_fallback,
            fanout_environment="staging" if staging_fallback else None,
        )
        client_msg = result.get("client_nate_text") or ""
        await send_client_negotiation_update_email(
            db_pool,
            result.get("negotiation") or neg,
            nate_message=client_msg,
        )
    except Exception as e:
        logger.warning("session_negotiation_notify: finalize side effects failed: %s", e)

    result["via"] = "channel_staging_fallback" if staging_fallback else "channel"
    return result


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
    When prod flag is off / row missing, optional staging DB fallback (bake).
    """
    result = await _apply_coach_on_pool(
        db_pool,
        decision=decision,
        negotiation_id=negotiation_id,
        coach_email=coach_email,
        coach_phone=coach_phone,
        force=False,
        staging_fallback=False,
    )
    if result.get("ok"):
        return result
    if (
        result.get("error") in ("flag_off", "negotiation_not_found")
        and negotiation_id
        and staging_inbound_fallback_enabled()
    ):
        staging = await _get_staging_pool()
        if staging:
            return await _apply_coach_on_pool(
                staging,
                decision=decision,
                negotiation_id=negotiation_id,
                coach_email=coach_email,
                coach_phone=coach_phone,
                force=True,
                staging_fallback=True,
            )
    return result


async def _apply_client_on_pool(
    db_pool: Any,
    *,
    decision: str,
    negotiation_id: str,
    chosen_start: str,
    slot_index: Optional[int],
    force: bool,
    staging_fallback: bool,
) -> Dict[str, Any]:
    from app.services.session_negotiation_service import client_respond, negotiation_enabled, _row_to_dict

    if not force and not negotiation_enabled():
        return {"ok": False, "error": "flag_off"}
    decision = (decision or "").strip().lower()
    if decision not in _CLIENT_ACTIONS:
        return {"ok": False, "error": "invalid_decision"}
    if not negotiation_id:
        return {"ok": False, "error": "missing_negotiation_id"}

    try:
        async with db_pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM session_negotiations WHERE id = $1::uuid",
                negotiation_id,
            )
        if not row:
            return {"ok": False, "error": "negotiation_not_found"}
        neg = _row_to_dict(row)
        client_id = neg.get("client_id") or ""
        if not client_id:
            return {"ok": False, "error": "missing_client"}
    except Exception as e:
        return {"ok": False, "error": "db_error", "detail": str(e)[:200]}

    start = chosen_start
    if decision == "accept_alt" and not start and slot_index is not None:
        alts = neg.get("alt_slots") or []
        if 0 <= slot_index < len(alts):
            slot = alts[slot_index]
            start = slot.get("start") if isinstance(slot, dict) else str(slot)

    result = await client_respond(
        db_pool,
        client_id=client_id,
        negotiation_id=negotiation_id,
        decision=decision,
        chosen_start=start or None,
        force=force,
    )
    if not result.get("ok"):
        return result

    try:
        await _finalize_session_from_result(
            db_pool,
            result,
            neg,
            skip_local_json=staging_fallback,
            fanout_environment="staging" if staging_fallback else None,
        )
        if decision == "reject_alt":
            await send_coach_negotiation_notify(db_pool, result.get("negotiation") or neg)
        elif decision == "accept_alt":
            await send_client_negotiation_update_email(
                db_pool,
                result.get("negotiation") or neg,
                nate_message=result.get("client_nate_text") or "Session confirmed.",
            )
    except Exception as e:
        logger.warning("session_negotiation_notify: client finalize failed: %s", e)

    result["via"] = "channel_staging_fallback" if staging_fallback else "channel"
    return result


async def apply_client_channel_decision(
    db_pool: Any,
    *,
    decision: str,
    negotiation_id: str,
    chosen_start: str = "",
    slot_index: Optional[int] = None,
) -> Dict[str, Any]:
    """Apply accept_alt|reject_alt from client email/SMS/HTTPS links."""
    result = await _apply_client_on_pool(
        db_pool,
        decision=decision,
        negotiation_id=negotiation_id,
        chosen_start=chosen_start,
        slot_index=slot_index,
        force=False,
        staging_fallback=False,
    )
    if result.get("ok"):
        return result
    if (
        result.get("error") in ("flag_off", "negotiation_not_found")
        and negotiation_id
        and staging_inbound_fallback_enabled()
    ):
        staging = await _get_staging_pool()
        if staging:
            return await _apply_client_on_pool(
                staging,
                decision=decision,
                negotiation_id=negotiation_id,
                chosen_start=chosen_start,
                slot_index=slot_index,
                force=True,
                staging_fallback=True,
            )
    return result
