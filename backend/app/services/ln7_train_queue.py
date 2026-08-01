"""LN7 continuous train queue — enqueue micro-batches from graded outcomes / prefs.

Worker hosts (BLUE Apple Silicon / CUDA rental) drain jobs; GREEN never trains weights.
Identity firewall: no vendor fine-tune APIs. Held-out packs excluded at export time.

# QUANTUM-CRYSTAL-ARCH
"""
from __future__ import annotations

import json
import logging
import os
from typing import Any, Dict, List, Optional, Sequence

logger = logging.getLogger("ln7_train_queue")

try:
    # Phase D: shared with ln7_export_train_jsonl.py — packs_index.json's
    # "heldout" list is the single source of truth, never a local copy.
    from app.services.ln7_heldout_registry import heldout_packs as _heldout_packs

    HELDOUT_PACKS = _heldout_packs()
except Exception:
    HELDOUT_PACKS = frozenset({"env_redis_prefix"})


def continuous_enabled() -> bool:
    return os.getenv("ENABLE_LN7_CONTINUOUS", "").strip().lower() in (
        "1", "true", "yes", "on",
    )


def min_batch() -> int:
    try:
        return max(1, int(os.getenv("LN7_CONTINUOUS_MIN_BATCH", "4")))
    except ValueError:
        return 4


def target_batch() -> int:
    try:
        return max(min_batch(), int(os.getenv("LN7_CONTINUOUS_BATCH_N", "8")))
    except ValueError:
        return 8


