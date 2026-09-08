"""
Session Approval Service
========================

Shared helpers for the pending-booking approval workflow:

- HMAC-signed action tokens for one-click email approve/decline links
- Coach notification email (pending booking) + client decision email
- PG <-> bridge sessions.json reconciliation (email approvals and REST
  cancellations land in PostgreSQL first; the bridge must pick them up
  before running conflict checks or listing pending bookings)
- Coach earnings ledger entry shared by WS approval and auto-accept

Consumed by: app/routers/sessions.py (public email endpoints) and
app/websocket/bridge_server.py (client_book_session, cancel, pending list).
"""

import os
import hmac
import json
import time
import base64
import hashlib
import logging
from datetime import datetime, timezone
from typing import Optional, Dict, Tuple, List

logger = logging.getLogger(__name__)

_SECRET = (
    os.getenv("SESSION_ACTION_SECRET")
    or os.getenv("JWT_SECRET")
    or os.getenv("SECRET_KEY", "")
)
PUBLIC_API_BASE = os.getenv("PUBLIC_API_BASE", "https://api.sovereignsanctuary.net")
TOKEN_TTL_SECONDS = 30 * 24 * 3600  # 30 days — links stay valid until decided

# Statuses that occupy a calendar slot (block double-booking)
BLOCKING_STATUSES = ("scheduled", "active", "pending_approval")


# =============================================================================
# ACTION TOKENS (email approve/decline links)
# =============================================================================

def make_action_token(session_id: str, action: str) -> str:
    """HMAC-signed token encoding session_id + action + expiry."""
    payload = json.dumps(
        {"sid": session_id, "act": action, "exp": int(time.time()) + TOKEN_TTL_SECONDS},
        separators=(",", ":"),
    ).encode()
    body = base64.urlsafe_b64encode(payload).rstrip(b"=")
    sig = hmac.new(_SECRET.encode(), body, hashlib.sha256).hexdigest()[:32]
    return f"{body.decode()}.{sig}"


def verify_action_token(token: str) -> Optional[Tuple[str, str]]:
    """Returns (session_id, action) or None if invalid/expired."""
    try:
        body, sig = token.rsplit(".", 1)
        expected = hmac.new(_SECRET.encode(), body.encode(), hashlib.sha256).hexdigest()[:32]
        if not hmac.compare_digest(sig, expected):
            return None
        padded = body + "=" * (-len(body) % 4)
        data = json.loads(base64.urlsafe_b64decode(padded))
        if int(data.get("exp", 0)) < time.time():
            return None
        action = data.get("act", "")
        if action not in ("approve", "decline"):
            return None
        return str(data.get("sid", "")), action
    except Exception:
        return None


def action_url(session_id: str, action: str) -> str:
    return f"{PUBLIC_API_BASE}/api/sessions-public/booking-action?token={make_action_token(session_id, action)}"


# =============================================================================
# FORMATTING / LOOKUPS
# =============================================================================

def format_session_time(session: Dict, profile: Optional[Dict] = None) -> str:
    """Human-readable session time in the recipient's profile timezone."""
    from app.utils.timezone_resolver import format_session_start_for_profile

    raw = session.get("scheduled_start") or session.get("scheduled_time") or ""
    try:
        dt = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        formatted, _tz = format_session_start_for_profile(dt, profile or {})
        return formatted
    except Exception:
        return str(raw)


async def lookup_user_contact(db_pool, hw_or_username: str) -> Dict[str, str]:
    """Resolve email + display name for a hardware_id or username."""
    if not db_pool or not hw_or_username:
        return {}
    try:
        async with db_pool.acquire() as conn:
            row = await conn.fetchrow(
                """SELECT username,
                          COALESCE(profile_data->>'email', '') AS email,
                          COALESCE(profile_data->>'phone', '') AS phone,
                          COALESCE(profile_data->>'name', username) AS name,
                          COALESCE(profile_data->>'timezone', '') AS timezone
                   FROM users
                   WHERE hardware_id = $1 OR username = $1
                   LIMIT 1""",
                hw_or_username,
            )
            if row:
                return {
                    "username": row["username"],
                    "email": row["email"],
                    "phone": row["phone"],
                    "name": row["name"],
                    "timezone": row["timezone"],
                }
    except Exception as e:
        logger.warning("session_approval: contact lookup failed for %s: %s", hw_or_username, e)
    return {}


# =============================================================================
# EMAILS
# =============================================================================

