#!/usr/bin/env python3
"""Idempotent seed of alphaln_synthetic_profiles (ON CONFLICT DO NOTHING).

Run inside nate_backend:
  python /app/scripts/seed_alphaln_synthetic_profiles.py
"""

from __future__ import annotations

import asyncio
import json
import os
import sys

# Allow `python backend/scripts/...` from repo root.
_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)


async def _seed(db_pool) -> int:
    from app.services.alphaln_synthetic_client import generate_profile_grid, is_gym_enabled

    if not is_gym_enabled():
        print("ENABLE_ALPHALN_GYM is off — seed skipped")
        return 0
    grid = generate_profile_grid()
    inserted = 0
    async with db_pool.acquire() as conn:
        for p in grid:
            status = await conn.execute(
                """INSERT INTO alphaln_synthetic_profiles
                       (profile_id, base_persona, co_occurring_patterns,
                        trigger_context, difficulty_level, combo_key)
                     VALUES ($1, $2, $3::jsonb, $4, $5, $6)
                     ON CONFLICT DO NOTHING""",
                p["profile_id"],
                p["base_persona"],
                json.dumps(p["co_occurring_patterns"]),
                p["trigger_context"],
                int(p["difficulty_level"]),
                p["combo_key"],
            )
            if status and status.endswith("1"):
                inserted += 1
    print(f"seeded {inserted} new rows (grid={len(grid)})")
    return inserted


async def main() -> int:
    import asyncpg

    dsn = os.getenv("DATABASE_URL") or ""
    if not dsn:
        print("DATABASE_URL missing", file=sys.stderr)
        return 2
    pool = await asyncpg.create_pool(dsn, min_size=1, max_size=4)
    try:
        await _seed(pool)
    finally:
        await pool.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
