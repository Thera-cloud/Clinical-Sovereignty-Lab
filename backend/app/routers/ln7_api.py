"""Little Nate 7 admin API — bakeoff, leaderboard, revision, scorecard, usage events.

# QUANTUM-CRYSTAL-ARCH
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request

logger = logging.getLogger("ln7_api")

router = APIRouter(prefix="/api/ln7", tags=["ln7"])

# Single-flight bakeoff tasks: revision_id -> asyncio.Task (ORANGE PEFT = one adapter).
_BAKEOFF_TASKS: Dict[str, asyncio.Task] = {}


def _pool(request: Request):
    return getattr(request.app.state, "db_pool", None)


def _bakeoff_running_ids() -> list:
    dead = [k for k, t in _BAKEOFF_TASKS.items() if t.done()]
    for k in dead:
        _BAKEOFF_TASKS.pop(k, None)
    return list(_BAKEOFF_TASKS.keys())


def _bakeoff_recommend_refire(
    *,
    in_flight: bool,
    n: int,
    expected_packs: int,
    outcomes_age_s: Optional[int],
    stale_outcomes_s: int,
) -> bool:
    """True when memory empty, packs incomplete, and outcomes idle (or never started)."""
    if in_flight or n >= expected_packs:
        return False
    if outcomes_age_s is None:
        return True
    return outcomes_age_s >= stale_outcomes_s


try:
    from app.services.api_server import require_admin
except Exception:
    async def require_admin():  # type: ignore
        return {"role": "ADMIN"}


@router.get("/health")
async def ln7_health():
    try:
        import os
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
            "coder_fast": coder_model("fast"),
            "ln7_inference_url": bool(os.getenv("LN7_INFERENCE_URL") or os.getenv("SOVEREIGN_INFERENCE_URL")),
            "home_gpu_configured": bool(os.getenv("HOME_GPU_URL")),
            "shadow_spend": os.getenv("LN7_SHADOW_SPEND", "").strip().lower() in ("1", "true", "yes"),
            "public_harness_mode": (os.getenv("LN7_PUBLIC_HARNESS_MODE") or "smoke").strip().lower(),
            "non_clinical_claim": True,
        }
    except Exception as exc:
        return {"status": "degraded", "error": str(exc)[:200]}


@router.get("/revision")
async def get_revision(request: Request, _admin=Depends(require_admin)):
    from app.services.little_nate_7 import load_active_revision

    deep = await load_active_revision(_pool(request), tier="deep")
    fast = await load_active_revision(_pool(request), tier="fast")
    return {
        "status": "ok",
        "active": deep or {"revision_id": "LN7-baseline", "active": True, "tier": "deep"},
        "active_deep": deep or {"revision_id": "LN7-baseline", "active": True, "tier": "deep"},
        "active_fast": fast or {
            "revision_id": "LN7-fast-baseline",
            "active": False,
            "tier": "fast",
            "hint": "register+activate LN7-fast-baseline for PEFT fast path",
        },
    }


@router.get("/leaderboard")
async def get_leaderboard(request: Request, days: int = 30, _admin=Depends(require_admin)):
    from app.services.ln7_ledger import leaderboard
    rows = await leaderboard(_pool(request), days=max(1, min(365, days)))
    return {"status": "ok", "days": days, "rows": rows, "non_clinical_claim": True}


@router.get("/bakeoff/running")
async def get_bakeoff_running(_admin=Depends(require_admin)):
    """In-flight background bakeoffs (single-flight guard visibility)."""
    return {"status": "ok", "running": _bakeoff_running_ids(), "non_clinical_claim": True}


@router.get("/bakeoff/sweep-status")
async def get_bakeoff_sweep_status(
    request: Request,
    revision_id: str = Query(..., description="LN7 revision to inspect"),
    since: Optional[str] = Query(None, description="ISO; count outcomes after this"),
    expected_packs: int = Query(18, ge=1, le=64),
    stale_outcomes_s: int = Query(600, ge=60, le=86400),
    _admin=Depends(require_admin),
):
    """Age of last ln7_coding_outcomes row + whether re-fire is recommended.

    Survives backend restart clearing in-memory _BAKEOFF_TASKS while client still polls.
    """
    from datetime import datetime, timezone

    pool = _pool(request)
    if not pool:
        raise HTTPException(503, "db unavailable")
    since_dt = None
    if since:
        try:
            since_dt = datetime.fromisoformat(since.replace("Z", "+00:00"))
        except ValueError:
            raise HTTPException(422, "since must be an ISO-8601 timestamp")
    running = _bakeoff_running_ids()
    try:
        async with pool.acquire() as conn:
            if since_dt is not None:
                row = await conn.fetchrow(
                    """
                    SELECT COUNT(*)::int AS n,
                           MAX(created_at) AS last_at
                    FROM ln7_coding_outcomes
                    WHERE revision_id = $1
                      AND generator = 'ln7'
                      AND created_at > $2::timestamptz
                    """,
                    revision_id,
                    since_dt,
                )
            else:
                row = await conn.fetchrow(
                    """
                    SELECT COUNT(*)::int AS n,
                           MAX(created_at) AS last_at
                    FROM ln7_coding_outcomes
                    WHERE revision_id = $1
                      AND generator = 'ln7'
                    """,
                    revision_id,
                )
    except Exception as exc:
        logger.warning("bakeoff sweep-status: %s", exc)
        raise HTTPException(500, str(exc)[:200])

    n = int((row and row["n"]) or 0)
    last_at = row["last_at"] if row else None
    age_s = None
    if last_at is not None:
        if last_at.tzinfo is None:
            last_at = last_at.replace(tzinfo=timezone.utc)
        age_s = max(0, int((datetime.now(timezone.utc) - last_at).total_seconds()))
    # Any in-memory bakeoff blocks re-fire (single-flight PEFT)
    in_flight = bool(running)
    recommend_refire = _bakeoff_recommend_refire(
        in_flight=in_flight,
        n=n,
        expected_packs=expected_packs,
        outcomes_age_s=age_s,
        stale_outcomes_s=stale_outcomes_s,
    )
    return {
        "status": "ok",
        "revision_id": revision_id,
        "running": running,
        "in_flight": in_flight,
        "n": n,
        "expected_packs": expected_packs,
        "last_outcome_at": last_at.isoformat() if last_at else None,
        "outcomes_age_s": age_s,
        "stale_outcomes_s": stale_outcomes_s,
        "since": since,
        "recommend_refire": recommend_refire,
        "non_clinical_claim": True,
    }


@router.post("/bakeoff/sweep")
async def post_bakeoff_sweep(
    request: Request,
    body: Optional[Dict[str, Any]] = None,
    _admin=Depends(require_admin),
):
    """Optional re-fire when running empty and n << expected (wedged / restart wipe)."""
    body = body or {}
    rid = str(body.get("revision_id") or "").strip()
    if not rid:
        raise HTTPException(422, "revision_id required")
    expected = int(body.get("expected_packs") or 18)
    stale_s = int(body.get("stale_outcomes_s") or 600)
    since = body.get("since")
    do_refire = bool(body.get("refire", True))

    status = await get_bakeoff_sweep_status(
        request,
        revision_id=rid,
        since=str(since) if since else None,
        expected_packs=max(1, min(64, expected)),
        stale_outcomes_s=max(60, min(86400, stale_s)),
        _admin=_admin,
    )
    if not do_refire or not status.get("recommend_refire"):
        return {**status, "refired": False}

    started = await post_bakeoff(
        request,
        body={
            "revision_id": rid,
            "background": True,
            "mode": body.get("mode") or "max",
            "include_public": bool(body.get("include_public", True)),
            "include_private": bool(body.get("include_private", True)),
            "seed_golden": bool(body.get("seed_golden", False)),
        },
        _admin=_admin,
    )
    return {**status, "refired": True, "bakeoff": started}


@router.post("/bakeoff")
async def post_bakeoff(request: Request, body: Optional[Dict[str, Any]] = None, _admin=Depends(require_admin)):
    from app.services.ln7_bakeoff_engine import run_full_scorecard
    body = body or {}
    rid = str(body.get("revision_id") or "LN7-baseline")
    background = bool(body.get("background", False))
    mode = str(body.get("mode") or "max")
    include_public = bool(body.get("include_public", True))
    include_private = bool(body.get("include_private", True))
    seed_golden = bool(body.get("seed_golden", False))
    pool = _pool(request)

    # QUANTUM-CRYSTAL-ARCH — single-flight: PEFT serve holds one adapter
    running = _bakeoff_running_ids()
    if running:
        raise HTTPException(
            409,
            f"bakeoff already running for {running[0]}; wait or GET /api/ln7/bakeoff/running",
        )

    async def _run_and_notify():
        result = await run_full_scorecard(
            pool,
            revision_id=rid,
            mode=mode,
            include_public=include_public,
            include_private=include_private,
            seed_golden=seed_golden,
        )
        notify_out = None
        if result.get("ok") and rid and rid != "LN7-baseline":
            try:
                from app.services.ln7_revision import notify_revision_candidate
                from app.services.ln7_revision_readiness import assess_revision_readiness

                ready = await assess_revision_readiness(pool, rid)
                if ready.get("ready"):
                    notify_out = await notify_revision_candidate(
                        pool, rid, force_ready=True
                    )
            except Exception as exc:
                notify_out = {"status": "error", "error": str(exc)[:120]}
        return {**result, "ceo_notify": notify_out}

    if background:
        task = asyncio.create_task(_run_and_notify())
        _BAKEOFF_TASKS[rid] = task

        def _clear(_t: asyncio.Task, _rid: str = rid) -> None:
            _BAKEOFF_TASKS.pop(_rid, None)

        task.add_done_callback(_clear)
        return {
            "status": "ok",
            "ok": True,
            "started": True,
            "background": True,
            "revision_id": rid,
            "non_clinical_claim": True,
        }

    result = await _run_and_notify()
    return {
        "status": "ok" if result.get("ok") else "error",
        **result,
    }


@router.post("/public-benches")
async def post_public_benches(
    request: Request,
    body: Optional[Dict[str, Any]] = None,
    _admin=Depends(require_admin),
):
    """Run smoke/ingest/full public benches (report-only). Prefer ORANGE/BLUE for full."""
    import os
    body = body or {}
    if body.get("mode"):
        os.environ["LN7_PUBLIC_HARNESS_MODE"] = str(body["mode"])
    from app.services.ln7_bakeoff_engine import run_public_benchmarks
    rid = str(body.get("revision_id") or "LN7-baseline").strip() or "LN7-baseline"
    rows = await run_public_benchmarks(revision_id=rid, db_pool=_pool(request))
    return {
        "status": "ok",
        "public": rows,
        "report_only": True,
        "non_clinical_claim": True,
    }


@router.post("/train/export")
async def post_train_export(
    request: Request,
    body: Optional[Dict[str, Any]] = None,
    _admin=Depends(require_admin),
):
    """Export rejection samples (train split only) for offline QLoRA on BLUE."""
    from app.services.ln7_revision import collect_rejection_samples
    body = body or {}
    limit = max(1, min(2000, int(body.get("limit") or 500)))
    rows = await collect_rejection_samples(_pool(request), limit=limit)
    # Strip heldout pack markers
    filtered = []
    for r in rows:
        meta = r.get("metrics_json") or {}
        if isinstance(meta, str):
            import json as _json
            try:
                meta = _json.loads(meta)
            except Exception:
                meta = {}
        if (meta or {}).get("pack") == "env_redis_prefix":
            continue
        filtered.append({
            "outcome_id": str(r.get("id")),
            "task_id": r.get("task_id"),
            "patch_hash": r.get("patch_hash"),
            "revision_id": r.get("revision_id"),
            "harness_mode": r.get("harness_mode"),
        })
    return {
        "status": "ok",
        "n": len(filtered),
        "samples": filtered,
        "hint": "Write JSONL on BLUE via backend/scripts/ln7_export_train_jsonl.py then ln7_qlora_train.py",
        "non_clinical_claim": True,
    }


@router.post("/revision/shadow")
async def post_revision_shadow(
    request: Request,
    body: Optional[Dict[str, Any]] = None,
    _admin=Depends(require_admin),
):
    from app.services.ln7_revision import set_shadow
    body = body or {}
    rid = str(body.get("revision_id") or "").strip()
    if not rid:
        raise HTTPException(422, "revision_id required")
    ok = await set_shadow(_pool(request), rid)
    return {"status": "ok" if ok else "error", "revision_id": rid, "status_field": "shadow"}


@router.get("/scorecard/{revision_id}")
async def get_scorecard(
    revision_id: str,
    request: Request,
    since: Optional[str] = Query(None, description="ISO timestamp; only outcomes created_at > since"),
    _admin=Depends(require_admin),
):
    # Return last private LN7 outcomes summary; re-running full bakeoff is POST
    pool = _pool(request)
    if not pool:
        raise HTTPException(503, "db unavailable")
    since_dt = None
    if since:
        try:
            from datetime import datetime as _dt

            since_dt = _dt.fromisoformat(since.replace("Z", "+00:00"))
        except ValueError:
            raise HTTPException(422, "since must be an ISO-8601 timestamp")
    try:
        async with pool.acquire() as conn:
            if since_dt is not None:
                rows = await conn.fetch(
                    """
                    SELECT passed, latency_ms, cost_usd, harness_mode, created_at
                    FROM ln7_coding_outcomes
                    WHERE revision_id = $1
                      AND generator = 'ln7'
                      AND created_at > $2::timestamptz
                    ORDER BY created_at DESC
                    LIMIT 500
                    """,
                    revision_id,
                    since_dt,
                )
            else:
                rows = await conn.fetch(
                    """
                    SELECT passed, latency_ms, cost_usd, harness_mode, created_at
                    FROM ln7_coding_outcomes
                    WHERE revision_id = $1
                      AND generator = 'ln7'
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
            "since": since,
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
        result["ceo_notify"] = await notify_revision_candidate(
            _pool(request), result["revision_id"]
        )
    return result


