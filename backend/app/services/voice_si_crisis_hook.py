"""Voice-call SI / violence → coach alert + risk window + spoken resources.

Thin hook so twilio_grok_xtts_pipeline stays within the protected-file line budget.
QUANTUM-CRYSTAL-ARCH / SOVEREIGN-VOICE
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Awaitable, Callable, Dict, Optional

logger = logging.getLogger(__name__)

SpeakFn = Callable[[str], Awaitable[None]]


def schedule_voice_si_crisis(
    db_pool,
    username: str,
    user_text: str,
    profile: Optional[Dict[str, Any]] = None,
    speak_fn: Optional[SpeakFn] = None,
) -> None:
    """Fire-and-forget SI coach alert (+ optional spoken crisis resources)."""
    if not db_pool or not username or not (user_text or "").strip():
        return
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return
    loop.create_task(_run(db_pool, username, user_text, profile, speak_fn))


async def _run(
    db_pool,
    username: str,
    user_text: str,
    profile: Optional[Dict[str, Any]],
    speak_fn: Optional[SpeakFn],
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
        # SOVEREIGN-VOICE — speak population-aware resources (chat banner equivalent)
        if (result or {}).get("push_client_resources") and speak_fn:
            try:
                from app.services.crisis_resource_registry import spoken_crisis_resources_line

                line = spoken_crisis_resources_line(prof)
                if line:
                    await speak_fn(line)
            except Exception as speak_e:
                logger.warning("[VOICE-SI] speak resources failed: %s", speak_e)
    except Exception as e:
        logger.warning("[VOICE-SI] non-fatal: %s", e)
