#!/usr/bin/env python3
"""
Fresh held-out κ evaluation against the v2 six-quotient battery only
(TRUST_LEDGER.md Entries 29-34; docs/TIER1_HUMAN_GOLD_WORKSHEET.md).

WHY THIS IS A SEPARATE SCRIPT, NOT A FLAG ON compute_tier1_gold_kappa.py:

compute_tier1_gold_kappa.py's load_scored_gold() (tier1_gold_evidence.py)
selects every human_scored=true row in six_quotient_human_gold with no
version filter. The v2 battery (70 stems, scenario_ids *-V01..*-V12) was
built specifically to be FRESH judge-recertification fuel -- material the
judge prompt has never been tuned against. If v2 rows get scored and then
folded into a routine compute_tier1_gold_kappa.py run (which defaults to
gold_locked=True and therefore becomes the number
clinical_tier1_competence_gate_check.py reads for the live D.14b gate),
the fresh set is silently burned/mixed with v1's already-used-for-tuning
rows -- the exact contamination pattern compute_tier1_v5_fresh_holdout_kappa.py
exists to prevent for v5 (see that file's docstring + TRUST_LEDGER Entry 6).

This script mirrors that precedent for the v2 battery:
  - Scoped by scenario_id ~ '-V(0[1-9]|1[0-2])$' (schema-level, not a
    hand-maintained id list -- v1 stems use bare "-N" ids, no collision).
  - Judge track only (nate_response / primary/accuracy/naturalness),
    matching compute_tier1_gold_kappa.py's convention -- kappa measures the
    judge's agreement with the clinician on the judge track, not the
    capability/live track.
  - --judge-id has NO default. TRUST_LEDGER Entry 4 documented a real
    incident where a stale default judge-id mislabeled an evidence row.
    Callers must say explicitly which judge version this run evaluates.
  - gold_locked=False by DEFAULT (informational; excluded from the D.14b
    certification gate). Pass --gold-locked to opt this run into counting
    toward certification -- a deliberate choice, never automatic.

Usage (inside nate_backend, PYTHONPATH=/app):
  python /app/scripts/compute_tier1_v2_battery_holdout_kappa.py --judge-id grok-judge-v7 --dry-run
  python /app/scripts/compute_tier1_v2_battery_holdout_kappa.py --judge-id grok-judge-v7
  python /app/scripts/compute_tier1_v2_battery_holdout_kappa.py --judge-id grok-judge-v7 --gold-locked
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys

if "/app" not in sys.path and os.path.isdir("/app/app"):
    sys.path.insert(0, "/app")

# Schema-level scope, not a hand-maintained id list. v1 stems use bare
# "-N" scenario_ids (e.g. AQ-1); v2 stems always end in -V01..-V12
# (confirmed collision-free against v1 at build time, TRUST_LEDGER Entry 29).
V2_BATTERY_ID_RE = r"-V(0[1-9]|1[0-2])$"


async def _load_v2_scored_items(conn):
    rows = await conn.fetch(
        f"""SELECT scenario_id, section, client_says, nate_response,
                   response_class, difficulty, is_degraded_distractor,
                   primary_score, accuracy_score, naturalness_score,
                   provenance
            FROM six_quotient_human_gold
            WHERE scenario_id ~ '{V2_BATTERY_ID_RE}'
              AND human_scored = true
              AND pairs_locked = true
              AND primary_score IS NOT NULL
              AND accuracy_score IS NOT NULL
              AND naturalness_score IS NOT NULL
              AND COALESCE(nate_response, '') <> ''
              AND nate_response NOT ILIKE '%DRY-RUN%'
              AND nate_response NOT ILIKE '%Placeholder Nate reply%'
            ORDER BY scenario_id"""
    )
    return [dict(r) for r in rows]


async def _v2_battery_totals(conn) -> dict:
    row = await conn.fetchrow(
        f"""SELECT COUNT(*)::int AS total,
                   COUNT(*) FILTER (WHERE human_scored)::int AS scored
            FROM six_quotient_human_gold
            WHERE scenario_id ~ '{V2_BATTERY_ID_RE}'"""
    )
    return dict(row) if row else {"total": 0, "scored": 0}


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
    parser.add_argument(
        "--judge-id",
        default="",
        required=False,
        help="Required. No default — TRUST_LEDGER Entry 4 (stale-default mislabeling incident).",
    )
    parser.add_argument("--min-items", type=int, default=1)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--gold-locked",
        action="store_true",
        help="Opt this run into the D.14b certification gate. Default off "
        "(informational-only, matches compute_tier1_v5_fresh_holdout_kappa.py precedent).",
    )
    args = parser.parse_args()

    if not args.judge_id.strip():
        print("FAIL: --judge-id is required (e.g. grok-judge-v7) — no default on purpose")
        return 2

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
        totals = await _v2_battery_totals(conn)
        items = await _load_v2_scored_items(conn)
        print(
            f"v2 battery: {totals.get('scored', 0)}/{totals.get('total', 0)} scored total; "
            f"{len(items)} pass the score-complete/locked/non-placeholder filter"
        )
        if len(items) < args.min_items:
            print(f"FAIL: {len(items)} scored v2 items < --min-items {args.min_items}")
            return 1

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
            judge_id=args.judge_id.strip(),
            aggregate_kappa=agg,
            per_dimension=per,
            n_items=len(used),
            safety_veto_ok=ok,
            safety_miss_count=miss_n,
            safety_miss_ids=miss_ids,
            notes=(
                f"v2 battery ({V2_BATTERY_ID_RE}) fresh held-out eval, "
                f"n={len(used)}. gold_locked={bool(args.gold_locked)}. "
                f"misses={miss_ids}"
            ),
            gold_locked=bool(args.gold_locked),
        )
        print(
            f"OK: evidence_id={eid} gold_locked={bool(args.gold_locked)} "
            f"({'COUNTS toward D.14b gate' if args.gold_locked else 'excluded from D.14b gate'})"
        )
        return 0
    except Exception as e:
        print(f"FAIL: {e}")
        return 2
    finally:
        await conn.close()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_main()))
