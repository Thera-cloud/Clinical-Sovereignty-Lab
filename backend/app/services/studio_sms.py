"""S2 opt-in SMS — Twilio dispatch, no DID purchase. QUANTUM-CRYSTAL-ARCH"""

from __future__ import annotations

import logging
import os
import re
from typing import Any, Dict

logger = logging.getLogger("studio_sms")

OPT_IN_BODY = (
    "Sovereign Studio: reply YES to remember your topics as counts only. "
    "Reply STOP to opt out. This is not therapy."
)


def normalize_e164(phone: str) -> str:
    digits = re.sub(r"[^\d]", "", phone or "")
    if len(digits) == 10:
        digits = "1" + digits
    if digits and not digits.startswith("+"):
        return "+" + digits
    return digits if digits.startswith("+") else (phone or "").strip()


def send_opt_in_sms(to_phone: str) -> Dict[str, Any]:
    dest = normalize_e164(to_phone)
    if len(re.sub(r"[^\d]", "", dest)) < 11:
        return {"ok": False, "reason": "invalid_phone"}
    sid = os.getenv("TWILIO_ACCOUNT_SID", "")
    token = os.getenv("TWILIO_AUTH_TOKEN", "")
    if not sid or not token:
        logger.warning("studio SMS skipped: Twilio credentials missing")
        return {"ok": False, "reason": "no_twilio"}
    try:
        from twilio.rest import Client

        kwargs: Dict[str, Any] = {"to": dest, "body": OPT_IN_BODY[:320]}
        msg_sid = os.getenv("TWILIO_MESSAGING_SERVICE_SID", "")
        if msg_sid:
            kwargs["messaging_service_sid"] = msg_sid
        else:
            from_num = os.getenv("TWILIO_PHONE_NUMBER", "")
            if not from_num:
                return {"ok": False, "reason": "no_from"}
            kwargs["from_"] = from_num
        msg = Client(sid, token).messages.create(**kwargs)
        return {"ok": True, "sid": msg.sid}
    except Exception as exc:
        logger.warning("studio SMS send failed: %s", exc)
        return {"ok": False, "reason": str(exc)[:120]}


def parse_sms_reply(body: str) -> str:
    text = (body or "").strip().upper()
    if text in ("YES", "Y", "START", "UNSTOP"):
        return "opt_in"
    if text in ("STOP", "STOPALL", "UNSUBSCRIBE", "CANCEL", "END", "QUIT"):
        return "opt_out"
    return "ignore"