def session_duration_minutes(session: Dict) -> int:
    raw = session.get("duration_minutes")
    try:
        n = int(raw)
        if n > 0:
            return n
    except (TypeError, ValueError):
        pass
    try:
        st = datetime.fromisoformat(str(session.get("scheduled_start") or "").replace("Z", "+00:00"))
        en = datetime.fromisoformat(str(session.get("scheduled_end") or "").replace("Z", "+00:00"))
        if en > st:
            return max(5, int((en - st).total_seconds() / 60))
    except Exception:
        pass
    return 50


async def notify_coach_of_pending(
    db_pool,
    session: Dict,
    *,
    connected_clients=None,
    connected_coaches=None,
) -> bool:
    """One coach email per request: Nate negotiation if flagged, else legacy approve/decline."""
    if not db_pool or str(session.get("status", "")).lower() != "pending_approval":
        return False
    try:
        from app.services.session_negotiation_service import negotiation_enabled
        if negotiation_enabled():
            from app.services.session_negotiation_bridge import after_pending_booking
            await after_pending_booking(
                db_pool,
                session,
                connected_clients=connected_clients or {},
                connected_coaches=connected_coaches or {},
            )
            return True
        return await send_pending_booking_email(db_pool, session)
    except Exception as e:
        logger.warning("session_approval: notify_coach_of_pending failed: %s", e)
        return False


async def send_pending_booking_email(db_pool, session: Dict) -> bool:
    """Email the coach an approve/decline request for a pending booking."""
    try:
        coach = await lookup_user_contact(db_pool, session.get("coach_id", ""))
        if not coach.get("email"):
            logger.warning("session_approval: no coach email for %s — pending email skipped",
                           session.get("coach_id"))
            return False
        from app.services.notifications_service import EmailService
        sid = session.get("session_id", "")
        return await EmailService().send_email(
            to_email=coach["email"],
            template_name="pending_booking_coach",
            context={
                "client_name": session.get("client_name") or session.get("client_id", "Client"),
                "session_time": format_session_time(session, {"timezone": coach.get("timezone")}),
                "duration": session_duration_minutes(session),
                "session_title": session.get("title", "Coaching Session"),
                "approve_url": action_url(sid, "approve"),
                "decline_url": action_url(sid, "decline"),
            },
        )
    except Exception as e:
        logger.warning("session_approval: pending booking email failed: %s", e)
        return False


async def send_booking_decision_email(db_pool, session: Dict, decision: str, reason: str = "") -> bool:
    """Email the client that their request was approved or declined. Idempotent per decision."""
    try:
        if session.get("client_decision_emailed") == decision:
            return True
        client = await lookup_user_contact(db_pool, session.get("client_id", ""))
        if not client.get("email"):
            logger.warning("session_approval: no client email for %s — decision email skipped",
                           session.get("client_id"))
            return False
        coach = await lookup_user_contact(db_pool, session.get("coach_id", ""))
        from app.services.notifications_service import EmailService
        ok = await EmailService().send_email(
            to_email=client["email"],
            template_name="booking_decision_client",
            context={
                "decision": decision,
                "coach_name": coach.get("name") or session.get("coach_id", "your coach"),
                "session_time": format_session_time(session, {"timezone": client.get("timezone")}),
                "zoom_link": session.get("zoom_link", ""),
                "reason": reason,
            },
        )
        if ok:
            session["client_decision_emailed"] = decision
            if db_pool:
                try:
                    from app.services.pg_data_helpers import upsert_session_pg
                    await upsert_session_pg(db_pool, session)
                except Exception:
                    pass
        return ok
    except Exception as e:
        logger.warning("session_approval: decision email failed: %s", e)
        return False


def write_sessions_json_both(sessions: List[Dict]) -> None:
    """Write sessions.json to backend DATA_DIR and optional BRIDGE_DATA_DIR."""
    from pathlib import Path

    blob = json.dumps(sessions, indent=2, default=str)
    paths = []
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
    for path in paths:
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(blob)
        except Exception as e:
            logger.warning("session_approval: write %s failed: %s", path, e)


# =============================================================================
# PG <-> JSON RECONCILIATION
# =============================================================================

