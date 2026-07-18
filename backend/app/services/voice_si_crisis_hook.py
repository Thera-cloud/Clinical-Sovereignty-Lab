"""Voice-call SI / violence → coach alert + risk window — QUANTUM-CRYSTAL-ARCH / SOVEREIGN-VOICE.

Thin hook so twilio_grok_xtts_pipeline stays within the protected-file line budget.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


def schedule_voice_si_crisis(
    db_pool,
    username: str,
    user_text: str,
    profile: Optional[Dict[str, Any]] = None,
) -> None:
    """Fire-and-forget SI coach alert for a voice transcript turn."""
    if not db_pool or not username or not (user_text or "").strip():
        return
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return
    loop.create_task(_run(db_pool, username, user_text, profile))


async def _run(
    db_pool,
    username: str,
    user_text: str,
    profile: Optional[Dict[str, Any]],
) -> None:
    try:
        from app.services.suicide_ideation_coach_alert import maybe_dispatch_si_coach_alert

        prof = dict(profile or {})
        if not prof.get("username"):
            prof["username"] = username
        if (prof.get("role") or "").upper() != "CLIENT":
            prof["role"] = "CLIENT"
        result = await maybe_dispatch_si_coach_alert(
            db_pool, prof, user_text, turn_id=f"voice:{username}"
        )
        status = (result or {}).get("status")
        if status and status not in ("no_match", "skipped", "disabled"):
            logger.info(
                "[VOICE-SI] status=%s user=%s push=%s",
                status,
                username,
                (result or {}).get("push_client_resources"),
            )
    except Exception as e:
        logger.warning("[VOICE-SI] non-fatal: %s", e)
