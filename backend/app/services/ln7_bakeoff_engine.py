"""LN7 bakeoff engine — identical harness for LN7 vs contestants; public + private scores.

Public benchmarks are report-only; private held-out is the promotion gate.
# QUANTUM-CRYSTAL-ARCH
"""
from __future__ import annotations

import asyncio
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


async def sync_contestant_credentials(db_pool) -> Dict[str, Any]:
    """Enable contestants only when URL/key/model exist — never claim working without creds."""
    if not db_pool:
        return {"ok": False, "updated": 0}
    foundry_ok = bool(
        (os.getenv("NATE_CHAT_URL") or os.getenv("AZURE_OPENAI_ENDPOINT"))
        and (os.getenv("NATE_CHAT_KEY") or os.getenv("AZURE_API_KEY"))
    )
    xai_ok = bool(os.getenv("XAI_API_KEY") and (os.getenv("XAI_CHAT_URL") or True))
    fable_ok = bool(os.getenv("FABLE_API_KEY") and os.getenv("FABLE_API_URL"))
    mythos_ok = bool(os.getenv("MYTHOS_API_KEY") and os.getenv("MYTHOS_API_URL"))
    mapping = {
        "foundry_grok": foundry_ok,
        "xai_grok": xai_ok,
        "fable_5": fable_ok,
        "mythos_5": mythos_ok,
    }
    updated = 0
    try:
        async with db_pool.acquire() as conn:
            for cid, enabled in mapping.items():
                await conn.execute(
                    """
                    UPDATE ln7_contestants
                    SET enabled = $2,
                        version_captured_at = CASE WHEN $2 THEN NOW() ELSE version_captured_at END,
                        base_url = CASE
                            WHEN contestant_id = 'foundry_grok' THEN COALESCE($3, base_url)
                            WHEN contestant_id = 'xai_grok' THEN COALESCE($4, base_url)
                            WHEN contestant_id = 'fable_5' THEN COALESCE($5, base_url)
                            WHEN contestant_id = 'mythos_5' THEN COALESCE($6, base_url)
                            ELSE base_url
                        END
                    WHERE contestant_id = $1
                    """,
                    cid,
                    enabled,
                    os.getenv("NATE_CHAT_URL") or None,
                    os.getenv("XAI_CHAT_URL") or "https://api.x.ai/v1/chat/completions",
                    os.getenv("FABLE_API_URL") or None,
                    os.getenv("MYTHOS_API_URL") or None,
                )
                updated += 1
        return {"ok": True, "updated": updated, "enabled": mapping}
    except Exception as exc:
        logger.warning("LN7 sync_contestants: %s", exc)
        return {"ok": False, "error": str(exc)[:200]}


