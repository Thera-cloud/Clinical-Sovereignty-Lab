# SOVEREIGN-VOICE — Parallel inference racing (Grok + Azure co-primary)
#
# Fires both Grok Chat HTTP and Azure Realtime WS simultaneously.
# Uses whichever responds first.  Cancels the loser.

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from typing import Any, Callable, Coroutine, Dict, Optional, Tuple

logger = logging.getLogger("inference_race")

_GROK_URL = os.environ.get(
    "NATE_CHAT_URL",
    "https://nathanlhr-0393-resource.services.ai.azure.com"
    "/models/chat/completions?api-version=2024-05-01-preview",
)
_GROK_KEY = os.environ.get("NATE_CHAT_KEY", os.environ.get("AZURE_API_KEY", ""))
_GROK_MODEL = os.environ.get("NATE_CHAT_MODEL", "grok-4-1-fast-non-reasoning")

_AZURE_OAI_HOST = os.environ.get("AZURE_OPENAI_ENDPOINT", "")
_AZURE_OAI_DEPLOY = os.environ.get("AZURE_OPENAI_DEPLOYMENT", "gpt-4o-realtime-preview")
_AZURE_API_KEY = os.environ.get("AZURE_API_KEY", "")
_AZURE_ENDPOINT = (
    f"wss://{_AZURE_OAI_HOST}/openai/realtime"
    f"?api-version=2024-10-01-preview&deployment={_AZURE_OAI_DEPLOY}"
    if _AZURE_OAI_HOST else ""
)


async def _call_grok(
    system_prompt: str,
    user_text: str,
    uid: str,
    max_tokens: int = 150,
    temperature: float = 1.37,
) -> Tuple[str, str]:
    """Call Grok Chat Completions (HTTP POST, non-streaming)."""
    import aiohttp

    headers = {"Content-Type": "application/json", "api-key": _GROK_KEY}
    payload = {
        "model": _GROK_MODEL,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_text},
        ],
        "max_completion_tokens": max_tokens,
        "temperature": temperature,
    }

    t0 = time.monotonic()
    async with aiohttp.ClientSession() as session:
        async with session.post(
            _GROK_URL, headers=headers, json=payload, timeout=aiohttp.ClientTimeout(total=60)
        ) as resp:
            if resp.status != 200:
                body = await resp.text()
                raise RuntimeError(f"Grok HTTP {resp.status}: {body[:200]}")
            data = await resp.json()

    elapsed = time.monotonic() - t0
    text = data.get("choices", [{}])[0].get("message", {}).get("content", "")
    logger.info("Grok completed in %.1fs for %s (%d chars)", elapsed, uid, len(text))
    return text, "grok"


async def _call_azure_realtime(
    system_prompt: str,
    user_text: str,
    uid: str,
    send_fn: Optional[Callable[[str, str], Coroutine]] = None,
) -> Tuple[str, str]:
    """Call Azure Realtime (WebSocket, streaming text deltas)."""
    import aiohttp

    url = _AZURE_ENDPOINT
    headers = {"api-key": _AZURE_API_KEY, "OpenAI-Beta": "realtime=v1"}

    t0 = time.monotonic()
    async with aiohttp.ClientSession() as session:
        async with session.ws_connect(url, headers=headers) as ws:
            await ws.send_str(json.dumps({
                "type": "session.update",
                "session": {
                    "modalities": ["text"],
                    "instructions": system_prompt,
                    "voice": "ballad",
                    "turn_detection": None,
                },
            }))
            await ws.send_str(json.dumps({
                "type": "conversation.item.create",
                "item": {
                    "type": "message",
                    "role": "user",
                    "content": [{"type": "input_text", "text": user_text}],
                },
            }))
            await ws.send_str(json.dumps({"type": "response.create"}))

            full_response = ""
            async for msg in ws:
                if msg.type == aiohttp.WSMsgType.TEXT:
                    event = json.loads(msg.data)
                    etype = event.get("type")
                    if etype == "response.text.delta":
                        full_response += event.get("delta", "")
                        if send_fn:
                            await send_fn(uid, full_response)
                    elif etype in ("response.text.done", "response.done"):
                        break
                    elif etype == "error":
                        raise RuntimeError(f"Azure error: {event}")

    elapsed = time.monotonic() - t0
    logger.info("Azure completed in %.1fs for %s (%d chars)", elapsed, uid, len(full_response))
    return full_response, "azure"


async def race_inference(
    system_prompt: str,
    user_text: str,
    uid: str,
    send_fn: Optional[Callable[[str, str], Coroutine]] = None,
    temperature: float = 1.37,
    max_tokens: int = 150,
) -> Tuple[str, str]:
    """Race Grok HTTP vs Azure Realtime.  Returns (response_text, provider_name).

    If Grok is not configured, falls back to Azure only.
    If Azure is not configured, falls back to Grok only.
    """
    has_grok = bool(_GROK_URL and _GROK_KEY)
    has_azure = bool(_AZURE_ENDPOINT and _AZURE_API_KEY)

    if has_grok and has_azure:
        grok_task = asyncio.create_task(
            _call_grok(system_prompt, user_text, uid, max_tokens, temperature)
        )
        azure_task = asyncio.create_task(
            _call_azure_realtime(system_prompt, user_text, uid, send_fn)
        )

        done, pending = await asyncio.wait(
            {grok_task, azure_task}, return_when=asyncio.FIRST_COMPLETED
        )

        for p in pending:
            p.cancel()
            try:
                await p
            except (asyncio.CancelledError, Exception):
                pass

        winner = done.pop()
        try:
            text, provider = winner.result()
            if text.strip():
                return text, provider
        except Exception as e:
            logger.warning("Race winner failed: %s", e)

        for p in done:
            try:
                text, provider = p.result()
                if text.strip():
                    return text, provider
            except Exception:
                pass

        raise RuntimeError("Both Grok and Azure failed")

    elif has_grok:
        return await _call_grok(system_prompt, user_text, uid, max_tokens, temperature)
    elif has_azure:
        return await _call_azure_realtime(system_prompt, user_text, uid, send_fn)
    else:
        raise RuntimeError("No inference provider configured")