async def sync_sessions_with_pg(db_pool, sessions: List[Dict]) -> bool:
    """
    Refresh status (+ zoom fields) of active-ish JSON sessions from PostgreSQL.

    Email approvals/declines and REST cancellations write to PG first, so the
    bridge's sessions.json can hold stale 'pending_approval'/'scheduled' rows.
    Returns True if any session was mutated (caller should re-save the JSON).
    """
    if not db_pool:
        return False
    ids = [s.get("session_id") for s in sessions
           if s.get("session_id") and str(s.get("status", "")).lower() in BLOCKING_STATUSES]
    if not ids:
        return False
    try:
        async with db_pool.acquire() as conn:
            rows = await conn.fetch(
                """SELECT session_id, status, zoom_link, zoom_meeting_id
                   FROM coaching_sessions WHERE session_id = ANY($1::text[])""",
                ids,
            )
    except Exception as e:
        logger.warning("session_approval: PG sync query failed: %s", e)
        return False
    pg_map = {r["session_id"]: r for r in rows}
    changed = False
    for s in sessions:
        row = pg_map.get(s.get("session_id"))
        if not row:
            continue
        pg_status = (row["status"] or "").lower()
        if pg_status and pg_status != str(s.get("status", "")).lower():
            s["status"] = pg_status
            changed = True
        if row["zoom_link"] and not s.get("zoom_link"):
            s["zoom_link"] = row["zoom_link"]
            s["zoom_meeting_id"] = row["zoom_meeting_id"]
            changed = True
    return changed


async def locate_pending_booking(
    db_pool, sessions: List[Dict], session_id: str, coach_id: str,
    *, _pg_loader=None,
) -> Optional[Dict]:
    """JSON first, then PG-only Nate-tool rows missing from sessions.json."""
    sid = (session_id or "").strip()
    cid = (coach_id or "").strip()
    if not sid or not cid:
        return None
    for s in sessions:
        if (
            s.get("session_id") == sid
            and s.get("coach_id") == cid
            and str(s.get("status") or "").lower() == "pending_approval"
        ):
            return s
    if not db_pool:
        return None
    try:
        loader = _pg_loader
        if loader is None:
            from app.services.pg_data_helpers import load_sessions_pg
            loader = load_sessions_pg
        rows = await loader(db_pool, coach_id=cid, status="pending_approval")
        for r in rows:
            if r.get("session_id") == sid:
                sessions.append(r)
                return r
    except Exception as e:
        logger.warning("session_approval: PG pending lookup failed: %s", e)
    return None


async def merge_pg_pendings(
    db_pool, sessions: List[Dict], coach_id: str, *, _pg_loader=None,
) -> bool:
    """Append PG pending_approval rows that are not in the JSON list."""
    cid = (coach_id or "").strip()
    if not db_pool or not cid:
        return False
    existing = {(s.get("session_id") or "") for s in sessions}
    try:
        loader = _pg_loader
        if loader is None:
            from app.services.pg_data_helpers import load_sessions_pg
            loader = load_sessions_pg
        rows = await loader(db_pool, coach_id=cid, status="pending_approval")
    except Exception as e:
        logger.warning("session_approval: merge_pg_pendings failed: %s", e)
        return False
    changed = False
    for r in rows:
        sid = r.get("session_id") or ""
        if not sid or sid in existing:
            continue
        sessions.append(r)
        existing.add(sid)
        changed = True
    return changed


_CLIENT_UPCOMING_STATUSES = frozenset({
    "scheduled", "active", "pending_approval", "confirmed",
})
_CLIENT_GONE_STATUSES = frozenset({
    "cancelled", "canceled", "cancelled_by_google", "no_show",
    "declined", "rejected", "expired",
})


def schedule_pg_merge_client_enabled() -> bool:
    return os.getenv("SCHEDULE_PG_MERGE_CLIENT", "true").lower() in (
        "1", "true", "yes",
    )


