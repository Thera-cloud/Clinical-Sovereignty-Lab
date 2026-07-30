#!/usr/bin/env python3
"""One-shot: promote existing passed outcomes into ln7_learning_artifacts (g4 verify)."""
from __future__ import annotations

import asyncio
import json
import os
import sys


async def main() -> int:
    url = os.environ.get("DATABASE_URL") or ""
    # One-off scripts should hit Postgres directly (PgBouncer rejects some session features).
    if "pgbouncer" in url:
        url = url.replace("@pgbouncer:6432", "@postgres:5432").replace(
            "@pgbouncer:", "@postgres:"
        )
    if not url:
        print("DATABASE_URL missing", file=sys.stderr)
        return 1

    import asyncpg
    from app.services.ln7_ledger import _auto_promote_learning_artifact

    pool = await asyncpg.create_pool(url, min_size=1, max_size=2)
    try:
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT id, revision_id, task_id, harness_mode, patch_text,
                       metrics_json, generator
                FROM ln7_coding_outcomes
                WHERE passed = true
                  AND patch_text IS NOT NULL
                  AND LENGTH(patch_text) > 10
                ORDER BY id DESC
                LIMIT 20
                """
            )
        print(f"candidates={len(rows)}")
        promoted = 0
        for r in rows:
            metrics = r["metrics_json"]
            if isinstance(metrics, str):
                metrics = json.loads(metrics)
            row = {
                "task_id": r["task_id"],
                "revision_id": r["revision_id"],
                "harness_mode": r["harness_mode"],
                "generator": r["generator"],
                "metrics_json": metrics or {},
            }
            ok = await _auto_promote_learning_artifact(
                pool, int(r["id"]), row, r["patch_text"]
            )
            pack = (metrics or {}).get("pack")
            print(f"id={r['id']} pack={pack} promote={ok}")
            if ok:
                promoted += 1
        async with pool.acquire() as conn:
            n = await conn.fetchval("SELECT COUNT(*) FROM ln7_learning_artifacts")
        print(f"promoted_now={promoted} artifacts_total={n}")
        return 0 if n and int(n) > 0 else 2
    finally:
        await pool.close()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
