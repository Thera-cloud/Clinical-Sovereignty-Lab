#!/usr/bin/env python3
"""
Freeze (stem, response) pairs after genuine + degraded seeding.

Refuses if any row lacks nate_response or if degraded count < 8.
Does NOT set human_scored.

Usage:
  DATABASE_URL=... python3 backend/scripts/freeze_gold_response_pairs.py
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
        total = int(await conn.fetchval("SELECT COUNT(*) FROM six_quotient_human_gold") or 0)
        empty = int(
            await conn.fetchval(
                """SELECT COUNT(*) FROM six_quotient_human_gold
                   WHERE COALESCE(nate_response,'') = ''"""
            )
            or 0
        )
        dry = int(
            await conn.fetchval(
                """SELECT COUNT(*) FROM six_quotient_human_gold
                   WHERE nate_response ILIKE '%DRY-RUN%'
                      OR nate_response ILIKE '%Placeholder Nate reply%'
                      OR nate_response ILIKE '%External scoring required%'"""
            )
            or 0
        )
        deg = int(
            await conn.fetchval(
                "SELECT COUNT(*) FROM six_quotient_human_gold WHERE is_degraded_distractor"
            )
            or 0
        )
        if total < 50:
            print(f"FAIL: only {total} gold rows (need 50)")
            return 1
        if empty:
            print(f"FAIL: {empty} rows still missing nate_response")
            return 1
        if dry:
            print(
                f"FAIL: {dry} rows still have DRY-RUN/placeholder nate_response — "
                "run fill_human_gold_nate_responses.py --replace-placeholders --infer-missing"
            )
            return 1
        if deg < 8:
            print(f"FAIL: degraded distractors {deg}<8 — seed before freeze")
            return 1
        await conn.execute(
            """UPDATE six_quotient_human_gold
               SET pairs_locked = true
               WHERE COALESCE(nate_response,'') <> ''"""
        )
        locked = int(
            await conn.fetchval(
                "SELECT COUNT(*) FROM six_quotient_human_gold WHERE pairs_locked"
            )
            or 0
        )
        print(f"OK: pairs_locked={locked} degraded={deg} (ready for clinician session)")
        return 0
    except Exception as e:
        print(f"FAIL: {e} (apply migration 259)")
        return 2
    finally:
        await conn.close()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_main()))