async def merge_pg_upcoming_for_client(
    db_pool, sessions: List[Dict], client_id: str, *, _pg_loader=None,
) -> bool:
    """PG-on-read for client Schedule: hydrate REST bookings, drop PG-cancelled."""
    cid = (client_id or "").strip()
    if not db_pool or not cid:
        return False
    if not schedule_pg_merge_client_enabled():
        return False
    try:
        loader = _pg_loader
        if loader is None:
            from app.services.pg_data_helpers import load_sessions_pg
            loader = load_sessions_pg
        rows = await loader(
            db_pool,
            client_id=cid,
            statuses=list(_CLIENT_UPCOMING_STATUSES | _CLIENT_GONE_STATUSES),
        )
    except Exception as e:
        logger.warning("session_approval: merge_pg_upcoming_for_client failed: %s", e)
        return False

    by_id = {(r.get("session_id") or ""): r for r in rows if r.get("session_id")}
    changed = False
    keep: List[Dict] = []
    for s in sessions:
        sid = s.get("session_id") or ""
        pg = by_id.get(sid)
        if pg:
            st = str(pg.get("status") or "").lower()
            if st in _CLIENT_GONE_STATUSES:
                changed = True
                continue
            s["status"] = pg.get("status") or s.get("status")
            if pg.get("payment_status") is not None:
                s["payment_status"] = pg.get("payment_status")
            if "price_cents" in pg:
                s["price_cents"] = pg.get("price_cents")
            if pg.get("cancellation_deadline") is not None:
                s["cancellation_deadline"] = pg.get("cancellation_deadline")
        keep.append(s)
    if len(keep) != len(sessions):
        sessions[:] = keep
        changed = True
    elif changed:
        sessions[:] = keep

    existing = {(s.get("session_id") or "") for s in sessions}
    for r in rows:
        sid = r.get("session_id") or ""
        st = str(r.get("status") or "").lower()
        if not sid or sid in existing:
            continue
        if st not in _CLIENT_UPCOMING_STATUSES:
            continue
        sessions.append(r)
        existing.add(sid)
        changed = True
    return changed


def schedule_client_cancel_pg_enabled() -> bool:
    return os.getenv("SCHEDULE_CLIENT_CANCEL_PG", "true").lower() in (
        "1", "true", "yes",
    )


async def notify_coach_of_client_cancel(
    db_pool,
    session: Dict,
    *,
    notification_system=None,
    _lookup=None,
    _send_email=None,
) -> Dict[str, bool]:
    """Email + SMS the assigned coach after a client cancel."""
    result = {"email": False, "sms": False}
    if not session:
        return result
    lookup = _lookup or lookup_user_contact
    coach = await lookup(db_pool, session.get("coach_id", "")) if db_pool else {}
    client_name = session.get("client_name") or session.get("client_id") or "A client"
    when = format_session_time(session, {"timezone": (coach or {}).get("timezone")})
    dest = ((coach or {}).get("email") or "").strip()
    sender = _send_email
    if sender is None and dest:
        try:
            from app.services.notifications_service import EmailService
            sender = EmailService().send_email
        except Exception as e:
            logger.warning("session_approval: EmailService unavailable: %s", e)
    if dest and sender:
        try:
            result["email"] = bool(await sender(
                dest,
                "session_cancelled_coach",
                {
                    "client_name": client_name,
                    "session_time": when,
                    "session_id": session.get("session_id") or "",
                },
            ))
        except Exception as e:
            logger.warning("session_approval: cancel email failed: %s", e)
    phone = ((coach or {}).get("phone") or "").strip()
    if phone and notification_system is not None:
        try:
            body = f"Sanctuary: {client_name} cancelled their session {when}."
            result["sms"] = bool(await notification_system.send_sms(phone, body))
        except Exception as e:
            logger.warning("session_approval: cancel SMS failed: %s", e)
    logger.info(
        "session_approval: client cancel notify email=%s sms=%s sid=%s",
        result["email"], result["sms"], session.get("session_id"),
    )
    return result


