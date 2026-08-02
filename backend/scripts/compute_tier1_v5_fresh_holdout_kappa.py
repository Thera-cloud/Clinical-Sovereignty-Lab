#!/usr/bin/env python3
"""
Judge-v5 FRESH held-out evaluation (D.14b certification remediation,
post-Entry-6/7/8/9 restart).

This is deliberately a separate script from compute_tier1_holdout_kappa.py,
not a --judge-id flag change on it, because the two runs draw from
overlapping-but-not-identical pools and conflating them in one script
invites exactly the silent-relabeling failure this file exists to prevent
(TRUST_LEDGER.md Entry 6's note on compute_tier1_holdout_kappa.py's own
--judge-id default).

WHY THIS SET EXCLUDES ROWS THE NAIVE QUERY WOULD INCLUDE
(TRUST_LEDGER.md Entry 10):

The original n=9 held-out set (compute_tier1_holdout_kappa.py) was used
as v4-failure error-analysis material to write JUDGE_SYSTEM_PROMPT_V5
(Entry 6). All 9 of those items are therefore burned for v5 evaluation --
scoring v5 against material it was revised against is the exact leak
this project spent a week catching in v4. That set was:
  - AQ-1, AQ-2, AQ-G07, AQ-G08 x {before_no_affinity, after_affinity_fix}
    (8 rows, quartet_dose_response_queue)
  - MQ-2 (1 row, six_quotient_human_gold live-track;
    named explicitly in Entry 6's mechanism table as one of the five
    "all overscored" disagreement rows that motivated the anti-mirror-
    warmth guardrail)

This script's held-out pool is six_quotient_human_gold live-track rows
ONLY (the quartet table is not queried at all here -- those 4 scenario_ids
never had a "fresh" live row to draw from once the dose-response
after-condition duplicate is excluded). Two independent exclusion
mechanisms apply, logged separately so a reviewer can audit each:

  1. live_scored_via IS NULL -- excludes AQ-1/AQ-2/AQ-G07/AQ-G08's
     live rows, which migration 318 + writeback_dose_response_to_live_gold.py
     flag with live_scored_via='dose_response_queue' once ported. This is
     an exclusion by construction (schema-enforced), not a hand-maintained
     id list -- the whole point per the original instruction.
  2. scenario_id NOT IN (_BURNED_SCENARIO_IDS) -- excludes MQ-2 by name,
     because MQ-2 was never "ported" (no duplicate-row problem), it was
     scored once and then used as v5 revision material directly. No
     schema flag distinguishes that case; a literal exclusion list is the
     only honest mechanism here, and it is confined to this one constant
     so it's auditable at a glance.

Usage (inside nate_backend, PYTHONPATH=/app):
  python /app/scripts/compute_tier1_v5_fresh_holdout_kappa.py --dry-run
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys

if "/app" not in sys.path and os.path.isdir("/app/app"):
    sys.path.insert(0, "/app")

# Exclusion mechanism 2 (see module docstring): scenario_ids burned by
# direct use as v5 error-analysis material, not by row-duplication.
# TRUST_LEDGER.md Entry 6, mechanism table.
_BURNED_SCENARIO_IDS = frozenset({"MQ-2"})


async def _load_fresh_holdout_items(conn):
    live_rows = await conn.fetch(
        """SELECT scenario_id, section, client_says,
                  nate_response_live AS nate_response, response_class,
                  is_degraded_distractor,
                  live_primary_score AS primary_score,
                  live_accuracy_score AS accuracy_score,
                  live_naturalness_score AS naturalness_score,
                  live_safety_veto AS safety_veto,
                  live_scored_via
           FROM six_quotient_human_gold
           WHERE live_human_scored = true
             AND live_primary_score IS NOT NULL
             AND live_accuracy_score IS NOT NULL
             AND live_naturalness_score IS NOT NULL
             AND COALESCE(nate_response_live, '') <> ''
             AND live_scored_via IS NULL
           ORDER BY scenario_id"""
    )

    items = []
    excluded_burned = []
    for r in live_rows:
        d = dict(r)
        if d["scenario_id"] in _BURNED_SCENARIO_IDS:
            excluded_burned.append(d["scenario_id"])
            continue
        d["scenario_id"] = f"{d['scenario_id']}::live"
        items.append(d)
    return items, excluded_burned


async def _count_excluded_ported(conn) -> int:
    row = await conn.fetchrow(
        """SELECT COUNT(*) AS n
           FROM six_quotient_human_gold
           WHERE live_human_scored = true
             AND live_scored_via IS NOT NULL"""
    )
    return int(row["n"])


async def _judge_all(items):
    from app.services.six_quotient_auto_judge import _llm_judge

    out = {}
    for g in items:
        sid = g["scenario_id"]
        judged = await _llm_judge(
            None,
            scenario_id=sid,
            section=str(g.get("section") or ""),
            rubric_focus=str(g.get("response_class") or ""),
            client_says=str(g.get("client_says") or ""),
            response=str(g.get("nate_response") or ""),
            degraded_distractor=bool(g.get("is_degraded_distractor")),
        )
        if not judged:
            print(f"FAIL judge: {sid}")
            return None
        out[sid] = {
            "primary": judged["primary"],
            "accuracy": judged["accuracy"],
            "naturalness": judged["naturalness"],
        }
        print(
            f"judged {sid}: {out[sid]}  "
            f"(human={g['primary_score']}/{g['accuracy_score']}/{g['naturalness_score']})"
        )
    return out


async def _main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--judge-id", default="grok-judge-v5")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    import asyncpg

    from app.services.tier1_gold_evidence import (
        KAPPA_METHOD,
        compute_safety_veto,
        mean_per_dimension_kappa,
        persist_kappa_evidence,
    )

    dsn = os.getenv("DATABASE_URL") or os.getenv("POSTGRES_DSN")
    if not dsn:
        print("FAIL: set DATABASE_URL")
        return 2

    conn = await asyncpg.connect(dsn)
    try:
        items, excluded_burned = await _load_fresh_holdout_items(conn)
        n_ported_excluded = await _count_excluded_ported(conn)

        if not items:
            print("FAIL: 0 fresh held-out items found (nothing to evaluate)")
            return 2

        print(
            f"fresh held-out set: {len(items)} live-track rows "
            f"(excluded {n_ported_excluded} ported dose-response row(s) via "
            f"live_scored_via, excluded {len(excluded_burned)} named-burned "
            f"row(s): {excluded_burned})"
        )

        judge_by = await _judge_all(items)
        if judge_by is None:
            return 1

        paired_g, paired_j, used = [], [], []
        for g in items:
            sid = g["scenario_id"]
            j = judge_by.get(sid)
            if not j:
                continue
            paired_g.append(
                {
                    "primary": int(g["primary_score"]),
                    "accuracy": int(g["accuracy_score"]),
                    "naturalness": int(g["naturalness_score"]),
                }
            )
            paired_j.append(j)
            used.append(sid)

        agg, per = mean_per_dimension_kappa(paired_g, paired_j)
        ok, miss_n, miss_ids = compute_safety_veto(items, judge_by)
        print(
            f"\nmethod={KAPPA_METHOD} n={len(used)} aggregate={agg} "
            f"per={per} safety_veto_ok={ok} misses={miss_n} {miss_ids}"
        )
        print(f"items scored: {used}")

        if args.dry_run:
            print("DRY-RUN: no insert")
            return 0

        eid = await persist_kappa_evidence(
            conn,
            judge_id=args.judge_id,
            aggregate_kappa=agg,
            per_dimension=per,
            n_items=len(used),
            safety_veto_ok=ok,
            safety_miss_count=miss_n,
            notes=(
                f"FRESH held-out eval of v5 (post Entry 6/7/8/9 restart), "
                f"n={len(used)} live-track rows. Excluded {n_ported_excluded} "
                f"dose-response-ported row(s) via live_scored_via flag "
                f"(migration 318) + {len(excluded_burned)} named-burned "
                f"row(s) {excluded_burned} (used as v5 error-analysis "
                f"material, Entry 6). misses={miss_ids}"
            ),
            gold_locked=False,
        )
        print(f"OK: evidence_id={eid} (gold_locked=false, excluded from certification gate)")
        return 0
    except Exception as e:
        print(f"FAIL: {e}")
        return 2
    finally:
        await conn.close()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_main()))
