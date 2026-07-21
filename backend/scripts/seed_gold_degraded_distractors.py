#!/usr/bin/env python3
"""
Seed ~10 degraded distractor responses into six_quotient_human_gold.

Does NOT set human_scored. Overwrites nate_response only when
pairs_locked=false and (empty response OR already a distractor).

Usage:
  DATABASE_URL=... python3 backend/scripts/seed_gold_degraded_distractors.py
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path


def _load() -> list:
    candidates = [
        Path(__file__).resolve().parents[1]
        / "app"
        / "data"
        / "six_quotient_gold_degraded_distractors_v1.json",
        Path("/app/app/data/six_quotient_gold_degraded_distractors_v1.json"),
    ]
    for p in candidates:
        if p.is_file():
            return list(json.loads(p.read_text()).get("distractors") or [])
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
    items = _load()
    if not items:
        print("FAIL: distractor file missing")
        return 2
    conn = await asyncpg.connect(dsn)
    try:
        updated = 0
        missing = 0
        for d in items:
            sid = str(d.get("scenario_id") or "").strip()
            resp = str(d.get("nate_response") or "").strip()
            if not sid or not resp:
                continue
            try:
                status = await conn.execute(
                    """UPDATE six_quotient_human_gold
                       SET nate_response = $2,
                           response_provenance = 'degraded_distractor_seeded',
                           is_degraded_distractor = true,
                           notes = COALESCE(notes, '') ||
                             CASE WHEN COALESCE(notes,'') = '' THEN '' ELSE ' | ' END ||
                             'degraded:' || $3::text
                       WHERE scenario_id = $1
                         AND COALESCE(pairs_locked, false) = false
                         AND human_scored = false
                         AND (
                           COALESCE(nate_response, '') = ''
                           OR is_degraded_distractor = true
                           OR response_provenance = 'unset'
                         )""",
                    sid,
                    resp[:4000],
                    str(d.get("degradation_type") or "unspecified")[:80],
                )
            except Exception as e:
                print(f"FAIL: {e} (apply migration 259)")
                return 2
            if status and status.endswith("1"):
                updated += 1
            else:
                # row may not exist
                exists = await conn.fetchval(
                    "SELECT 1 FROM six_quotient_human_gold WHERE scenario_id=$1",
                    sid,
                )
                if not exists:
                    missing += 1
        deg = await conn.fetchval(
            "SELECT COUNT(*) FROM six_quotient_human_gold WHERE is_degraded_distractor"
        )
        filled = await conn.fetchval(
            """SELECT COUNT(*) FROM six_quotient_human_gold
               WHERE COALESCE(nate_response,'') <> ''"""
        )
        print(
            f"distractors_updated={updated} missing_rows={missing} "
            f"degraded_total={deg} with_response={filled}/50"
        )
        return 0
    finally:
        await conn.close()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_main()))
