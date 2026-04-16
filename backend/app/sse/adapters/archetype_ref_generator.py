"""Archetype Reference Image Generator.

Equivalent to "Generate Character Refs" in the Thera-World Studio Pipeline.
Generates a canonical character reference image for a user's archetype
using Grok Imagine, stores it in R2, and updates the user's profile.

Uses the same prompt template as layer1_identity_forge._generate_archetype_image().
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


async def generate_archetype_ref(user_id: str, db_pool) -> str | None:
    """Generate and store a character reference image for a user's archetype.

    1. Loads archetype_hint + character_visual from sse_identity_forge
    2. Builds prompt using the same template as Studio Pipeline character refs
    3. Calls grok.generate_image(prompt)
    4. Stores result in R2 at sse/archetype/{user_id}/archetype.png
    5. Updates archetype_image_url in sse_identity_forge + sse_user_journeys
    6. Returns the stored URL
    """
    try:
        async with db_pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT character_visual, archetype_hint "
                "FROM sse_identity_forge WHERE user_id = $1",
                user_id)

        if not row or not row.get("character_visual"):
            logger.warning(
                "[ARCHETYPE_GEN] No character_visual for user %s — cannot generate ref",
                user_id)
            return None

        char_vis = row["character_visual"]
        archetype = row.get("archetype_hint") or "explorer"

        prompt = (
            f"{char_vis[:200]}, standing at the edge of a dark misty forest, "
            f"{archetype} archetype, painterly style, muted warm palette "
            f"with golden light accents, no text, no words, no lettering"
        )

        from app.sse.infrastructure.grok_imagine_client import generate_image
        from app.sse.infrastructure.r2_storage import store_image

        image_bytes = await generate_image(prompt)
        r2_key = f"sse/archetype/{user_id}/archetype.png"
        r2_url = await store_image(image_bytes, r2_key)

        async with db_pool.acquire() as conn:
            await conn.execute(
                "UPDATE sse_identity_forge SET archetype_image_url = $1 "
                "WHERE user_id = $2",
                r2_url, user_id)
            await conn.execute(
                "UPDATE sse_user_journeys SET journey_metadata = "
                "jsonb_set(COALESCE(journey_metadata, '{}'), "
                "'{archetype_image_url}', to_jsonb($1::text)) "
                "WHERE user_id = $2",
                r2_url, user_id)

        logger.info("[ARCHETYPE_GEN] Generated ref for user %s: %s", user_id, r2_url)
        return r2_url

    except Exception as e:
        logger.warning("[ARCHETYPE_GEN] Failed for user %s: %s", user_id, e)
        return None
