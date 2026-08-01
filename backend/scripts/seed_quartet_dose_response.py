#!/usr/bin/env python3
"""
Seed the quartet_dose_response_v1 scoring queue: 8 rows (4 scenarios x 2
conditions), interleaved by scenario, before/after pairs adjacent.

Read-only against generation data, write-only to the scoring queue:

  - "after_affinity_fix" rows: SELECT-only snapshot of
    six_quotient_human_gold.nate_response_live for the given --after-run-id.
    Never writes back to six_quotient_human_gold.
  - "before_no_affinity" rows: ingested from the recovered transcript file
    (backend/app/data/recovered_transcripts/) because the original DB row
    was overwritten in-place by the later regeneration (UNIQUE(scenario_id)
    on six_quotient_human_gold — one row per scenario, not one per run).

Idempotent: re-running with the same --session-label upserts on
(session_label, scenario_id, condition_label) rather than duplicating rows.
Scores already recorded on existing rows are preserved (ON CONFLICT only
touches the generation-derived columns, never the scoring columns).

Usage (inside the backend container, matches production DATABASE_URL):
    python /app/scripts/seed_quartet_dose_response.py \\
        --after-run-id fuel_burning_verify_20260801_affinity \\
        --before-transcript /app/app/data/recovered_transcripts/quartet_before_no_affinity_fuel_burning_verify_20260801.txt \\
        --before-original-run-id fuel_burning_verify_20260801
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

AFTER_QUERY = """
SELECT id, scenario_id, section, client_says, nate_response_live, live_stack_run_id,
       COALESCE(live_human_scored, false) AS live_human_scored
FROM six_quotient_human_gold
WHERE scenario_id = ANY($1::text[])
  AND live_stack_run_id = $2
"""

STATIC_QUERY = """
SELECT scenario_id, section, client_says
FROM six_quotient_human_gold
WHERE scenario_id = ANY($1::text[])
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


def parse_transcript(path: str) -> Dict[str, str]:
    """SCENARIO_ID|response text, one line per scenario -> {scenario_id: text}."""
    out: Dict[str, str] = {}
    p = Path(path)
    if not p.exists():
        print(f"ERROR: transcript not found: {path}", file=sys.stderr)
        sys.exit(2)
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.rstrip("\n")
        if not line.strip() or "|" not in line:
            continue
        sid, _, text = line.partition("|")
        sid = sid.strip()
        if sid in QUARTET_SCENARIOS:
            out[sid] = text.strip()
    return out


async def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--session-label", default="quartet_dose_response_v1")
    ap.add_argument("--after-run-id", required=True, help="live_stack_run_id for the post-fix regeneration")
    ap.add_argument("--before-transcript", required=True, help="path to recovered SCENARIO_ID|text file")
    ap.add_argument(
        "--before-original-run-id",
        required=True,
        help="the run_id the before-rows were originally generated under (for provenance, not a live lookup)",
    )
    ap.add_argument(
        "--before-source-note",
        default=None,
        help="free-text provenance note; default auto-generated from --before-original-run-id",
    )
    args = ap.parse_args()

    if asyncpg is None:
        print("ERROR: asyncpg not installed", file=sys.stderr)
        return 2

    before_texts = parse_transcript(args.before_transcript)
    missing_before = [s for s in QUARTET_SCENARIOS if s not in before_texts]
    if missing_before:
        print(f"ERROR: transcript missing scenarios: {missing_before}", file=sys.stderr)
        return 2

    try:
        conn = await asyncpg.connect(_dsn())
    except Exception as e:
        print(f"ERROR: could not connect to database: {e}", file=sys.stderr)
        return 2

    try:
        after_rows = await conn.fetch(AFTER_QUERY, QUARTET_SCENARIOS, args.after_run_id)
        after_by_scenario: Dict[str, Any] = {r["scenario_id"]: r for r in after_rows}
        missing_after = [s for s in QUARTET_SCENARIOS if s not in after_by_scenario]
        if missing_after:
            print(
                f"ERROR: live_stack_run_id={args.after_run_id!r} missing scenarios "
                f"in six_quotient_human_gold: {missing_after} (regenerate first)",
                file=sys.stderr,
            )
            return 2
        for sid, row in after_by_scenario.items():
            if not (row["nate_response_live"] or "").strip():
                print(f"ERROR: {sid} has empty nate_response_live for run {args.after_run_id!r}", file=sys.stderr)
                return 2
            if row["live_human_scored"]:
                print(
                    f"ERROR: {sid} (id={row['id']}) already has live_human_scored=true for run "
                    f"{args.after_run_id!r} — the pull query only serves unscored rows "
                    "(live_human_scored = false) so the dose-response queue never diverges "
                    "from the live capability-track scoring state. Use an unscored run.",
                    file=sys.stderr,
                )
                return 2

        static_rows = await conn.fetch(STATIC_QUERY, QUARTET_SCENARIOS)
        static_by_scenario: Dict[str, Any] = {r["scenario_id"]: r for r in static_rows}

        note = args.before_source_note or (
            f"Recovered from transcript snapshot; original live_stack_run_id="
            f"{args.before_original_run_id!r} was overwritten in six_quotient_human_gold "
            f"by a later regeneration (UNIQUE(scenario_id) — one row per scenario). "
            f"See backend/app/data/recovered_transcripts/PROVENANCE.md."
        )

        sort_order = 0
        inserted: List[str] = []
        async with conn.transaction():
            for sid in QUARTET_SCENARIOS:
                static = static_by_scenario.get(sid, {})
                # before (recovered) — condition adjacent to its after pair
                await conn.execute(
                    UPSERT,
                    args.session_label,
                    sid,
                    static.get("section"),
                    static.get("client_says"),
                    "before_no_affinity",
                    before_texts[sid],
                    "recovered_transcript",
                    args.before_original_run_id,
                    note,
                    sort_order,
                )
                sort_order += 1
                # after (live snapshot, read-only)
                after_row = after_by_scenario[sid]
                await conn.execute(
                    UPSERT,
                    args.session_label,
                    sid,
                    after_row["section"] or static.get("section"),
                    after_row["client_says"] or static.get("client_says"),
                    "after_affinity_fix",
                    after_row["nate_response_live"],
                    "live_snapshot",
                    args.after_run_id,
                    f"Read-only snapshot of nate_response_live at seed time "
                    f"(six_quotient_human_gold.id={after_row['id']}, "
                    f"live_stack_run_id={args.after_run_id!r}, live_human_scored=false "
                    f"at snapshot time); never written back.",
                    sort_order,
                )
                sort_order += 1
                inserted.append(sid)

        count = await conn.fetchval(
            "SELECT COUNT(*)::int FROM quartet_dose_response_queue WHERE session_label = $1",
            args.session_label,
        )
        print(f"OK: seeded/updated {len(inserted) * 2} rows for session_label={args.session_label!r}")
        print(f"    scenarios: {inserted}")
        print(f"    total rows now in queue for this session: {count}")
        return 0
    finally:
        await conn.close()


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
