"""LLM fallback chain for SSE story generation.

Priority: Azure Foundry (Grok) → xAI direct → Anthropic Claude.
Returns None if all providers fail so the caller can use a template fallback.
"""
from __future__ import annotations

import logging
import os
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

_TIMEOUT = 15


async def chat_completion_with_fallback(
    messages: list,
    max_tokens: int = 400,
    temperature: float = 0.7,
) -> Optional[str]:
    """Try LLM providers in priority order. Returns content string or None."""
    from app.services.nate_ai_config import (
        NATE_CHAT_KEY as _pri_key,
        NATE_CHAT_MODEL as _pri_model,
        NATE_CHAT_URL as _pri_url,
    )

    providers = []

    if _pri_url and _pri_key:
        is_azure = "azure" in _pri_url.lower() or "services.ai" in _pri_url.lower()
        providers.append({
            "name": "azure_foundry",
            "url": _pri_url,
            "headers": {"Content-Type": "application/json",
                        **({"api-key": _pri_key} if is_azure else {"Authorization": f"Bearer {_pri_key}"})},
            "payload": {"model": _pri_model, "max_tokens": max_tokens,
                        "temperature": temperature, "messages": messages},
        })

    xai_key = os.getenv("XAI_API_KEY", "")
    if xai_key:
        providers.append({
            "name": "xai_direct",
            "url": "https://api.x.ai/v1/chat/completions",
            "headers": {"Content-Type": "application/json", "Authorization": f"Bearer {xai_key}"},
            "payload": {"model": os.getenv("XAI_MODEL", "grok-3-mini"),
                        "max_tokens": max_tokens, "temperature": temperature,
                        "messages": messages},
        })

    anthropic_key = os.getenv("ANTHROPIC_API_KEY", "")
    if anthropic_key:
        providers.append({
            "name": "anthropic",
            "url": "https://api.anthropic.com/v1/messages",
            "headers": {"Content-Type": "application/json",
                        "x-api-key": anthropic_key,
                        "anthropic-version": "2023-06-01"},
            "payload": {"model": "claude-sonnet-4-20250514", "max_tokens": max_tokens,
                        "messages": [m for m in messages if m["role"] != "system"],
                        "system": next((m["content"] for m in messages if m["role"] == "system"), "")},
        })

    for prov in providers:
        try:
            async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
                r = await client.post(prov["url"], headers=prov["headers"], json=prov["payload"])
                if r.status_code in (429, 500, 502, 503):
                    logger.warning("llm_fallback: %s returned %s, trying next", prov["name"], r.status_code)
                    continue
                data = r.json()
                if prov["name"] == "anthropic":
                    content = (data.get("content") or [{}])[0].get("text", "")
                else:
                    content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
                if content:
                    logger.info("llm_fallback: served by %s", prov["name"])
                    return content
        except Exception as e:
            logger.warning("llm_fallback: %s failed: %s", prov["name"], e)

    logger.error("llm_fallback: all providers exhausted")
    return None
