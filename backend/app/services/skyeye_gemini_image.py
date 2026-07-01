"""SkyEye-only Gemini image generation (LinkedIn campaign). Not used by SSE."""
from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
from typing import Optional

import aiohttp

logger = logging.getLogger(__name__)

_GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/interactions"
_DEFAULT_MODEL = "gemini-3.1-flash-image"
_DEFAULT_ASPECT = "16:9"

# Gemini Interactions API supported ratios (maps LinkedIn 1.91:1 → 16:9)
_ASPECT_ALIASES = {
    "1.91:1": "16:9",
    "1.91/1": "16:9",
}


def _normalize_aspect_ratio(ratio: str) -> str:
    r = (ratio or _DEFAULT_ASPECT).strip()
    return _ASPECT_ALIASES.get(r, r)

_session: Optional[aiohttp.ClientSession] = None
_lock: Optional[asyncio.Lock] = None


async def _get_lock() -> asyncio.Lock:
    global _lock
    if _lock is None:
        _lock = asyncio.Lock()
    return _lock


def _get_api_key() -> str:
    return os.getenv("GEMINI_API_KEY", "").strip()


def _get_model() -> str:
    return os.getenv("GEMINI_IMAGE_MODEL", _DEFAULT_MODEL).strip() or _DEFAULT_MODEL


def _get_aspect_ratio() -> str:
    raw = os.getenv("GEMINI_LINKEDIN_ASPECT", _DEFAULT_ASPECT).strip() or _DEFAULT_ASPECT
    return _normalize_aspect_ratio(raw)


async def _get_session() -> aiohttp.ClientSession:
    global _session
    if _session is None or _session.closed:
        timeout = aiohttp.ClientTimeout(total=120)
        _session = aiohttp.ClientSession(timeout=timeout)
    return _session


def _extract_image_bytes(data: dict) -> bytes:
    for step in data.get("steps") or []:
        if step.get("type") != "model_output":
            continue
        for item in step.get("content") or []:
            if item.get("type") == "image" and item.get("data"):
                return base64.b64decode(item["data"])
    if isinstance(data.get("output"), list):
        for item in data["output"]:
            if item.get("type") == "image":
                b64 = item.get("data") or (item.get("image") or {}).get("data")
                if b64:
                    return base64.b64decode(b64)
    raise RuntimeError(f"Gemini response had no image payload: {json.dumps(data)[:500]}")


def _has_image_steps(data: dict) -> bool:
    for step in data.get("steps") or []:
        if step.get("type") != "model_output":
            continue
        for item in step.get("content") or []:
            if item.get("type") == "image" and item.get("data"):
                return True
    return False


def _get_image_size() -> Optional[str]:
    return os.getenv("GEMINI_LINKEDIN_IMAGE_SIZE", "").strip() or None


async def generate_image(
    prompt: str,
    *,
    aspect_ratio: Optional[str] = None,
    reference_images: Optional[list[tuple[bytes, str]]] = None,
) -> bytes:
    """Generate JPEG bytes via Gemini Interactions API."""
    key = _get_api_key()
    if not key:
        raise RuntimeError("GEMINI_API_KEY not set")

    ratio = _normalize_aspect_ratio(aspect_ratio or _get_aspect_ratio())
    import base64

    input_blocks: list[dict] = [{"type": "text", "text": prompt}]
    for blob, mime in reference_images or []:
        input_blocks.append(
            {
                "type": "image",
                "data": base64.b64encode(blob).decode("ascii"),
                "mime_type": mime,
            }
        )
    response_format: dict = {
        "type": "image",
        "mime_type": "image/jpeg",
        "aspect_ratio": ratio,
    }
    image_size = _get_image_size()
    if image_size:
        response_format["image_size"] = image_size
    payload = {
        "model": _get_model(),
        "input": input_blocks,
        "response_format": response_format,
    }
    headers = {"x-goog-api-key": key, "Content-Type": "application/json"}
    session = await _get_session()
    lock = await _get_lock()

    async with lock:
        async with session.post(_GEMINI_URL, json=payload, headers=headers) as resp:
            body = await resp.text()
            if resp.status != 200:
                raise RuntimeError(f"Gemini {resp.status}: {body[:400]}")
            data = json.loads(body)

        if not _has_image_steps(data) and data.get("id"):
            fetch_url = f"{_GEMINI_URL}/{data['id']}"
            async with session.get(fetch_url, headers=headers) as resp:
                body = await resp.text()
                if resp.status != 200:
                    raise RuntimeError(f"Gemini fetch {resp.status}: {body[:400]}")
                data = json.loads(body)

        image_bytes = _extract_image_bytes(data)
        await asyncio.sleep(0.5)
        return image_bytes


async def close_session() -> None:
    global _session
    if _session is not None and not _session.closed:
        await _session.close()
        _session = None