async def enqueue_outcome(
    db_pool,
    outcome_id: int,
    *,
    trigger_source: str = "outcome",
    notes: str = "",
) -> Optional[int]:
    """Attach outcome to an open queued job or open a new one when batch full."""
    if not continuous_enabled() or not db_pool or not outcome_id:
        return None
    try:
        async with db_pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT id, outcome_ids, batch_n FROM ln7_train_jobs
                WHERE status = 'queued' AND trigger_source = $1
                ORDER BY created_at ASC LIMIT 1
                """,
                trigger_source,
            )
            if row:
                ids = list(row["outcome_ids"] or [])
                if outcome_id in ids:
                    return int(row["id"])
                ids.append(int(outcome_id))
                n = len(ids)
                await conn.execute(
                    """
                    UPDATE ln7_train_jobs
                    SET outcome_ids = $2::bigint[], batch_n = $3,
                        updated_at = NOW(), notes = COALESCE(notes, '') || $4
                    WHERE id = $1
                    """,
                    int(row["id"]),
                    ids,
                    n,
                    ("; " + notes) if notes else "",
                )
                return int(row["id"])
            job_id = await conn.fetchval(
                """
                INSERT INTO ln7_train_jobs
                    (status, trigger_source, outcome_ids, batch_n, notes)
                VALUES ('queued', $1, ARRAY[$2]::bigint[], 1, $3)
                RETURNING id
                """,
                trigger_source,
                int(outcome_id),
                notes or "",
            )
            return int(job_id) if job_id else None
    except Exception as exc:
        logger.warning("ln7_train_queue enqueue: %s", exc)
        return None


async def enqueue_usage_preference(
    db_pool,
    *,
    event_type: str,
    revision_id: Optional[str] = None,
    patch_hash: Optional[str] = None,
) -> Optional[int]:
    """Preference → weight bridge: rejected/edited usage events open preference jobs."""
    if event_type not in ("rejected", "edited_after_apply"):
        return None
    if not continuous_enabled() or not db_pool:
        return None
    # Find latest matching passed outcome by patch_hash if present
    try:
        async with db_pool.acquire() as conn:
            oid = None
            if patch_hash:
                oid = await conn.fetchval(
                    """
                    SELECT id FROM ln7_coding_outcomes
                    WHERE patch_hash = $1 AND passed = TRUE
                    ORDER BY created_at DESC LIMIT 1
                    """,
                    patch_hash,
                )
            src = "usage_reject" if event_type == "rejected" else "usage_edit"
            if oid:
                return await enqueue_outcome(
                    db_pool, int(oid), trigger_source=src,
                    notes=f"pref:{event_type}:rev={revision_id or ''}",
                )
            # Preference-only job (no outcome yet) — empty batch marker
            job_id = await conn.fetchval(
                """
                INSERT INTO ln7_train_jobs
                    (status, trigger_source, outcome_ids, batch_n, notes, gate_json)
                VALUES (
                    'queued', $1, '{}'::bigint[], 0, $2,
                    $3::jsonb
                )
                RETURNING id
                """,
                src,
                f"pref:{event_type}",
                json.dumps({"revision_id": revision_id, "patch_hash": patch_hash}),
            )
            return int(job_id) if job_id else None
    except Exception as exc:
        logger.warning("ln7_train_queue usage enqueue: %s", exc)
        return None


async def claim_ready_job(db_pool) -> Optional[Dict[str, Any]]:
    """Claim a queued job with batch_n >= min_batch (FOR UPDATE SKIP LOCKED)."""
    if not db_pool:
        return None
    try:
        async with db_pool.acquire() as conn:
            async with conn.transaction():
                row = await conn.fetchrow(
                    """
                    SELECT * FROM ln7_train_jobs
                    WHERE status = 'queued' AND batch_n >= $1
                    ORDER BY created_at ASC
                    LIMIT 1
                    FOR UPDATE SKIP LOCKED
                    """,
                    min_batch(),
                )
                if not row:
                    return None
                await conn.execute(
                    """
                    UPDATE ln7_train_jobs
                    SET status = 'exporting', updated_at = NOW()
                    WHERE id = $1
                    """,
                    int(row["id"]),
                )
                return dict(row)
    except Exception as exc:
        logger.warning("ln7_train_queue claim: %s", exc)
        return None


async def update_job(
    db_pool,
    job_id: int,
    *,
    status: Optional[str] = None,
    train_jsonl_path: Optional[str] = None,
    adapter_path: Optional[str] = None,
    revision_id: Optional[str] = None,
    gate_json: Optional[Dict[str, Any]] = None,
    error: Optional[str] = None,
    worker_host: Optional[str] = None,
) -> bool:
    if not db_pool:
        return False
    sets = ["updated_at = NOW()"]
    args: List[Any] = []
    i = 1
    if status is not None:
        sets.append(f"status = ${i}"); args.append(status); i += 1
    if train_jsonl_path is not None:
        sets.append(f"train_jsonl_path = ${i}"); args.append(train_jsonl_path); i += 1
    if adapter_path is not None:
        sets.append(f"adapter_path = ${i}"); args.append(adapter_path); i += 1
    if revision_id is not None:
        sets.append(f"revision_id = ${i}"); args.append(revision_id); i += 1
    if gate_json is not None:
        sets.append(f"gate_json = ${i}::jsonb"); args.append(json.dumps(gate_json)); i += 1
    if error is not None:
        sets.append(f"error = ${i}"); args.append(error[:2000]); i += 1
    if worker_host is not None:
        sets.append(f"worker_host = ${i}"); args.append(worker_host); i += 1
    args.append(int(job_id))
    try:
        async with db_pool.acquire() as conn:
            await conn.execute(
                f"UPDATE ln7_train_jobs SET {', '.join(sets)} WHERE id = ${i}",
                *args,
            )
        return True
    except Exception as exc:
        logger.warning("ln7_train_queue update: %s", exc)
        return False


async def list_jobs(db_pool, *, limit: int = 50) -> List[Dict[str, Any]]:
    if not db_pool:
        return []
    try:
        async with db_pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT id, created_at, updated_at, status, trigger_source,
                       batch_n, revision_id, error, worker_host, gate_json
                FROM ln7_train_jobs
                ORDER BY created_at DESC LIMIT $1
                """,
                max(1, min(200, limit)),
            )
        return [dict(r) for r in rows]
    except Exception as exc:
        logger.warning("ln7_train_queue list: %s", exc)
        return []


async def pending_outcome_ids(db_pool, ids: Sequence[int]) -> List[int]:
    """Filter out heldout pack outcomes."""
    if not db_pool or not ids:
        return []
    try:
        async with db_pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT id, metrics_json FROM ln7_coding_outcomes
                WHERE id = ANY($1::bigint[]) AND passed = TRUE
                  AND generator IN ('ln7', 'ln7_golden')
                """,
                list(ids),
            )
        out = []
        for r in rows:
            meta = r["metrics_json"] or {}
            if isinstance(meta, str):
                try:
                    meta = json.loads(meta)
                except Exception:
                    meta = {}
            if (meta or {}).get("pack") in HELDOUT_PACKS:
                continue
            out.append(int(r["id"]))
        return out
    except Exception as exc:
        logger.warning("ln7_train_queue filter: %s", exc)
        return list(ids)
