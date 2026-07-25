#!/usr/bin/env python3
"""
Live-stack blind generation — capability-track baseline (not judge κ).

See module docstring in app.services.live_stack_blinds and
docs/TIER1_HUMAN_GOLD_WORKSHEET.md (Dual-track blinds).

Usage (inside nate_backend):
  python /app/scripts/generate_live_stack_blinds.py --limit 20
  python /app/scripts/generate_live_stack_blinds.py --scenario-ids AQ-1,SQ-4,MQ-2
  python /app/scripts/generate_live_stack_blinds.py --scrub-delta-quotes-only
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys

if "/app" not in sys.path and os.path.isdir("/app/app"):
    sys.path.insert(0, "/app")


async def _main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--all-with-nate", action="store_true")
    ap.add_argument("--scenario-ids", type=str, default="")
    ap.add_argument("--limit", type=int, default=50)
    ap.add_argument("--run-id", type=str, default="")
    ap.add_argument("--user", type=str, default=os.getenv("GOLD_LIVE_STACK_USER", "audit_client"))
    ap.add_argument("--force-rewrite-live", action="store_true")
    ap.add_argument("--scrub-delta-quotes-only", action="store_true")
    args = ap.parse_args()

    dsn = os.getenv("DATABASE_URL") or os.getenv("POSTGRES_DSN")
    if not dsn:
        print("FAIL: set DATABASE_URL")
        return 2

    import asyncpg
    from app.services.live_stack_blinds import (
        generate_live_stack_batch,
        scrub_contaminated_deltas,
    )

    pool = await asyncpg.create_pool(dsn, min_size=1, max_size=3)
    try:
        if args.scrub_delta_quotes_only:
            async with pool.acquire() as conn:
                n = await scrub_contaminated_deltas(conn)
            print(f"scrubbed={n}")
            return 0
        ids = (
            [x.strip() for x in args.scenario_ids.split(",") if x.strip()]
            if args.scenario_ids.strip()
            else None
        )
        out = await generate_live_stack_batch(
            pool,
            scenario_ids=ids,
            scored_only=not args.all_with_nate,
            limit=args.limit,
            user=args.user,
            force_rewrite=args.force_rewrite_live,
            run_id=args.run_id or None,
        )
        print(
            f"run_id={out['run_id']} written={out['written']}/{out['attempted']} "
            f"relabel={out['relabel']} scrubbed_deltas={out['scrubbed_deltas']}"
        )
        for it in out.get("items") or []:
            print(
                f"  {it.get('scenario_id')}: {it.get('status')} "
                f"chars={it.get('chars')} viol={it.get('violations')}"
            )
        return 0
    except Exception as e:
        print(f"FAIL: {e}")
        return 2
    finally:
        await pool.close()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_main()))
