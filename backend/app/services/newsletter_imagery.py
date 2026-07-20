"""Topic hero images for Little Nate Dispatch — Grok Imagine with Gemini fallback.

# QUANTUM-CRYSTAL-ARCH — Little Nate Dispatch
"""
from __future__ import annotations

import logging
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

logger = logging.getLogger("nate.newsletter_imagery")

API_BASE = os.getenv(
    "API_PUBLIC_BASE", "https://api.sovereignsanctuary.net"
).rstrip("/")


def _flag_on() -> bool:
    return os.getenv("ENABLE_NEWSLETTER_HERO_IMAGE", "true").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


def _has_xai() -> bool:
    return bool(
        os.getenv("XAI_SSE_KEY", "").strip()
        or os.getenv("XAI_API_KEY", "").strip()
    )


def _has_gemini() -> bool:
    return bool(os.getenv("GEMINI_API_KEY", "").strip())


def hero_enabled() -> bool:
    if not _flag_on():
        return False
    return _has_xai() or _has_gemini()


def hero_public_url(slug: str) -> str:
    return f"{API_BASE}/api/newsletter/library/{slug}/hero"


def build_hero_prompt(topic: str, subject: str = "") -> str:
    """Safe, editorial still — no clinical gore, no identifiable faces in crisis."""
    theme = (topic or subject or "emotional steadiness").strip()
    theme = re.sub(r"\s+", " ", theme)[:180]
    return (
        "Editorial illustration for a mental-health newsletter called Little Nate Dispatch. "
        f"Theme: {theme}. "
        "Warm cinematic atmosphere, soft gold and deep charcoal palette (#C9A962 accents on #050505), "
        "symbolic and hopeful — light through fog, open doorway, small figure reaching toward connection, "
        "or quiet landscape with a single lantern. "
        "Painterly digital art, no text, no logos, no medical equipment, no blood, no weapons, "
        "no photorealistic identifiable faces, family-safe, contemplative, 1:1 square composition."
    )


def sniff_image_meta(data: bytes) -> Tuple[str, str]:
    """Return (file_suffix, media_type) from magic bytes."""
    if data and len(data) >= 8 and data[:8] == b"\x89PNG\r\n\x1a\n":
        return ".png", "image/png"
    if data and len(data) >= 2 and data[:2] == b"\xff\xd8":
        return ".jpg", "image/jpeg"
    return ".png", "image/png"


async def _generate_via_grok(prompt: str) -> bytes:
    from app.sse.infrastructure.grok_imagine_client import (
        GROK_IMAGINE_LOCK,
        generate_image,
    )

    async with GROK_IMAGINE_LOCK:
        return await generate_image(prompt)


async def _generate_via_gemini(prompt: str) -> bytes:
    from app.services.skyeye_gemini_image import generate_image as gemini_generate

    return await gemini_generate(prompt, aspect_ratio="1:1")


async def generate_hero_bytes(prompt: str) -> Tuple[bytes, str]:
    """Grok Imagine first, then Gemini. Returns (bytes, provider)."""
    errors: list[str] = []

    if _has_xai():
        try:
            image_bytes = await _generate_via_grok(prompt)
            if image_bytes and len(image_bytes) >= 500:
                return image_bytes, "grok_imagine"
            errors.append("grok:empty_image")
        except Exception as e:
            logger.warning("newsletter hero Grok Imagine failed, trying Gemini: %s", e)
            errors.append(f"grok:{e}")

    if _has_gemini():
        try:
            image_bytes = await _generate_via_gemini(prompt)
            if image_bytes and len(image_bytes) >= 500:
                return image_bytes, "gemini"
            errors.append("gemini:empty_image")
        except Exception as e:
            logger.warning("newsletter hero Gemini failed: %s", e)
            errors.append(f"gemini:{e}")

    detail = "; ".join(errors) if errors else "no_image_provider"
    raise RuntimeError(detail)


