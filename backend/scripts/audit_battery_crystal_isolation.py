#!/usr/bin/env python3
"""
Read-only battery→crystal isolation audit (Tier-1 D.14b / Priority 2).

Uses marker / metadata hits (fast) instead of full-text stem scans.

Exit 0 = no contaminated crystals.
Exit 1 = contamination found.
Exit 2 = DB error.
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
        await conn.execute("SET statement_timeout = '15s'")
        # Metadata-only first (avoids full crystal_text seqscan on large tables)
        rows = await conn.fetch(
            """SELECT id::text, LEFT(crystal_text, 120) AS preview, scope
               FROM nate_intelligence_crystals
               WHERE COALESCE(scope, '') != 'archived'
                 AND (
                   origin_surface IN (
                     'six_quotient_battery', 'six_quotient_nightly',
                     'six_quotient_weekly', 'six_quotient_transfer',
                     'six_quotient_smoke'
                   )
                   OR (
                     metadata IS NOT NULL AND (
                       metadata::text ILIKE '%six_quotient_battery%'
                       OR metadata::text ILIKE '%six_quotient_nightly%'
                       OR metadata::text ILIKE '%six_quotient_weekly%'
                     )
                   )
                   OR crystal_text ILIKE 'BATTERY-VALIDATED%'
                   OR crystal_text LIKE '%[SIX_QUOTIENT_BATTERY]%'
                 )
               LIMIT 25"""
        )
        print("=== Battery crystal isolation audit ===")
        print(f"marker_hits={len(rows)}")
        for r in rows[:20]:
            print(f"HIT crystal={r['id']} preview={r['preview']!r}")
        if rows:
            print("RESULT: RED — battery markers found in active crystals")
            return 1
        print("RESULT: GREEN — no battery markers in active crystals")
        return 0
    except Exception as e:
        print(f"FAIL: {e}")
        return 2
    finally:
        await conn.close()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_main()))
