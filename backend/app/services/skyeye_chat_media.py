"""Big Nate Chat media: screenshot vision, attachment storage, LinkedIn image gen."""
from __future__ import annotations

import base64
import logging
import os
import re
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import aiohttp

logger = logging.getLogger(__name__)

_MAX_IMAGE_BYTES = 5 * 1024 * 1024
_ATTACH_TTL_S = 6 * 3600
_RECENT: Dict[str, Dict[str, Any]] = {}

_IMAGE_GEN_RE = re.compile(
    r"\b(?:generate|create|make|draw|render)\b.{0,90}\b(?:image|illustration|graphic|visual|artwork)\b"
    r"|\b(?:image|illustration)\s+(?:for|of)\s+(?:this|the)\s+post\b"
    r"|\bwaiting\s+room\b.{0,40}\b(?:illustration|image)\b"
    r"|\bcounseling the other bots\b",
    re.IGNORECASE,
)


def wants_image_generation(message: str) -> bool:
    return bool(_IMAGE_GEN_RE.search(message or ""))


def _purge_stale() -> None:
    now = time.time()
    dead = [k for k, v in _RECENT.items() if now - float(v.get("ts", 0)) > _ATTACH_TTL_S]
    for k in dead:
        _RECENT.pop(k, None)


def get_attachment(attachment_id: str) -> Optional[Dict[str, Any]]:
    _purge_stale()
    return _RECENT.get(attachment_id)


def latest_attachment() -> Optional[Dict[str, Any]]:
    _purge_stale()
    if not _RECENT:
        return None
    return max(_RECENT.values(), key=lambda v: float(v.get("ts", 0)))


def decode_data_url_or_b64(
    data: str,
    mime_type: str = "image/jpeg",
) -> Tuple[bytes, str]:
    raw = (data or "").strip()
    mime = (mime_type or "image/jpeg").split(";")[0].strip() or "image/jpeg"
    if raw.startswith("data:"):
        header, _, b64 = raw.partition(",")
        m = re.search(r"data:([^;]+)", header)
        if m:
            mime = m.group(1).strip() or mime
        raw = b64
    blob = base64.b64decode(raw, validate=False)
    if len(blob) > _MAX_IMAGE_BYTES:
        raise ValueError(f"Image exceeds {_MAX_IMAGE_BYTES // (1024 * 1024)}MB limit")
    if len(blob) < 32:
        raise ValueError("Image payload too small")
    return blob, mime


def _local_media_dir() -> Path:
    candidates = [
        os.getenv("SKYEYE_CHAT_MEDIA_DIR", "").strip(),
        "/app/data/skyeye_chat_media",
        str(Path.cwd() / "data" / "skyeye_chat_media"),
        "/tmp/skyeye_chat_media",
    ]
    for c in candidates:
        if not c:
            continue
        try:
            root = Path(c)
            root.mkdir(parents=True, exist_ok=True)
            return root
        except Exception:
            continue
    root = Path("/tmp/skyeye_chat_media")
    root.mkdir(parents=True, exist_ok=True)
    return root


def store_attachment_bytes(
    image_bytes: bytes,
    *,
    mime_type: str = "image/jpeg",
    description: str = "",
    source: str = "upload",
) -> Dict[str, Any]:
    """Persist bytes locally (and R2 when configured); register in process cache."""
    _purge_stale()
    att_id = uuid.uuid4().hex[:16]
    ext = "png" if "png" in mime_type else "jpg"
    if "webp" in mime_type:
        ext = "webp"
    rel_key = f"skyeye_chat_attachments/{att_id}.{ext}"
    local_path = _local_media_dir() / f"{att_id}.{ext}"
    local_path.write_bytes(image_bytes)

    media_url = str(local_path)
    storage_kind = "local"
    try:
        from app.services.r2_storage import is_r2_configured, upload_bytes

        if is_r2_configured():
            storage_kind, media_url = upload_bytes(
                key=rel_key,
                content=image_bytes,
                content_type=mime_type,
            )
    except Exception as e:
        logger.warning("SkyEye chat media R2 upload skipped: %s", e)

    rec = {
        "id": att_id,
        "bytes": image_bytes,
        "mime_type": mime_type,
        "description": description or "",
        "media_url": media_url,
        "local_path": str(local_path),
        "storage_kind": storage_kind,
        "source": source,
        "ts": time.time(),
    }
    _RECENT[att_id] = rec
    return {
        "id": att_id,
        "description": rec["description"],
        "media_url": media_url,
        "mime_type": mime_type,
        "storage_kind": storage_kind,
        "byte_len": len(image_bytes),
    }


