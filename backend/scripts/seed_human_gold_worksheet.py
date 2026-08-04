#!/usr/bin/env python3
"""
Seed human-gold worksheet rows from curated stem JSON (v1 + v2).

Prefers backend/app/data/six_quotient_human_gold_stems_v{1,2}.json, then
scenario bank for soft-target fill. Does NOT invent clinician scores.

v2 stems may carry scoring_guide (rater-only expected-moves rubric). That
column is never selected by response-generation paths — see
test_v2_battery_scoring_guide_isolation.py.

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
    """Load and merge all versioned stem batches (v1 + v2, additive).

    v2 (backend/app/data/six_quotient_human_gold_stems_v2.json) carries a
    clinician-authored `scoring_guide` field (the rater's expected-moves
    rubric) that is intentionally NOT read by any response-generation code
    path -- see test_v2_battery_scoring_guide_isolation.py. Do not add
    scoring_guide (or its content) to any SELECT used to build a generation
    prompt.
    """
    filenames = [
        "six_quotient_human_gold_stems_v1.json",
        "six_quotient_human_gold_stems_v2.json",
    ]
    roots = [
        Path(__file__).resolve().parents[1] / "app" / "data",
        Path("/app/app/data"),
        Path("/app/data"),
    ]
    merged: list = []
    seen_ids: set = set()
    for name in filenames:
        for root in roots:
            p = root / name
            if not p.is_file():
                continue
            data = json.loads(p.read_text())
            for s in data.get("stems") or []:
                sid = str(s.get("scenario_id") or "").strip()
                if not sid or sid in seen_ids:
                    continue
                seen_ids.add(sid)
                merged.append(s)
            break  # first matching root wins for this filename
    return merged


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

    # Soft ceiling for bank-fallback only. Curated stem files always upsert
    # regardless of count (v2 battery grows past the original 50).
    target = int(os.getenv("HUMAN_GOLD_TARGET", "120"))
    conn = await asyncpg.connect(dsn)
    try:
        stems = _load_stems()
        has_scoring_guide = False
        try:
            has_scoring_guide = bool(
                await conn.fetchval(
                    """SELECT 1 FROM information_schema.columns
                       WHERE table_name = 'six_quotient_human_gold'
                         AND column_name = 'scoring_guide'"""
                )
            )
        except Exception:
            has_scoring_guide = False

        # Always upsert curated stems (v1+v2). scoring_guide is rater-only
        # metadata — never read by fill_human_gold_nate_responses /
        # live_stack_blinds generation SELECTs.
        synced = 0
        inserted = 0
        for s in stems:
            sid = str(s.get("scenario_id") or "").strip()
            if not sid:
                continue
            section = str(s.get("section") or "AQ")[:8]
            client_says = str(s.get("client_says") or "")[:8000]
            title = str(s.get("title") or "")[:200] or None
            provenance = str(s.get("provenance") or "unknown_requires_label")[:80]
            response_class = str(s.get("response_class") or "therapeutic_engage")[:40]
            difficulty = str(s.get("difficulty") or "medium")[:20]
            author = str(s.get("author") or "")[:300] or None
            scoring_guide = str(s.get("scoring_guide") or "")[:8000] or None
            try:
                if has_scoring_guide:
                    status = await conn.execute(
                        """INSERT INTO six_quotient_human_gold
                           (scenario_id, section, client_says, human_scored, blinded, notes,
                            provenance, response_class, difficulty, author_note, scoring_guide)
                           VALUES ($1, $2, $3, false, true, $4, $5, $6, $7, $8, $9)
                           ON CONFLICT (scenario_id) DO UPDATE SET
                             provenance = EXCLUDED.provenance,
                             response_class = EXCLUDED.response_class,
                             difficulty = EXCLUDED.difficulty,
                             author_note = COALESCE(EXCLUDED.author_note, six_quotient_human_gold.author_note),
                             notes = COALESCE(EXCLUDED.notes, six_quotient_human_gold.notes),
                             scoring_guide = COALESCE(EXCLUDED.scoring_guide, six_quotient_human_gold.scoring_guide),
                             client_says = CASE
                               WHEN COALESCE(six_quotient_human_gold.pairs_locked, false)
                               THEN six_quotient_human_gold.client_says
                               ELSE EXCLUDED.client_says
                             END
                           WHERE six_quotient_human_gold.human_scored = false""",
                        sid,
                        section,
                        client_says,
                        title,
                        provenance,
                        response_class,
                        difficulty,
                        author,
                        scoring_guide,
                    )
                else:
                    status = await conn.execute(
                        """INSERT INTO six_quotient_human_gold
                           (scenario_id, section, client_says, human_scored, blinded, notes,
                            provenance, response_class, difficulty, author_note)
                           VALUES ($1, $2, $3, false, true, $4, $5, $6, $7, $8)
                           ON CONFLICT (scenario_id) DO UPDATE SET
                             provenance = EXCLUDED.provenance,
                             response_class = EXCLUDED.response_class,
                             difficulty = EXCLUDED.difficulty,
                             author_note = COALESCE(EXCLUDED.author_note, six_quotient_human_gold.author_note),
                             notes = COALESCE(EXCLUDED.notes, six_quotient_human_gold.notes),
                             client_says = CASE
                               WHEN COALESCE(six_quotient_human_gold.pairs_locked, false)
                               THEN six_quotient_human_gold.client_says
                               ELSE EXCLUDED.client_says
                             END
                           WHERE six_quotient_human_gold.human_scored = false""",
                        sid,
                        section,
                        client_says,
                        title,
                        provenance,
                        response_class,
                        difficulty,
                        author,
                    )
            except Exception:
                status = await conn.execute(
                    """INSERT INTO six_quotient_human_gold
                       (scenario_id, section, client_says, human_scored, blinded, notes)
                       VALUES ($1, $2, $3, false, true, $4)
                       ON CONFLICT (scenario_id) DO NOTHING""",
                    sid,
                    section,
                    client_says[:2000],
                    title,
                )
            if status and ("INSERT" in status or "UPDATE" in status):
                if status.startswith("INSERT") and status.endswith("1"):
                    inserted += 1
                elif "UPDATE" in status and status.endswith("1"):
                    synced += 1

        # Fallback: bank keys not already in gold (soft target only)
        total_now = int(
            await conn.fetchval("SELECT COUNT(*) FROM six_quotient_human_gold") or 0
        )
        if total_now < target:
            still = target - total_now
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
                total_now = int(
                    await conn.fetchval("SELECT COUNT(*) FROM six_quotient_human_gold")
                    or 0
                )
                if total_now >= target:
                    break
                status = await conn.execute(
                    """INSERT INTO six_quotient_human_gold
                       (scenario_id, section, client_says, human_scored, blinded)
                       VALUES ($1, $2, $3, false, true)
                       ON CONFLICT (scenario_id) DO NOTHING""",
                    r["scenario_key"],
                    r["section"],
                    (r["client_says"] or "")[:2000],
                )
                if status and status.endswith("1"):
                    inserted += 1

        total = await conn.fetchval("SELECT COUNT(*) FROM six_quotient_human_gold")
        scored = await conn.fetchval(
            "SELECT COUNT(*) FROM six_quotient_human_gold WHERE human_scored"
        )
        print(
            f"seeded≈{inserted} synced≈{synced} curated_stems={len(stems)} "
            f"scoring_guide_col={has_scoring_guide} total_rows={total} scored={scored} "
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