@router.get("/revision/{revision_id}/readiness")
async def get_revision_readiness(
    revision_id: str,
    request: Request,
    _admin=Depends(require_admin),
):
    """Admin/debug readiness snapshot used by Dual-COO CEO LN7 briefs."""
    from app.services.ln7_revision_readiness import assess_revision_readiness

    rid = (revision_id or "").strip()
    if not rid:
        raise HTTPException(422, "revision_id required")
    readiness = await assess_revision_readiness(_pool(request), rid)
    return {"status": "ok", "readiness": readiness, "non_clinical_claim": True}


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


@router.get("/train/jobs")
async def get_train_jobs(request: Request, limit: int = 50, _admin=Depends(require_admin)):
    from app.services.ln7_train_queue import list_jobs, continuous_enabled
    return {
        "status": "ok",
        "continuous": continuous_enabled(),
        "jobs": await list_jobs(_pool(request), limit=limit),
        "non_clinical_claim": True,
    }


@router.post("/train/enqueue")
async def post_train_enqueue(
    request: Request,
    body: Optional[Dict[str, Any]] = None,
    _admin=Depends(require_admin),
):
    from app.services.ln7_train_queue import enqueue_outcome, continuous_enabled
    body = body or {}
    if not continuous_enabled():
        raise HTTPException(400, "ENABLE_LN7_CONTINUOUS is off")
    oid = body.get("outcome_id")
    if oid is None:
        raise HTTPException(422, "outcome_id required")
    job_id = await enqueue_outcome(
        _pool(request), int(oid), trigger_source=str(body.get("trigger_source") or "manual"),
    )
    return {"status": "ok" if job_id else "error", "job_id": job_id}


@router.post("/canary/evaluate")
async def post_canary_evaluate(
    request: Request,
    body: Optional[Dict[str, Any]] = None,
    _admin=Depends(require_admin),
):
    from app.services.ln7_canary_promoter import evaluate_canary, start_canary
    body = body or {}
    rid = str(body.get("revision_id") or "").strip()
    if not rid:
        raise HTTPException(422, "revision_id required")
    if body.get("start"):
        # QUANTUM-CRYSTAL-ARCH — fast candidates default incumbent LN7-fast-baseline
        raw_inc = body.get("incumbent_id")
        await start_canary(
            _pool(request),
            rid,
            incumbent_id=str(raw_inc).strip() if raw_inc else None,
        )
    result = await evaluate_canary(_pool(request), rid)
    # QUANTUM-CRYSTAL-ARCH — READY renotify when gate awaits CEO
    if result.get("action") == "await_ceo" and result.get("ok"):
        try:
            from app.services.ln7_revision import notify_revision_candidate

            result["ceo_notify"] = await notify_revision_candidate(
                _pool(request), rid, force_ready=True
            )
        except Exception as exc:
            result["ceo_notify"] = {"status": "error", "error": str(exc)[:120]}
    return result


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
