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
                    "name": row["name"],
                    "timezone": row["timezone"],
                }
    except Exception as e:
        logger.warning("session_approval: contact lookup failed for %s: %s", hw_or_username, e)
    return {}


# =============================================================================
# EMAILS
# =============================================================================

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
                "duration": session.get("duration_minutes", 60),
                "session_title": session.get("title", "Coaching Session"),
                "approve_url": action_url(sid, "approve"),
                "decline_url": action_url(sid, "decline"),
            },
        )
    except Exception as e:
        logger.warning("session_approval: pending booking email failed: %s", e)
        return False


async def send_booking_decision_email(db_pool, session: Dict, decision: str, reason: str = "") -> bool:
    """Email the client that their request was approved or declined."""
    try:
        client = await lookup_user_contact(db_pool, session.get("client_id", ""))
        if not client.get("email"):
            logger.warning("session_approval: no client email for %s — decision email skipped",
                           session.get("client_id"))
            return False
        coach = await lookup_user_contact(db_pool, session.get("coach_id", ""))
        from app.services.notifications_service import EmailService
        return await EmailService().send_email(
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
    except Exception as e:
        logger.warning("session_approval: decision email failed: %s", e)
        return False


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
