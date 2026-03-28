"""
SendGrid Inbound Parse Webhook — Check-In Reply Pipeline
=========================================================

Receives parsed email replies sent to checkin@reply.sovereignsanctuary.net.
Matches the sender to a user, finds their most recent check-in, and stores
the response in checkin_wisdom for Little Nate context injection.
Then fires async follow-up: Little Nate reply in INSIGHTS/client chat + email/SMS.

DNS: MX record on reply.sovereignsanctuary.net -> mx.sendgrid.net (priority 10)
SendGrid: Inbound Parse hostname reply.sovereignsanctuary.net
"""

import asyncio
import json
import logging
import os
import re
from datetime import datetime, timezone

from fastapi import APIRouter, Request, Response

logger = logging.getLogger("nate.sendgrid_inbound")

router = APIRouter(prefix="/api/webhooks/sendgrid", tags=["webhooks"])

SENDGRID_INBOUND_SECRET = os.getenv("SENDGRID_INBOUND_SECRET", "")

_QUOTED_REPLY_PATTERNS = [
    re.compile(r"^On .+ wrote:$", re.MULTILINE),
    re.compile(r"^-{3,}\s*Original Message\s*-{3,}$", re.MULTILINE | re.IGNORECASE),
    re.compile(r"^>{1,2}\s", re.MULTILINE),
    re.compile(r"^From:\s", re.MULTILINE),
]


async def _run_checkin_followup(
    user_id, role, response_text, channel, checkin_id, name, db_pool, notification_system
):
    """Fire-and-forget wrapper for check-in reply processor (Little Nate follow-up)."""
    try:
        from app.services.checkin_reply_processor import process_checkin_reply

        await process_checkin_reply(
            user_id=user_id,
            role=role,
            response_text=response_text,
            channel=channel,
            checkin_id=checkin_id,
            name=name,
            db_pool=db_pool,
            notification_system=notification_system,
        )
    except Exception as e:
        logger.warning("SendGrid inbound: check-in follow-up error: %s", e)


def _strip_quoted_reply(text: str) -> str:
    """Remove quoted reply text below separator lines."""
    lines = text.split("\n")
    cleaned = []
    for line in lines:
        if any(p.match(line.strip()) for p in _QUOTED_REPLY_PATTERNS[:2]):
            break
        if line.strip().startswith(">"):
            continue
        cleaned.append(line)
    result = "\n".join(cleaned).strip()
    return result if result else text.strip()


@router.post("/inbound")
async def handle_sendgrid_inbound(request: Request):
    """Receive parsed email from SendGrid Inbound Parse."""

    if SENDGRID_INBOUND_SECRET:
        secret_param = request.query_params.get("secret", "")
        if secret_param != SENDGRID_INBOUND_SECRET:
            logger.warning("SendGrid inbound: invalid secret")
            return Response(status_code=403)

    try:
        form_data = await request.form()
    except Exception as e:
        logger.warning("SendGrid inbound: failed to parse form data: %s", e)
        return Response(status_code=400)

    sender_email = (form_data.get("from") or "").strip()
    text_body = form_data.get("text") or form_data.get("html") or ""

    if not sender_email or not text_body:
        logger.info("SendGrid inbound: empty sender or body")
        return Response(status_code=200)

    email_match = re.search(r"[\w.+-]+@[\w.-]+\.\w+", sender_email)
    if not email_match:
        logger.info("SendGrid inbound: could not extract email from '%s'", sender_email[:50])
        return Response(status_code=200)

    sender_email = email_match.group(0).lower()
    cleaned_text = _strip_quoted_reply(str(text_body))

    if len(cleaned_text) < 3:
        logger.info("SendGrid inbound: reply too short after stripping")
        return Response(status_code=200)

    db_pool = getattr(request.app.state, "db_pool", None) or getattr(router, "_db_pool", None)
    if not db_pool:
        logger.warning("SendGrid inbound: no db_pool available")
        return Response(status_code=200)

    try:
        from app.services.rls_context import set_rls_admin

        set_rls_admin()  # Trusted webhook — RLS blocks INSERT without admin context
        async with db_pool.acquire() as conn:
            user_row = await conn.fetchrow(
                """SELECT username, role, COALESCE(profile_data->>'name', username) AS name
                   FROM users WHERE LOWER(profile_data->>'email') = LOWER($1)""",
                sender_email,
            )
            if not user_row:
                logger.info("SendGrid inbound: no user found for email %s", sender_email)
                return Response(status_code=200)

            username = user_row["username"]
            role = user_row["role"]
            name = user_row["name"] or username

            # Dedup: skip if identical reply from same user within 60 seconds
            dup = await conn.fetchval(
                """SELECT 1 FROM checkin_wisdom
                   WHERE user_id = $1 AND response_text = $2
                     AND created_at > NOW() - INTERVAL '60 seconds'
                   LIMIT 1""",
                username, cleaned_text[:5000],
            )
            if dup:
                logger.info("SendGrid inbound: duplicate reply from %s, skipping", username)
                return Response(status_code=200)

            checkin_row = await conn.fetchrow("""
                SELECT id FROM nate_checkins
                WHERE user_id = $1 AND status IN ('sent', 'responded')
                  AND created_at > NOW() - INTERVAL '7 days'
                ORDER BY created_at DESC LIMIT 1
            """, username)

            checkin_id = checkin_row["id"] if checkin_row else None

            if checkin_row:
                await conn.execute("""
                    UPDATE nate_checkins SET status = 'responded', responded_at = NOW()
                    WHERE id = $1
                """, checkin_id)

            await conn.execute("""
                INSERT INTO checkin_wisdom (user_id, role, checkin_id, channel, response_text)
                VALUES ($1, $2, $3, 'email', $4)
            """, username, role, checkin_id, cleaned_text[:5000])

            logger.info("SendGrid inbound: stored reply from %s (checkin=%s)",
                        username, str(checkin_id)[:8] if checkin_id else "none")

            notify = getattr(request.app.state, "notification_system", None)
            asyncio.create_task(
                _run_checkin_followup(
                    user_id=username,
                    role=role,
                    response_text=cleaned_text[:5000],
                    channel="email",
                    checkin_id=checkin_id,
                    name=name,
                    db_pool=db_pool,
                    notification_system=notify,
                )
            )
    except Exception as e:
        logger.warning("SendGrid inbound: DB error: %s", e)

    return Response(status_code=200)