async def cancel_client_session(
    db_pool,
    sessions: List[Dict],
    session_id: str,
    client_id: str,
    *,
    notification_system=None,
    _pg_loader=None,
    _refund=None,
    _upsert=None,
    _notify=None,
) -> Dict:
    """JSON then PG lookup; one refund_on_client_cancel; upsert; coach notify.

    Does not write sessions.json (caller saves when json_changed).
    """
    sid = (session_id or "").strip()
    cid = (client_id or "").strip()
    if not sid or not cid:
        return {"ok": False, "reason": "missing"}

    json_changed = False
    cancelled: Optional[Dict] = None
    for s in sessions:
        if s.get("session_id") != sid or s.get("client_id") != cid:
            continue
        if str(s.get("status") or "").lower() in _CLIENT_GONE_STATUSES:
            return {"ok": False, "reason": "already_gone"}
        s["status"] = "cancelled"
        s["cancelled_at"] = str(datetime.now())
        s["cancelled_by"] = "CLIENT"
        cancelled = s
        json_changed = True
        break

    if cancelled is None and db_pool and schedule_client_cancel_pg_enabled():
        try:
            loader = _pg_loader
            if loader is None:
                from app.services.pg_data_helpers import load_sessions_pg
                loader = load_sessions_pg
            rows = await loader(db_pool, client_id=cid, session_id=sid)
        except Exception as e:
            logger.warning("session_approval: cancel PG load failed: %s", e)
            rows = []
        for r in rows:
            if r.get("session_id") != sid or r.get("client_id") != cid:
                continue
            if str(r.get("status") or "").lower() in _CLIENT_GONE_STATUSES:
                return {"ok": False, "reason": "already_gone"}
            r = dict(r)
            r["status"] = "cancelled"
            r["cancelled_at"] = str(datetime.now())
            r["cancelled_by"] = "CLIENT"
            cancelled = r
            break

    if cancelled is None:
        return {"ok": False, "reason": "not_found"}

    refund_outcome, refund_detail = "skipped", ""
    refund_fn = _refund
    if refund_fn is None and db_pool:
        try:
            from app.services.session_booking_billing import refund_on_client_cancel
            refund_fn = refund_on_client_cancel
        except Exception as e:
            logger.warning("session_approval: refund import failed: %s", e)
    if refund_fn and db_pool:
        try:
            refund_outcome, refund_detail = await refund_fn(db_pool, cancelled)
        except Exception as e:
            logger.warning("session_approval: refund_on_client_cancel: %s", e)
            refund_outcome, refund_detail = "error", str(e)

    upsert = _upsert
    if upsert is None and db_pool:
        try:
            from app.services.pg_data_helpers import upsert_session_pg
            upsert = upsert_session_pg
        except Exception as e:
            logger.warning("session_approval: upsert import failed: %s", e)
    if upsert and db_pool:
        try:
            await upsert(db_pool, cancelled)
        except Exception as e:
            logger.warning("session_approval: cancel upsert failed: %s", e)

    notify = _notify if _notify is not None else notify_coach_of_client_cancel
    try:
        await notify(db_pool, cancelled, notification_system=notification_system)
    except Exception as e:
        logger.warning("session_approval: cancel notify failed: %s", e)

    return {
        "ok": True,
        "session": cancelled,
        "refund_outcome": refund_outcome,
        "refund_detail": refund_detail,
        "json_changed": json_changed,
    }


async def close_pending_negotiation(db_pool, session_id: str, terminal_status: str = "declined") -> None:
    if not db_pool or not session_id:
        return
    status = terminal_status if terminal_status in (
        "approved", "declined", "busy", "cancelled", "expired"
    ) else "declined"
    try:
        async with db_pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE session_negotiations
                SET status = $2, updated_at = NOW()
                WHERE session_id = $1
                  AND status = ANY($3::text[])
                """,
                session_id,
                status,
                ["awaiting_coach", "alt_proposed", "awaiting_client"],
            )
    except Exception as e:
        logger.warning("session_approval: close negotiation failed: %s", e)


# =============================================================================
# COACH LEDGER (shared by WS approve + auto-accept)
# =============================================================================

def apply_coach_ledger_txn(coach_profile: Dict, session: Dict) -> None:
    """
    Record the session fee on the coach's financial ledger.
    Mirrors the WS coach_approve_booking handler exactly so email-approve and
    auto-accept produce identical financial records.
    """
    try:
        import secrets as _secrets
        coach_fee = float(session.get("coach_fee", 0))
        platform_fee = float(session.get("platform_fee", 0))
        coach_payout = float(session.get("coach_payout", 0))
        if coach_fee <= 0 and platform_fee <= 0:
            return
        now = datetime.now()
        txn = {
            "txn_id": f"TXN_{now.strftime('%Y%m%d%H%M%S')}_{_secrets.token_hex(3).upper()}",
            "date": str(now.date()),
            "type": "session_fee",
            "session_id": session.get("session_id"),
            "client_name": session.get("client_name", ""),
            "coach_fee": coach_fee,
            "platform_fee": platform_fee,
            "coach_payout": coach_payout,
            "status": "recorded",
        }
        if "financial_ledger" not in coach_profile:
            coach_profile["financial_ledger"] = []
        coach_profile["financial_ledger"].append(txn)
        coach_profile["total_earnings_ytd"] = round(coach_profile.get("total_earnings_ytd", 0) + coach_fee, 2)
        coach_profile["total_platform_fees_ytd"] = round(coach_profile.get("total_platform_fees_ytd", 0) + platform_fee, 2)
        coach_profile["total_sessions_billable"] = coach_profile.get("total_sessions_billable", 0) + 1
        if coach_profile["total_earnings_ytd"] >= 600:
            coach_profile["requires_1099"] = True
    except Exception as e:
        logger.warning("session_approval: ledger entry failed: %s", e)
