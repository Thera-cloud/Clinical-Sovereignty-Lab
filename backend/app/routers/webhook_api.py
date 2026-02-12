"""
LITTLE NATE — Webhook API
SendGrid and Twilio event webhook handlers for delivery tracking.
"""

from fastapi import APIRouter, HTTPException, Request
from typing import Optional, List
from datetime import datetime
import json

router = APIRouter(prefix="/api/webhooks", tags=["webhooks"])


# =============================================================================
# SENDGRID EVENT WEBHOOK
# =============================================================================

@router.post("/sendgrid")
async def sendgrid_event_webhook(request: Request):
    """
    Handle SendGrid event webhooks.
    Events: delivered, open, click, bounce, dropped, deferred, unsubscribe, spam_report
    """
    pool = request.app.state.db_pool
    try:
        events = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON payload")

    if not isinstance(events, list):
        events = [events]

    async with pool.acquire() as conn:
        for event in events:
            event_type = event.get("event", "")
            sg_message_id = event.get("sg_message_id", "")
            email = event.get("email", "")
            timestamp = event.get("timestamp")

            # Clean SendGrid message ID (remove .filter suffix)
            if "." in sg_message_id:
                sg_message_id = sg_message_id.split(".")[0]

            if not sg_message_id:
                continue

            # Map SendGrid events to our status
            status_map = {
                "delivered": "delivered",
                "open": "opened",
                "click": "clicked",
                "bounce": "bounced",
                "dropped": "failed",
                "deferred": "sent",          # Still attempting
                "unsubscribe": "unsubscribed",
                "spamreport": "failed",
            }

            new_status = status_map.get(event_type)
            if not new_status:
                continue

            # Update delivery log
            ts = datetime.utcfromtimestamp(timestamp) if timestamp else datetime.utcnow()

            if event_type == "delivered":
                await conn.execute(
                    """UPDATE delivery_log
                       SET status = $1, delivered_at = $2
                       WHERE provider_message_id = $3""",
                    new_status, ts, sg_message_id
                )
            elif event_type == "open":
                await conn.execute(
                    """UPDATE delivery_log
                       SET status = CASE WHEN status != 'clicked' THEN $1 ELSE status END,
                           opened_at = COALESCE(opened_at, $2)
                       WHERE provider_message_id = $3""",
                    new_status, ts, sg_message_id
                )
            elif event_type == "click":
                await conn.execute(
                    """UPDATE delivery_log
                       SET status = $1, clicked_at = COALESCE(clicked_at, $2)
                       WHERE provider_message_id = $3""",
                    new_status, ts, sg_message_id
                )
            elif event_type in ("bounce", "dropped", "spamreport"):
                reason = event.get("reason", "") or event.get("response", "")
                await conn.execute(
                    """UPDATE delivery_log
                       SET status = $1, failed_at = $2, failure_reason = $3
                       WHERE provider_message_id = $4""",
                    new_status, ts, reason, sg_message_id
                )
            elif event_type == "unsubscribe":
                # Also update prospect opt-out
                await conn.execute(
                    """UPDATE delivery_log
                       SET status = $1
                       WHERE provider_message_id = $2""",
                    new_status, sg_message_id
                )
                # Opt out the prospect
                await conn.execute(
                    """UPDATE prospects SET email_opt_out = TRUE, status = 'unsubscribed'
                       WHERE email = $1""",
                    email
                )

    return {"status": "ok", "processed": len(events)}


# =============================================================================
# TWILIO STATUS CALLBACK
# =============================================================================

@router.post("/twilio/status")
async def twilio_status_callback(request: Request):
    """
    Handle Twilio SMS delivery status callbacks.
    Events: queued, sent, delivered, undelivered, failed
    """
    pool = request.app.state.db_pool
    form = await request.form()

    message_sid = form.get("MessageSid", "")
    message_status = form.get("MessageStatus", "")
    error_code = form.get("ErrorCode", "")
    error_message = form.get("ErrorMessage", "")

    if not message_sid:
        return {"status": "ignored"}

    status_map = {
        "queued": "queued",
        "sent": "sent",
        "delivered": "delivered",
        "undelivered": "failed",
        "failed": "failed",
    }

    new_status = status_map.get(message_status, "sent")
    now = datetime.utcnow()

    async with pool.acquire() as conn:
        if new_status == "delivered":
            await conn.execute(
                """UPDATE delivery_log
                   SET status = $1, delivered_at = $2
                   WHERE provider_message_id = $3""",
                new_status, now, message_sid
            )
        elif new_status == "failed":
            reason = f"Error {error_code}: {error_message}" if error_code else "Delivery failed"
            await conn.execute(
                """UPDATE delivery_log
                   SET status = $1, failed_at = $2, failure_reason = $3
                   WHERE provider_message_id = $4""",
                new_status, now, reason, message_sid
            )
        else:
            await conn.execute(
                """UPDATE delivery_log SET status = $1
                   WHERE provider_message_id = $2""",
                new_status, message_sid
            )

    return {"status": "ok"}
