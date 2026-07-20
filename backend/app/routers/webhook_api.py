"""
LITTLE NATE — Webhook API
SendGrid, Twilio, and Meta/Instagram event webhook handlers.
Tapped through Pipeline Drum for environmental sensing (Hive Defense v4.3).
SendGrid HMAC-SHA256 signature verification (Hive Defense v4.3 — GAP H1).
"""

import hashlib
import hmac
import base64
import logging
import os
import time as _time
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import PlainTextResponse
from typing import Optional, List
from datetime import datetime
import json

_logger = logging.getLogger("webhook_api")

SENDGRID_WEBHOOK_VERIFICATION_KEY = os.getenv("SENDGRID_WEBHOOK_VERIFICATION_KEY", "")
INSTAGRAM_WEBHOOK_VERIFY_TOKEN = os.getenv("INSTAGRAM_WEBHOOK_VERIFY_TOKEN", "")
INSTAGRAM_APP_SECRET = os.getenv("INSTAGRAM_APP_SECRET", "")

router = APIRouter(prefix="/api/webhooks", tags=["webhooks"])


def _tap_pipeline_drum(request: Request, endpoint: str, method: str, status_code: int, payload_bytes: bytes = b""):
    """Non-blocking Pipeline Drum tap for webhook traffic."""
    try:
        hive_v4 = getattr(request.app.state, "hive_v4", None)
        if hive_v4:
            drum = hive_v4.get("pipeline_drum")
            if drum:
                drum.tap_request(
                    endpoint=endpoint,
                    method=method,
                    status_code=status_code,
                    response_time_ms=0,
                    payload=payload_bytes,
                )
    except Exception:
        pass


def _verify_sendgrid_signature(request: Request, raw_body: bytes) -> bool:
    """
    Verify SendGrid Event Webhook signature using HMAC-SHA256.
    SendGrid sends:
      X-Twilio-Email-Event-Webhook-Signature: base64-encoded ECDSA signature
      X-Twilio-Email-Event-Webhook-Timestamp: Unix timestamp
    For HMAC verification key (simpler), it uses the verification key from
    the SendGrid UI to compute HMAC-SHA256(timestamp + payload).
    """
    if not SENDGRID_WEBHOOK_VERIFICATION_KEY:
        _logger.warning("SENDGRID_WEBHOOK_VERIFICATION_KEY not set — skipping signature verification")
        return True  # Degrade to no verification if key not configured

    signature = request.headers.get("X-Twilio-Email-Event-Webhook-Signature", "")
    timestamp = request.headers.get("X-Twilio-Email-Event-Webhook-Timestamp", "")

    if not signature or not timestamp:
        _logger.warning("SendGrid webhook missing signature/timestamp headers")
        return False

    try:
        # Construct the signed payload: timestamp + raw body
        payload = timestamp.encode("utf-8") + raw_body
        expected = hmac.new(
            SENDGRID_WEBHOOK_VERIFICATION_KEY.encode("utf-8"),
            payload,
            hashlib.sha256,
        ).digest()
        received = base64.b64decode(signature)
        return hmac.compare_digest(expected, received)
    except Exception as exc:
        _logger.error("SendGrid signature verification error: %s", exc)
        return False


async def _log_webhook_audit(pool, provider: str, event_type: str, result: str, detail: str = "") -> None:
    """Record webhook verification events to audit trail."""
    if not pool:
        return
    try:
        await pool.execute(
            """INSERT INTO webhook_events_v2
               (event_id, event_type, cord1_passed, cord2_passed, cord3_passed, processing_result, processed_at)
               VALUES ($1, $2, $3, FALSE, FALSE, $4, NOW())
               ON CONFLICT (event_id) DO NOTHING""",
            f"wh_{provider}_{int(_time.time())}_{hashlib.sha256(detail.encode()).hexdigest()[:8]}",
            event_type,
            result == "verified",
            result,
        )
    except Exception:
        pass


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

    # ── HIVE DEFENSE v4.3: Tap SendGrid callback through Pipeline Drum ──
    raw_body = await request.body()
    _tap_pipeline_drum(request, "/api/webhooks/sendgrid", "POST", 200, raw_body)

    # ── HIVE DEFENSE v4.3: Verify SendGrid signature (GAP H1) ──
    if not _verify_sendgrid_signature(request, raw_body):
        _logger.warning("SendGrid webhook REJECTED: invalid signature")
        await _log_webhook_audit(pool, "sendgrid", "signature_verification", "rejected", "invalid_signature")
        _tap_pipeline_drum(request, "/api/webhooks/sendgrid", "POST", 403)
        raise HTTPException(status_code=403, detail="Invalid webhook signature")

    _logger.info("SendGrid webhook accepted: %d bytes", len(raw_body))
    await _log_webhook_audit(pool, "sendgrid", "signature_verification", "verified")

    try:
        events = json.loads(raw_body)
    except Exception:
        _logger.warning("SendGrid webhook: invalid JSON payload")
        _tap_pipeline_drum(request, "/api/webhooks/sendgrid", "POST", 400)
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

            # QUANTUM-CRYSTAL-ARCH — Little Nate Dispatch channel (custom_args)
            channel = (
                event.get("channel")
                or (event.get("custom_args") or {}).get("channel")
                or ""
            )
            _ca = event.get("custom_args") if isinstance(event.get("custom_args"), dict) else {}
            if str(channel).lower() == "newsletter" or str(_ca.get("channel", "")).lower() == "newsletter":
                await _handle_newsletter_sendgrid_event(
                    conn, event, event_type, sg_message_id, email, timestamp
                )
                continue

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


