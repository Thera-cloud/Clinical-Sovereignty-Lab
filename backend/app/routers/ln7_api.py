"""Little Nate 7 admin API — bakeoff, leaderboard, revision, scorecard, usage events.

# QUANTUM-CRYSTAL-ARCH
"""
from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Request

logger = logging.getLogger("ln7_api")

router = APIRouter(prefix="/api/ln7", tags=["ln7"])


def _pool(request: Request):
    return getattr(request.app.state, "db_pool", None)


try:
    from app.services.api_server import require_admin
except Exception:
    async def require_admin():  # type: ignore
        return {"role": "ADMIN"}


@router.get("/health")
async def ln7_health():
    try:
        from app.services.little_nate_7 import (
            PRODUCT_NAME,
            PRODUCT_MAJOR,
            bakeoff_enabled,
            coder_model,
            harness_enabled,
            ln7_enabled,
        )
        return {
            "status": "ok",
            "product": PRODUCT_NAME,
            "major": PRODUCT_MAJOR,
            "enabled": ln7_enabled(),
            "harness": harness_enabled(),
            "bakeoff": bakeoff_enabled(),
            "coder_deep": coder_model("deep"),
            "non_clinical_claim": True,
        }
    except Exception as exc:
        return {"status": "degraded", "error": str(exc)[:200]}


@router.get("/revision")
async def get_revision(request: Request, _admin=Depends(require_admin)):
    from app.services.little_nate_7 import load_active_revision
    rev = await load_active_revision(_pool(request))
    return {"status": "ok", "active": rev or {"revision_id": "LN7-baseline", "active": True}}


@router.get("/leaderboard")
async def get_leaderboard(request: Request, days: int = 30, _admin=Depends(require_admin)):
    from app.services.ln7_ledger import leaderboard
    rows = await leaderboard(_pool(request), days=max(1, min(365, days)))
    return {"status": "ok", "days": days, "rows": rows, "non_clinical_claim": True}


@router.post("/bakeoff")
async def post_bakeoff(request: Request, body: Optional[Dict[str, Any]] = None, _admin=Depends(require_admin)):
    from app.services.ln7_bakeoff_engine import run_full_scorecard
    body = body or {}
    result = await run_full_scorecard(
        _pool(request),
        revision_id=str(body.get("revision_id") or "LN7-baseline"),
        mode=str(body.get("mode") or "max"),
    )
    return {"status": "ok" if result.get("ok") else "error", **result}


@router.get("/scorecard/{revision_id}")
async def get_scorecard(revision_id: str, request: Request, _admin=Depends(require_admin)):
    from app.services.ln7_bakeoff_engine import run_full_scorecard
    # Return last private outcomes summary; re-running full bakeoff is POST
    pool = _pool(request)
    if not pool:
        raise HTTPException(503, "db unavailable")
    try:
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT passed, latency_ms, cost_usd, harness_mode, created_at
                FROM ln7_coding_outcomes
                WHERE revision_id = $1
                ORDER BY created_at DESC
                LIMIT 200
                """,
                revision_id,
            )
        passes = [bool(r["passed"]) for r in rows]
        from app.services.ln7_bakeoff_engine import bootstrap_ci
        return {
            "status": "ok",
            "revision_id": revision_id,
            "pass_rate": bootstrap_ci(passes),
            "n": len(rows),
            "non_clinical_claim": True,
            "public_report_only": True,
        }
    except Exception as exc:
        logger.warning("scorecard: %s", exc)
        raise HTTPException(500, str(exc)[:200])


@router.post("/revision/register")
async def post_register_revision(
    request: Request,
    body: Optional[Dict[str, Any]] = None,
    _admin=Depends(require_admin),
):
    from app.services.ln7_revision import register_revision, notify_revision_candidate
    body = body or {}
    result = await register_revision(
        _pool(request),
        revision_id=body.get("revision_id"),
        base_checkpoint=body.get("base_checkpoint"),
        quantization=body.get("quantization"),
        harness_config=body.get("harness_config"),
        notes=str(body.get("notes") or ""),
        status=str(body.get("status") or "draft"),
        scorecard=body.get("scorecard"),
    )
    if result.get("ok") and body.get("notify_ceo"):
        await notify_revision_candidate(result["revision_id"])
    return result


@router.post("/revision/activate")
async def post_activate(
    request: Request,
    body: Optional[Dict[str, Any]] = None,
    _admin=Depends(require_admin),
):
    from app.services.ln7_revision import activate_revision
    body = body or {}
    rid = str(body.get("revision_id") or "").strip()
    if not rid:
        raise HTTPException(422, "revision_id required")
    return await activate_revision(
        _pool(request),
        rid,
        promoted_by=str(body.get("promoted_by") or "ceo"),
        ceo_decision_id=body.get("ceo_decision_id"),
    )


@router.post("/usage-event")
async def post_usage_event(
    request: Request,
    body: Optional[Dict[str, Any]] = None,
    _admin=Depends(require_admin),
):
    from app.services.ln7_ledger import record_usage_event
    body = body or {}
    ok = await record_usage_event(
        _pool(request),
        str(body.get("event_type") or ""),
        patch_hash=body.get("patch_hash"),
        content_hash=body.get("content_hash"),
        revision_id=body.get("revision_id"),
        workspace_hint=body.get("workspace_hint"),
        metadata_json=body.get("metadata_json"),
    )
    return {"status": "ok" if ok else "error"}


@router.get("/contestants")
async def get_contestants(request: Request, _admin=Depends(require_admin)):
    from app.services.ln7_bakeoff_engine import list_contestants, sync_contestant_credentials
    sync = await sync_contestant_credentials(_pool(request))
    return {
        "status": "ok",
        "contestants": await list_contestants(_pool(request)),
        "credential_sync": sync,
    }


@router.post("/tasks/seed-packs")
async def post_seed_packs(request: Request, _admin=Depends(require_admin)):
    """Idempotent seed of the 3 first-party CI packs into ln7_tasks."""
    import hashlib
    pool = _pool(request)
    if not pool:
        raise HTTPException(503, "db unavailable")
    packs = (
        ("pack:asyncpg_cast", "asyncpg_cast", "train", "easy",
         "Fix asyncpg polymorphic cast failures. Return a unified diff."),
        ("pack:catch_all_routes", "catch_all_routes", "train", "medium",
         "Fix FastAPI catch-all route ordering. Return a unified diff."),
        ("pack:env_redis_prefix", "env_redis_prefix", "heldout", "medium",
         "Fix ENVIRONMENT Redis key prefix mismatch. Return a unified diff."),
    )
    try:
        async with pool.acquire() as conn:
            for tid, pack, split, diff, prompt in packs:
                th = hashlib.sha256(f"{tid}:v1".encode()).hexdigest()
                await conn.execute(
                    """
                    INSERT INTO ln7_tasks
                        (task_id, source, difficulty, task_hash, split,
                         pack_name, prompt_summary, metadata_json)
                    VALUES ($1, 'authored', $2, $3, $4, $5, $6, $7::jsonb)
                    ON CONFLICT (task_id) DO NOTHING
                    """,
                    tid, diff, th, split, pack, prompt,
                    f'{{"pack":"{pack}"}}',
                )
            n = await conn.fetchval("SELECT COUNT(*) FROM ln7_tasks")
        return {"status": "ok", "task_count": int(n or 0)}
    except Exception as exc:
        logger.warning("seed packs: %s", exc)
        raise HTTPException(500, str(exc)[:200])
