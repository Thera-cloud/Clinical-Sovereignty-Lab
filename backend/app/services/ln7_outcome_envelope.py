"""Unified outcome envelope dual-write (E1 / W7).

# QUANTUM-CRYSTAL-ARCH
"""
from __future__ import annotations

import json
import logging
from typing import Any, Dict, Optional
from uuid import UUID

logger = logging.getLogger("ln7_outcome_envelope")


async def write_envelope(
    db_pool,
    *,
    loop_name: str,
    event_kind: str,
    revision_id: Optional[str] = None,
    task_hash: Optional[str] = None,
    patch_hash: Optional[str] = None,
    domain_tag: Optional[str] = None,
    source_node: Optional[str] = None,
    burst_id: Optional[str] = None,
    attribution: Optional[Dict[str, Any]] = None,
    metrics: Optional[Dict[str, Any]] = None,
    provenance: Optional[Dict[str, Any]] = None,
    shadow_outcome: Optional[Dict[str, Any]] = None,
    confounded: bool = False,
    cost_usd: Optional[float] = None,
) -> Optional[str]:
    if not db_pool:
        return None
    try:
        async with db_pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                INSERT INTO outcome_envelope (
                    loop_name, event_kind, revision_id, task_hash, patch_hash,
                    domain_tag, source_node, burst_id, attribution_json,
                    metrics_json, provenance_json, shadow_outcome, confounded, cost_usd
                ) VALUES (
                    $1, $2, $3, $4, $5, $6, $7, $8,
                    $9::jsonb, $10::jsonb, $11::jsonb, $12::jsonb, $13, $14
                )
                RETURNING envelope_id::text
                """,
                loop_name,
                event_kind,
                revision_id,
                task_hash,
                patch_hash,
                domain_tag,
                source_node,
                burst_id,
                json.dumps(attribution or {}),
                json.dumps(metrics or {}),
                json.dumps(provenance or {}),
                json.dumps(shadow_outcome) if shadow_outcome is not None else None,
                confounded,
                cost_usd,
            )
        return str(row["envelope_id"]) if row else None
    except Exception as e:
        logger.warning("outcome_envelope write failed: %s", e)
        return None


async def attach_envelope_to_outcome(
    db_pool, outcome_id: int, envelope_id: str
) -> bool:
    if not db_pool or not outcome_id or not envelope_id:
        return False
    try:
        async with db_pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE ln7_coding_outcomes
                SET envelope_id = $1::uuid
                WHERE id = $2
                """,
                envelope_id,
                outcome_id,
            )
        return True
    except Exception as e:
        logger.warning("attach envelope failed: %s", e)
        return False


async def update_shadow_outcome(
    db_pool, envelope_id: str, shadow: Dict[str, Any]
) -> bool:
    if not db_pool or not envelope_id:
        return False
    try:
        async with db_pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE outcome_envelope
                SET shadow_outcome = $2::jsonb
                WHERE envelope_id = $1::uuid
                """,
                envelope_id,
                json.dumps(shadow),
            )
        return True
    except Exception as e:
        logger.warning("shadow_outcome update failed: %s", e)
        return False


async def has_shadow_outcome_for_patch(db_pool, patch_hash: str) -> bool:
    """G1 promote gate: require executed sandbox row."""
    if not db_pool or not patch_hash:
        return False
    try:
        async with db_pool.acquire() as conn:
            val = await conn.fetchval(
                """
                SELECT 1 FROM outcome_envelope
                WHERE patch_hash = $1
                  AND shadow_outcome IS NOT NULL
                  AND (shadow_outcome->>'passed') IS NOT NULL
                LIMIT 1
                """,
                patch_hash,
            )
        return val is not None
    except Exception as e:
        logger.warning("has_shadow_outcome check failed: %s", e)
        return False