async def describe_screenshot(
    image_bytes: bytes,
    *,
    mime_type: str = "image/jpeg",
) -> str:
    """OCR/vision describe via Azure GPT-4o, then Workers AI fallback."""
    desc = await _azure_vision_describe(image_bytes, mime_type=mime_type)
    if desc:
        return desc
    try:
        from app.services.vectorize_service import vision_describe_image

        fallback = await vision_describe_image(image_bytes)
        if fallback:
            return fallback.strip()
    except Exception as e:
        logger.warning("Workers AI vision fallback failed: %s", e)
    return (
        "[Screenshot received — vision description unavailable. "
        "Describe what you need from this image.]"
    )


async def _azure_vision_describe(
    image_bytes: bytes,
    *,
    mime_type: str = "image/jpeg",
) -> Optional[str]:
    api_key = os.getenv("AZURE_API_KEY", "").strip()
    endpoint = os.getenv("AZURE_OPENAI_ENDPOINT", "").strip()
    deployment = os.getenv("AZURE_OPENAI_CHAT_DEPLOYMENT", "gpt-4o").strip()
    if not api_key or not endpoint:
        return None
    endpoint = endpoint.replace("https://", "").replace("wss://", "").rstrip("/")
    url = (
        f"https://{endpoint}/openai/deployments/{deployment}"
        f"/chat/completions?api-version=2024-06-01"
    )
    b64 = base64.b64encode(image_bytes).decode("ascii")
    data_url = f"data:{mime_type};base64,{b64}"
    payload = {
        "messages": [
            {
                "role": "system",
                "content": (
                    "You read screenshots for Big Nate Chat (SkyEye admin). "
                    "Transcribe visible UI text accurately. Summarize layout, "
                    "buttons, errors, drafts, and LinkedIn/post content. "
                    "Be concrete; do not invent text that is not visible."
                ),
            },
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": (
                            "Read this screenshot. Extract all readable text, "
                            "note the app/site if clear, and summarize what the "
                            "admin is looking at for social posting decisions."
                        ),
                    },
                    {"type": "image_url", "image_url": {"url": data_url, "detail": "high"}},
                ],
            },
        ],
        "max_completion_tokens": 1200,
    }
    try:
        timeout = aiohttp.ClientTimeout(total=45)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(
                url,
                json=payload,
                headers={"api-key": api_key, "Content-Type": "application/json"},
            ) as resp:
                if resp.status != 200:
                    body = await resp.text()
                    logger.warning("Azure vision describe %s: %s", resp.status, body[:200])
                    return None
                data = await resp.json()
                content = (
                    (data.get("choices") or [{}])[0]
                    .get("message", {})
                    .get("content")
                )
                return (content or "").strip() or None
    except Exception as e:
        logger.warning("Azure vision describe error: %s", e)
        return None


