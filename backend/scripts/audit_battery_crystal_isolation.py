#!/usr/bin/env python3
"""
Read-only battery→crystal isolation audit (Tier-1 D.14b / Priority 2).

Exit 0 = no contaminated crystals matching scenario-bank stems.
Exit 1 = contamination found.
Exit 2 = DB error.

Usage:
  DATABASE_URL=... python3 backend/scripts/audit_battery_crystal_isolation.py
"""

from __future__ import annotations

import asyncio
import os
import sys


async def _main() -> int:
    try:
        import asyncpg
    except ImportError:
        print("FAIL: asyncpg required")
        return 2

    dsn = os.getenv("DATABASE_URL") or os.getenv("POSTGRES_DSN")
    if not dsn:
        print("FAIL: set DATABASE_URL")
        return 2

    conn = await asyncpg.connect(dsn)
    try:
        stems = await conn.fetch(
            """SELECT LEFT(client_says, 80) AS stem
               FROM six_quotient_scenario_bank
               WHERE status = 'approved' AND LENGTH(COALESCE(client_says,'')) >= 40
               LIMIT 40"""
        )
        if not stems:
            print("WARN: no approved scenario stems — skip")
            return 0

        hits = []
        for s in stems:
            stem = (s["stem"] or "").strip()
            if len(stem) < 40:
                continue
            rows = await conn.fetch(
                """SELECT id::text, LEFT(crystal_text, 120) AS preview
                   FROM nate_intelligence_crystals
                   WHERE crystal_text ILIKE '%' || $1 || '%'
                     AND COALESCE(scope, '') != 'archived'
                   LIMIT 5""",
                stem[:60],
            )
            for r in rows:
                hits.append((stem[:40], r["id"], r["preview"]))

        print(f"=== Battery crystal isolation audit ===")
        print(f"stems_checked={len(stems)} contaminated_hits={len(hits)}")
        for stem, cid, prev in hits[:20]:
            print(f"HIT stem={stem!r} crystal={cid} preview={prev!r}")
        if hits:
            print("RESULT: RED — battery-like stems found in active crystals")
            return 1
        print("RESULT: GREEN — no scenario-stem contamination in active crystals")
        return 0
    finally:
        await conn.close()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_main()))
