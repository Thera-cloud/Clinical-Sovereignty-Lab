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


def should_attach_image_for_lane(lane: Optional[str]) -> bool:
    return linkedin_images_enabled() and (lane or "").upper() in ("ORIG", "PERS")


def build_image_prompt(
    post_text: str,
    *,
    lane: str = "",
    slot_key: str = "",
) -> str:
    """Visual prompt from post body — branded infographic or legacy painterly fallback."""
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
) -> Optional[bytes]:
    """Return JPEG bytes or None on any failure (caller posts text-only)."""
    if not should_attach_image_for_lane(lane):
        return None
    if not os.getenv("GEMINI_API_KEY", "").strip():
        logger.warning("SkyEye LinkedIn image: GEMINI_API_KEY missing — text-only post")
        return None
    try:
        from app.services.skyeye_gemini_image import generate_image

        prompt = build_image_prompt(post_text, lane=lane, slot_key=slot_key)
        refs = None
        if _use_brand_system():
            from app.services.skyeye_linkedin_brand import load_brand_reference_images

            refs = load_brand_reference_images()
            if not refs:
                logger.warning(
                    "SkyEye LinkedIn brand refs missing in %s — prompt-only generation",
                    os.getenv("SKYEYE_LINKEDIN_BRAND_DIR", "default brand dir"),
                )
        return await generate_image(prompt, reference_images=refs or None)
    except Exception as e:
        logger.warning(
            "SkyEye LinkedIn image skipped (lane=%s slot=%s): %s",
            lane,
            slot_key,
            e,
        )
        return None
