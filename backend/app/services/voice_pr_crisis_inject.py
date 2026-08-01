"""Voice mid-call Principal-Review crisis Guide inject.

Kept outside twilio_grok_xtts_pipeline.py (protected 50-line budget).
QUANTUM-CRYSTAL-ARCH / SOVEREIGN-VOICE
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)


async def inject_principal_review_crisis_guides(
    grok_ws,
    db_pool,
    user_text: str,
    *,
    username: str = "",
) -> bool:
    """If caller language is SI/HI, inject class-shaped PR Guides into Grok."""
    if not grok_ws or not db_pool or not (user_text or "").strip():
        return False
    try:
        from app.services.principal_review_crisis_policy import (
            classify_crisis_turn_class,
            fetch_principal_review_crisis_guides,
            format_crisis_guide_injection,
        )
    except Exception as e:
        logger.warning("voice_pr_crisis_inject: import failed: %s", e)
        return False

    turn_class = classify_crisis_turn_class(user_text)
    if not turn_class:
        return False

    try:
        guides = await fetch_principal_review_crisis_guides(
            db_pool,
            limit=3,
            turn_class=turn_class,
            actor_id=username or None,
            user_text=user_text,
        )
        block = format_crisis_guide_injection(guides, turn_class=turn_class)
    except Exception as e:
        logger.warning("voice_pr_crisis_inject: fetch failed: %s", e)
        return False

    if not block:
        return False

    who = username or "caller"
    context_msg = (
        f"[PRINCIPAL-REVIEW CRISIS POLICY — BIND THIS REPLY FOR {who}]\n"
        "Follow these constraints for your NEXT spoken reply. "
        "First person only. Plain language. Name danger and escalate — "
        "do not recite Guide text verbatim.\n\n"
        f"{block}\n"
        "[END PRINCIPAL-REVIEW CRISIS POLICY]"
    )
    try:
        await grok_ws.send(
            json.dumps(
                {
                    "type": "conversation.item.create",
                    "item": {
                        "type": "message",
                        "role": "user",
                        "content": [{"type": "input_text", "text": context_msg}],
                    },
                }
            )
        )
        await asyncio.sleep(0.3)
        await grok_ws.send(json.dumps({"type": "response.create"}))
        gids = [str(g.get("id") or "") for g in guides]
        print(
            f"[VOICE-PR-CRISIS] injected turn_class={turn_class} "
            f"n={len(guides)} ids={gids}"
        )
        return True
    except Exception as e:
        logger.warning("voice_pr_crisis_inject: websocket inject failed: %s", e)
        return False


def schedule_voice_pr_crisis_inject(
    grok_ws,
    db_pool,
    user_text: str,
    *,
    username: str = "",
) -> None:
    """Fire-and-forget mid-call PR crisis inject."""
    if not grok_ws or not db_pool or not (user_text or "").strip():
        return
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return
    loop.create_task(
        inject_principal_review_crisis_guides(
            grok_ws, db_pool, user_text, username=username
        )
    )
