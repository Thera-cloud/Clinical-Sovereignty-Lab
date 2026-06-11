"""
Multi-channel coach notifications for voice overflow / escalation (Sovereign Voice v3.1).
Separate from call_coaching_engine (live third-party coaching).
"""

from __future__ import annotations

import json
import logging
import os
import re
import time
from typing import Any, Dict, List, Optional
from xml.sax.saxutils import escape

logger = logging.getLogger("nate.coach_notifications")


def _normalize_phone_e164(phone: str) -> str:
    """Normalize profile phone to E.164 for Twilio (+1XXXXXXXXXX for US NANP)."""
    digits = re.sub(r"[^\d]", "", phone or "")
    if len(digits) == 10:
        digits = "1" + digits
    if digits and not digits.startswith("+"):
        digits = "+" + digits
    return digits


def _send_coach_sms(to_phone: str, body: str) -> bool:
    """Send coach SMS via Messaging Service (A2P). Returns True only on carrier delivery."""
    to_phone = _normalize_phone_e164(to_phone)
    if not to_phone or len(re.sub(r"[^\d]", "", to_phone)) < 11:
        logger.warning("coach SMS skipped: invalid phone %s", (to_phone or "")[:8])
        return False
    sid = os.getenv("TWILIO_ACCOUNT_SID", "")
    token = os.getenv("TWILIO_AUTH_TOKEN", "")
    if not sid or not token:
        logger.warning("coach SMS skipped: Twilio credentials missing")
        return False
    try:
        from twilio.rest import Client

        client = Client(sid, token)
        kwargs: Dict[str, Any] = {"to": to_phone, "body": body[:1400]}
        messaging_sid = os.getenv("TWILIO_MESSAGING_SERVICE_SID", "")
        if messaging_sid:
            kwargs["messaging_service_sid"] = messaging_sid
        else:
            from_num = os.getenv("TWILIO_PHONE_NUMBER", "")
            if not from_num:
                logger.warning("coach SMS skipped: no messaging service or from number")
                return False
            kwargs["from_"] = from_num
        msg = client.messages.create(**kwargs)
        if not msg.sid:
            logger.warning("coach SMS failed: empty sid for %s", to_phone[:8])
            return False

        # A2P 30034: Twilio accepts the API call but carriers block undelivered messages.
        for _ in range(5):
            time.sleep(1.2)
            fetched = client.messages(msg.sid).fetch()
            status = (fetched.status or "").lower()
            if status == "delivered":
                logger.info("coach SMS delivered to %s sid=%s", to_phone[:8], msg.sid)
                return True
            if status in ("undelivered", "failed", "canceled"):
                logger.warning(
                    "coach SMS blocked for %s: status=%s error=%s "
                    "(Twilio A2P campaign FAILED → carrier error 30034; fix in Twilio console)",
                    to_phone[:8],
                    fetched.status,
                    fetched.error_code,
                )
                return False
        logger.warning(
            "coach SMS not confirmed for %s sid=%s last_status=%s",
            to_phone[:8],
            msg.sid,
            status,
        )
        return False
    except Exception as e:
        logger.warning("coach SMS failed for %s: %s", to_phone[:8], e)
        return False


def _send_coach_voice_ping(to_phone: str, speak_text: str) -> bool:
    """Outbound voice alert when SMS is blocked (A2P). Uses voice number, not messaging service."""
    to_phone = _normalize_phone_e164(to_phone)
    from_num = os.getenv("TWILIO_PHONE_NUMBER", "")
    sid = os.getenv("TWILIO_ACCOUNT_SID", "")
    token = os.getenv("TWILIO_AUTH_TOKEN", "")
    if not to_phone or not from_num or not sid or not token:
        return False
    try:
        from twilio.rest import Client

        client = Client(sid, token)
        twiml = f'<Response><Say voice="Polly.Joanna">{escape(speak_text)}</Say></Response>'
        call = client.calls.create(to=to_phone, from_=from_num, twiml=twiml, timeout=25)
        if call.sid:
            logger.info("coach voice ping to %s sid=%s", to_phone[:8], call.sid)
            return True
        return False
    except Exception as e:
        logger.warning("coach voice ping failed for %s: %s", to_phone[:8], e)
        return False