async def generate_hero_for_issue(db_pool, issue_id: str) -> Dict[str, Any]:
    """Generate topic still (Grok → Gemini), persist local + R2, set hero_image_url."""
    if not db_pool:
        return {"ok": False, "error": "no_db"}
    if not hero_enabled():
        return {"ok": False, "error": "hero_disabled_or_no_image_key"}

    async with db_pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT id, slug, topic, subject_line, status
            FROM newsletter_issues WHERE id = $1::uuid
            """,
            issue_id,
        )
    if not row:
        return {"ok": False, "error": "not_found"}

    slug = row["slug"]
    prompt = build_hero_prompt(row["topic"] or "", row["subject_line"] or "")

    try:
        image_bytes, provider = await generate_hero_bytes(prompt)
    except Exception as e:
        logger.warning("newsletter hero generate failed: %s", e)
        return {"ok": False, "error": f"imagine_failed:{e}"}

    suffix, content_type = sniff_image_meta(image_bytes)
    data_dir = Path(os.getenv("DATA_DIR", "/app/data"))
    root = data_dir / "newsletter_library"
    root.mkdir(parents=True, exist_ok=True)
    local_path = root / f"{slug}-hero{suffix}"
    # Remove sibling ext if regenerating with a different provider format
    for other in (".png", ".jpg", ".jpeg"):
        if other == suffix:
            continue
        sibling = root / f"{slug}-hero{other}"
        if sibling.is_file():
            try:
                sibling.unlink()
            except Exception:
                pass
    local_path.write_bytes(image_bytes)
    try:
        os.chmod(local_path, 0o644)
    except Exception:
        pass

    r2_key = f"newsletter_library/{slug}-hero{suffix}"
    try:
        from app.services import r2_storage

        await r2_storage.upload_bytes_async(
            key=r2_key,
            content=image_bytes,
            content_type=content_type,
        )
    except Exception as e:
        logger.warning("newsletter hero R2 upload: %s", e)

    public_url = hero_public_url(slug)
    stored_prompt = f"[provider:{provider}]\n{prompt}"[:2000]
    async with db_pool.acquire() as conn:
        await conn.execute(
            """
            UPDATE newsletter_issues SET
                hero_image_url = $2,
                hero_image_r2_key = $3,
                hero_image_prompt = $4,
                hero_image_generated_at = NOW(),
                updated_at = NOW()
            WHERE id = $1::uuid
            """,
            issue_id,
            public_url,
            r2_key,
            stored_prompt,
        )
        issue = await conn.fetchrow(
            "SELECT * FROM newsletter_issues WHERE id = $1::uuid", issue_id
        )

    if issue and issue["status"] == "sent":
        try:
            from app.services.newsletter_delivery import _write_library_html

            await _write_library_html(dict(issue), db_pool=db_pool)
        except Exception as e:
            logger.warning("hero library html refresh: %s", e)

    return {
        "ok": True,
        "issue_id": str(issue_id),
        "slug": slug,
        "hero_image_url": public_url,
        "provider": provider,
        "content_type": content_type,
        "bytes": len(image_bytes),
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


async def load_hero_bytes(db_pool, slug: str) -> Optional[bytes]:
    """Load hero image from local disk, then R2."""
    if not slug or not db_pool:
        return None
    data_dir = Path(os.getenv("DATA_DIR", "/app/data"))
    root = data_dir / "newsletter_library"
    for suffix in (".png", ".jpg", ".jpeg"):
        local_path = root / f"{slug}-hero{suffix}"
        if local_path.is_file():
            try:
                return local_path.read_bytes()
            except Exception:
                pass

    r2_key = None
    try:
        async with db_pool.acquire() as conn:
            r2_key = await conn.fetchval(
                """
                SELECT hero_image_r2_key FROM newsletter_issues
                WHERE slug = $1 AND hero_image_r2_key IS NOT NULL
                """,
                slug,
            )
    except Exception:
        r2_key = None

    candidates = []
    if r2_key:
        candidates.append(r2_key)
    candidates.extend(
        [
            f"newsletter_library/{slug}-hero.png",
            f"newsletter_library/{slug}-hero.jpg",
        ]
    )

    for key in candidates:
        try:
            from app.services import r2_storage

            data = r2_storage.download_bytes(key=key)
            if data:
                try:
                    suffix, _ = sniff_image_meta(data)
                    local_path = root / f"{slug}-hero{suffix}"
                    local_path.parent.mkdir(parents=True, exist_ok=True)
                    local_path.write_bytes(data)
                except Exception:
                    pass
                return data
        except Exception as e:
            logger.debug("hero R2 download %s: %s", key, e)
    return None
