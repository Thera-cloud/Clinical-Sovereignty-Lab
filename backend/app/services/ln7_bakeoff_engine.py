"""LN7 bakeoff engine — identical harness for LN7 vs contestants; public + private scores.

Public benchmarks are report-only; private held-out is the promotion gate.
# QUANTUM-CRYSTAL-ARCH
"""
from __future__ import annotations

import logging
import math
import os
import random
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("ln7_bakeoff")

PUBLIC_BENCHMARKS = (
    "swe_bench_verified",
    "livecodebench",
    "aider_polyglot",
    "terminal_bench",
)


def bakeoff_enabled() -> bool:
    return os.getenv("ENABLE_LN7_BAKEOFF", "true").strip().lower() in ("1", "true", "yes", "on")


def bootstrap_ci(passes: List[bool], *, n_boot: int = 1000, seed: int = 42) -> Dict[str, float]:
    """Bootstrap 95% CI on pass rate."""
    if not passes:
        return {"mean": 0.0, "lo": 0.0, "hi": 0.0, "n": 0}
    rng = random.Random(seed)
    n = len(passes)
    point = sum(1 for p in passes if p) / n
    samples = []
    for _ in range(n_boot):
        draw = [passes[rng.randrange(n)] for _ in range(n)]
        samples.append(sum(1 for p in draw if p) / n)
    samples.sort()
    lo = samples[int(0.025 * n_boot)]
    hi = samples[min(n_boot - 1, int(0.975 * n_boot))]
    return {"mean": point, "lo": lo, "hi": hi, "n": n}


def beats_incumbent(candidate_ci: Dict[str, float], incumbent_point: float) -> bool:
    """Activate only if candidate CI lower bound exceeds incumbent point estimate."""
    return float(candidate_ci.get("lo") or 0) > float(incumbent_point or 0)


async def list_contestants(db_pool) -> List[Dict[str, Any]]:
    if not db_pool:
        return []
    try:
        async with db_pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT contestant_id, display_name, provider, base_url, model_id,
                       version_captured_at, enabled
                FROM ln7_contestants
                ORDER BY contestant_id
                """
            )
        return [dict(r) for r in rows]
    except Exception as exc:
        logger.warning("LN7 list_contestants: %s", exc)
        return []


async def run_private_pack_bakeoff(
    db_pool,
    *,
    revision_id: str = "LN7-baseline",
    pack_names: Optional[List[str]] = None,
    mode: str = "max",
) -> Dict[str, Any]:
    """Run LN7 harness on CI packs (private / first-party). Contestants optional later."""
    if not bakeoff_enabled():
        return {"ok": False, "error": "bakeoff_disabled"}

    try:
        from app.services.ln_sandbox_engineering_ci import list_pack_names
        from app.websocket.ln7_harness import run_task
        from app.services.ln7_ledger import record_outcome, task_hash
    except Exception as exc:
        return {"ok": False, "error": f"import:{exc}"}

    packs = pack_names or list_pack_names()
    if not packs:
        return {"ok": False, "error": "no_packs"}

    passes: List[bool] = []
    rows: List[Dict[str, Any]] = []
    for pack in packs:
        prompt = (
            f"Fix the failing tests in pack {pack}. "
            "Return a unified diff that makes pytest pass."
        )
        result = await run_task(prompt, pack_name=pack, mode=mode)
        passed = bool(result.get("passed"))
        passes.append(passed)
        th = task_hash(f"pack:{pack}")
        oid = await record_outcome(db_pool, {
            "task_id": None,
            "generator": "ln7",
            "revision_id": revision_id,
            "harness_mode": mode,
            "patch_hash": task_hash(result.get("diff") or ""),
            "passed": passed,
            "diff_lines": result.get("diff_lines"),
            "tokens": result.get("tokens"),
            "latency_ms": result.get("latency_ms"),
            "cost_usd": 0.0,
            "recall_at_k": result.get("recall_at_k"),
            "exec_node": "green",
            "metrics_json": {"pack": pack, "task_hash": th},
        })
        rows.append({"pack": pack, "passed": passed, "outcome_id": oid, **result})

    ci = bootstrap_ci(passes)
    return {
        "ok": True,
        "surface": "private_packs",
        "revision_id": revision_id,
        "harness_mode": mode,
        "pass_rate": ci,
        "results": rows,
        "report_only_public": False,
        "gate_surface": True,
    }


def public_benchmark_stub(name: str) -> Dict[str, Any]:
    """Placeholder until official harness containers are wired on ORANGE/BLUE."""
    return {
        "benchmark": name,
        "status": "harness_pending",
        "report_only": True,
        "note": (
            "Official containerized harness runs on ORANGE/BLUE only. "
            "Scores are report-only; private held-out is the promotion gate."
        ),
        "pass_rate": None,
    }


async def run_full_scorecard(
    db_pool,
    *,
    revision_id: str = "LN7-baseline",
    mode: str = "max",
) -> Dict[str, Any]:
    private = await run_private_pack_bakeoff(
        db_pool, revision_id=revision_id, mode=mode,
    )
    public = [public_benchmark_stub(b) for b in PUBLIC_BENCHMARKS]
    contestants = await list_contestants(db_pool)
    return {
        "ok": bool(private.get("ok")),
        "revision_id": revision_id,
        "private": private,
        "public": public,
        "contestants": contestants,
        "non_clinical_claim": True,
    }


def statistical_gate(
    candidate_passes: List[bool],
    incumbent_passes: List[bool],
    *,
    min_tasks: int = 3,
) -> Dict[str, Any]:
    if len(candidate_passes) < min_tasks:
        return {"ok": False, "reason": "insufficient_tasks", "n": len(candidate_passes)}
    cand = bootstrap_ci(candidate_passes)
    inc_point = (
        sum(1 for p in incumbent_passes if p) / len(incumbent_passes)
        if incumbent_passes else 0.0
    )
    ok = beats_incumbent(cand, inc_point)
    return {
        "ok": ok,
        "candidate_ci": cand,
        "incumbent_point": inc_point,
        "reason": "ci_beats_incumbent" if ok else "ci_not_above_incumbent",
    }
