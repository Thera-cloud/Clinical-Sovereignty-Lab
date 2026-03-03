"""
Twilio Incoming SMS Webhook — A2P 10DLC STOP/START/HELP Compliance
==================================================================

Handles incoming SMS replies from Twilio. When a user texts STOP,
their phone number is added to the opt-out list and all future SMS
sends to that number are blocked.

Twilio A2P 10DLC Campaign: CM36cec5ba43165b643df6ec3ade396302
Brand: BN3309563dc845ee9667a111ad2a3f0ffe
Customer Profile: BU8c4a7586c4f6ffce4a93afb4098bdc02
"""

import base64
import hashlib
import hmac
import json
import os
import re
from pathlib import Path
from fastapi import APIRouter, Request, Response
from typing import Optional

# Optional IP whitelisting for webhook providers (WH-M9)
WEBHOOK_IP_WHITELIST_ENABLED = os.getenv("WEBHOOK_IP_WHITELIST_ENABLED", "false").lower() == "true"
STRIPE_IP_RANGES = [x.strip() for x in os.getenv("STRIPE_WEBHOOK_IPS", "").split(",") if x.strip()]
TWILIO_IP_RANGES = [x.strip() for x in os.getenv("TWILIO_WEBHOOK_IPS", "").split(",") if x.strip()]

TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN", "")
TWILIO_WEBHOOK_URL = os.getenv("TWILIO_WEBHOOK_URL", "")  # The full public URL of the webhook


def verify_twilio_signature(request_url: str, params: dict, signature: str) -> bool:
    """Verify Twilio webhook signature."""
    if not TWILIO_AUTH_TOKEN:
        print(">>> [TWILIO] WARNING: TWILIO_AUTH_TOKEN not set — skipping signature verification")
        return True  # Allow in dev mode
    # Build the data string: URL + sorted POST params
    data = request_url
    for key in sorted(params.keys()):
        data += key + params[key]
    # HMAC-SHA1
    mac = hmac.new(TWILIO_AUTH_TOKEN.encode('utf-8'), data.encode('utf-8'), hashlib.sha1)
    computed = base64.b64encode(mac.digest()).decode('utf-8')
    return hmac.compare_digest(computed, signature)

router = APIRouter(prefix="/webhook/twilio", tags=["twilio"])

# Shared data directory — same location as NotificationSystem's sms_opt_out.json
from app.config import settings as _settings
DATA_DIR = Path(_settings.DATA_DIR)
OPT_OUT_FILE = DATA_DIR / "sms_opt_out.json"

# Standard STOP keywords recognized by CTIA / Twilio A2P
STOP_KEYWORDS = {"STOP", "STOPALL", "UNSUBSCRIBE", "CANCEL", "END", "QUIT"}
START_KEYWORDS = {"START", "UNSTOP", "YES"}

# Approval protocol keywords (Sovereign Swarm strategy proposals)
APPROVAL_PREFIXES = ("APPROVE", "REJECT", "HOLD", "MODIFY")
APPROVAL_SYNONYMS = {"YES", "GO", "DO IT", "SHIP IT", "WAIT", "DEFER", "LATER", "NO", "NOPE"}


def _normalize_phone(phone: str) -> str:
    """Normalize to E.164 format."""
    digits = re.sub(r'[^\d]', '', phone)
    if len(digits) == 10:
        digits = '1' + digits
    if not phone.startswith('+'):
        return '+' + digits
    return phone


def _load_opt_outs() -> set:
    if OPT_OUT_FILE.exists():
        try:
            with open(OPT_OUT_FILE, 'r') as f:
                return set(json.load(f))
        except Exception:
            pass
    return set()


def _save_opt_outs(numbers: set):
    OPT_OUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(OPT_OUT_FILE, 'w') as f:
        json.dump(sorted(numbers), f, indent=2)


