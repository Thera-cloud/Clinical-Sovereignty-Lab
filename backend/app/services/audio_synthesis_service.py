"""Shared Azure TTS for coach audio briefs. Not the Twilio therapy pipeline."""

from __future__ import annotations

import logging
import os
from typing import Optional

import aiohttp

from app.services.google_workspace_service import FlagOff

logger = logging.getLogger("audio_synthesis_service")


def _flag_on(name: str) -> bool:
    return os.getenv(name, "false").strip().lower() in ("1", "true", "yes")


async def synthesize(text: str, *, voice: str = "alloy") -> Optional[bytes]:
    """Azure gpt-4o-mini-tts. ENABLE_AUDIO_BRIEFS. Isolated from therapy media stream."""
    if not _flag_on("ENABLE_AUDIO_BRIEFS"):
        raise FlagOff("ENABLE_AUDIO_BRIEFS")
    text = (text or "").strip()
    if not text:
        return b""
    endpoint = (os.getenv("AZURE_OPENAI_ENDPOINT") or "").strip().rstrip("/")
    key = (os.getenv("AZURE_API_KEY") or "").strip()
    deployment = os.getenv("AZURE_OPENAI_MINI_TTS_DEPLOYMENT", "gpt-4o-mini-tts")
    if not endpoint or not key:
        logger.warning("audio_synthesis_service: Azure TTS env missing")
        return None
    url = (
        f"https://{endpoint}/openai/deployments/{deployment}/audio/speech"
        "?api-version=2025-03-01-preview"
    )
    if endpoint.startswith("http"):
        url = f"{endpoint}/openai/deployments/{deployment}/audio/speech?api-version=2025-03-01-preview"
    async with aiohttp.ClientSession() as session:
        async with session.post(
            url,
            headers={"api-key": key, "Content-Type": "application/json"},
            json={"model": deployment, "input": text[:4000], "voice": voice},
        ) as resp:
            if resp.status != 200:
                logger.warning("audio_synthesis_service TTS failed: %d", resp.status)
                return None
            return await resp.read()
