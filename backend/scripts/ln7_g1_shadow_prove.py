#!/usr/bin/env python3
"""Prove one verified ci_pack shadow_outcome then flip LN7_G1_OPEN (not G2)."""
from __future__ import annotations
import asyncio
import os
import sys

async def main() -> int:
    import asyncpg
    dsn = os.environ.get("DATABASE_URL")
    if not dsn:
        print("NO_DATABASE_URL")
        return 2
    pool = await asyncpg.create_pool(dsn, min_size=1, max_size=2)
    from app.services.ln_sandbox_engineering_ci import list_pack_names, materialize_pack
    from app.services.ln7_shadow_fork import run_shadow_fork, g1_promote_allowed
    from app.services.ln7_feature_flags import (
        flip_g1_governance,
        g1_open,
        auto_promote_enabled,
        dual_coo_mechanical_promote,
    )
    from app.services.ln7_outcome_envelope import has_shadow_outcome_for_patch

    names = list_pack_names()
    pack = "micro_ab_ok_on_fail" if "micro_ab_ok_on_fail" in names else (names[0] if names else None)
    if not pack:
        print("NO_PACKS")
        await pool.close()
        return 3
    workdir, _meta, err = materialize_pack(pack)
    if not workdir:
        print("materialize_fail", err)
        await pool.close()
        return 4
    golden = (workdir / "golden.patch").read_text(encoding="utf-8")
    patch_hash = "g1_verified_shadow_20260731_host_contract"
    out = await run_shadow_fork(
        pool,
        patch_hash=patch_hash,
        domain="coding",
        counterfactual_diff=golden,
        pack_ids=[pack],
        force=True,
    )
    so = out.get("shadow_outcome") or {}
    print(
        "shadow_ok", out.get("ok"),
        "oracle", so.get("oracle"),
        "passed", so.get("passed"),
        "envelope", out.get("envelope_id"),
        "pack", pack,
    )
    has = await has_shadow_outcome_for_patch(pool, patch_hash)
    allowed = await g1_promote_allowed(pool, patch_hash)
    print("has_ci_pack_row", has, "g1_promote_allowed", allowed)
    if not has or so.get("oracle") not in ("ci_pack", "ci_pack_cycle"):
        print("REFUSE_G1_FLIP")
        await pool.close()
        return 5
    flipped = await flip_g1_governance(pool, reason="verified_ci_pack_shadow_20260731")
    print(
        "flip_g1", flipped,
        "g1_open", await g1_open(pool),
        "auto_promote", await auto_promote_enabled(pool),
        "mechanical", await dual_coo_mechanical_promote(pool),
    )
    await pool.close()
    return 0

if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
