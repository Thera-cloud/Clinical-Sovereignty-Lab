"""LN7 shadow fork after Queens merge (G1 / W1).

Event: queens.task.merged → ln7_shadow_fork → sandbox apply+pytest →
envelope.shadow_outcome. Similarity scoring forbidden.

# QUANTUM-CRYSTAL-ARCH
"""
from __future__ import annotations

import json
import logging
import time
from typing import Any, Dict, List, Optional

logger = logging.getLogger("ln7_shadow_fork")


async def run_shadow_fork(
    db_pool,
    *,
    patch_hash: str,
    domain: str = "",
    evidence_uri: str = "",
    counterfactual_diff: str = "",
    pack_ids: Optional[List[str]] = None,
    engine: Any = None,
) -> Dict[str, Any]:
    """Apply LN7 counterfactual patch in sandbox CI; record shadow_outcome."""
    from app.services.ln7_outcome_envelope import write_envelope

    started = time.time()
    passed = False
    pack_results: List[Dict[str, Any]] = []
    detail: Dict[str, Any] = {
        "pack_ids": pack_ids or [],
        "domain": domain,
        "evidence_uri": evidence_uri,
    }

    if not counterfactual_diff.strip():
        detail["error"] = "empty_counterfactual_diff"
        envelope_id = await write_envelope(
            db_pool,
            loop_name="ln7_shadow",
            event_kind="shadow_fork",
            patch_hash=patch_hash,
            domain_tag=domain or None,
            shadow_outcome={
                "passed": False,
                "pack_ids": pack_ids or [],
                "latency_ms": 0,
                "error": "empty_diff",
            },
        )
        return {"ok": False, "passed": False, "envelope_id": envelope_id, **detail}

    try:
        from app.services.ln_sandbox_engineering_ci import (
            apply_unified_diff,
            list_pack_names,
            materialize_pack,
            run_pytest,
            score_from_pytest,
        )

        names = pack_ids or list_pack_names()[:3]
        for name in names:
            workdir, meta, err = materialize_pack(name)
            if not workdir or not meta:
                pack_results.append({"pack": name, "ok": False, "error": err})
                continue
            ok_apply, apply_msg = apply_unified_diff(workdir, counterfactual_diff)
            if not ok_apply:
                pack_results.append({
                    "pack": name, "ok": False, "error": apply_msg,
                })
                continue
            test_path = meta.get("test_path") or "tests/test_fix.py"
            pytest_res = run_pytest(workdir, test_path)
            scored = score_from_pytest(pytest_res)
            pack_ok = bool(scored.get("passed") or pytest_res.get("ok"))
            pack_results.append({"pack": name, "ok": pack_ok, "score": scored})
            if pack_ok:
                passed = True
        detail["pack_results"] = pack_results
    except Exception as e:
        detail["error"] = str(e)
        logger.warning("shadow fork failed: %s", e)

    # Optional engine path when no pack_ids / materialize unavailable
    if not pack_results and engine is not None:
        try:
            from app.services.ln_sandbox_engineering_ci import run_ci_pack_cycle

            cycle = await run_ci_pack_cycle(
                engine, pack_name=(pack_ids[0] if pack_ids else None)
            )
            if isinstance(cycle, dict):
                passed = bool(cycle.get("passed") or cycle.get("ok"))
                detail["cycle"] = cycle
        except Exception as e:
            detail["error"] = str(e)

    latency_ms = int((time.time() - started) * 1000)
    shadow = {
        "passed": passed,
        "pack_ids": [p.get("pack") for p in pack_results] or (pack_ids or []),
        "latency_ms": latency_ms,
        "error": detail.get("error"),
    }
    envelope_id = await write_envelope(
        db_pool,
        loop_name="ln7_shadow",
        event_kind="shadow_fork",
        patch_hash=patch_hash,
        domain_tag=domain or None,
        shadow_outcome=shadow,
        metrics=detail,
    )
    return {
        "ok": True,
        "passed": passed,
        "envelope_id": envelope_id,
        "shadow_outcome": shadow,
        **detail,
    }


async def on_queens_task_merged(
    db_pool,
    *,
    patch_hash: str,
    domain: str = "",
    evidence_uri: str = "",
    counterfactual_diff: str = "",
    pack_ids: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """W1 trigger: publish ln7_shadow_fork and run."""
    try:
        from app.websocket.cli_task_bus import publish_task
        from app.services.ln7_living_packs import record_pack_candidate

        publish_task(
            origin="queens",
            kind="ln7_shadow_fork",
            notes=json.dumps({
                "patch_hash": patch_hash,
                "domain": domain,
                "evidence_uri": evidence_uri,
            }),
            files=[],
        )
        await record_pack_candidate(
            db_pool,
            patch_hash=patch_hash,
            domain=domain,
            evidence_uri=evidence_uri,
        )
    except Exception as e:
        logger.info("publish ln7_shadow_fork side-effects: %s", e)

    return await run_shadow_fork(
        db_pool,
        patch_hash=patch_hash,
        domain=domain,
        evidence_uri=evidence_uri,
        counterfactual_diff=counterfactual_diff,
        pack_ids=pack_ids,
    )


async def g1_promote_allowed(db_pool, patch_hash: str) -> bool:
    """Hard-disable G1 promote without executed shadow_outcome rows."""
    from app.services.ln7_outcome_envelope import has_shadow_outcome_for_patch

    return await has_shadow_outcome_for_patch(db_pool, patch_hash)
