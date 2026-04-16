"""Archetype Resolver — user_id → archetype_image_url lookup.

Used by delivery_runtime.py and group_video_generator.py to provide
character consistency via source_image_url. Uses the same Grok Imagine
approach as the Thera-World Studio Pipeline "Generate Character Refs".

Unlike the LoRA approach, a missing archetype_ref is a SOFT fallback —
Grok Imagine can still generate from prompt alone with reduced character
consistency but content is not blocked.
"""
from __future__ import annotations

import logging
from typing import Optional

logger = logging.getLogger(__name__)


async def get_archetype_ref(user_id: str, db_pool) -> Optional[str]:
    """Resolve user_id to their archetype_image_url from sse_identity_forge.

    Returns the R2 URL of the user's generated character reference image,
    or None if missing. Callers should proceed with prompt-only generation
    when None is returned (reduced consistency, not blocked).
    """
    try:
        async with db_pool.acquire() as conn:
            url = await conn.fetchval(
                "SELECT archetype_image_url FROM sse_identity_forge "
                "WHERE user_id = $1 AND status = 'complete' "
                "LIMIT 1",
                user_id,
            )
        if not url:
            logger.warning(
                "[ARCHETYPE] No archetype_image_url for user %s — "
                "generation will proceed with prompt-only (reduced consistency)",
                user_id)
            return None
        return url
    except Exception as e:
        logger.warning("[ARCHETYPE] Failed to resolve archetype for user %s: %s", user_id, e)
        return None
