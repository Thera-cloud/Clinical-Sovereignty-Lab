"""A2P 10DLC SMS create kwargs — Messaging Service over from_.

Campaign CM36cec5ba43165b643df6ec3ade396302 (LOW_VOLUME) is registered on
Messaging Service MG17b08b844584ea171a5d019d846888fc. Sending with from_
alone hits carrier error 30034 until the number rides that service.
OTP/MFA stays on Twilio Verify (TWILIO_VERIFY_SID), not this path.
"""

from __future__ import annotations

import os
from typing import Any, Dict, Optional


def messaging_service_sid() -> str:
    return (
        os.getenv("TWILIO_MESSAGING_SERVICE_SID")
        or os.getenv("TWILIO_MESSAGING_SID")
        or ""
    ).strip()


def from_number() -> str:
    return (
        os.getenv("TWILIO_FROM_NUMBER") or os.getenv("TWILIO_PHONE_NUMBER") or ""
    ).strip()


def sms_create_kwargs(
    to: str,
    body: str,
    *,
    max_len: int = 1600,
) -> Optional[Dict[str, Any]]:
    """Return Twilio messages.create kwargs, or None if SMS is not configured.

    When a Messaging Service SID is set, omit from_ so Twilio uses the
    A2P-registered sender on that service.
    """
    dest = (to or "").strip()
    text = (body or "")[:max_len]
    if not dest or not text:
        return None
    kwargs: Dict[str, Any] = {"to": dest, "body": text}
    ms = messaging_service_sid()
    if ms:
        kwargs["messaging_service_sid"] = ms
        return kwargs
    src = from_number()
    if not src:
        return None
    kwargs["from_"] = src
    return kwargs
