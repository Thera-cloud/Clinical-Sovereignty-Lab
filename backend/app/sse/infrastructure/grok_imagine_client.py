"""SSE Infrastructure — Grok Imagine + Video API client.

Primary generation API for all SSE delivery content:
- Daily panels (generate_image)
- Weekly clips (generate_video with source panel)
- Monthly recaps (generate_video with archetype reference)
- Group videos (generate_image for composite + generate_video for animation)
- Gap recovery panels
- Admin preview generation

Character consistency is achieved via source_image_url parameter using
archetype_image_url from sse_identity_forge — the same approach as the
Thera-World Studio Pipeline "Generate Character Refs".
"""
from __future__ import annotations

import asyncio
import logging
import os
from typing import Any, Optional

import aiohttp

logger = logging.getLogger(__name__)

_IMAGINE_URL = "https://api.x.ai/v1/images/generations"
_VIDEO_URL = "https://api.x.ai/v1/videos/generations"

_session: Optional[aiohttp.ClientSession] = None

GROK_IMAGINE_LOCK = asyncio.Lock()


def _get_api_key() -> str:
    return os.getenv("XAI_SSE_KEY", "").strip() or os.getenv("XAI_API_KEY", "").strip()


def _get_studio_key() -> str:
    return os.getenv("XAI_STUDIO_KEY", "").strip() or _get_api_key()


def _get_fallback_key() -> str:
    return os.getenv("XAI_FALLBACK_KEY", "").strip()


def _get_session() -> aiohttp.ClientSession:
    global _session
    if _session is None or _session.closed:
        timeout = aiohttp.ClientTimeout(total=30, sock_read=25)
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


_MODERATION_SOFTENERS = [
    (r"\bterror\b", "surprise"),
    (r"\bterrifying\b", "dramatic"),
    (r"\bterrified\b", "startled"),
    (r"\bfrozen in terror\b", "wide-eyed with wonder"),
    (r"\bhurt\b", "concern"),
    (r"\banger\b", "determination"),
    (r"\bfists are clenched\b", "hands at his sides"),
    (r"\bgrabbing the legs of\b", "lifting"),
    (r"\bjaws wide open descending upon\b", "looming protectively over"),
    (r"\bteeth and fire visible\b", "glowing breath visible"),
    (r"\bfalling backwards\b", "leaning back"),
    (r"\bfire crashes\b", "light radiates"),
    (r"\bfrightened\b", "awed"),
    (r"\bscared\b", "awed"),
    (r"\bscreeches\b", "calls out"),
    (r"\bdefiantly\b", "bravely"),
    (r"\berupting from\b", "emerging from"),
    (r"\bexploding\b", "splashing"),
    (r"\bdark red\b", "warm amber"),
    (r"\bdread\b", "mystery"),
    (r"\bclimax\b", "crescendo"),
]


def _soften_prompt(prompt: str) -> str:
    """Apply content moderation softeners to a prompt for retry."""
    import re
    result = prompt
    for pattern, replacement in _MODERATION_SOFTENERS:
        result = re.sub(pattern, replacement, result, flags=re.IGNORECASE)
    return f"Whimsical fantasy illustration, family-friendly animated style: {result}"


def _is_credit_or_auth_block(err_str: str) -> bool:
    """True when xAI refuses generation for credits / spend / permission."""
    low = (err_str or "").lower()
    return any(
        marker in low
        for marker in (
            "permission-denied",
            "used all available credits",
            "monthly spending limit",
            "insufficient credits",
            "spending limit",
            " 403:",
            "grok imagine 403",
        )
    )


async def _gemini_image_fallback(
    prompt: str,
    source_image_url: Optional[str] = None,
) -> bytes:
    """Gemini stills when Grok Imagine is unavailable (credits / missing key)."""
    from app.services.skyeye_gemini_image import generate_image as gemini_generate

    refs: list[tuple[bytes, str]] = []
    if source_image_url:
        try:
            session = _get_session()
            async with session.get(source_image_url) as resp:
                if resp.status == 200:
                    blob = await resp.read()
                    ctype = (resp.headers.get("Content-Type") or "image/png").split(";")[0].strip()
                    if blob and len(blob) >= 200:
                        refs.append((blob, ctype or "image/png"))
        except Exception as e:
            logger.warning("Gemini fallback: archetype download failed: %s", e)

    return await gemini_generate(
        prompt,
        aspect_ratio="1:1",
        reference_images=refs or None,
    )


