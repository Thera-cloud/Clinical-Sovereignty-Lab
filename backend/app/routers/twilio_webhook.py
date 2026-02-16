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

    # Unknown keyword — acknowledge silently
    print(f">>> [TWILIO_WEBHOOK] Unhandled message received ({len(Body)} chars)")
    return Response(
        content='<?xml version="1.0" encoding="UTF-8"?><Response></Response>',
        media_type="application/xml",
    )
