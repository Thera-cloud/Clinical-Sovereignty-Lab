#!/usr/bin/env python3
"""
Seed up to 50 stratified human-gold worksheet rows.

Prefers backend/app/data/six_quotient_human_gold_stems_v1.json, then scenario bank.
Does NOT invent clinician scores.

Usage:
  DATABASE_URL=... python3 backend/scripts/seed_human_gold_worksheet.py
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path


def _load_stems() -> list:
    candidates = [
        Path(__file__).resolve().parents[1] / "app" / "data" / "six_quotient_human_gold_stems_v1.json",
        Path("/app/app/data/six_quotient_human_gold_stems_v1.json"),
        Path("/app/data/six_quotient_human_gold_stems_v1.json"),
    ]
    for p in candidates:
        if p.is_file():
            data = json.loads(p.read_text())
            return list(data.get("stems") or [])
    return []


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

        inserted = 0
        stems = _load_stems()
        for s in stems:
            if inserted >= need:
                break
            sid = str(s.get("scenario_id") or "").strip()
            if not sid:
                continue
            await conn.execute(
                """INSERT INTO six_quotient_human_gold
                   (scenario_id, section, client_says, human_scored, blinded, notes)
                   VALUES ($1, $2, $3, false, true, $4)
                   ON CONFLICT (scenario_id) DO NOTHING""",
                sid,
                str(s.get("section") or "AQ")[:8],
                str(s.get("client_says") or "")[:2000],
                str(s.get("title") or "")[:200] or None,
            )
            inserted += 1

        # Fallback: bank keys not already in gold
        if existing + inserted < target:
            still = target - (existing + inserted)
            rows = await conn.fetch(
                """SELECT scenario_key, section, COALESCE(client_says,'') AS client_says
                   FROM six_quotient_scenario_bank
                   WHERE status IN ('approved', 'pending_review')
                     AND scenario_key NOT IN (SELECT scenario_id FROM six_quotient_human_gold)
                   ORDER BY section, scenario_key
                   LIMIT $1""",
                still + 5,
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
        scored = await conn.fetchval(
            "SELECT COUNT(*) FROM six_quotient_human_gold WHERE human_scored"
        )
        print(
            f"seeded≈{inserted} total_rows={total} scored={scored} "
            f"(clinician scoring still required for D.14b)"
        )
        return 0
    except Exception as e:
        print(f"FAIL: {e}")
        return 2
    finally:
        await conn.close()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_main()))
