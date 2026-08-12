#!/usr/bin/env python3
"""PRE6 fuel-only volume burst — ci_pack shadow forks, no cohort notices.

Does NOT send #17 emails/in-app notices. Does NOT flip paid bakeoff gates.
Safe to re-run with a new --volume label (unique patch_hash per pack).

# QUANTUM-CRYSTAL-ARCH
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

# Container: /app/scripts → /app; local: backend/scripts → backend
_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

HELDOUT = frozenset(
    {"env_redis_prefix", "mut_off_by_one_range", "mut_mutable_default_arg"}
)


async def main() -> None:
    parser = argparse.ArgumentParser(description="LN7 fuel-only shadow burst")
    parser.add_argument(
        "--volume",
        default="vol3",
        help="Label embedded in patch_hash / evidence_uri (default vol3)",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="Max packs to fork (0 = all non-heldout)",
    )
    parser.add_argument(
        "--digest",
        action="store_true",
        help="Force close digest after gauge (optional)",
    )
    args = parser.parse_args()

    import asyncpg
    from app.jobs.ln7_fuel_gauge import run_fuel_gauge_cycle
    from app.services.ln7_shadow_fork import run_shadow_fork
    from app.services.ln_sandbox_engineering_ci import list_pack_names, materialize_pack

    pool = await asyncpg.create_pool(os.environ["DATABASE_URL"], min_size=1, max_size=4)
    names = [n for n in list_pack_names() if n not in HELDOUT]
    if args.limit > 0:
        names = names[: args.limit]

    ok = fail = skip = 0
    for pack in names:
        wd, meta, err = materialize_pack(pack)
        if not wd:
            skip += 1
            print("SKIP_MAT", pack, err)
            continue
        golden = Path(wd, "golden.patch").read_text(encoding="utf-8")
        ph = f"fuel_{args.volume}_{pack}_{uuid.uuid4().hex[:8]}"
        out = await run_shadow_fork(
            pool,
            patch_hash=ph,
            domain="coding",
            evidence_uri=f"close_#15_{args.volume}:{pack}",
            counterfactual_diff=golden,
            pack_ids=[pack],
            force=True,
        )
        if out.get("passed"):
            ok += 1
        else:
            fail += 1
        print("FORK", pack, "pass" if out.get("passed") else "fail", ph)

    print(
        "FUEL_SUMMARY",
        json.dumps(
            {
                "volume": args.volume,
                "pass": ok,
                "fail": fail,
                "skip": skip,
                "packs": len(names),
                "at_utc": datetime.now(timezone.utc).isoformat(),
            }
        ),
    )
    gauge = await run_fuel_gauge_cycle(pool)
    print("GAUGE", json.dumps(gauge, default=str)[:1200])

    if args.digest:
        from app.services.ln7_close_sentinel import run_close_digest

        await run_close_digest(pool, force_send=True)
        print("DIGEST forced")

    await pool.close()


if __name__ == "__main__":
    asyncio.run(main())
