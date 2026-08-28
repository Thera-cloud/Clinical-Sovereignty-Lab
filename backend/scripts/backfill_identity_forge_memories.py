#!/usr/bin/env python3
"""Persist completed Identity Forge conversations as Nate crystals.

Usage (inside nate_backend):
  python /app/scripts/backfill_identity_forge_memories.py --username Godsbabi
  python /app/scripts/backfill_identity_forge_memories.py --all
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys


async def _run(username: str | None, all_users: bool) -> int:
    import asyncpg
    from app.sse.layer1_identity_forge import persist_identity_forge_memories

    dsn = os.environ.get("DATABASE_URL")
    if not dsn:
        print("DATABASE_URL missing", file=sys.stderr)
        return 2
    pool = await asyncpg.create_pool(dsn, min_size=1, max_size=3)
    try:
        async with pool.acquire() as conn:
            if all_users:
                rows = await conn.fetch(
                    "SELECT user_id, conversation_history FROM sse_identity_forge "
                    "WHERE status = 'complete' AND conversation_history IS NOT NULL"
                )
            else:
                if not username:
                    print("--username or --all required", file=sys.stderr)
                    return 2
                rows = await conn.fetch(
                    """
                    SELECT f.user_id, f.conversation_history
                    FROM sse_identity_forge f
                    JOIN users u ON (
                        f.user_id = u.username
                        OR f.user_id = u.hardware_id
                        OR f.user_id = u.id::text
                    )
                    WHERE u.username = $1 AND f.status = 'complete'
                    """,
                    username,
                )
        total = 0
        for row in rows:
            n = await persist_identity_forge_memories(
                pool, row["user_id"], row["conversation_history"]
            )
            print(f"{row['user_id']}: {n} crystals")
            total += n
        print(f"total={total}")
        return 0 if rows else 1
    finally:
        await pool.close()


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--username")
    p.add_argument("--all", action="store_true")
    args = p.parse_args()
    return asyncio.run(_run(args.username, args.all))


if __name__ == "__main__":
    raise SystemExit(main())
