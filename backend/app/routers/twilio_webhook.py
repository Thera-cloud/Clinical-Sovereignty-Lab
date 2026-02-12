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

import json
import os
import re
from pathlib import Path
from fastapi import APIRouter, Form, Response
from typing import Optional

router = APIRouter(prefix="/webhook/twilio", tags=["twilio"])

# Shared data directory — same location as NotificationSystem's sms_opt_out.json
DATA_DIR = Path(os.getenv("DATA_DIR", "/app/data"))
OPT_OUT_FILE = DATA_DIR / "sms_opt_out.json"

# Standard STOP keywords recognized by CTIA / Twilio A2P
STOP_KEYWORDS = {"STOP", "STOPALL", "UNSUBSCRIBE", "CANCEL", "END", "QUIT"}
START_KEYWORDS = {"START", "UNSTOP", "YES"}


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
async def handle_incoming_sms(
    From: str = Form(default=""),
    Body: str = Form(default=""),
    To: str = Form(default=""),
    MessageSid: Optional[str] = Form(default=None),
):
    """Handle incoming SMS from Twilio (STOP, START, HELP).

    Twilio's Advanced Opt-Out for 10DLC campaigns auto-replies to
    STOP/START at the carrier level. This webhook syncs the local
    opt-out list so the app also blocks sends.
    """
    keyword = Body.strip().upper()
    phone = _normalize_phone(From)

    if keyword in STOP_KEYWORDS:
        numbers = _load_opt_outs()
        numbers.add(phone)
        _save_opt_outs(numbers)
        print(f">>> [TWILIO_WEBHOOK] STOP from {phone} — added to opt-out list")
        # Return empty TwiML — Twilio Advanced Opt-Out already sent its auto-reply
        return Response(
            content='<?xml version="1.0" encoding="UTF-8"?><Response></Response>',
            media_type="application/xml",
        )

    elif keyword in START_KEYWORDS:
        numbers = _load_opt_outs()
        numbers.discard(phone)
        _save_opt_outs(numbers)
        print(f">>> [TWILIO_WEBHOOK] START from {phone} — removed from opt-out list")
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
        print(f">>> [TWILIO_WEBHOOK] HELP from {phone}")
        return Response(content=twiml, media_type="application/xml")

    # Unknown keyword — acknowledge silently
    print(f">>> [TWILIO_WEBHOOK] Unhandled message from {phone}: {Body[:50]}")
    return Response(
        content='<?xml version="1.0" encoding="UTF-8"?><Response></Response>',
        media_type="application/xml",
    )
