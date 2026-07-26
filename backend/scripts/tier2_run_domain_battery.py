#!/usr/bin/env python3
"""
Run Tier 2 cross-domain battery pack(s).  # QUANTUM-CRYSTAL-ARCH

Single subject:
  python /app/scripts/tier2_run_domain_battery.py CLIENT_LETSGOLISA_ID

Multi-family (≥2 subjects):
  python /app/scripts/tier2_run_domain_battery.py --multi HW_A HW_B
  python /app/scripts/tier2_run_domain_battery.py --multi HW_A,HW_B
"""

from __future__ import annotations

import asyncio
import json
import os
import sys


async def main() -> int:
    args = [a for a in sys.argv[1:] if a]
    multi = False
    if args and args[0] in ("--multi", "-m"):
        multi = True
        args = args[1:]
    subjects: list = []
    for a in args:
        subjects.extend([p.strip() for p in a.split(",") if p.strip()])
    if not subjects:
        print(
            "Usage: tier2_run_domain_battery.py <hardware_id|username>\n"
            "       tier2_run_domain_battery.py --multi <id1> <id2> [...]"
        )
        return 2
    dsn = os.environ.get("DATABASE_URL")
    if not dsn:
        print("DATABASE_URL required")
        return 1
    import asyncpg
    from app.services.tier2_cross_domain_battery import run_multi_family_pack, run_pack

    pool = await asyncpg.create_pool(dsn, min_size=1, max_size=3)
    try:
        if multi or len(subjects) > 1:
            out = await run_multi_family_pack(pool, subjects)
        else:
            out = await run_pack(pool, subjects[0])
        print(json.dumps(out, indent=2, default=str))
        if not out.get("ok"):
            return 1
        if multi or len(subjects) > 1:
            return 0 if out.get("multi_family_certify") else 3
        return 0 if out.get("certify_candidate") else 3
    finally:
        await pool.close()


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
