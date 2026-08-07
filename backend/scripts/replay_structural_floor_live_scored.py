#!/usr/bin/env python3
"""Full-width structural floor replay vs live_safety_veto (TRUST_LEDGER Entry 41).

Replays verify_structural_floor on every live-scored gold row and reports
TP/TN/FP/FN vs human live_safety_veto, plus a miss taxonomy for FPs.

  fire = floor_met False  (floor would block / rewrite)
  human fail = safety_veto fail  (expect fire)
  human ok   = safety_veto ok    (expect quiet)

Usage (GREEN):
  PYTHONPATH=/app python /app/scripts/replay_structural_floor_live_scored.py
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List


async def _main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--out",
        default="",
        help="Optional JSON report path (host or /tmp)",
    )
    parser.add_argument(
        "--crisis-only",
        action="store_true",
        help="Only rows whose floor turn_class is crisis_si/crisis_hi "
        "(default: all live-scored; non-crisis reported as N/A quiet)",
    )
    args = parser.parse_args()

    import asyncpg
    from app.services.ln7_structural_verifier_floor import verify_structural_floor

    dsn = os.getenv("DATABASE_URL") or os.getenv("POSTGRES_DSN")
    if not dsn:
        print("FAIL: set DATABASE_URL")
        return 2

    conn = await asyncpg.connect(dsn)
    try:
        rows = await conn.fetch(
            """SELECT scenario_id, section, client_says, nate_response_live,
                      live_safety_veto, live_primary_score, live_accuracy_score,
                      live_naturalness_score, live_scored_at, live_stack_run_id
               FROM six_quotient_human_gold
               WHERE live_human_scored = true
                 AND COALESCE(nate_response_live, '') <> ''
                 AND live_safety_veto IN ('ok', 'fail')
               ORDER BY scenario_id"""
        )
    finally:
        await conn.close()

    tp = tn = fp = fn = skipped = 0
    fp_rows: List[Dict[str, Any]] = []
    fn_rows: List[Dict[str, Any]] = []
    miss_counter: Counter = Counter()
    turn_class_counter: Counter = Counter()

    for r in rows:
        sid = r["scenario_id"]
        human = (r["live_safety_veto"] or "").lower()
        result = verify_structural_floor(
            r["nate_response_live"] or "",
            user_text=r["client_says"] or "",
            scenario_id=sid,
        )
        tc = (result.get("turn_class") or "none") or "none"
        turn_class_counter[tc] += 1
        crisis = tc in ("crisis_si", "crisis_hi")
        if args.crisis_only and not crisis:
            skipped += 1
            continue

        # Non-crisis: floor gate does not apply in live audit path — treat as quiet.
        floor_met = bool(result["floor_met"]) if crisis else True
        fired = not floor_met
        expect_fire = human == "fail"
        missing = [k for k, v in (result.get("floor_checks") or {}).items() if not v]

        if expect_fire and fired:
            tp += 1
        elif (not expect_fire) and (not fired):
            tn += 1
        elif (not expect_fire) and fired:
            fp += 1
            for m in missing:
                miss_counter[m] += 1
            fp_rows.append(
                {
                    "scenario_id": sid,
                    "section": r["section"],
                    "turn_class": tc,
                    "missing": missing,
                    "scores": {
                        "primary": r["live_primary_score"],
                        "accuracy": r["live_accuracy_score"],
                        "naturalness": r["live_naturalness_score"],
                    },
                    "resp_head": (r["nate_response_live"] or "")[:280],
                }
            )
        else:
            fn += 1
            fn_rows.append(
                {
                    "scenario_id": sid,
                    "section": r["section"],
                    "turn_class": tc,
                    "floor_checks": result.get("floor_checks"),
                    "scores": {
                        "primary": r["live_primary_score"],
                        "accuracy": r["live_accuracy_score"],
                        "naturalness": r["live_naturalness_score"],
                    },
                    "resp_head": (r["nate_response_live"] or "")[:280],
                }
            )

    n = tp + tn + fp + fn
    print(f"live_scored_with_veto={len(rows)} evaluated={n} skipped_non_crisis={skipped}")
    print(f"TP={tp} TN={tn} FP={fp} FN={fn}")
    if n:
        print(
            f"precision={tp / (tp + fp) if (tp + fp) else 'n/a'} "
            f"recall={tp / (tp + fn) if (tp + fn) else 'n/a'} "
            f"specificity={tn / (tn + fp) if (tn + fp) else 'n/a'} "
            f"fp_rate={fp / (fp + tn) if (fp + tn) else 'n/a'} "
            f"fn_rate={fn / (fn + tp) if (fn + tp) else 'n/a'}"
        )
    print(f"turn_class_counts={dict(turn_class_counter)}")
    print(f"FP miss taxonomy (count of missing floor_checks across FP rows): {dict(miss_counter)}")
    print("\n=== FALSE POSITIVES (floor fired, human ok) ===")
    for row in fp_rows:
        print(
            f"  {row['scenario_id']} tc={row['turn_class']} missing={row['missing']} "
            f"scores={row['scores']}"
        )
        print(f"    {row['resp_head']!r}")
    print("\n=== FALSE NEGATIVES (floor quiet, human fail) ===")
    for row in fn_rows:
        print(
            f"  {row['scenario_id']} tc={row['turn_class']} checks={row['floor_checks']} "
            f"scores={row['scores']}"
        )
        print(f"    {row['resp_head']!r}")

    report = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "n_live_scored": len(rows),
        "evaluated": n,
        "skipped_non_crisis": skipped,
        "tp": tp,
        "tn": tn,
        "fp": fp,
        "fn": fn,
        "turn_class_counts": dict(turn_class_counter),
        "fp_miss_taxonomy": dict(miss_counter),
        "false_positives": fp_rows,
        "false_negatives": fn_rows,
    }
    if args.out:
        out_path = Path(args.out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(report, indent=2, default=str) + "\n", encoding="utf-8")
        print(f"\nwrote {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_main()))
