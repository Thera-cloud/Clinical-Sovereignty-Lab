"""LoRA Resolver — thin lookup for user_id → replicate_model_ref.

Used by delivery_runtime.py and group_video_generator.py to guard
generation calls. If no active LoRA exists for a user, generation
is skipped (never fallback to generic).

R2 path verification is NOT done here — trust the DB URL for
individual resolution. R2 verification belongs only in
compile_group_lora_folder() and sync_group_lora_folder().
"""
from __future__ import annotations

import logging
from typing import Optional

logger = logging.getLogger(__name__)


async def get_lora_ref(user_id: str, db_pool) -> Optional[str]:
    """Return the active replicate_model_ref for a user, or None.

    If None, the caller must skip generation and log a warning.
    Never fall back to generic/LoRA-less generation.
    """
    try:
        async with db_pool.acquire() as conn:
            ref = await conn.fetchval(
                "SELECT replicate_model_ref FROM character_lora_models "
                "WHERE user_id = $1 AND status = 'active' "
                "ORDER BY created_at DESC LIMIT 1",
                user_id,
            )
        if not ref:
            logger.warning("[LORA] No active LoRA for user %s — skipping generation", user_id)
            return None
        return ref
    except Exception as e:
        logger.warning("[LORA] Failed to resolve LoRA for user %s: %s", user_id, e)
        return None
