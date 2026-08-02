#!/usr/bin/env python3
"""
Write back the 4 dose-response "after_affinity_fix" scores into
six_quotient_human_gold, so the Principal-Review capability-track queue
stops re-serving already-scored text as unscored.

Background (TRUST_LEDGER.md Entry 10): the dose-response seed step copied
AQ-1/AQ-2/AQ-G07/AQ-G08's nate_response_live text out of
six_quotient_human_gold into quartet_dose_response_queue
(condition_label='after_affinity_fix', source='live_snapshot') for the
8-row move-level sitting, but never wrote live_human_scored=true back onto
the source rows. Those 4 gold rows therefore still show as unscored in the
capability-track UI, even though the identical text was already
human-scored (at move-level, in the dose-response queue) on 2026-08-02.

This script is a targeted, auditable UPDATE — not a bulk migration. It:
  1. Joins the 4 after_affinity_fix dose-response rows to their gold rows
     by scenario_id.
  2. Refuses to write back unless nate_response_live == response_text
     EXACTLY (the safety check that makes this a legitimate port rather
     than a guess). Any mismatch aborts the whole run with no writes.
  3. Refuses to overwrite a gold row that is already live_human_scored=true
     (idempotent / non-destructive on rerun).
  4. Sets live_scored_via='dose_response_queue' (migration 318) so the
     provenance is queryable, not just inferable from timestamps.

Usage:
    python3 writeback_dose_response_to_live_gold.py            # dry run (default)
    python3 writeback_dose_response_to_live_gold.py --apply    # actually write

Run inside the backend container on GREEN so DATABASE_URL / asyncpg match
production (see docker-compose-prod-file.mdc):
    docker compose -f docker-compose.prod.yml exec -T backend \\
        python /app/scripts/writeback_dose_response_to_live_gold.py --apply
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys

import asyncpg


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Actually write. Without this flag, only prints what would happen.",
    )
    args = parser.parse_args()

    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        print("ERROR: DATABASE_URL not set.", file=sys.stderr)
        return 2

    conn = await asyncpg.connect(database_url)
    try:
        rows = await conn.fetch(
            """
            SELECT
                q.scenario_id,
                q.primary_score, q.accuracy_score, q.naturalness_score,
                q.safety_veto, q.notes,
                q.rater_id, q.scored_at, q.score_session_id,
                q.gold_admin_run_id, q.score_latency_ms,
                g.live_human_scored AS gold_already_scored,
                g.nate_response_live = q.response_text AS text_exact_match,
                g.live_scored_via AS gold_existing_provenance
            FROM quartet_dose_response_queue q
            JOIN six_quotient_human_gold g
              ON g.scenario_id = q.scenario_id
            WHERE q.condition_label = 'after_affinity_fix'
              AND q.human_scored = true
            ORDER BY q.scenario_id
            """
        )

        if len(rows) != 4:
            print(
                f"ERROR: expected 4 scored after_affinity_fix rows, found {len(rows)}. "
                "Aborting -- this script is hard-coded to the known AQ-1/AQ-2/AQ-G07/AQ-G08 set.",
                file=sys.stderr,
            )
            return 2

        plan = []
        for r in rows:
            sid = r["scenario_id"]
            if not r["text_exact_match"]:
                print(
                    f"ERROR: {sid} -- nate_response_live does NOT exactly match "
                    "quartet_dose_response_queue.response_text. Refusing to write back "
                    "(this would be porting a score onto the wrong text). Aborting all 4.",
                    file=sys.stderr,
                )
                return 2
            if r["gold_already_scored"]:
                print(
                    f"SKIP: {sid} -- six_quotient_human_gold.live_human_scored is already true "
                    f"(live_scored_via={r['gold_existing_provenance']!r}). Not overwriting."
                )
                continue
            plan.append(r)

        if not plan:
            print("Nothing to do -- all 4 rows already ported or already scored. Exiting.")
            return 0

        print(f"Plan: write back {len(plan)} row(s):")
        for r in plan:
            print(
                f"  {r['scenario_id']}: primary={r['primary_score']} "
                f"accuracy={r['accuracy_score']} naturalness={r['naturalness_score']} "
                f"veto={r['safety_veto']} rater={r['rater_id']} "
                f"scored_at={r['scored_at']}"
            )

        if not args.apply:
            print("\nDry run only -- no writes made. Re-run with --apply to commit.")
            return 0

        async with conn.transaction():
            for r in plan:
                result = await conn.execute(
                    """
                    UPDATE six_quotient_human_gold
                    SET live_primary_score = $2,
                        live_accuracy_score = $3,
                        live_naturalness_score = $4,
                        live_safety_veto = $5,
                        live_notes = $6,
                        live_human_scored = true,
                        live_rater_id = $7,
                        live_scored_at = $8,
                        live_score_session_id = $9,
                        live_gold_admin_run_id = $10,
                        live_score_latency_ms = $11,
                        live_scored_via = 'dose_response_queue'
                    WHERE scenario_id = $1
                      AND live_human_scored = false
                    """,
                    r["scenario_id"],
                    r["primary_score"],
                    r["accuracy_score"],
                    r["naturalness_score"],
                    r["safety_veto"],
                    r["notes"],
                    r["rater_id"],
                    r["scored_at"],
                    r["score_session_id"],
                    r["gold_admin_run_id"],
                    r["score_latency_ms"],
                )
                # asyncpg execute() returns "UPDATE n"
                n = int(result.split()[-1])
                if n != 1:
                    raise RuntimeError(
                        f"{r['scenario_id']}: expected to update exactly 1 row, updated {n}. "
                        "Aborting transaction -- see race condition or scenario_id collision."
                    )
                print(f"  WROTE: {r['scenario_id']}")

        print(f"\nDone. {len(plan)} row(s) written back with live_scored_via='dose_response_queue'.")
        return 0
    finally:
        await conn.close()


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
