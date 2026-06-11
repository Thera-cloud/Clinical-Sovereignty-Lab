"""Client-facing confirmations after a coach handoff full dispatch.

Fires after the coach has been alerted (email + phone) for a client-initiated
handoff: sends the client a confirmation email and places a Little Nate
announcement call (Polly voice, no conversation) telling them their coach
was contacted. Both channels are best-effort — failures never fail the handoff.
"""

from __future__ import annotations

import logging
import os
from typing import Any, Dict, Optional, Tuple

logger = logging.getLogger(__name__)


async def _lookup_client_contact(
    db_pool, client_username: str
) -> Tuple[Optional[str], Optional[str]]:
    """Return (email, phone) from users.profile_data."""
    if not db_pool:
        return None, None
    try:
        async with db_pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT profile_data->>'email' AS email,
                       profile_data->>'phone' AS phone
                  FROM users
                 WHERE username = $1
                 LIMIT 1
                """,
                client_username,
            )
        if not row:
            return None, None
        email = (row["email"] or "").strip() or None
        phone = (row["phone"] or "").strip() or None
        return email, phone
    except Exception as e:
        logger.warning("handoff_client_confirmation: contact lookup failed: %s", e)
        return None, None


async def _lookup_coach_display_name(db_pool, coach_username: str) -> str:
    if not db_pool or not coach_username:
        return coach_username or "your coach"
    try:
        async with db_pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT profile_data->>'name' AS name FROM users WHERE username = $1 LIMIT 1",
                coach_username,
            )
        if row and (row["name"] or "").strip():
            return str(row["name"]).strip()
    except Exception as e:
        logger.warning("handoff_client_confirmation: coach name lookup failed: %s", e)
    return coach_username


def _place_announcement_call(to_phone: str, coach_name: str) -> bool:
    """Polly announcement call to the client (no answer detection; voicemail counts)."""
    try:
        from app.services.coach_notifications import _send_coach_voice_ping
    except ImportError:
        return False
    script = (
        f"Hello, this is Little Nate from Sovereign Sanctuary. Your coach "
        f"{coach_name} has been contacted by phone and email about your request "
        "to reach out. They typically respond within 12 hours. An email "
        "confirmation has also been sent to you. Take care."
    )
    return _send_coach_voice_ping(to_phone, script)


async def confirm_handoff_to_client(
    db_pool,
    *,
    client_username: str,
    client_profile: Optional[Dict[str, Any]] = None,
    coach_username: str = "",
) -> Dict[str, Any]:
    """Send the client a confirmation email + Little Nate announcement call.

    Returns {"client_email_sent": bool, "client_call_placed": bool}.
    """
    result = {"client_email_sent": False, "client_call_placed": False}

    email, phone = await _lookup_client_contact(db_pool, client_username)
    profile = client_profile or {}
    email = email or (profile.get("email") or "").strip() or None
    phone = phone or (profile.get("phone") or "").strip() or None

    coach_name = await _lookup_coach_display_name(db_pool, coach_username)

    if email:
        try:
            from app.services.notifications_service import EmailService

            ok = await EmailService().send_handoff_confirmation(email, coach_name)
            result["client_email_sent"] = bool(ok)
        except Exception as e:
            logger.warning(
                "handoff_client_confirmation: client email failed for %s: %s",
                client_username,
                e,
            )
    else:
        logger.info(
            "handoff_client_confirmation: no email on file for %s", client_username
        )

    if phone and os.getenv("HANDOFF_CLIENT_CALL_ENABLED", "true").lower() != "false":
        try:
            result["client_call_placed"] = _place_announcement_call(phone, coach_name)
        except Exception as e:
            logger.warning(
                "handoff_client_confirmation: client call failed for %s: %s",
                client_username,
                e,
            )
    elif not phone:
        logger.info(
            "handoff_client_confirmation: no phone on file for %s", client_username
        )

    return result
