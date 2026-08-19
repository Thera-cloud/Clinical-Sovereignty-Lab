"""S2 Twilio show DID provision — admin-scoped, rate-limited. QUANTUM-CRYSTAL-ARCH"""

from __future__ import annotations

import logging
import os
import time
from typing import Any, Dict

logger = logging.getLogger("studio_did")

_LAST: Dict[str, float] = {}


def _rate_ok(key: str, cooldown_s: float = 10.0) -> bool:
    now = time.time()
    last = _LAST.get(key, 0.0)
    if now - last < cooldown_s:
        return False
    _LAST[key] = now
    return True


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
