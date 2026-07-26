#!/usr/bin/env python3
"""
Refresh PGSD ACCESS/FIELD tables for users who already have snapshots.  # QUANTUM-CRYSTAL-ARCH

Requires PGSD_ENABLED + ENABLE_PGSD_ACCESS (FIELD optional).
Run inside nate_backend after flag ladder enable:

  docker compose -f docker-compose.prod.yml exec -T backend \\
    python /app/scripts/pgsd_refresh_access_field.py
"""

from __future__ import annotations

import asyncio
import os
import sys


def _env_true(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in ("1", "true", "yes", "on")


async def main() -> int:
    if not _env_true("PGSD_ENABLED") or not _env_true("ENABLE_PGSD_ACCESS"):
        print("Need PGSD_ENABLED + ENABLE_PGSD_ACCESS")
        return 1

    import asyncpg
    from app.services.pgsd_correlation import (
        compute_cross_domain_series,
        correlate_recent_chat,
    )
    from app.services.pgsd_discernment_scorer import PGSDDiscernmentScorer
    from app.services.pgsd_field_engine import PGSDFieldEngine
    from app.services.pgsd_trauma_wells import TraumaWellEngine

    dsn = os.environ.get("DATABASE_URL")
    if not dsn:
        print("DATABASE_URL required")
        return 1

    pool = await asyncpg.create_pool(dsn, min_size=1, max_size=3)
    scored = 0
    wells = 0
    try:
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT DISTINCT ON (user_id) user_id, id AS snapshot_id
                FROM pgsd_snapshots
                ORDER BY user_id, computed_at DESC
                LIMIT 200
                """
            )
        scorer = PGSDDiscernmentScorer(db_pool=pool)
        well_eng = TraumaWellEngine(db_pool=pool)
        field = PGSDFieldEngine(db_pool=pool)
        field_on = _env_true("ENABLE_PGSD_FIELD")
        for r in rows:
            hw = r["user_id"]
            sid = int(r["snapshot_id"])
            try:
                await correlate_recent_chat(pool, hw, sid, "refresh_script")
                out = await scorer.score_user(hw)
                await compute_cross_domain_series(pool, hw)
                scored += 1
                print(
                    f"access ok user={hw} composite={out.get('score_composite')} "
                    f"claims={out.get('claim_count')}"
                )
                if field_on:
                    ids = await well_eng.refresh_wells(hw)
                    await field.track_hamiltonian(hw, sid)
                    await field.compute_spectrum([hw])
                    wells += len(ids or [])
            except Exception as e:
                print(f"skip {hw}: {e}")
            await asyncio.sleep(0.05)
    finally:
        await pool.close()
    print(f"refresh complete scored={scored} wells_touched={wells}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
