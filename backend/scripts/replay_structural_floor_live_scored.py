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
    from app.services.principal_review_crisis_policy import classify_crisis_turn_class

    dsn = os.getenv("DATABASE_URL") or os.getenv("POSTGRES_DSN")
    if not dsn:
        print("FAIL: set DATABASE_URL")
        return 2

    conn = await asyncpg.connect(dsn)
    try:
        rows = await conn.fetch(
            """SELECT scenario_id, section, client_says, nate_response_live,
                      live_safety_veto, live_primary_score, live_accuracy_score,
                      live_naturalness_score, live_scored_at, live_stack_run_id,
                      live_inject_meta
               FROM six_quotient_human_gold
               WHERE live_human_scored = true
                 AND COALESCE(nate_response_live, '') <> ''
               ORDER BY scenario_id"""
        )
    finally:
        await conn.close()

    tp = tn = fp = fn = skipped = 0
    unlabeled_crisis_fire = unlabeled_crisis_quiet = unlabeled_non_crisis = 0
    fp_rows: List[Dict[str, Any]] = []
    fn_rows: List[Dict[str, Any]] = []
    miss_counter: Counter = Counter()
    turn_class_counter: Counter = Counter()
    unlabeled_fire_miss: Counter = Counter()

    for r in rows:
        sid = r["scenario_id"]
        human = (r["live_safety_veto"] or "").strip().lower()
        labeled = human in ("ok", "fail")
        # Match live gate: only crisis_si/crisis_hi — never default to SI.
        # Prefer stamp from live_inject_meta when present (generation-time class).
        meta = r["live_inject_meta"] or {}
        if isinstance(meta, str):
            meta = json.loads(meta) if meta.strip() else {}
        tc = (meta.get("principal_review_turn_class") or "").strip()
        if not tc:
            tc = (classify_crisis_turn_class(r["client_says"] or "") or "").strip()
        turn_class_counter[tc or "none"] += 1
        crisis = tc in ("crisis_si", "crisis_hi")
        if not crisis:
            skipped += 1
            if not labeled:
                unlabeled_non_crisis += 1
            # Floor does not run on non-crisis in production — exclude from FP/FN.
            continue

        result = verify_structural_floor(
            r["nate_response_live"] or "",
            user_text=r["client_says"] or "",
            turn_class=tc,
            scenario_id=sid,
        )
        floor_met = bool(result["floor_met"])
        fired = not floor_met
        missing = [k for k, v in (result.get("floor_checks") or {}).items() if not v]

        if not labeled:
            if fired:
                unlabeled_crisis_fire += 1
                for m in missing:
                    unlabeled_fire_miss[m] += 1
            else:
                unlabeled_crisis_quiet += 1
            continue

        expect_fire = human == "fail"

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
    n_all = len(rows)
    print(f"live_scored={n_all} veto_labeled={n} unlabeled={n_all - n} skipped_non_crisis={skipped}")
    print(f"LABELED CONCORDANCE: TP={tp} TN={tn} FP={fp} FN={fn}")
    if n:
        print(
            f"precision={tp / (tp + fp) if (tp + fp) else 'n/a'} "
            f"recall={tp / (tp + fn) if (tp + fn) else 'n/a'} "
            f"specificity={tn / (tn + fp) if (tn + fp) else 'n/a'} "
            f"fp_rate={fp / (fp + tn) if (fp + tn) else 'n/a'} "
            f"fn_rate={fn / (fn + tp) if (fn + tp) else 'n/a'}"
        )
    print(
        f"UNLABELED (empty live_safety_veto): crisis_fire={unlabeled_crisis_fire} "
        f"crisis_quiet={unlabeled_crisis_quiet} non_crisis={unlabeled_non_crisis}"
    )
    print(f"unlabeled crisis-fire miss taxonomy: {dict(unlabeled_fire_miss)}")
    print(f"turn_class_counts={dict(turn_class_counter)}")
    print(f"FP miss taxonomy (labeled): {dict(miss_counter)}")
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
        "n_live_scored": n_all,
        "veto_labeled": n,
        "unlabeled": n_all - n,
        "unlabeled_crisis_fire": unlabeled_crisis_fire,
        "unlabeled_crisis_quiet": unlabeled_crisis_quiet,
        "unlabeled_non_crisis": unlabeled_non_crisis,
        "unlabeled_fire_miss_taxonomy": dict(unlabeled_fire_miss),
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
