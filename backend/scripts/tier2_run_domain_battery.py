#!/usr/bin/env python3
"""
Run Tier 2 cross-domain battery pack.  # QUANTUM-CRYSTAL-ARCH

  docker compose -f docker-compose.prod.yml exec -T -e PYTHONPATH=/app backend \\
    python /app/scripts/tier2_run_domain_battery.py CLIENT_LETSGOLISA_ID
"""

from __future__ import annotations

import asyncio
import json
import os
import sys


async def main() -> int:
    subject = (sys.argv[1] if len(sys.argv) > 1 else "").strip()
    if not subject:
        print("Usage: tier2_run_domain_battery.py <hardware_id|username>")
        return 2
    dsn = os.environ.get("DATABASE_URL")
    if not dsn:
        print("DATABASE_URL required")
        return 1
    import asyncpg
    from app.services.tier2_cross_domain_battery import run_pack

    pool = await asyncpg.create_pool(dsn, min_size=1, max_size=3)
    try:
        out = await run_pack(pool, subject)
        print(json.dumps(out, indent=2, default=str))
        return 0 if out.get("ok") else 1
    finally:
        await pool.close()


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
