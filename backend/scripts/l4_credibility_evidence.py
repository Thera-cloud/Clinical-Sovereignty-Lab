#!/usr/bin/env python3
"""Run one L4 credibility cycle against DATABASE_URL (GREEN evidence artifact).

Usage (on GREEN inside nate_backend):
  python /app/scripts/l4_credibility_evidence.py

Prints JSON with l4_credible, cycle actions, and shadow accuracy.
"""
from __future__ import annotations

import asyncio
import json
import os
import sys


async def main() -> int:
    import asyncpg

    url = os.environ.get("DATABASE_URL") or ""
    if not url:
        print(json.dumps({"status": "error", "reason": "DATABASE_URL missing"}))
        return 2
    # Prefer app import path used in container
    sys.path.insert(0, "/app")
    from app.services.ln_rule_loop import run_l4_credibility_cycle, rule_loop_enabled

    if not rule_loop_enabled():
        print(json.dumps({"status": "skipped", "reason": "ENABLE_LN_RULE_LOOP off"}))
        return 1
    pool = await asyncpg.create_pool(url, min_size=1, max_size=3)
    try:
        out = await run_l4_credibility_cycle(
            pool, gate_class=os.environ.get("L4_EVIDENCE_CLASS", "sleep_aid"),
        )
        print(json.dumps(out, default=str, indent=2))
        return 0 if out.get("l4_credible") else 3
    finally:
        await pool.close()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
