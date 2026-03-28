"""
Grok / xAI reasoning for Sovereign Voice.

v3.1 plan: prefer Grok for phone-turn reasoning; Realtime WebSocket to api.x.ai
can be enabled later. Production path uses the same Grok Foundry HTTP endpoint
as the rest of the platform (NATE_CHAT_URL) — modalities stay text; audio stays
on Whisper + XTTS.
"""

from __future__ import annotations

import json
import logging
import os
from typing import List, Optional

logger = logging.getLogger("nate.grok_voice")

USE_XAI_REALTIME_WS = os.getenv("SOVEREIGN_VOICE_GROK_REALTIME_WS", "").lower() in ("1", "true", "yes")
XAI_REALTIME_URL = os.getenv("XAI_REALTIME_URL", "wss://api.x.ai/v1/realtime")
XAI_API_KEY = os.getenv("XAI_API_KEY", "")


async def grok_voice_chat_completion(
    *,
    username: str,
    system_prompt: str,
    user_content: str,
    max_tokens: int = 120,
) -> Optional[str]:
    """
    Chat-completions style call (Azure Foundry / Grok deployment).
    Returns assistant text or None on failure.
    """
    try:
        import httpx
        from app.services.nate_ai_config import (
            NATE_CHAT_KEY,
            NATE_CHAT_MODEL,
            NATE_CHAT_URL,
            nate_chat_headers,
            nate_chat_payload,
        )
    except Exception as e:
        logger.warning("grok_voice imports failed: %s", e)
        return None

    if not NATE_CHAT_KEY or not NATE_CHAT_URL:
        return None

    messages: List[dict] = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_content},
    ]
    payload = nate_chat_payload(messages, max_tokens=max_tokens, temperature=0.55, user_id=username)
    payload["model"] = NATE_CHAT_MODEL

    try:
        async with httpx.AsyncClient(timeout=12.0) as client:
            resp = await client.post(NATE_CHAT_URL, headers=nate_chat_headers(), json=payload)
        if resp.status_code != 200:
            logger.warning("grok_voice_chat_completion status=%s body=%s", resp.status_code, resp.text[:200])
            return None
        data = resp.json()
        choice = (data.get("choices") or [{}])[0]
        msg = choice.get("message") or {}
        text = (msg.get("content") or "").strip()
        return text or None
    except Exception as e:
        logger.warning("grok_voice_chat_completion error: %s", e)
        return None


# Optional: xAI native Realtime WebSocket (SOVEREIGN_VOICE_GROK_REALTIME_WS + XAI_API_KEY).
# Schema evolves — implement audio-in/text-out against current docs when enabling.
