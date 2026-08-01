"""LN7 outcome ledger helpers — eval isolation, license gates, learning promo.

# QUANTUM-CRYSTAL-ARCH
"""
from __future__ import annotations

import hashlib
import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger("ln7_ledger")

try:
    from app.services.little_nate_7 import PERMISSIVE_SPDX
except Exception:
    PERMISSIVE_SPDX = frozenset({
        "MIT", "Apache-2.0", "BSD-2-Clause", "BSD-3-Clause", "ISC", "Unlicense", "FIRST-PARTY",
    })


def task_hash(payload: str) -> str:
    return hashlib.sha256((payload or "").encode("utf-8", errors="replace")).hexdigest()


def license_allowed_for_training(spdx: Optional[str]) -> bool:
    if not spdx:
        return False
    return spdx.strip() in PERMISSIVE_SPDX


async def get_task_split(db_pool, task_hash_val: str) -> Optional[str]:
    if not db_pool:
        return None
    try:
        async with db_pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT split FROM ln7_tasks WHERE task_hash = $1 LIMIT 1",
                task_hash_val,
            )
        return row["split"] if row else None
    except Exception as exc:
        logger.warning("LN7 get_task_split: %s", exc)
        return None


async def assert_train_eligible(db_pool, task_hash_val: str) -> bool:
    """Mechanical eval isolation — heldout/eval never enter learning repo."""
    split = await get_task_split(db_pool, task_hash_val)
    if split in ("heldout", "eval"):
        return False
    return True


async def record_outcome(db_pool, row: Dict[str, Any]) -> Optional[int]:
    if not db_pool:
        return None
    patch_body = row.get("patch_text") or row.get("diff") or None
    if isinstance(patch_body, str) and len(patch_body) > 120_000:
        patch_body = patch_body[:120_000]
    args_common = (
        row.get("task_id"),
        row.get("generator") or "ln7",
        row.get("revision_id"),
        row.get("harness_mode"),
        row.get("patch_hash"),
        bool(row.get("passed")),
        row.get("tests_passed"),
        row.get("diff_lines"),
        row.get("tokens"),
        row.get("latency_ms"),
        row.get("cost_usd"),
        row.get("recall_at_k"),
        row.get("exec_node") or "green",
        __import__("json").dumps(row.get("metrics_json") or {}),
    )
    try:
        async with db_pool.acquire() as conn:
            try:
                # QUANTUM-CRYSTAL-ARCH — clean train export needs real diffs (migration 294)
                oid = await conn.fetchval(
                    """
                    INSERT INTO ln7_coding_outcomes (
                        task_id, generator, revision_id, harness_mode, patch_hash,
                        passed, tests_passed, diff_lines, tokens, latency_ms,
                        cost_usd, recall_at_k, exec_node, metrics_json, patch_text
                    ) VALUES (
                        $1, $2, $3, $4, $5,
                        $6, $7, $8, $9, $10,
                        $11, $12, $13, $14::jsonb, $15
                    ) RETURNING id
                    """,
                    *args_common,
                    patch_body,
                )
            except Exception as col_exc:
                if "patch_text" not in str(col_exc):
                    raise
                oid = await conn.fetchval(
                    """
                    INSERT INTO ln7_coding_outcomes (
                        task_id, generator, revision_id, harness_mode, patch_hash,
                        passed, tests_passed, diff_lines, tokens, latency_ms,
                        cost_usd, recall_at_k, exec_node, metrics_json
                    ) VALUES (
                        $1, $2, $3, $4, $5,
                        $6, $7, $8, $9, $10,
                        $11, $12, $13, $14::jsonb
                    ) RETURNING id
                    """,
                    *args_common,
                )
        oid_i = int(oid) if oid is not None else None
        # QUANTUM-CRYSTAL-ARCH — dual-write outcome_envelope (W7 / B1)
        if oid_i is not None:
            try:
                from app.services.ln7_outcome_envelope import (
                    attach_envelope_to_outcome,
                    cross_loop_attribution,
                    write_envelope,
                )

                metrics = dict(row.get("metrics_json") or {})
                if row.get("route_tier") is not None:
                    metrics["route_tier"] = row.get("route_tier")
                if row.get("runner_ups") is not None:
                    metrics["runner_ups"] = row.get("runner_ups")
                # E2: coding_outcome is the genesis envelope for a lineage —
                # every downstream write (shadow_fork, hive_burst,
                # checklist_disagree, canary_eval) joins back to this row via
                # attribution_json, so surface the full key set here.
                attribution = cross_loop_attribution(row)
                env_id = await write_envelope(
                    db_pool,
                    loop_name="ln7",
                    event_kind="coding_outcome",
                    revision_id=row.get("revision_id"),
                    task_hash=row.get("task_hash"),
                    patch_hash=row.get("patch_hash"),
                    domain_tag=row.get("domain_tag"),
                    source_node=row.get("exec_node") or "green",
                    burst_id=row.get("burst_id"),
                    attribution=attribution,
                    metrics=metrics,
                    provenance=row.get("provenance_json") or {},
                    cost_usd=row.get("cost_usd"),
                )
                if env_id:
                    await attach_envelope_to_outcome(db_pool, oid_i, env_id)
            except Exception as _env_exc:
                logger.warning("LN7 envelope dual-write: %s", _env_exc)
        # Continuous gated self-improvement: enqueue green outcomes (train split only)
        if oid_i is not None and bool(row.get("passed")):
            try:
                from app.services.ln7_train_queue import enqueue_outcome
                await enqueue_outcome(db_pool, oid_i, trigger_source="outcome")
            except Exception as _eq:
                logger.debug("LN7 train enqueue: %s", _eq)
            # G4: wire accepted outcome -> ln7_learning_artifacts feedback loop.
            # promote_learning_artifact() re-checks split (heldout/eval excluded)
            # and license (permissive-only) internally, so this is safe to fire
            # unconditionally for every passed outcome.
            try:
                await _auto_promote_learning_artifact(db_pool, oid_i, row, patch_body)
            except Exception as _pl:
                logger.warning("LN7 auto-promote failed for outcome %s: %s", oid_i, _pl)
        return oid_i
    except Exception as exc:
        logger.warning("LN7 record_outcome: %s", exc)
        return None


