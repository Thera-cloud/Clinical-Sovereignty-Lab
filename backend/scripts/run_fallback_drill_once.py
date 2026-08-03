#!/usr/bin/env python3
"""
One-shot live execution of ln7_fallback_drill.run_fallback_drill()
(TRUST_LEDGER.md Entry 24/27 — "a live-exercised run_fallback_drill()
result" was one of three named prerequisites for re-attempting the G2
flip; code existing was never evidence it ran).

Safe to run in production: the drill's hive-burst leg is HARD-forced to
dry_run=True (this script also mirrors run_fallback_drill()'s own
LN7_HIVE_DRY_RUN=1 env guard as a second belt) — dry mode never reaches
scripts/ln7_hive_burst.sh (the real, paid-GPU-provisioning path); it only
publishes a localhost stub serve-endpoint pointer to Redis and clears it
again. No droplet is provisioned, no cost is incurred.

Writes a real outcome_envelope(loop_name='ops', event_kind='fallback_drill')
row on completion — this script's success is that row existing, not just
this script exiting 0.

Usage (inside nate_backend, PYTHONPATH=/app):
  python /app/scripts/run_fallback_drill_once.py
"""
from __future__ import annotations

import asyncio
import os
import sys

if "/app" not in sys.path and os.path.isdir("/app/app"):
    sys.path.insert(0, "/app")


async def _main() -> int:
    import asyncpg

    from app.services.ln7_fallback_drill import run_fallback_drill

    dsn = os.getenv("DATABASE_URL") or os.getenv("POSTGRES_DSN")
    if not dsn:
        print("FAIL: set DATABASE_URL")
        return 2

    # Belt: hard-force dry regardless of any stray env state.
    os.environ["LN7_HIVE_DRY_RUN"] = "1"

    conn_pool = await asyncpg.create_pool(dsn, min_size=1, max_size=2)
    try:
        print("Running fallback drill (hive-burst leg forced dry_run=True)...")
        out = await run_fallback_drill(conn_pool)
        print(f"Result: ok={out.get('ok')}")
        for r in out.get("results", []):
            print(f"  - {r.get('id')}: ok={r.get('ok')}")

        row = await conn_pool.fetchrow(
            """
            SELECT envelope_id, created_at FROM outcome_envelope
            WHERE loop_name = 'ops' AND event_kind = 'fallback_drill'
            ORDER BY created_at DESC LIMIT 1
            """
        )
        if not row:
            print(
                "FAIL: run_fallback_drill() completed but no outcome_envelope "
                "row was found — db_pool write may have silently failed."
            )
            return 2
        print(f"OK: outcome_envelope row confirmed — envelope_id={row['envelope_id']} "
              f"created_at={row['created_at']}")
        return 0 if out.get("ok") else 1
    finally:
        await conn_pool.close()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_main()))
