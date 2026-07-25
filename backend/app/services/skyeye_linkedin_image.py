"""Publish-time LinkedIn hero images for SkyEye campaign (ORIG/PERS lanes)."""
from __future__ import annotations

import logging
import os
import re
from typing import Optional

logger = logging.getLogger(__name__)

def _use_brand_system() -> bool:
    return os.getenv("SKYEYE_LINKEDIN_BRAND_STYLE", "true").strip().lower() in (
        "1",
        "true",
        "yes",
    )

_BANNED_IN_PROMPT = re.compile(
    r"\b(liminal|threshold|aching)\b", re.IGNORECASE
)


def linkedin_images_enabled() -> bool:
    return os.getenv("ENABLE_SKYEYE_LINKEDIN_IMAGES", "").strip().lower() in (
        "1",
        "true",
        "yes",
    )


def should_attach_image_for_lane(
    lane: Optional[str],
    *,
    force_image: bool = False,
) -> bool:
    if not linkedin_images_enabled():
        return False
    if force_image:
        return True
    return (lane or "").upper() in ("ORIG", "PERS")


def build_image_prompt(
    post_text: str,
    *,
    lane: str = "",
    slot_key: str = "",
    image_prompt: Optional[str] = None,
) -> str:
    """Visual prompt from post body — branded infographic or legacy painterly fallback."""
    if image_prompt and image_prompt.strip():
        return image_prompt.strip()
    if _use_brand_system():
        from app.services.skyeye_linkedin_brand import build_branded_image_prompt

        return build_branded_image_prompt(post_text, lane=lane, slot_key=slot_key)
    body = (post_text or "").strip()
    body = re.sub(r"\s+", " ", body)
    if len(body) > 400:
        body = body[:397] + "..."
    body = _BANNED_IN_PROMPT.sub("", body).strip()
    lane_note = f"Lane {lane}. " if lane else ""
    slot_note = f"Campaign slot {slot_key}. " if slot_key else ""
    theme_hint = (
        "Reflect the emotional theme of the accompanying LinkedIn post visually; "
        "abstract metaphor, no literal quotes from the post. "
    )
    legacy = (
        "Professional LinkedIn feed illustration, painterly therapeutic fantasy, "
        "muted warm palette, hopeful atmosphere, wide landscape composition, "
        "no text, no words, no lettering, no writing on image. "
    )
    return f"{legacy}{lane_note}{slot_note}{theme_hint}Post theme: {body or 'presence and coaching'}"


async def try_generate_linkedin_image(
    post_text: str,
    *,
    lane: str = "",
    slot_key: str = "",
    force_image: bool = False,
    image_prompt: Optional[str] = None,
) -> Optional[bytes]:
    """Return JPEG bytes or None on any failure (caller posts text-only).

    Ladder: Gemini (brand refs when available) → xAI Grok Imagine backup.
    """
    if not should_attach_image_for_lane(lane, force_image=force_image):
        return None
    prompt = build_image_prompt(
        post_text,
        lane=lane,
        slot_key=slot_key,
        image_prompt=image_prompt,
    )
    has_gemini = bool(os.getenv("GEMINI_API_KEY", "").strip())
    has_xai = bool(
        os.getenv("XAI_SSE_KEY", "").strip() or os.getenv("XAI_API_KEY", "").strip()
    )
    if not has_gemini and not has_xai:
        logger.warning(
            "SkyEye LinkedIn image: GEMINI_API_KEY and XAI_API_KEY missing — text-only"
        )
        return None

    if has_gemini:
        try:
            from app.services.skyeye_gemini_image import generate_image

            refs = None
            if _use_brand_system():
                from app.services.skyeye_linkedin_brand import load_brand_reference_images

                refs = load_brand_reference_images()
                if not refs:
                    logger.warning(
                        "SkyEye LinkedIn brand refs missing in %s — prompt-only generation",
                        os.getenv("SKYEYE_LINKEDIN_BRAND_DIR", "default brand dir"),
                    )
            blob = await generate_image(prompt, reference_images=refs or None)
            if blob and len(blob) >= 500:
                return blob
        except Exception as e:
            logger.warning(
                "SkyEye LinkedIn Gemini failed (lane=%s slot=%s) — trying xAI: %s",
                lane,
                slot_key,
                e,
            )

    if has_xai:
        try:
            from app.sse.infrastructure.grok_imagine_client import (
                GROK_IMAGINE_LOCK,
                generate_image as grok_generate,
            )

            async with GROK_IMAGINE_LOCK:
                blob = await grok_generate(prompt)
            if blob and len(blob) >= 500:
                return blob
        except Exception as e:
            logger.warning(
                "SkyEye LinkedIn xAI backup failed (lane=%s slot=%s): %s",
                lane,
                slot_key,
                e,
            )
    return None
