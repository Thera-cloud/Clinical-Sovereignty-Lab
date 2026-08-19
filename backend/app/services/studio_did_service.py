"""S2 Twilio show DID — attach existing or admin provision. Never auto-buy. QUANTUM-CRYSTAL-ARCH"""

from __future__ import annotations

import logging
import os
import re
import time
from typing import Any, Dict

logger = logging.getLogger("studio_did")

VOICE_INBOUND = "https://api.sovereignsanctuary.net/api/studio/voice/inbound"
COACHN_DID = "+15617833006"
_LAST: Dict[str, float] = {}


def normalize_e164(raw: str) -> str:
    digits = re.sub(r"\D", "", raw or "")
    if not digits:
        return ""
    if len(digits) == 10:
        digits = "1" + digits
    return f"+{digits}"


def digits_only(raw: str) -> str:
    return re.sub(r"\D", "", normalize_e164(raw))


def _rate_ok(key: str, cooldown_s: float = 10.0) -> bool:
    now = time.time()
    last = _LAST.get(key, 0.0)
    if now - last < cooldown_s:
        return False
    _LAST[key] = now
    return True


def _configure_voice_webhook(e164: str) -> Dict[str, Any]:
    sid = os.getenv("TWILIO_ACCOUNT_SID", "")
    token = os.getenv("TWILIO_AUTH_TOKEN", "")
    if not sid or not token:
        return {"ok": False, "reason": "twilio_not_configured"}
    try:
        from twilio.rest import Client

        client = Client(sid, token)
        found = client.incoming_phone_numbers.list(phone_number=e164, limit=1)
        if not found:
            return {"ok": False, "reason": "twilio_number_not_in_account"}
        found[0].update(voice_url=VOICE_INBOUND, voice_method="POST")
        return {"ok": True, "sid": found[0].sid, "sms_untouched": True}
    except Exception as exc:
        logger.warning("studio DID voice webhook: %s", exc)
        return {"ok": False, "reason": "twilio_error"}


async def attach_existing_did(
    db_pool, show_id: str, did: str, admin_username: str, *, configure_voice: bool = True
) -> Dict[str, Any]:
    e164 = normalize_e164(did)
    if not e164.startswith("+") or len(digits_only(e164)) < 11:
        return {"ok": False, "reason": "e164 required", "code": 422}
    if not db_pool:
        return {"ok": False, "reason": "no_db", "code": 503}
    async with db_pool.acquire() as conn:
        show = await conn.fetchrow(
            "SELECT id FROM studio_shows WHERE id = $1::uuid",
            show_id,
        )
        if not show:
            return {"ok": False, "reason": "not_found", "code": 404}
        clash = await conn.fetchrow(
            """
            SELECT id FROM studio_shows
            WHERE regexp_replace(COALESCE(did_e164, ''), '[^0-9]', '', 'g') = $2
              AND id <> $1::uuid
            """,
            show_id,
            digits_only(e164),
        )
        if clash:
            return {"ok": False, "reason": "did_in_use", "code": 409}
        await conn.execute(
            "UPDATE studio_shows SET did_e164 = $2, updated_at = NOW() WHERE id = $1::uuid",
            show_id,
            e164,
        )
    voice = {"ok": False, "reason": "skipped"}
    if configure_voice:
        voice = _configure_voice_webhook(e164)
    return {
        "ok": True,
        "did_e164": e164,
        "admin": admin_username,
        "purchased": False,
        "sms": "disabled_pending_a2p",
        "voice_webhook": voice,
    }


async def provision_did(db_pool, show_id: str, admin_username: str) -> Dict[str, Any]:
    if not _rate_ok(f"did:{admin_username}"):
        return {"ok": False, "reason": "rate_limited", "code": 429}
    sid = os.getenv("TWILIO_ACCOUNT_SID", "")
    token = os.getenv("TWILIO_AUTH_TOKEN", "")
    if not sid or not token:
        return {"ok": False, "reason": "twilio_not_configured", "code": 503}
    if not db_pool:
        return {"ok": False, "reason": "no_db", "code": 503}
    async with db_pool.acquire() as conn:
        show = await conn.fetchrow(
            "SELECT id, did_e164 FROM studio_shows WHERE id = $1::uuid",
            show_id,
        )
        if not show:
            return {"ok": False, "reason": "not_found", "code": 404}
        if show["did_e164"]:
            return {"ok": True, "did_e164": show["did_e164"], "already": True}
    try:
        from twilio.rest import Client

        client = Client(sid, token)
        numbers = client.available_phone_numbers("US").local.list(limit=1)
        if not numbers:
            return {"ok": False, "reason": "no_available_did", "code": 503}
        bought = client.incoming_phone_numbers.create(
            phone_number=numbers[0].phone_number,
            voice_url="https://api.sovereignsanctuary.net/api/studio/voice/inbound",
            voice_method="POST",
        )
        e164 = bought.phone_number
    except Exception as exc:
        logger.warning("studio DID provision failed: %s", exc)
        return {"ok": False, "reason": "twilio_error", "code": 502}
    async with db_pool.acquire() as conn:
        await conn.execute(
            "UPDATE studio_shows SET did_e164 = $2, updated_at = NOW() WHERE id = $1::uuid",
            show_id,
            e164,
        )
    return {"ok": True, "did_e164": e164, "admin": admin_username}