async def process_chat_images(
    images: Optional[List[Dict[str, Any]]],
) -> Tuple[str, List[Dict[str, Any]]]:
    """Decode/upload/describe images from chat payload. Returns (context block, metas)."""
    if not images:
        return "", []
    blocks: List[str] = []
    metas: List[Dict[str, Any]] = []
    for idx, img in enumerate(images[:4], start=1):
        if not isinstance(img, dict):
            continue
        try:
            blob, mime = decode_data_url_or_b64(
                str(img.get("data") or ""),
                mime_type=str(img.get("mime_type") or "image/jpeg"),
            )
        except Exception as e:
            blocks.append(f"[ATTACHMENT {idx} ERROR: {e}]")
            continue
        description = await describe_screenshot(blob, mime_type=mime)
        meta = store_attachment_bytes(
            blob,
            mime_type=mime,
            description=description,
            source="chat_upload",
        )
        filename = str(img.get("filename") or f"screenshot_{idx}")
        metas.append({**meta, "filename": filename})
        blocks.append(
            f"[SCREENSHOT {idx} id={meta['id']} file={filename}]\n{description}\n"
            f"[/SCREENSHOT {idx}]"
        )
    if not blocks:
        return "", []
    ctx = (
        "\n\n═══ ATTACHED SCREENSHOTS (vision-read — treat as ground truth) ═══\n"
        + "\n\n".join(blocks)
        + "\n═══ END SCREENSHOTS ═══\n"
    )
    return ctx, metas


async def _generate_image_bytes_gemini_then_xai(prompt: str) -> Tuple[Optional[bytes], str]:
    """Gemini primary, Grok Imagine (xAI) backup — same ladder as newsletter heroes."""
    errors: List[str] = []
    if os.getenv("GEMINI_API_KEY", "").strip():
        try:
            from app.services.skyeye_gemini_image import generate_image as gemini_generate

            blob = await gemini_generate(prompt)
            if blob and len(blob) >= 500:
                return blob, "gemini"
            errors.append("gemini:empty")
        except Exception as e:
            logger.warning("Chat image Gemini failed — trying xAI: %s", e)
            errors.append(f"gemini:{e}")
    else:
        errors.append("gemini:missing_key")

    xai_key = (
        os.getenv("XAI_SSE_KEY", "").strip()
        or os.getenv("XAI_API_KEY", "").strip()
    )
    if xai_key:
        try:
            from app.sse.infrastructure.grok_imagine_client import (
                GROK_IMAGINE_LOCK,
                generate_image as grok_generate,
            )

            async with GROK_IMAGINE_LOCK:
                blob = await grok_generate(prompt)
            if blob and len(blob) >= 500:
                return blob, "grok_imagine"
            errors.append("xai:empty")
        except Exception as e:
            logger.warning("Chat image xAI/Grok Imagine failed: %s", e)
            errors.append(f"xai:{e}")
    else:
        errors.append("xai:missing_key")

    logger.warning("Chat image gen exhausted providers: %s", "; ".join(errors))
    return None, "none"


async def generate_linkedin_image_for_chat(
    post_text: str,
    *,
    image_prompt: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """Generate a LinkedIn hero image for explicit Big Nate Chat requests."""
    prompt = (image_prompt or "").strip()
    if not prompt:
        prompt = (
            "Professional LinkedIn feed illustration matching this post theme. "
            "No text, no lettering on image. "
            f"Theme: {(post_text or '')[:400]}"
        )
    blob, provider = await _generate_image_bytes_gemini_then_xai(prompt)
    if not blob:
        return None
    meta = store_attachment_bytes(
        blob,
        mime_type="image/jpeg",
        description=f"Generated illustration ({provider}): {prompt[:160]}",
        source="chat_image_gen",
    )
    meta["provider"] = provider
    return meta


def load_image_bytes_for_publish(
    *,
    attachment_id: Optional[str] = None,
    prefer_latest: bool = True,
) -> Optional[bytes]:
    att = get_attachment(attachment_id) if attachment_id else None
    if not att and prefer_latest:
        att = latest_attachment()
    if not att:
        return None
    blob = att.get("bytes")
    if blob:
        return blob
    path = att.get("local_path")
    if path and Path(path).is_file():
        return Path(path).read_bytes()
    return None


def extract_image_prompt(message: str) -> Optional[str]:
    msg = message or ""
    for sep in (":", "—", "–"):
        if sep in msg and _IMAGE_GEN_RE.search(msg):
            idx = msg.find(sep)
            tail = msg[idx + 1 :].strip()
            if len(tail) >= 12:
                return tail[:800]
    m = _IMAGE_GEN_RE.search(msg)
    if m:
        return msg[m.start() :].strip()[:800]
    return None
