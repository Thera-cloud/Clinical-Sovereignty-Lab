#!/usr/bin/env python3
"""
One-shot PGSD snapshot backfill (≤1/day/user for last 90d).  # QUANTUM-CRYSTAL-ARCH

Gated by ENABLE_PGSD_BACKFILL=true and PGSD_ENABLED=true.
Primary-only recommended. Run inside nate_backend:

  docker compose -f docker-compose.prod.yml exec -T backend \\
    python /app/scripts/pgsd_backfill_snapshots.py
"""

from __future__ import annotations

import asyncio
import os
import sys


def _env_true(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in ("1", "true", "yes", "on")


async def main() -> int:
    if not _env_true("PGSD_ENABLED") or not _env_true("ENABLE_PGSD_BACKFILL"):
        print("Backfill disabled — set PGSD_ENABLED and ENABLE_PGSD_BACKFILL")
        return 1

    import asyncpg
    from app.services.pgsd_engine import PGSDEngine

    dsn = os.environ.get("DATABASE_URL")
    if not dsn:
        print("DATABASE_URL required")
        return 1

    pool = await asyncpg.create_pool(dsn, min_size=1, max_size=3)
    engine = PGSDEngine(db_pool=pool)
    written = 0
    try:
        async with pool.acquire() as conn:
            users = await conn.fetch(
                """
                SELECT hardware_id, username FROM users
                WHERE role = 'CLIENT'
                  AND hardware_id IS NOT NULL AND hardware_id != ''
                  AND LOWER(username) NOT LIKE 'audit\\_%'
                LIMIT 500
                """
            )
        for u in users:
            hw = u["hardware_id"]
            try:
                async with pool.acquire() as conn:
                    n = await conn.fetchval(
                        """
                        SELECT COUNT(*)::int FROM pgsd_snapshots
                        WHERE user_id = $1
                          AND computed_at > NOW() - INTERVAL '90 days'
                        """,
                        hw,
                    )
                if (n or 0) >= 7:
                    continue
                # At most one synthetic backfill snapshot if series thin
                pgsd = await engine.compute_full_pgsd(hw)
                if not pgsd:
                    continue
                from app.websocket.pgsd_handlers import PGSDWebSocketRouter

                router = PGSDWebSocketRouter(db_pool=pool)
                pgsd["_trigger_source"] = "backfill"
                pgsd["_username"] = u["username"] or ""
                sid = await router._save_snapshot(hw, pgsd, evolution=None)
                if sid:
                    written += 1
                    print(f"wrote snapshot id={sid} user={hw}")
                await asyncio.sleep(0.2)
            except Exception as e:
                print(f"skip {hw}: {e}")
    finally:
        await pool.close()
    print(f"backfill complete written={written}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
