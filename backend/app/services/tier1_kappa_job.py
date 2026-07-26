"""
In-process async κ compute jobs for Principal-Review.

Live LLM judge over 50 gold items is slow; API returns job_id immediately
and UI/CLI poll GET /gold/kappa/jobs/{id}. Durable CLI remains
compute_tier1_gold_kappa.py for ops that outlive process restarts.
"""

from __future__ import annotations

import asyncio
import logging
import secrets
import threading
import time
from datetime import datetime, timezone
from typing import Any, Dict, Optional

logger = logging.getLogger("nate.tier1_kappa_job")

_JOBS: Dict[str, Dict[str, Any]] = {}
# threading.Lock — safe at import on Python 3.9 (asyncio.Lock needs a running loop).
_LOCK = threading.Lock()
_ACTIVE_JOB_ID: Optional[str] = None


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def get_job(job_id: str) -> Optional[Dict[str, Any]]:
    j = _JOBS.get(job_id)
    return dict(j) if j else None


def latest_job() -> Optional[Dict[str, Any]]:
    if not _JOBS:
        return None
    jid = max(_JOBS.keys(), key=lambda k: _JOBS[k].get("created_ts", 0))
    return dict(_JOBS[jid])


async def start_kappa_job(
    *,
    pool,
    app_state,
    min_items: int = 50,
    judge_id: str = "grok-judge-v3",
    limit: int = 0,
) -> Dict[str, Any]:
    """Enqueue one background κ compute. Rejects if another job is running."""
    global _ACTIVE_JOB_ID
    with _LOCK:
        if _ACTIVE_JOB_ID and _JOBS.get(_ACTIVE_JOB_ID, {}).get("status") == "running":
            cur = _JOBS[_ACTIVE_JOB_ID]
            return {
                "status": "busy",
                "job_id": _ACTIVE_JOB_ID,
                "job": dict(cur),
            }
        job_id = (
            f"kappa_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}_"
            f"{secrets.token_hex(3)}"
        )
        job = {
            "job_id": job_id,
            "status": "queued",
            "judge_id": (judge_id or "grok-judge-v3")[:80],
            "min_items": int(min_items),
            "limit": int(limit or 0),
            "total": 0,
            "done": 0,
            "current_scenario_id": None,
            "evidence_id": None,
            "aggregate_kappa": None,
            "safety_veto_ok": None,
            "error": None,
            "created_at": _now_iso(),
            "created_ts": time.time(),
            "updated_at": _now_iso(),
            "finished_at": None,
        }
        _JOBS[job_id] = job
        _ACTIVE_JOB_ID = job_id
    asyncio.create_task(
        _run_kappa_job(job_id, pool, app_state, min_items, judge_id, limit),
        name=f"tier1_kappa_{job_id}",
    )
    return {"status": "queued", "job_id": job_id, "job": dict(job)}


async def _run_kappa_job(
    job_id: str,
    pool,
    app_state,
    min_items: int,
    judge_id: str,
    limit: int,
) -> None:
    global _ACTIVE_JOB_ID
    from app.services.six_quotient_auto_judge import _llm_judge
    from app.services.tier1_gold_evidence import (
        KAPPA_METHOD,
        compute_safety_veto,
        load_scored_gold,
        mean_per_dimension_kappa,
        persist_kappa_evidence,
    )

    job = _JOBS.get(job_id)
    if not job:
        return
    job["status"] = "running"
    job["updated_at"] = _now_iso()
    try:
        async with pool.acquire() as conn:
            items = await load_scored_gold(conn, min_items=max(1, min_items))
            if limit and limit > 0:
                items = items[:limit]
            job["total"] = len(items)
            job["updated_at"] = _now_iso()
            judge_by: Dict[str, Dict[str, int]] = {}
            for g in items:
                sid = g["scenario_id"]
                job["current_scenario_id"] = sid
                job["updated_at"] = _now_iso()
                judged = await _llm_judge(
                    app_state,
                    scenario_id=sid,
                    section=str(g.get("section") or ""),
                    rubric_focus=str(g.get("response_class") or ""),
                    client_says=str(g.get("client_says") or ""),
                    response=str(g.get("nate_response") or ""),
                    degraded_distractor=bool(g.get("is_degraded_distractor")),
                )
                if not judged:
                    raise RuntimeError(f"judge failed for {sid}")
                judge_by[sid] = {
                    "primary": judged["primary"],
                    "accuracy": judged["accuracy"],
                    "naturalness": judged["naturalness"],
                }
                job["done"] = len(judge_by)
                job["updated_at"] = _now_iso()

            paired_g, paired_j, used = [], [], []
            for g in items:
                sid = g["scenario_id"]
                j = judge_by[sid]
                paired_g.append(
                    {
                        "primary": int(g["primary_score"]),
                        "accuracy": int(g["accuracy_score"]),
                        "naturalness": int(g["naturalness_score"]),
                    }
                )
                paired_j.append(j)
                used.append(sid)
            if len(used) < min_items:
                raise RuntimeError(f"paired {len(used)} < min_items {min_items}")
            agg, per = mean_per_dimension_kappa(paired_g, paired_j)
            ok, miss_n, miss_ids = compute_safety_veto(items, judge_by)
            eid = await persist_kappa_evidence(
                conn,
                judge_id=(judge_id or "grok-judge-v3")[:80],
                aggregate_kappa=agg,
                per_dimension=per,
                n_items=len(used),
                safety_veto_ok=ok,
                safety_miss_count=miss_n,
                notes=f"async compute job {job_id}; misses={miss_ids}",
            )
        job["status"] = "done"
        job["evidence_id"] = eid
        job["aggregate_kappa"] = agg
        job["per_dimension"] = per
        job["safety_veto_ok"] = ok
        job["safety_miss_count"] = miss_n
        job["safety_miss_ids"] = miss_ids
        job["kappa_method"] = KAPPA_METHOD
        job["n_items"] = len(used)
        job["current_scenario_id"] = None
        job["finished_at"] = _now_iso()
        job["updated_at"] = _now_iso()
        logger.info(
            "tier1 kappa job %s done κ=%s n=%s safety_ok=%s",
            job_id,
            agg,
            len(used),
            ok,
        )
    except Exception as e:
        logger.warning("tier1 kappa job %s failed: %s", job_id, e)
        job["status"] = "failed"
        job["error"] = str(e)[:2000]
        job["finished_at"] = _now_iso()
        job["updated_at"] = _now_iso()
    finally:
        with _LOCK:
            if _ACTIVE_JOB_ID == job_id:
                _ACTIVE_JOB_ID = None