async def _handle_newsletter_sendgrid_event(
    conn, event, event_type, sg_message_id, email, timestamp
):
    """Fail-closed newsletter ledger updates — never write to prospects."""
    try:
        status_map = {
            "delivered": "delivered",
            "open": "opened",
            "click": "clicked",
            "bounce": "bounced",
            "dropped": "failed",
            "spamreport": "failed",
        }
        new_status = status_map.get(event_type)
        issue_id = None
        subscriber_id = None
        custom = event.get("custom_args") if isinstance(event.get("custom_args"), dict) else {}
        # Prefer ledger join on provider id; fall back to SendGrid custom_args
        if sg_message_id:
            row = await conn.fetchrow(
                """
                SELECT issue_id, subscriber_id FROM newsletter_sends
                WHERE provider_message_id = $1
                   OR provider_message_id LIKE $1 || '.%'
                LIMIT 1
                """,
                sg_message_id,
            )
            if row:
                issue_id = row["issue_id"]
                subscriber_id = row["subscriber_id"]
                if new_status:
                    await conn.execute(
                        """
                        UPDATE newsletter_sends SET status = $1
                        WHERE provider_message_id = $2
                           OR provider_message_id LIKE $2 || '.%'
                        """,
                        new_status,
                        sg_message_id,
                    )
        if issue_id is None:
            raw_issue = event.get("issue_id") or custom.get("issue_id")
            if raw_issue:
                try:
                    import uuid as _uuid

                    issue_id = _uuid.UUID(str(raw_issue))
                except Exception:
                    issue_id = None
        if subscriber_id is None:
            raw_sub = event.get("subscriber_id") or custom.get("subscriber_id")
            if raw_sub:
                try:
                    import uuid as _uuid

                    subscriber_id = _uuid.UUID(str(raw_sub))
                except Exception:
                    subscriber_id = None
        if issue_id is None and email:
            # Last resort: match active send by email for this event window
            row = await conn.fetchrow(
                """
                SELECT s.issue_id, s.subscriber_id
                FROM newsletter_sends s
                JOIN newsletter_subscribers sub ON sub.id = s.subscriber_id
                WHERE LOWER(sub.email) = LOWER($1)
                  AND s.sent_at > NOW() - INTERVAL '14 days'
                ORDER BY s.sent_at DESC NULLS LAST
                LIMIT 1
                """,
                email,
            )
            if row:
                issue_id = row["issue_id"]
                subscriber_id = row["subscriber_id"]
        await conn.execute(
            """
            INSERT INTO newsletter_send_events
                (issue_id, subscriber_id, provider_message_id, event_type, payload)
            VALUES ($1, $2, $3, $4, $5::jsonb)
            """,
            issue_id,
            subscriber_id,
            sg_message_id or None,
            event_type,
            json.dumps(
                {
                    "email": email,
                    "sg_message_id": sg_message_id,
                    "issue_id": str(issue_id) if issue_id else None,
                    "subscriber_id": str(subscriber_id) if subscriber_id else None,
                }
            )[:2000],
        )
        if event_type in ("bounce", "spamreport", "unsubscribe") and email:
            await conn.execute(
                """
                UPDATE newsletter_subscribers
                SET status = CASE
                      WHEN $2 = 'unsubscribe' THEN 'unsubscribed'
                      ELSE 'suppressed'
                    END,
                    suppressed_reason = CASE
                      WHEN $2 = 'unsubscribe' THEN NULL
                      ELSE $2
                    END,
                    updated_at = NOW()
                WHERE LOWER(email) = LOWER($1)
                """,
                email,
                event_type,
            )
    except Exception as e:
        _logger.warning("newsletter sendgrid event failed: %s", e)