async def _auto_promote_learning_artifact(
    db_pool, outcome_id: int, row: Dict[str, Any], patch_body: Optional[str]
) -> bool:
    """Look up the task's hash/license and promote a passed outcome automatically.

    This is the G4 fix: previously promote_learning_artifact() existed but was
    never called from record_outcome(), so ln7_learning_artifacts stayed empty
    even though passed outcomes were accumulating.

    Private-pack bakeoff outcomes (run_private_pack_bakeoff) always pass
    task_id=None by design — the pack identity lives in metrics_json.pack
    instead. Resolve the task row by pack_name in that case so those outcomes
    (the vast majority of LN7's passed outcomes) aren't silently skipped.
    """
    if not patch_body:
        return False
    task_id = row.get("task_id")
    metrics = row.get("metrics_json") or {}
    pack_name = metrics.get("pack") if isinstance(metrics, dict) else None
    async with db_pool.acquire() as conn:
        if task_id:
            task_row = await conn.fetchrow(
                "SELECT task_hash, spdx_license, pack_name, source FROM ln7_tasks WHERE task_id = $1",
                task_id,
            )
        elif pack_name:
            task_row = await conn.fetchrow(
                "SELECT task_hash, spdx_license, pack_name, source FROM ln7_tasks "
                "WHERE pack_name = $1 ORDER BY created_at DESC LIMIT 1",
                pack_name,
            )
        else:
            task_row = None
    if not task_row:
        return False
    th = task_row["task_hash"]
    spdx = task_row["spdx_license"]
    if not th:
        return False
    pack_or_src = task_row["pack_name"] or task_row["source"] or "unknown"
    summary = (
        f"{row.get('generator') or 'ln7'} passed {pack_or_src} "
        f"(harness={row.get('harness_mode') or 'max'}, revision={row.get('revision_id') or 'n/a'})"
    )
    return await promote_learning_artifact(
        db_pool,
        outcome_id=outcome_id,
        path_or_r2_key=f"ln7_coding_outcomes/{outcome_id}",
        summary=summary,
        task_hash_val=th,
        spdx_license=spdx,
    )


async def promote_learning_artifact(
    db_pool,
    *,
    outcome_id: int,
    path_or_r2_key: str,
    summary: str,
    task_hash_val: str,
    spdx_license: Optional[str],
    crystal_id: Optional[str] = None,
) -> bool:
    if not await assert_train_eligible(db_pool, task_hash_val):
        logger.info("LN7 learning reject: task_hash in heldout/eval")
        return False
    if not license_allowed_for_training(spdx_license):
        logger.info("LN7 learning reject: non-permissive license %s", spdx_license)
        return False
    try:
        async with db_pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO ln7_learning_artifacts (
                    outcome_id, path_or_r2_key, summary, crystal_id, spdx_license, task_hash
                ) VALUES ($1, $2, $3, $4, $5, $6)
                """,
                outcome_id,
                path_or_r2_key,
                summary,
                crystal_id,
                spdx_license,
                task_hash_val,
            )
        return True
    except Exception as exc:
        logger.warning("LN7 promote_learning: %s", exc)
        return False


async def record_usage_event(db_pool, event_type: str, **kwargs) -> bool:
    if event_type not in ("accepted", "rejected", "edited_after_apply"):
        return False
    if not db_pool:
        return False
    try:
        import json
        async with db_pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO ln7_usage_event (
                    event_type, patch_hash, content_hash, revision_id,
                    workspace_hint, metadata_json
                ) VALUES ($1, $2, $3, $4, $5, $6::jsonb)
                """,
                event_type,
                kwargs.get("patch_hash"),
                kwargs.get("content_hash"),
                kwargs.get("revision_id"),
                kwargs.get("workspace_hint"),
                json.dumps(kwargs.get("metadata_json") or {}),
            )
        try:
            from app.services.ln7_train_queue import enqueue_usage_preference
            await enqueue_usage_preference(
                db_pool,
                event_type=event_type,
                revision_id=kwargs.get("revision_id"),
                patch_hash=kwargs.get("patch_hash"),
            )
        except Exception as _eq:
            logger.debug("LN7 pref enqueue: %s", _eq)
        return True
    except Exception as exc:
        logger.warning("LN7 usage_event: %s", exc)
        return False


async def leaderboard(db_pool, *, days: int = 30) -> List[Dict[str, Any]]:
    if not db_pool:
        return []
    try:
        async with db_pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT generator,
                       COUNT(*) AS n,
                       AVG(CASE WHEN passed THEN 1.0 ELSE 0.0 END) AS pass_rate,
                       AVG(latency_ms) AS avg_latency_ms,
                       AVG(COALESCE(cost_usd, 0)) AS avg_cost_usd,
                       AVG(COALESCE(recall_at_k, 0)) AS avg_recall
                FROM ln7_coding_outcomes
                WHERE created_at > NOW() - ($1::int * INTERVAL '1 day')
                GROUP BY generator
                ORDER BY pass_rate DESC NULLS LAST, n DESC
                """,
                days,
            )
        return [dict(r) for r in rows]
    except Exception as exc:
        logger.warning("LN7 leaderboard: %s", exc)
        return []
