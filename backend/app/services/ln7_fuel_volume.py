"""Callable PRE6 fuel volume burst (shared by CLI script + CEO APPROVE).

# QUANTUM-CRYSTAL-ARCH
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, FrozenSet, List, Optional, Set

logger = logging.getLogger("nate.ln7_fuel_volume")

HELDOUT = frozenset(
    {"env_redis_prefix", "mut_off_by_one_range", "mut_mutable_default_arg"}
)


def fuel_heldout() -> FrozenSet[str]:
    """Static index heldout ∪ living sidecar heldout."""
    try:
        from app.services.ln7_heldout_registry import heldout_packs
        from app.services.ln7_living_packs import living_heldout_names

        return heldout_packs() | living_heldout_names()
    except Exception:
        return HELDOUT


def filter_burst_packs(
    names: List[str],
    existing: Set[str],
    *,
    only_new: bool,
) -> List[str]:
    held = fuel_heldout()
    out = [n for n in names if n not in held]
    if only_new:
        out = [n for n in out if n not in existing]
    return out


async def existing_ci_pack_names(db_pool) -> Set[str]:
    if not db_pool:
        return set()
    try:
        async with db_pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT DISTINCT jsonb_array_elements_text(
                    COALESCE(shadow_outcome->'pack_ids', '[]'::jsonb)
                ) AS pack
                FROM outcome_envelope
                WHERE COALESCE(shadow_outcome->>'oracle', '')
                      IN ('ci_pack', 'ci_pack_cycle')
                """
            )
        return {str(r["pack"]) for r in rows if r["pack"]}
    except Exception as e:
        logger.warning("existing_ci_pack_names: %s", e)
        return set()


async def run_fuel_volume_burst(
    db_pool,
    *,
    volume: str = "vol",
    limit: int = 0,
    digest: bool = False,
    only_new: bool = True,
) -> Dict[str, Any]:
    """Materialize CI packs → shadow forks → fuel gauge (+ optional close digest)."""
    if not db_pool:
        return {"ok": False, "error": "no_db"}

    from app.jobs.ln7_fuel_gauge import run_fuel_gauge_cycle
    from app.services.ln7_shadow_fork import run_shadow_fork
    from app.services.ln_sandbox_engineering_ci import list_pack_names, materialize_pack

    existing = await existing_ci_pack_names(db_pool) if only_new else set()
    names = filter_burst_packs(list_pack_names(), existing, only_new=only_new)
    if limit and limit > 0:
        names = names[: int(limit)]

    ok = fail = skip = 0
    forks: List[Dict[str, Any]] = []
    for pack in names:
        wd, _meta, err = materialize_pack(pack)
        if not wd:
            skip += 1
            forks.append({"pack": pack, "status": "skip", "error": str(err)[:120]})
            continue
        golden = Path(wd, "golden.patch").read_text(encoding="utf-8")
        ph = f"fuel_{volume}_{pack}_{uuid.uuid4().hex[:8]}"
        out = await run_shadow_fork(
            db_pool,
            patch_hash=ph,
            domain="coding",
            evidence_uri=f"close_#15_{volume}:{pack}",
            counterfactual_diff=golden,
            pack_ids=[pack],
            force=True,
        )
        passed = bool(out.get("passed"))
        if passed:
            ok += 1
        else:
            fail += 1
        forks.append({"pack": pack, "status": "pass" if passed else "fail", "patch_hash": ph})

    gauge = await run_fuel_gauge_cycle(db_pool)
    digest_out: Optional[Dict[str, Any]] = None
    if digest:
        try:
            from app.services.ln7_close_sentinel import run_close_digest

            digest_out = await run_close_digest(db_pool, force_send=True)
        except Exception as e:
            logger.warning("fuel volume digest: %s", e)
            digest_out = {"ok": False, "error": str(e)[:200]}

    return {
        "ok": True,
        "volume": volume,
        "pass": ok,
        "fail": fail,
        "skip": skip,
        "packs": len(names),
        "only_new": only_new,
        "at_utc": datetime.now(timezone.utc).isoformat(),
        "gauge": gauge,
        "digest": digest_out,
        "forks": forks[:40],
    }
