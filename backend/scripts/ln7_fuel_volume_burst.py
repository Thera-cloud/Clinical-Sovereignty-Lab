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
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))


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
    parser.add_argument(
        "--replay",
        action="store_true",
        help="Re-fork packs that already have ci_pack rows (default: new packs only)",
    )
    args = parser.parse_args()

    import asyncpg
    from app.services.ln7_fuel_volume import run_fuel_volume_burst

    pool = await asyncpg.create_pool(os.environ["DATABASE_URL"], min_size=1, max_size=4)
    out = await run_fuel_volume_burst(
        pool,
        volume=args.volume,
        limit=args.limit,
        digest=bool(args.digest),
        only_new=not bool(args.replay),
    )
    print("FUEL_SUMMARY", json.dumps({k: out.get(k) for k in (
        "volume", "pass", "fail", "skip", "packs", "at_utc", "ok"
    )}, default=str))
    print("GAUGE", json.dumps(out.get("gauge"), default=str)[:1200])
    if args.digest:
        print("DIGEST", json.dumps(out.get("digest"), default=str)[:400])
    await pool.close()


if __name__ == "__main__":
    asyncio.run(main())