@router.post("/incoming")
async def handle_incoming_sms(request: Request):
    """Handle incoming SMS from Twilio (STOP, START, HELP).

    Twilio's Advanced Opt-Out for 10DLC campaigns auto-replies to
    STOP/START at the carrier level. This webhook syncs the local
    opt-out list so the app also blocks sends.
    """
    # IP whitelisting (when enabled)
    if WEBHOOK_IP_WHITELIST_ENABLED and TWILIO_IP_RANGES:
        client_ip = request.client.host if request.client else ""
        if client_ip not in TWILIO_IP_RANGES:
            print(f">>> [TWILIO] Rejected request from non-whitelisted IP: {client_ip}")
            return Response(content="Forbidden", status_code=403)

    form_data = await request.form()
    params = {k: v for k, v in form_data.items()}

    # Verify Twilio signature
    signature = request.headers.get("X-Twilio-Signature", "")
    webhook_url = TWILIO_WEBHOOK_URL or str(request.url)
    if not verify_twilio_signature(webhook_url, params, signature):
        print(">>> [TWILIO] Invalid signature — request rejected")
        return Response(content="Unauthorized", status_code=403)

    From = form_data.get("From", "")
    Body = form_data.get("Body", "")
    keyword = (Body or "").strip().upper()
    phone = _normalize_phone(From)

    if keyword in STOP_KEYWORDS:
        numbers = _load_opt_outs()
        numbers.add(phone)
        _save_opt_outs(numbers)
        print(f">>> [TWILIO_WEBHOOK] STOP received — added to opt-out list")
        # Return empty TwiML — Twilio Advanced Opt-Out already sent its auto-reply
        return Response(
            content='<?xml version="1.0" encoding="UTF-8"?><Response></Response>',
            media_type="application/xml",
        )

    elif keyword in START_KEYWORDS:
        numbers = _load_opt_outs()
        numbers.discard(phone)
        _save_opt_outs(numbers)
        print(f">>> [TWILIO_WEBHOOK] START received — removed from opt-out list")
        return Response(
            content='<?xml version="1.0" encoding="UTF-8"?><Response></Response>',
            media_type="application/xml",
        )

    elif keyword == "HELP":
        twiml = (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<Response><Message>'
            'Sovereign Sanctuary: For support visit sovereignsanctuary.net or email support@sovereignsanctuary.net. '
            'Reply STOP to opt out.'
            '</Message></Response>'
        )
        print(f">>> [TWILIO_WEBHOOK] HELP request received")
        return Response(content=twiml, media_type="application/xml")

    # Check-in snooze replies: "1", "2", or "3" (days)
    if keyword in ("1", "2", "3"):
        days = int(keyword)
        try:
            import asyncpg
            from datetime import datetime, timedelta, timezone

            db_pool = getattr(router, "_db_pool", None)
            if db_pool:
                async with db_pool.acquire() as conn:
                    user_row = await conn.fetchrow(
                        "SELECT username FROM users WHERE profile_data->>'phone' LIKE '%' || $1 || '%'",
                        phone[-10:],
                    )
                    if user_row:
                        snooze_until = datetime.now(timezone.utc) + timedelta(days=days)
                        await conn.execute(
                            """UPDATE users SET profile_data = jsonb_set(
                                COALESCE(profile_data, '{}'::jsonb),
                                '{checkin_snooze_until}', to_jsonb($1::text)
                            ) WHERE username = $2""",
                            snooze_until.isoformat(), user_row["username"],
                        )
                        await conn.execute(
                            """UPDATE nate_checkins SET status = 'snoozed',
                                snooze_days = $1, snooze_until = $2, responded_at = NOW()
                            WHERE user_id = $3 AND status = 'sent'
                              AND created_at > NOW() - INTERVAL '7 days'
                            """,
                            days, snooze_until, user_row["username"],
                        )
                        print(f">>> [TWILIO_WEBHOOK] Check-in snooze: {days} day(s) for {user_row['username']}")
                        twiml = (
                            '<?xml version="1.0" encoding="UTF-8"?>'
                            f'<Response><Message>'
                            f'Got it! Little Nate will check back in {days} day{"s" if days > 1 else ""}. '
                            f'Take care!'
                            f'</Message></Response>'
                        )
                        return Response(content=twiml, media_type="application/xml")
        except Exception as e:
            print(f">>> [TWILIO_WEBHOOK] Snooze handling error: {e}")

    # Check for approval protocol keywords (Sovereign Swarm strategy proposals)
    if keyword.startswith(APPROVAL_PREFIXES) or keyword in APPROVAL_SYNONYMS:
        try:
            from app.services.approval_protocol import ApprovalProtocolService
            from app.config import settings
            import asyncpg

            # Get db_pool from app state if available, otherwise create a brief connection
            db_pool = getattr(router, "_db_pool", None)
            if db_pool:
                protocol = ApprovalProtocolService(db_pool)
                result = await protocol.handle_inbound_reply(
                    raw_message=Body.strip(),
                    channel="sms",
                )
                print(f">>> [TWILIO_WEBHOOK] Approval reply: {result.get('decision', '?')}")
                twiml_body = f"Received: {result.get('decision', 'UNKNOWN')}"
                if result.get("proposal_id"):
                    twiml_body += f" for proposal {result['proposal_id'][:8]}..."
                twiml = (
                    '<?xml version="1.0" encoding="UTF-8"?>'
                    f'<Response><Message>{twiml_body}</Message></Response>'
                )
                return Response(content=twiml, media_type="application/xml")
        except Exception as e:
            print(f">>> [TWILIO_WEBHOOK] Approval handling error: {e}")

    # Free-text reply — check if this is a response to a recent check-in
    if len(Body.strip()) > 3:
        try:
            db_pool = getattr(router, "_db_pool", None)
            if db_pool:
                from datetime import datetime, timedelta, timezone

                async with db_pool.acquire() as conn:
                    user_row = await conn.fetchrow(
                        "SELECT username, role FROM users WHERE profile_data->>'phone' LIKE '%' || $1 || '%'",
                        phone[-10:],
                    )
                    if user_row:
                        checkin_row = await conn.fetchrow(
                            """SELECT id FROM nate_checkins
                               WHERE user_id = $1 AND status = 'sent'
                                 AND created_at > NOW() - INTERVAL '7 days'
                               ORDER BY created_at DESC LIMIT 1""",
                            user_row["username"],
                        )
                        checkin_id = None
                        if checkin_row:
                            checkin_id = checkin_row["id"]
                            await conn.execute(
                                """UPDATE nate_checkins
                                   SET status = 'responded', responded_at = NOW()
                                   WHERE id = $1""",
                                checkin_id,
                            )

                        await conn.execute(
                            """INSERT INTO checkin_wisdom
                               (user_id, role, checkin_id, channel, response_text)
                               VALUES ($1, $2, $3, 'sms', $4)""",
                            user_row["username"], user_row["role"],
                            checkin_id, Body.strip(),
                        )
                        print(f">>> [TWILIO_WEBHOOK] Check-in reply stored for {user_row['username']}")
                        twiml = (
                            '<?xml version="1.0" encoding="UTF-8"?>'
                            '<Response><Message>'
                            'Little Nate heard you. Open the app when you\'re ready: '
                            'https://app.sovereignsanctuary.net'
                            '</Message></Response>'
                        )
                        return Response(content=twiml, media_type="application/xml")
        except Exception as e:
            print(f">>> [TWILIO_WEBHOOK] Free-text reply handling error: {e}")

    # Free-text reply — store as check-in wisdom if a recent check-in exists
    if len(Body.strip()) > 3:
        try:
            from datetime import datetime, timezone

            db_pool = getattr(router, "_db_pool", None)
            if db_pool:
                async with db_pool.acquire() as conn:
                    user_row = await conn.fetchrow(
                        "SELECT username, role FROM users WHERE profile_data->>'phone' LIKE '%' || $1 || '%'",
                        phone[-10:],
                    )
                    if user_row:
                        checkin_row = await conn.fetchrow("""
                            SELECT id FROM nate_checkins
                            WHERE user_id = $1 AND status = 'sent'
                              AND created_at > NOW() - INTERVAL '7 days'
                            ORDER BY created_at DESC LIMIT 1
                        """, user_row["username"])

                        checkin_id = checkin_row["id"] if checkin_row else None

                        if checkin_row:
                            await conn.execute("""
                                UPDATE nate_checkins SET status = 'responded', responded_at = NOW()
                                WHERE id = $1
                            """, checkin_id)

                        await conn.execute("""
                            INSERT INTO checkin_wisdom (user_id, role, checkin_id, channel, response_text)
                            VALUES ($1, $2, $3, 'sms', $4)
                        """, user_row["username"], user_row["role"], checkin_id, Body.strip()[:5000])

                        print(f">>> [TWILIO_WEBHOOK] Check-in wisdom stored for {user_row['username']}")
                        twiml = (
                            '<?xml version="1.0" encoding="UTF-8"?>'
                            '<Response><Message>'
                            'Little Nate heard you. Open the app when you\'re ready: '
                            'https://app.sovereignsanctuary.net'
                            '</Message></Response>'
                        )
                        return Response(content=twiml, media_type="application/xml")
        except Exception as e:
            print(f">>> [TWILIO_WEBHOOK] Free-text handler error: {e}")

    print(f">>> [TWILIO_WEBHOOK] Unhandled message received ({len(Body)} chars)")
    return Response(
        content='<?xml version="1.0" encoding="UTF-8"?><Response></Response>',
        media_type="application/xml",
    )
