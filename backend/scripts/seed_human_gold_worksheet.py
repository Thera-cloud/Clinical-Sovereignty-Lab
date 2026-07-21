#!/usr/bin/env python3
"""
Seed up to 50 stratified human-gold worksheet rows from approved scenario bank.

Does NOT invent clinician scores — only inserts scenario stems for blinded rating.
Clinicians fill primary/accuracy/naturalness via SQL or admin tool later.

Usage:
  DATABASE_URL=... python3 backend/scripts/seed_human_gold_worksheet.py
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

    target = int(os.getenv("HUMAN_GOLD_TARGET", "50"))
    conn = await asyncpg.connect(dsn)
    try:
        existing = int(
            await conn.fetchval("SELECT COUNT(*) FROM six_quotient_human_gold") or 0
        )
        need = max(0, target - existing)
        if need == 0:
            print(f"OK: already have {existing} gold rows (target {target})")
            return 0

        # Stratify by section
        sections = ["AQ", "EQ", "IQ", "MQ", "SQ", "CQ"]
        per = max(1, need // len(sections))
        inserted = 0
        for sec in sections:
            rows = await conn.fetch(
                """SELECT scenario_key, section, COALESCE(client_says,'') AS client_says
                   FROM six_quotient_scenario_bank
                   WHERE status='approved' AND section=$1
                     AND scenario_key NOT IN (SELECT scenario_id FROM six_quotient_human_gold)
                   ORDER BY scenario_key
                   LIMIT $2""",
                sec,
                per + 2,
            )
            for r in rows:
                if inserted >= need:
                    break
                await conn.execute(
                    """INSERT INTO six_quotient_human_gold
                       (scenario_id, section, client_says, human_scored, blinded)
                       VALUES ($1, $2, $3, false, true)
                       ON CONFLICT (scenario_id) DO NOTHING""",
                    r["scenario_key"],
                    r["section"],
                    (r["client_says"] or "")[:2000],
                )
                inserted += 1
        total = await conn.fetchval("SELECT COUNT(*) FROM six_quotient_human_gold")
        print(f"seeded≈{inserted} total_rows={total} scored=0 (clinician work remaining)")
        return 0
    except Exception as e:
        print(f"FAIL: {e}")
        return 2
    finally:
        await conn.close()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_main()))
