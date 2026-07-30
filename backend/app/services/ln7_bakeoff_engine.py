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

    # QUANTUM-CRYSTAL-ARCH — preflight serve identity.
    # The PEFT server is single-adapter and boot-pinned, so two revisions can
    # resolve to the same endpoint and score the SAME weights twice. Abort loudly
    # instead of writing a wall of 0.0 rows that poison pass_rate.
    if os.getenv("LN7_BAKEOFF_PREFLIGHT", "true").strip().lower() in ("1", "true", "yes", "on"):
        try:
            from app.services.little_nate_7 import (
                load_revision as _load_rev,
                probe_serve_identity,
                serve_target_from_revision,
            )
            _tier = "fast" if (mode or "").strip().lower() == "fast" else "deep"
            _rev = await _load_rev(db_pool, revision_id)
            if _rev is None:
                return {
                    "ok": False,
                    "status": "aborted_preflight",
                    "error": f"unknown_revision:{revision_id}",
                    "revision_id": revision_id,
                }
            _target = serve_target_from_revision(_rev, tier=_tier)
            _probe = await probe_serve_identity(_target, _rev)
            if not _probe.get("ok"):
                allow = os.getenv(
                    "LN7_BAKEOFF_ALLOW_SERVE_MISMATCH", "false"
                ).strip().lower() in ("1", "true", "yes", "on")
                logger.warning(
                    "LN7 bakeoff preflight failed rev=%s target=%s reason=%s allow=%s",
                    revision_id, _target, _probe.get("reason"), allow,
                )
                if not allow:
                    return {
                        "ok": False,
                        "status": "aborted_preflight",
                        "error": str(_probe.get("reason") or "serve_preflight_failed"),
                        "revision_id": revision_id,
                        "serve_target": _target,
                        "serve_probe": _probe,
                        "packs_run": 0,
                    }
            else:
                logger.info(
                    "LN7 bakeoff preflight ok rev=%s mode=%s reason=%s",
                    revision_id, _target.get("mode"), _probe.get("reason"),
                )
        except Exception as exc:
            logger.warning("LN7 bakeoff preflight error: %s", exc)

    packs = pack_names or list_pack_names()
    if not packs:
        return {"ok": False, "error": "no_packs"}

    # Phase D / R2: stratify vintage vs living_* (fresh) packs
    vintage = [p for p in packs if not str(p).startswith("living_")]
    fresh = [p for p in packs if str(p).startswith("living_")]
    if pack_names is None and (vintage or fresh):
        # Prefer mix: up to half slots from fresh when present
        n = min(len(packs), int(os.getenv("LN7_BAKEOFF_PACK_CAP", "24") or 24))
        fresh_n = min(len(fresh), max(0, n // 2)) if fresh else 0
        vintage_n = min(len(vintage), n - fresh_n)
        rng = random.Random(int(os.getenv("LN7_BAKEOFF_STRAT_SEED", "42") or 42))
        packs = rng.sample(vintage, vintage_n) if vintage_n else []
        if fresh_n:
            packs.extend(rng.sample(fresh, fresh_n))
        rng.shuffle(packs)

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
        # QUANTUM-CRYSTAL-ARCH — per-pack isolate: one failure must not abort the remaining packs
        try:
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
        except Exception as exc:
            logger.warning("LN7 private bakeoff pack %s failed: %s", pack, exc)
            result = {
                "passed": False,
                "diff": "",
                "diff_lines": 0,
                "tokens": 0,
                "latency_ms": 0,
                "error": f"pack_exception:{exc}"[:200],
                "log": str(exc)[:200],
            }
        passed = bool(result.get("passed"))
        passes.append(passed)
        th = task_hash(f"pack:{pack}")
        diff_text = result.get("diff") or ""
        try:
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
        except Exception as exc:
            logger.warning("LN7 record_outcome pack %s failed: %s", pack, exc)
            oid = None
        rows.append({"pack": pack, "passed": passed, "outcome_id": oid, **result})

    ci = bootstrap_ci(passes)
    fresh_passes = [
        bool(r.get("passed"))
        for r in rows
        if str(r.get("pack") or "").startswith("living_")
    ]
    vintage_passes = [
        bool(r.get("passed"))
        for r in rows
        if not str(r.get("pack") or "").startswith("living_")
    ]
    return {
        "ok": True,
        "surface": "private_packs",
        "revision_id": revision_id,
        "harness_mode": mode,
        "pass_rate": ci,
        "fresh_pass_rate": bootstrap_ci(fresh_passes) if fresh_passes else None,
        "vintage_pass_rate": bootstrap_ci(vintage_passes) if vintage_passes else None,
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


async def run_public_benchmarks(
    *, revision_id: Optional[str] = None, db_pool=None,
) -> List[Dict[str, Any]]:
    """Smoke / ingest / full public benches via ln7_public_harness, plus the
    real executed humaneval_subset benchmark (G3 fix)."""
    try:
        from app.services.ln7_public_harness import run_all_public
        return await run_all_public(revision_id=revision_id, db_pool=db_pool)
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
        public = await run_public_benchmarks(revision_id=revision_id, db_pool=db_pool)
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
