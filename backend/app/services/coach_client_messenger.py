"""Direct coach-to-client messaging (Coach Command VIEW BRIEF "Message Client").

A coach sends a free-text message to one of their assigned clients via email
and/or SMS. Assignment is verified against the same profile fields used by
coach_get_clients. Every send is audited in sensitive_bridge_log.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

_MAX_MESSAGE_CHARS = 2000


async def _fetch_client_row(db_pool, client_username: str) -> Optional[Dict[str, Any]]:
    try:
        async with db_pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT username, role, profile_data
                  FROM users
                 WHERE username = $1 AND role = 'CLIENT'
                 LIMIT 1
                """,
                client_username,
            )
        if not row:
            return None
        pd = row["profile_data"] or {}
        if isinstance(pd, str):
            try:
                pd = json.loads(pd)
            except Exception:
                pd = {}
        return {"username": row["username"], "profile_data": pd}
    except Exception as e:
        logger.warning("coach_client_messenger: client lookup failed: %s", e)
        return None


def _client_assigned_to_coach(
    client_pd: Dict[str, Any], coach_profile: Dict[str, Any]
) -> bool:
    """Mirror coach_get_clients assignment fields: coach_id / assigned_coach_id / assigned_coach."""
    coach_role = (coach_profile.get("role") or "").upper()
    if coach_role == "ADMIN":
        return True
    coach_hw = (coach_profile.get("hardware_id") or "").strip()
    coach_un = (coach_profile.get("username") or "").strip().lower()
    for key in ("coach_id", "assigned_coach_id"):
        v = str(client_pd.get(key) or "").strip()
        if v and coach_hw and v == coach_hw:
            return True
    v = str(client_pd.get("assigned_coach") or "").strip().lower()
    if v and coach_un and v == coach_un:
        return True
    return False


async def _emit_message_audit(
    db_pool,
    *,
    client_username: str,
    coach_username: str,
    channels: List[str],
    results: Dict[str, bool],
    message_len: int,
) -> None:
    payload = {
        "coach_username": coach_username,
        "channels_requested": channels,
        "email_sent": bool(results.get("email_sent")),
        "sms_sent": bool(results.get("sms_sent")),
        "message_length": message_len,
    }
    try:
        async with db_pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO sensitive_bridge_log
                    (user_id, session_id, event_type, event_severity,
                     payload_json, decision_summary, recorded_by,
                     access_classification, pii_screened_at)
                VALUES ($1, NULL, 'coach_direct_message_sent', 'low',
                        $2::jsonb, NULL, 'coach_client_messenger',
                        'clinician_and_admin', NOW())
                """,
                client_username,
                json.dumps(payload),
            )
    except Exception as e:
        logger.warning("coach_client_messenger: audit insert failed: %s", e)


async def send_direct_client_message(
    db_pool,
    coach_profile: Dict[str, Any],
    client_username: str,
    message: str,
    channels: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Send a direct message from a coach to an assigned client.

    channels: subset of ["email", "sms"] (default both).
    Returns per-channel results so the UI can report honestly
    (SMS may fail while A2P is carrier-blocked).
    """
    client_username = (client_username or "").strip()
    message = (message or "").strip()[:_MAX_MESSAGE_CHARS]
    channels = [c for c in (channels or ["email", "sms"]) if c in ("email", "sms")]

    if not db_pool:
        return {"status": "error", "reason": "no_db_pool"}
    if not client_username or not message:
        return {"status": "error", "reason": "missing_client_or_message"}
    if not channels:
        return {"status": "error", "reason": "no_valid_channels"}

    coach_role = (coach_profile.get("role") or "").upper()
    if coach_role not in ("COACH", "ADMIN"):
        return {"status": "error", "reason": "not_authorized"}

    client = await _fetch_client_row(db_pool, client_username)
    if not client:
        return {"status": "error", "reason": "client_not_found"}
    client_pd = client["profile_data"]
    if not _client_assigned_to_coach(client_pd, coach_profile):
        return {"status": "error", "reason": "client_not_assigned"}

    coach_name = (
        (coach_profile.get("name") or "").strip()
        or (coach_profile.get("username") or "").strip()
        or "Your coach"
    )
    client_email = (client_pd.get("email") or "").strip()
    client_phone = (client_pd.get("phone") or "").strip()

    results: Dict[str, Any] = {
        "status": "sent",
        "client_username": client_username,
        "email_sent": False,
        "sms_sent": False,
        "email_on_file": bool(client_email),
        "phone_on_file": bool(client_phone),
    }

    if "email" in channels and client_email:
        try:
            from app.services.notifications_service import EmailService

            ok = await EmailService().send_coach_direct_message(
                client_email, coach_name, message
            )
            results["email_sent"] = bool(ok)
        except Exception as e:
            logger.warning(
                "coach_client_messenger: email failed for %s: %s", client_username, e
            )

    if "sms" in channels and client_phone:
        try:
            from app.services.coach_notifications import _send_coach_sms

            body = f"Message from your coach {coach_name}: {message}"
            results["sms_sent"] = bool(_send_coach_sms(client_phone, body))
        except Exception as e:
            logger.warning(
                "coach_client_messenger: SMS failed for %s: %s", client_username, e
            )

    if not results["email_sent"] and not results["sms_sent"]:
        results["status"] = "no_channel_delivered"

    await _emit_message_audit(
        db_pool,
        client_username=client_username,
        coach_username=(coach_profile.get("username") or "").strip(),
        channels=channels,
        results=results,
        message_len=len(message),
    )
    return results