async def notify_coach(
    pool,
    coach_username: str,
    notification: Dict[str, Any],
) -> Dict[str, Any]:
    """
    notification keys: urgency (critical|high|medium|low), message, subject (optional),
    payload (optional dict).
    """
    urgency = (notification.get("urgency") or "medium").lower()
    message = notification.get("message") or ""
    subject = notification.get("subject") or "Sovereign Voice alert"
    payload = notification.get("payload") or {}

    channels: List[str] = ["in_app"]
    sent: Dict[str, bool] = {
        "in_app": False,
        "sms": False,
        "email": False,
        "push": False,
        "voice": False,
    }
    notification_id = 0

    if pool:
        try:
            async with pool.acquire() as conn:
                row = await conn.fetchrow(
                    """
                    INSERT INTO coach_escalation_notifications
                        (coach_username, urgency, subject, message, channels, payload)
                    VALUES ($1, $2, $3, $4, $5::jsonb, $6::jsonb)
                    RETURNING id
                    """,
                    coach_username,
                    urgency,
                    subject[:500],
                    message[:4000],
                    json.dumps(channels),
                    json.dumps(payload),
                )
                notification_id = int(row["id"]) if row else 0
            sent["in_app"] = True
        except Exception as e:
            logger.warning("coach in-app notification failed: %s", e)

    if urgency in ("critical", "high"):
        coach_phone, coach_email = await _lookup_coach_contact(pool, coach_username)
        # Handoff cooldown: repeat reaches skip SMS + voice ping (email/in-app only)
        suppress_voice = bool(payload.get("suppress_voice")) and (
            payload.get("alert_type") == "client_initiated_handoff"
        )
        if coach_phone and not suppress_voice:
            if _send_coach_sms(coach_phone, message):
                channels.append("sms")
                sent["sms"] = True
            elif payload.get("alert_type") == "client_initiated_handoff":
                voice_script = (
                    "Hello. This is Sovereign Sanctuary. One of your clients asked Little Nate "
                    "to reach out to you. This is a coach handoff request, not a crisis alert. "
                    "Please check your email for details."
                )
                if _send_coach_voice_ping(coach_phone, voice_script):
                    channels.append("voice")
                    sent["voice"] = True
            elif payload.get("alert_type") == "suicidal_ideation_escalation":
                voice_script = (
                    "Hello. This is Sovereign Sanctuary. Urgent: one of your clients used "
                    "language that may indicate suicidal or self-harm risk. Please check your "
                    "email and the coach portal immediately."
                )
                if _send_coach_voice_ping(coach_phone, voice_script):
                    channels.append("voice")
                    sent["voice"] = True

        if coach_email and urgency == "critical" and os.getenv("SENDGRID_API_KEY"):
            ok = await _send_sendgrid_simple(coach_email, subject[:200], message)
            if ok:
                channels.append("email")
                sent["email"] = True

        # FCM push: wire when mobile exposes token endpoint; placeholder
        fcm_token = payload.get("fcm_token")
        if fcm_token:
            sent["push"] = False  # integrate firebase_admin when available

    if pool and notification_id:
        try:
            async with pool.acquire() as conn:
                await conn.execute(
                    """
                    UPDATE coach_escalation_notifications
                       SET channels = $2::jsonb
                     WHERE id = $1
                    """,
                    notification_id,
                    json.dumps(channels),
                )
        except Exception as e:
            logger.warning("coach notification channel update failed: %s", e)

    return {
        "status": "ok",
        "channels": channels,
        "sent": sent,
        "notification_id": notification_id,
        "id": notification_id,
    }


async def _send_sendgrid_simple(to_email: str, subject: str, text: str) -> bool:
    key = os.getenv("SENDGRID_API_KEY", "")
    from_email = os.getenv("FROM_EMAIL", "support@sovereignsanctuary.net")
    if not key:
        return False
    try:
        import httpx

        payload = {
            "personalizations": [{"to": [{"email": to_email}]}],
            "from": {"email": from_email},
            "subject": subject,
            "content": [{"type": "text/plain", "value": text[:8000]}],
        }
        async with httpx.AsyncClient(timeout=15.0) as client:
            r = await client.post(
                "https://api.sendgrid.com/v3/mail/send",
                headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
                json=payload,
            )
        return r.status_code in (200, 202)
    except Exception as e:
        logger.warning("SendGrid coach email failed: %s", e)
        return False


async def _lookup_coach_contact(pool, coach_username: str) -> tuple:
    if not pool:
        return "", ""
    try:
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT profile_data->>'phone' AS phone, profile_data->>'email' AS email
                FROM users WHERE username = $1 AND role IN ('COACH', 'ADMIN')
                """,
                coach_username,
            )
        if not row:
            return "", ""
        return (row["phone"] or "", row["email"] or "")
    except Exception:
        return "", ""


async def notify_coach_of_voice_overflow(
    pool,
    *,
    coach_username: Optional[str],
    detail: str,
) -> None:
    if not coach_username:
        return
    await notify_coach(
        pool,
        coach_username,
        {
            "urgency": "high",
            "subject": "Voice queue overflow",
            "message": f"Little Nate voice capacity: {detail}",
            "payload": {"source": "voice_admission"},
        },
    )