async def generate_image(
    prompt: str,
    size: str = "1024x1024",
    source_image_url: Optional[str] = None,
) -> bytes:
    """Generate a static image via Grok Imagine API.

    Returns raw image bytes downloaded from the response URL.
    Tries primary key first, falls back to XAI_FALLBACK_KEY on 429.
    On credit/403 exhaustion (or missing xAI key), falls back to Gemini when
    GEMINI_API_KEY is set — keeps Thera-World / Sovereign Journey panels alive.
    On content moderation rejection, retries once with a softened prompt.
    When source_image_url is provided, sends image_url in the payload
    for image-to-image generation (character consistency anchor).
    Raises RuntimeError on API failure.
    """
    key = _get_api_key()
    if not key:
        if os.getenv("GEMINI_API_KEY", "").strip():
            logger.warning("XAI key missing — generating via Gemini fallback")
            return await _gemini_image_fallback(prompt, source_image_url)
        raise RuntimeError("XAI_API_KEY not set — cannot call Grok Imagine")

    payload: dict = {"model": "grok-imagine-image", "prompt": prompt, "n": 1}
    if source_image_url:
        payload["image_url"] = source_image_url

    try:
        result = await _imagine_with_key(key, payload)
        await asyncio.sleep(2)
        return result
    except RuntimeError as e:
        err_str = str(e)
        if "content moderation" in err_str.lower():
            logger.warning("Grok Imagine moderation rejection — retrying with softened prompt")
            softened = _soften_prompt(prompt)
            payload_soft: dict = {"model": "grok-imagine-image", "prompt": softened, "n": 1}
            if source_image_url:
                payload_soft["image_url"] = source_image_url
            try:
                result = await _imagine_with_key(key, payload_soft)
                await asyncio.sleep(2)
                return result
            except RuntimeError as soft_err:
                err_str = str(soft_err)
                if _is_credit_or_auth_block(err_str) and os.getenv("GEMINI_API_KEY", "").strip():
                    logger.warning("Grok Imagine credit/auth block after soften — Gemini fallback")
                    return await _gemini_image_fallback(softened, source_image_url)
                raise
        if _is_credit_or_auth_block(err_str) and os.getenv("GEMINI_API_KEY", "").strip():
            logger.warning("Grok Imagine credit/auth block — Gemini fallback: %s", err_str[:180])
            return await _gemini_image_fallback(prompt, source_image_url)
        if "429" not in err_str:
            raise
        fallback = _get_fallback_key()
        if not fallback:
            if os.getenv("GEMINI_API_KEY", "").strip():
                logger.warning("Grok Imagine 429 and no XAI_FALLBACK_KEY — Gemini fallback")
                return await _gemini_image_fallback(prompt, source_image_url)
            raise
        logger.info("Grok Imagine primary key 429 — retrying with fallback key")

    try:
        result = await _imagine_with_key(fallback, payload)
        await asyncio.sleep(2)
        return result
    except RuntimeError as e:
        if _is_credit_or_auth_block(str(e)) and os.getenv("GEMINI_API_KEY", "").strip():
            logger.warning("Grok Imagine fallback key credit/auth block — Gemini fallback")
            return await _gemini_image_fallback(prompt, source_image_url)
        raise


async def _video_with_key(key: str, payload: dict) -> str:
    """Call Grok Video with a specific API key. Returns request_id."""
    session = _get_session()
    async with session.post(_VIDEO_URL, json=payload, headers=_headers_for(key)) as resp:
        if resp.status != 200:
            body = await resp.text()
            raise RuntimeError(f"Grok Video {resp.status}: {body[:300]}")
        data = await resp.json()

    video_id = data.get("request_id", "") or data.get("id", "")
    if not video_id:
        raise RuntimeError("Grok Video response missing video id")
    return video_id


async def generate_video(
    prompt: str,
    source_image_url: Optional[str] = None,
    *,
    request_extras: Optional[dict[str, Any]] = None,
) -> str:
    """Start video generation via Grok Video API.

    Returns a request_id string for polling. Does NOT wait for completion.
    Tries primary key first, falls back to XAI_FALLBACK_KEY on 429.

    ``request_extras`` merges into the JSON body (e.g. undocumented motion knobs).
    Unknown keys may cause 400 — callers should treat failures as optional features.
    """
    key = _get_api_key()
    if not key:
        raise RuntimeError("XAI_API_KEY not set — cannot call Grok Video")

    # Payload is model-dependent; preset output.resolution (e.g. 1920x1080) is not wired here —
    # xAI returns native dimensions (often ~848x480 observed) unless/until API documents width/height.
    payload: dict[str, Any] = {"model": "grok-imagine-video", "prompt": prompt}
    if source_image_url:
        payload["image_url"] = source_image_url
    if request_extras:
        for ek, ev in request_extras.items():
            if ev is not None:
                payload[ek] = ev

    try:
        return await _video_with_key(key, payload)
    except RuntimeError as e:
        if "429" not in str(e):
            raise
        fallback = _get_fallback_key()
        if not fallback:
            raise
        logger.info("Grok Video primary key 429 — retrying with fallback key")
        return await _video_with_key(fallback, payload)


async def poll_video_status(video_id: str) -> dict:
    """Poll Grok Video API for generation status.

    xAI returns status="done" for BOTH pending and completed. The real
    completion signal is progress==100 AND video.url present. We normalize
    to: "completed" | "processing" | "failed".
    """
    url = f"https://api.x.ai/v1/videos/{video_id}"
    session = _get_session()

    for key in (_get_api_key(), _get_fallback_key()):
        if not key:
            continue
        async with session.get(url, headers=_headers_for(key)) as resp:
            if resp.status in (401, 403):
                continue
            if resp.status not in (200, 202):
                body = await resp.text()
                raise RuntimeError(f"Grok Video poll {resp.status}: {body[:300]}")
            data = await resp.json()

            progress = data.get("progress", 0)
            video_url = (data.get("video") or {}).get("url") or data.get("url")
            raw_status = data.get("status", "")

            if video_url and progress == 100:
                status = "completed"
            elif raw_status == "failed":
                status = "failed"
            else:
                status = "processing"

            return {
                "status": status,
                "url": video_url,
                "progress": progress,
                "duration": (data.get("video") or {}).get("duration"),
                "cost_ticks": (data.get("usage") or {}).get("cost_in_usd_ticks"),
            }

    raise RuntimeError("No valid API key for Grok Video poll")