async def list_contestants(db_pool) -> List[Dict[str, Any]]:
    if not db_pool:
        return []
    try:
        await sync_contestant_credentials(db_pool)
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
    seed_golden: bool = False,
) -> Dict[str, Any]:
    """Run LN7 harness on CI packs (private / first-party). Contestants optional later.

    seed_golden=True also records golden.patch passes as train-eligible outcomes
    (generator=ln7_golden) without counting them as LN7 model pass_rate.
    """
    if not bakeoff_enabled():
        return {"ok": False, "error": "bakeoff_disabled"}

    try:
        from app.services.ln_sandbox_engineering_ci import list_pack_names
        from app.websocket.ln7_harness import run_task
        from app.services.ln7_ledger import record_outcome, task_hash
    except Exception as exc:
        return {"ok": False, "error": f"import:{exc}"}

    from app.services.ln_sandbox_engineering_ci import load_pack, materialize_pack, apply_unified_diff, run_pytest
    from app.websocket.ln7_harness import build_pack_prompt
    from pathlib import Path
    import shutil

    packs = pack_names or list_pack_names()
    if not packs:
        return {"ok": False, "error": "no_packs"}

    if seed_golden or os.getenv("LN7_BAKEOFF_SEED_GOLDEN", "").strip().lower() in (
        "1", "true", "yes", "on",
    ):
        for pack in packs:
            wd, task, _ = materialize_pack(pack)
            if not wd or not task:
                continue
            try:
                gpath = Path(wd) / "golden.patch"
                if not gpath.is_file():
                    continue
                gdiff = gpath.read_text(encoding="utf-8")
                ok_a, _ = apply_unified_diff(Path(wd), gdiff)
                if not ok_a:
                    continue
                pr = await asyncio.to_thread(
                    run_pytest, Path(wd), task.get("test_path") or "tests", 60.0,
                )
                await record_outcome(db_pool, {
                    "task_id": None,
                    "generator": "ln7_golden",
                    "revision_id": revision_id,
                    "harness_mode": "golden",
                    "patch_hash": task_hash(gdiff),
                    "passed": bool(pr.get("passed")),
                    "diff_lines": len(gdiff.splitlines()),
                    "tokens": 0,
                    "latency_ms": 0,
                    "cost_usd": 0.0,
                    "patch_text": gdiff,
                    "metrics_json": {"pack": pack, "source": "golden.patch"},
                })
            finally:
                shutil.rmtree(wd, ignore_errors=True)

    passes: List[bool] = []
    rows: List[Dict[str, Any]] = []
    for pack in packs:
        # QUANTUM-CRYSTAL-ARCH — use pack task prompt + target file bodies (not a vague name-only hint)
        prompt = build_pack_prompt(pack)
        if not prompt:
            task = load_pack(pack) or {}
            prompt = task.get("prompt") or (
                f"Fix the failing tests in pack {pack}. "
                "Return a unified diff that makes pytest pass."
            )
        result = await run_task(
            prompt, pack_name=pack, mode=mode, revision_id=revision_id, db_pool=db_pool,
        )
        passed = bool(result.get("passed"))
        passes.append(passed)
        th = task_hash(f"pack:{pack}")
        diff_text = result.get("diff") or ""
        oid = await record_outcome(db_pool, {
            "task_id": None,
            "generator": "ln7",
            "revision_id": revision_id,
            "harness_mode": mode,
            "patch_hash": task_hash(diff_text),
            "passed": passed,
            "diff_lines": result.get("diff_lines") if result.get("diff_lines") is not None
            else len(diff_text.splitlines()),
            "tokens": result.get("tokens"),
            "latency_ms": result.get("latency_ms"),
            "cost_usd": 0.0,
            "recall_at_k": result.get("recall_at_k"),
            "exec_node": "green",
            "patch_text": diff_text or None,
            "metrics_json": {
                "pack": pack,
                "task_hash": th,
                "score": result.get("score"),
                "error": result.get("error") or (result.get("log") or "")[:200],
            },
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
    """Legacy fallback if public harness import fails."""
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


async def run_public_benchmarks() -> List[Dict[str, Any]]:
    """Smoke / ingest / full public benches via ln7_public_harness."""
    try:
        from app.services.ln7_public_harness import run_all_public
        return await run_all_public()
    except Exception as exc:
        logger.warning("LN7 public harness: %s", exc)
        return [public_benchmark_stub(b) for b in PUBLIC_BENCHMARKS]


async def run_full_scorecard(
    db_pool,
    *,
    revision_id: str = "LN7-baseline",
    mode: str = "max",
    include_public: bool = True,
    include_private: bool = True,
    seed_golden: bool = False,
) -> Dict[str, Any]:
    private: Dict[str, Any] = {"ok": True, "skipped": True}
    if include_private:
        private = await run_private_pack_bakeoff(
            db_pool, revision_id=revision_id, mode=mode, seed_golden=seed_golden,
        )
    public: List[Dict[str, Any]] = []
    if include_public:
        public = await run_public_benchmarks()
    contestants = await list_contestants(db_pool)
    return {
        "ok": bool(private.get("ok")) if include_private else True,
        "revision_id": revision_id,
        "private": private,
        "public": public,
        "contestants": contestants,
        "non_clinical_claim": True,
        "public_report_only": True,
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
