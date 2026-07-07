"""Cloudflare Turnstile server-side verification.

Used to gate the anonymous, card-free TRIAL_FREE registration path (Public
Trial Funnel Phase 3, security-registration-abuse) against scripted account
creation. Verification is unconditional for registration_type == TRIAL_FREE —
never gated on a client-declared platform field, which would be attacker
controlled (see plan Gap 2 / security-registration-abuse).

Fails CLOSED: missing secret, missing/blank token, or any network/parsing
error all return False. Never fails open.
"""
from __future__ import annotations

import logging
import os
from typing import Optional

logger = logging.getLogger(__name__)

TURNSTILE_VERIFY_URL = "https://challenges.cloudflare.com/turnstile/v0/siteverify"

# Snapshot at import time — never load_dotenv(override=True) territory.
_TURNSTILE_SECRET = os.getenv("TURNSTILE_SECRET_KEY", "").strip()


async def verify_turnstile(token: str, remote_ip: Optional[str] = None) -> bool:
    """Verify a Cloudflare Turnstile response token server-side.

    Returns True only on an explicit `success: true` from Cloudflare. Any
    missing configuration, missing token, network failure, or unexpected
    response shape returns False (fail closed).
    """
    if not _TURNSTILE_SECRET:
        logger.warning("verify_turnstile: TURNSTILE_SECRET_KEY not configured — failing closed")
        return False
    token = (token or "").strip()
    if not token:
        return False
    try:
        import aiohttp

        data = {"secret": _TURNSTILE_SECRET, "response": token}
        if remote_ip:
            data["remoteip"] = remote_ip
        timeout = aiohttp.ClientTimeout(total=8)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(TURNSTILE_VERIFY_URL, data=data) as resp:
                if resp.status != 200:
                    logger.warning("verify_turnstile: siteverify HTTP %s — failing closed", resp.status)
                    return False
                result = await resp.json(content_type=None)
                return bool(result.get("success"))
    except Exception as e:
        logger.warning("verify_turnstile: verification request failed, failing closed: %s", e)
        return False
