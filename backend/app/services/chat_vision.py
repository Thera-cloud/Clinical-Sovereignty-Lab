"""Compress and fetch images so Little Nate can study pixels, not captions."""

from __future__ import annotations

import asyncio
import base64
import io
import re
from typing import Optional
from urllib.parse import unquote, urlparse

_MAX_RAW = 8_000_000
_MAX_SIDE = 1280
_JPEG_QUALITY = 78


def r2_key_from_url(url: str) -> Optional[str]:
    raw = (url or "").strip()
    if not raw:
        return None
    if not raw.startswith("http"):
        return raw.lstrip("/") or None
    try:
        parsed = urlparse(raw.split("?")[0])
        path = unquote(parsed.path.lstrip("/"))
        if path.startswith("nate-vault/"):
            return path[len("nate-vault/") :]
        parts = path.split("/", 1)
        if len(parts) == 2 and parts[0] in ("nate-vault", "nate-warm-memory", "nate-cold-archive"):
            return parts[1]
        return path or None
    except Exception:
        return None


def bytes_to_vision_data_url(raw: bytes, *, max_side: int = _MAX_SIDE) -> Optional[str]:
    if not raw or len(raw) > _MAX_RAW:
        return None
    try:
        from PIL import Image

        img = Image.open(io.BytesIO(raw))
        if img.mode in ("RGBA", "P"):
            img = img.convert("RGB")
        elif img.mode != "RGB":
            img = img.convert("RGB")
        img.thumbnail((max_side, max_side))
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=_JPEG_QUALITY, optimize=True)
        out = buf.getvalue()
        if not out:
            return None
        b64 = base64.b64encode(out).decode("ascii")
        return f"data:image/jpeg;base64,{b64}"
    except Exception as exc:
        print(f">>> [VISION] JPEG compress skipped: {type(exc).__name__}: {exc}")
        if len(raw) > 900_000:
            return None
        b64 = base64.b64encode(raw).decode("ascii")
        return f"data:image/jpeg;base64,{b64}"


def _http_get_bytes(url: str) -> Optional[bytes]:
    import httpx

    with httpx.Client(timeout=12.0, follow_redirects=True) as client:
        resp = client.get(url)
        if resp.status_code != 200 or not resp.content:
            return None
        return resp.content


async def _s3_get(key: str) -> Optional[bytes]:
    if not key:
        return None
    try:
        from app.sse.infrastructure.r2_storage import download_bytes as sse_get

        data = await sse_get(key)
        if data:
            return data
    except Exception as exc:
        print(f">>> [VISION] SSE R2 get skipped: {type(exc).__name__}: {exc}")
    try:
        from app.services.r2_storage import download_bytes_async as svc_get

        data = await svc_get(key=key)
        if data:
            return data
    except Exception as exc:
        print(f">>> [VISION] services R2 get skipped: {type(exc).__name__}: {exc}")
    return None


async def fetch_image_bytes(url_or_key: str) -> Optional[bytes]:
    raw = (url_or_key or "").strip()
    if not raw or raw.startswith("mock://"):
        return None
    if not raw.startswith("http"):
        try:
            from app.services.vault.blob_manager import read_local_blob_bytes

            local = read_local_blob_bytes(raw)
            if local:
                return local
        except Exception as exc:
            print(f">>> [VISION] local blob skipped: {type(exc).__name__}: {exc}")
        if raw.startswith("/") or "archives/" in raw or raw.startswith("quarantine/"):
            return None
    key = r2_key_from_url(raw)
    if key:
        data = await _s3_get(key)
        if data:
            return data
        try:
            from app.sse.infrastructure.r2_storage import presigned_url

            signed = presigned_url(key)
            if signed:
                data = await asyncio.to_thread(_http_get_bytes, signed)
                if data:
                    return data
        except Exception:
            pass
    if raw.startswith("http"):
        try:
            data = await asyncio.to_thread(_http_get_bytes, raw)
            if data:
                return data
        except Exception as exc:
            print(f">>> [VISION] HTTP fetch skipped: {type(exc).__name__}: {exc}")
    return None


async def url_to_vision_data_url(url_or_key: str) -> Optional[str]:
    data = await fetch_image_bytes(url_or_key)
    return bytes_to_vision_data_url(data) if data else None


_WORD_RE = re.compile(r"[a-z]{4,}")


def overlap_score(a: str, b: str) -> int:
    wa = set(_WORD_RE.findall((a or "").lower()))
    wb = set(_WORD_RE.findall((b or "").lower()))
    return len(wa & wb)
