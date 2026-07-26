"""LoRA Character Identity Registry — cross-pipeline adapter.

Persists trained LoRA weights in `character_lora_models` so any generation
pipeline (trailer, Thera-World, SSE delivery) can resolve a character key
to a LoRA URL without loading project manifests.

Mirrors writes from studio_service / trailer_generator so legacy manifest
storage continues to work while this DB table becomes the canonical source.
"""
from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

logger = logging.getLogger(__name__)


async def register_lora(
    db_pool,
    user_id: str,
    replicate_model_ref: str,
    *,
    project_id: Optional[str] = None,
    trigger_word: Optional[str] = None,
    base_model: str = "flux-dev",
    metadata: Optional[dict] = None,
) -> str:
    """Insert or update a LoRA model record. Returns the model_id."""
    model_id = str(uuid.uuid4())
    tw = trigger_word or f"THERA_{user_id.upper()}"
    now = datetime.now(timezone.utc)
    meta_json = json.dumps(metadata or {})

    async with db_pool.acquire() as conn:
        existing = await conn.fetchval(
            "SELECT model_id FROM character_lora_models "
            "WHERE user_id = $1 AND status = 'active' LIMIT 1",
            user_id,
        )
        if existing:
            await conn.execute(
                "UPDATE character_lora_models SET "
                "replicate_model_ref = $1, trigger_word = $2, "
                "metadata = $3::jsonb, updated_at = $4 "
                "WHERE model_id = $5",
                replicate_model_ref, tw,
                meta_json, now, existing,
            )
            logger.info("LoRA registry: updated %s → %s", user_id, existing)
            return str(existing)

        await conn.execute(
            "INSERT INTO character_lora_models "
            "(model_id, user_id, project_id, replicate_model_ref, "
            " trigger_word, base_model, status, metadata, created_at, updated_at) "
            "VALUES ($1,$2,$3,$4,$5,$6,'active',$7::jsonb,$8,$8)",
            model_id, user_id, project_id, replicate_model_ref,
            tw, base_model, meta_json, now,
        )
        logger.info("LoRA registry: registered %s → %s", user_id, model_id)
        return model_id


async def resolve_lora(
    db_pool,
    user_id: str,
) -> Optional[dict[str, Any]]:
    """Resolve a user_id to its active LoRA record (URL + trigger word)."""
    async with db_pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT model_id, replicate_model_ref, trigger_word, base_model, "
            "metadata "
            "FROM character_lora_models "
            "WHERE user_id = $1 AND status = 'active' "
            "ORDER BY created_at DESC LIMIT 1",
            user_id,
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
    q = "SELECT model_id, user_id, replicate_model_ref, trigger_word, status, created_at FROM character_lora_models WHERE status = $1"
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
