"""LoRA Character Identity Registry — cross-pipeline adapter.

Persists trained LoRA weights in `character_lora_models` so any generation
pipeline (trailer, Thera-World, SSE delivery) can resolve a character key
to a LoRA URL without loading project manifests.

Mirrors writes from studio_service / trailer_generator so legacy manifest
storage continues to work while this DB table becomes the canonical source.
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

logger = logging.getLogger(__name__)


async def register_lora(
    db_pool,
    character_key: str,
    lora_weights_url: str,
    *,
    user_id: Optional[str] = None,
    trigger_word: Optional[str] = None,
    base_model: str = "flux-dev",
    training_steps: int = 1000,
    metadata: Optional[dict] = None,
) -> str:
    """Insert or update a LoRA model record. Returns the model_id."""
    model_id = str(uuid.uuid4())
    tw = trigger_word or f"THERA_{character_key.upper()}"
    now = datetime.now(timezone.utc)

    async with db_pool.acquire() as conn:
        existing = await conn.fetchval(
            "SELECT model_id FROM character_lora_models "
            "WHERE character_key = $1 AND status = 'active' LIMIT 1",
            character_key,
        )
        if existing:
            await conn.execute(
                "UPDATE character_lora_models SET "
                "lora_weights_url = $1, trigger_word = $2, "
                "training_steps = $3, metadata = $4, updated_at = $5 "
                "WHERE model_id = $6",
                lora_weights_url, tw, training_steps,
                metadata or {}, now, existing,
            )
            logger.info("LoRA registry: updated %s → %s", character_key, existing)
            return str(existing)

        await conn.execute(
            "INSERT INTO character_lora_models "
            "(model_id, character_key, user_id, lora_weights_url, "
            " trigger_word, base_model, training_steps, status, metadata, created_at) "
            "VALUES ($1,$2,$3,$4,$5,$6,$7,'active',$8,$9)",
            model_id, character_key, user_id, lora_weights_url,
            tw, base_model, training_steps, metadata or {}, now,
        )
        logger.info("LoRA registry: registered %s → %s", character_key, model_id)
        return model_id


async def resolve_lora(
    db_pool,
    character_key: str,
) -> Optional[dict[str, Any]]:
    """Resolve a character key to its active LoRA record (URL + trigger word)."""
    async with db_pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT model_id, lora_weights_url, trigger_word, base_model, "
            "training_steps, metadata "
            "FROM character_lora_models "
            "WHERE character_key = $1 AND status = 'active' "
            "ORDER BY created_at DESC LIMIT 1",
            character_key,
        )
    if not row:
        return None
    return dict(row)


async def list_loras(
    db_pool,
    *,
    user_id: Optional[str] = None,
    status: str = "active",
) -> list[dict[str, Any]]:
    """List all LoRA models, optionally filtered by user and status."""
    q = "SELECT model_id, character_key, user_id, lora_weights_url, trigger_word, status, created_at FROM character_lora_models WHERE status = $1"
    args: list[Any] = [status]
    if user_id:
        q += " AND user_id = $2"
        args.append(user_id)
    q += " ORDER BY created_at DESC"

    async with db_pool.acquire() as conn:
        rows = await conn.fetch(q, *args)
    return [dict(r) for r in rows]


async def deactivate_lora(db_pool, model_id: str) -> bool:
    """Mark a LoRA model as inactive (soft-delete)."""
    async with db_pool.acquire() as conn:
        tag = await conn.execute(
            "UPDATE character_lora_models SET status = 'inactive', "
            "updated_at = NOW() WHERE model_id = $1 AND status = 'active'",
            model_id,
        )
    return "UPDATE 1" in str(tag)
