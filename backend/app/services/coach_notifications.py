"""
Multi-channel coach notifications for voice overflow / escalation (Sovereign Voice v3.1).
Separate from call_coaching_engine (live third-party coaching).
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any, Dict, List, Optional

logger = logging.getLogger("nate.coach_notifications")


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
    sent: Dict[str, bool] = {"in_app": False, "sms": False, "email": False, "push": False}
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
        if coach_phone and os.getenv("TWILIO_ACCOUNT_SID") and os.getenv("TWILIO_AUTH_TOKEN"):
            try:
                from twilio.rest import Client

                client = Client(os.getenv("TWILIO_ACCOUNT_SID"), os.getenv("TWILIO_AUTH_TOKEN"))
                from_num = os.getenv("TWILIO_PHONE_NUMBER", "")
                if from_num:
                    client.messages.create(to=coach_phone, from_=from_num, body=message[:1400])
                    channels.append("sms")
                    sent["sms"] = True
            except Exception as e:
                logger.warning("coach SMS failed: %s", e)

        if coach_email and urgency == "critical" and os.getenv("SENDGRID_API_KEY"):
            ok = await _send_sendgrid_simple(coach_email, subject[:200], message)
            if ok:
                channels.append("email")
                sent["email"] = True

        # FCM push: wire when mobile exposes token endpoint; placeholder
        fcm_token = payload.get("fcm_token")
        if fcm_token:
            sent["push"] = False  # integrate firebase_admin when available

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
