"""SSE Infrastructure — Grok Imagine + Video API client."""
from __future__ import annotations

import asyncio
import logging
import os
from typing import Optional

import aiohttp

logger = logging.getLogger(__name__)

_IMAGINE_URL = "https://api.x.ai/v1/images/generations"
_VIDEO_URL = "https://api.x.ai/v1/videos/generations"

_session: Optional[aiohttp.ClientSession] = None


def _get_api_key() -> str:
    return os.getenv("XAI_API_KEY", "") or os.getenv("NATE_CHAT_KEY", "").strip()


def _get_fallback_key() -> str:
    return os.getenv("XAI_FALLBACK_KEY", "").strip()


def _get_session() -> aiohttp.ClientSession:
    global _session
    if _session is None or _session.closed:
        timeout = aiohttp.ClientTimeout(total=120, sock_read=90)
        connector = aiohttp.TCPConnector(limit=10, keepalive_timeout=120)
        _session = aiohttp.ClientSession(timeout=timeout, connector=connector)
    return _session


def _headers_for(key: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
    }


def _headers() -> dict[str, str]:
    return _headers_for(_get_api_key())


async def _imagine_with_key(key: str, payload: dict) -> bytes:
    """Call Grok Imagine with a specific API key. Returns image bytes."""
    session = _get_session()
    async with session.post(_IMAGINE_URL, json=payload, headers=_headers_for(key)) as resp:
        if resp.status != 200:
            body = await resp.text()
            raise RuntimeError(f"Grok Imagine {resp.status}: {body[:300]}")
        data = await resp.json()

    images = data.get("data", [])
    if not images:
        raise RuntimeError("Grok Imagine returned no images")

    image_url = images[0].get("url", "")
    if not image_url:
        raise RuntimeError("Grok Imagine response missing image URL")

    async with session.get(image_url) as dl_resp:
        if dl_resp.status != 200:
            raise RuntimeError(f"Image download failed: {dl_resp.status}")
        return await dl_resp.read()


async def generate_image(prompt: str, size: str = "1024x1024") -> bytes:
    """Generate a static image via Grok Imagine API.

    Returns raw image bytes downloaded from the response URL.
    Tries primary key first, falls back to XAI_FALLBACK_KEY on 429.
    Raises RuntimeError on API failure.
    """
    key = _get_api_key()
    if not key:
        raise RuntimeError("XAI_API_KEY not set — cannot call Grok Imagine")

    payload = {"model": "grok-imagine-image", "prompt": prompt, "n": 1}

    try:
        result = await _imagine_with_key(key, payload)
        await asyncio.sleep(2)
        return result
    except RuntimeError as e:
        if "429" not in str(e):
            raise
        fallback = _get_fallback_key()
        if not fallback:
            raise
        logger.info("Grok Imagine primary key 429 — retrying with fallback key")

    result = await _imagine_with_key(fallback, payload)
    await asyncio.sleep(2)
    return result


async def generate_video(
    prompt: str, source_image_url: Optional[str] = None
) -> str:
    """Start video generation via Grok Video API.

    Returns a video_id string for polling. Does NOT wait for completion.
    """
    key = _get_api_key()
    if not key:
        raise RuntimeError("XAI_API_KEY not set — cannot call Grok Video")

    payload: dict = {"model": "grok-imagine-video", "prompt": prompt}
    if source_image_url:
        payload["image_url"] = source_image_url

    session = _get_session()
    async with session.post(_VIDEO_URL, json=payload, headers=_headers()) as resp:
        if resp.status != 200:
            body = await resp.text()
            raise RuntimeError(f"Grok Video {resp.status}: {body[:300]}")
        data = await resp.json()

    video_id = data.get("request_id", "") or data.get("id", "")
    if not video_id:
        raise RuntimeError("Grok Video response missing video id")
    return video_id


async def poll_video_status(video_id: str) -> dict:
    """Poll Grok Video API for generation status.

    Returns {"status": "processing"|"completed"|"failed", "url": str|None}.
    Caller handles polling loop with backoff.
    """
    url = f"https://api.x.ai/v1/videos/{video_id}"
    session = _get_session()

    async with session.get(url, headers=_headers()) as resp:
        if resp.status != 200:
            body = await resp.text()
            raise RuntimeError(f"Grok Video poll {resp.status}: {body[:300]}")
        data = await resp.json()

    status = data.get("status", "processing")
    video_url = (data.get("video") or {}).get("url") or data.get("url")
    return {"status": status, "url": video_url}