# =============================================================================
# TWILIO STATUS CALLBACK
# =============================================================================

@router.post("/twilio/status")
async def twilio_status_callback(request: Request):
    """
    Handle Twilio SMS delivery status callbacks.
    Events: queued, sent, delivered, undelivered, failed
    """
    # ── HIVE DEFENSE v4.3: Tap Twilio callback through Pipeline Drum ──
    raw_body = await request.body()
    _tap_pipeline_drum(request, "/api/webhooks/twilio/status", "POST", 200, raw_body)

    pool = request.app.state.db_pool
    form = await request.form()

    message_sid = form.get("MessageSid", "")
    message_status = form.get("MessageStatus", "")
    error_code = form.get("ErrorCode", "")
    error_message = form.get("ErrorMessage", "")

    _logger.info("Twilio status callback: sid=%s status=%s", message_sid[:12] if message_sid else "?", message_status)

    if not message_sid:
        _logger.info("Twilio callback ignored: no MessageSid")
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

    await _log_webhook_audit(pool, "twilio", f"sms_{message_status}", "processed", message_sid[:12] if message_sid else "")

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


# =============================================================================
# META / INSTAGRAM WEBHOOKS
# =============================================================================

meta_webhook_router = APIRouter(prefix="/api/skyeye/webhooks", tags=["meta-webhooks"])


def _verify_meta_signature(payload: bytes, signature: str) -> bool:
    """Verify X-Hub-Signature-256 header from Meta webhook payloads."""
    if not INSTAGRAM_APP_SECRET:
        _logger.warning("INSTAGRAM_APP_SECRET not set — skipping Meta signature verification")
        return True
    if not signature or not signature.startswith("sha256="):
        return False
    expected = "sha256=" + hmac.new(
        INSTAGRAM_APP_SECRET.encode(),
        payload,
        hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(expected, signature)


@meta_webhook_router.get("/instagram")
async def instagram_webhook_verify(request: Request):
    """
    Meta webhook verification (GET).
    Meta sends hub.mode, hub.verify_token, hub.challenge.
    We verify the token matches ours and return the challenge as plain text.
    """
    mode = request.query_params.get("hub.mode", "")
    token = request.query_params.get("hub.verify_token", "")
    challenge = request.query_params.get("hub.challenge", "")

    if mode == "subscribe" and token == INSTAGRAM_WEBHOOK_VERIFY_TOKEN:
        _logger.info("Meta webhook verified successfully")
        return PlainTextResponse(content=challenge)

    _logger.warning("Meta webhook verification failed: mode=%s token_match=%s", mode, token == INSTAGRAM_WEBHOOK_VERIFY_TOKEN)
    raise HTTPException(status_code=403, detail="Verification failed")


@meta_webhook_router.post("/instagram")
async def instagram_webhook_receive(request: Request):
    """
    Meta webhook event receiver (POST).
    Receives Instagram DM events, story mentions, etc.
    Verifies X-Hub-Signature-256 before processing.
    """
    raw_body = await request.body()

    _tap_pipeline_drum(request, "/api/skyeye/webhooks/instagram", "POST", 200, raw_body)

    signature = request.headers.get("X-Hub-Signature-256", "")
    if not _verify_meta_signature(raw_body, signature):
        _logger.warning("Meta webhook REJECTED: invalid signature")
        raise HTTPException(status_code=403, detail="Invalid signature")

    try:
        payload = json.loads(raw_body)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON")

    obj = payload.get("object", "")
    entries = payload.get("entry", [])

    _logger.info("Meta webhook received: object=%s entries=%d", obj, len(entries))

    pool = getattr(request.app.state, "db_pool", None)
    if pool:
        for entry in entries:
            ig_id = entry.get("id", "")
            messaging = entry.get("messaging", [])
            for msg_event in messaging:
                sender_id = msg_event.get("sender", {}).get("id", "")
                message = msg_event.get("message", {})
                msg_text = message.get("text", "")

                if msg_text:
                    try:
                        async with pool.acquire() as conn:
                            await conn.execute(
                                """INSERT INTO skyeye_activity (type, platform, content, created_at)
                                   VALUES ($1, $2, $3, NOW())""",
                                "instagram_dm_received",
                                "instagram",
                                json.dumps({
                                    "sender_id": sender_id,
                                    "ig_account": ig_id,
                                    "text_length": len(msg_text),
                                }),
                            )
                    except Exception as e:
                        _logger.warning("Failed to log IG DM event: %s", e)

    return {"status": "ok"}
