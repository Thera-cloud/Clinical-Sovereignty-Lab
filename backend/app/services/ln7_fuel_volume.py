"""Callable PRE6 fuel volume burst (shared by CLI script + CEO APPROVE).

# QUANTUM-CRYSTAL-ARCH
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger("nate.ln7_fuel_volume")

HELDOUT = frozenset(
    {"env_redis_prefix", "mut_off_by_one_range", "mut_mutable_default_arg"}
)


async def run_fuel_volume_burst(
    db_pool,
    *,
    volume: str = "vol",
    limit: int = 0,
    digest: bool = False,
) -> Dict[str, Any]:
    """Materialize CI packs → shadow forks → fuel gauge (+ optional close digest)."""
    if not db_pool:
        return {"ok": False, "error": "no_db"}

    from app.jobs.ln7_fuel_gauge import run_fuel_gauge_cycle
    from app.services.ln7_shadow_fork import run_shadow_fork
    from app.services.ln_sandbox_engineering_ci import list_pack_names, materialize_pack

    names = [n for n in list_pack_names() if n not in HELDOUT]
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
        "at_utc": datetime.now(timezone.utc).isoformat(),
        "gauge": gauge,
        "digest": digest_out,
        "forks": forks[:40],
    }
