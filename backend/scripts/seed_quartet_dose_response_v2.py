#!/usr/bin/env python3
"""
Seed quartet_dose_response_v2 scoring queue (must-sequence pack format hypothesis).

8 rows = 4 scenarios × 2 conditions:
  - before_compound_must: snapshot from quartet_dose_response_v1 after_affinity_fix
    (affinity-ranked guides + compound ∧ MUST — the 0-for-40 structural baseline)
  - after_must_sequence_pack: live snapshot from six_quotient_human_gold for
    --after-run-id (regenerated with LN7_MUST_SEQUENCE_PACK_LIVE=true)

Does not write scores. Idempotent upsert on (session_label, scenario_id, condition_label).

Usage (inside nate_backend after regeneration):
  python /app/scripts/seed_quartet_dose_response_v2.py \\
      --after-run-id dose_response_v2_must_sequence_20260803
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path
from typing import Any, Dict, List

try:
    import asyncpg  # type: ignore
except ImportError:
    asyncpg = None  # type: ignore

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.quartet_spine_moves import QUARTET_SCENARIOS  # noqa: E402

SESSION_DEFAULT = "quartet_dose_response_v2"
BEFORE_SOURCE_SESSION = "quartet_dose_response_v1"
BEFORE_SOURCE_CONDITION = "after_affinity_fix"
BEFORE_CONDITION = "before_compound_must"
AFTER_CONDITION = "after_must_sequence_pack"

BEFORE_QUERY = """
SELECT scenario_id, section, client_says, response_text, original_run_id
FROM quartet_dose_response_queue
WHERE session_label = $1
  AND condition_label = $2
  AND scenario_id = ANY($3::text[])
"""

AFTER_QUERY = """
SELECT id, scenario_id, section, client_says, nate_response_live, live_stack_run_id,
       COALESCE(live_human_scored, false) AS live_human_scored
FROM six_quotient_human_gold
WHERE scenario_id = ANY($1::text[])
  AND live_stack_run_id = $2
"""

UPSERT = """
INSERT INTO quartet_dose_response_queue
    (session_label, scenario_id, section, client_says, condition_label,
     response_text, source, original_run_id, text_provenance, sort_order)
VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
ON CONFLICT (session_label, scenario_id, condition_label) DO UPDATE SET
    section = EXCLUDED.section,
    client_says = EXCLUDED.client_says,
    response_text = EXCLUDED.response_text,
    source = EXCLUDED.source,
    original_run_id = EXCLUDED.original_run_id,
    text_provenance = EXCLUDED.text_provenance,
    sort_order = EXCLUDED.sort_order
"""


def _dsn() -> str:
    return (
        os.getenv("DATABASE_URL")
        or os.getenv("POSTGRES_DSN")
        or "postgresql://nate_admin@localhost:5432/little_nate"
    )


async def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--session-label", default=SESSION_DEFAULT)
    ap.add_argument("--after-run-id", required=True)
    ap.add_argument("--before-source-session", default=BEFORE_SOURCE_SESSION)
    ap.add_argument("--before-source-condition", default=BEFORE_SOURCE_CONDITION)
    args = ap.parse_args()

    if asyncpg is None:
        print("ERROR: asyncpg not installed", file=sys.stderr)
        return 2

    try:
        conn = await asyncpg.connect(_dsn())
    except Exception as e:
        print(f"ERROR: could not connect: {e}", file=sys.stderr)
        return 2

    try:
        before_rows = await conn.fetch(
            BEFORE_QUERY,
            args.before_source_session,
            args.before_source_condition,
            QUARTET_SCENARIOS,
        )
        before_by: Dict[str, Any] = {r["scenario_id"]: r for r in before_rows}
        missing_before = [s for s in QUARTET_SCENARIOS if s not in before_by]
        if missing_before:
            print(
                f"ERROR: missing before rows from {args.before_source_session!r}/"
                f"{args.before_source_condition!r}: {missing_before}",
                file=sys.stderr,
            )
            return 2

        after_rows = await conn.fetch(AFTER_QUERY, QUARTET_SCENARIOS, args.after_run_id)
        after_by: Dict[str, Any] = {r["scenario_id"]: r for r in after_rows}
        missing_after = [s for s in QUARTET_SCENARIOS if s not in after_by]
        if missing_after:
            print(
                f"ERROR: live_stack_run_id={args.after_run_id!r} missing "
                f"scenarios: {missing_after}",
                file=sys.stderr,
            )
            return 2
        for sid, row in after_by.items():
            if not (row["nate_response_live"] or "").strip():
                print(f"ERROR: {sid} empty nate_response_live", file=sys.stderr)
                return 2
            if row["live_human_scored"]:
                print(
                    f"ERROR: {sid} already live_human_scored=true — use unscored run",
                    file=sys.stderr,
                )
                return 2

        sort_order = 0
        inserted: List[str] = []
        async with conn.transaction():
            for sid in QUARTET_SCENARIOS:
                b = before_by[sid]
                a = after_by[sid]
                await conn.execute(
                    UPSERT,
                    args.session_label,
                    sid,
                    b["section"],
                    b["client_says"],
                    BEFORE_CONDITION,
                    b["response_text"],
                    "live_snapshot",
                    b["original_run_id"] or args.before_source_session,
                    (
                        f"v2 before = v1 {args.before_source_condition} snapshot "
                        f"(compound MUST + affinity); source_session="
                        f"{args.before_source_session!r}"
                    ),
                    sort_order,
                )
                sort_order += 1
                await conn.execute(
                    UPSERT,
                    args.session_label,
                    sid,
                    a["section"] or b["section"],
                    a["client_says"] or b["client_says"],
                    AFTER_CONDITION,
                    a["nate_response_live"],
                    "live_snapshot",
                    args.after_run_id,
                    (
                        f"v2 after = must-sequence pack regen; "
                        f"gold.id={a['id']}, live_stack_run_id={args.after_run_id!r}, "
                        f"LN7_MUST_SEQUENCE_PACK_LIVE=true at generation"
                    ),
                    sort_order,
                )
                sort_order += 1
                inserted.append(sid)

        count = await conn.fetchval(
            "SELECT COUNT(*)::int FROM quartet_dose_response_queue WHERE session_label = $1",
            args.session_label,
        )
        print(f"OK: seeded {len(inserted) * 2} rows session_label={args.session_label!r}")
        print(f"    conditions: {BEFORE_CONDITION} / {AFTER_CONDITION}")
        print(f"    scenarios: {inserted}")
        print(f"    queue total for session: {count}")
        return 0
    finally:
        await conn.close()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
