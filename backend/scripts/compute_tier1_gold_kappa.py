#!/usr/bin/env python3
"""
Compute judge κ vs locked human gold and insert six_quotient_judge_kappa_evidence.

Uses pre-registered method: quadratic_weighted_per_dimension_mean.

Usage (inside nate_backend, PYTHONPATH=/app):
  python /app/scripts/compute_tier1_gold_kappa.py
  python /app/scripts/compute_tier1_gold_kappa.py --min-items 50 --judge-id grok-judge-v1
  python /app/scripts/compute_tier1_gold_kappa.py --from-json /tmp/judge_scores.json
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys

if "/app" not in sys.path and os.path.isdir("/app/app"):
    sys.path.insert(0, "/app")


async def _judge_all(app_state, items, limit: int):
    from app.services.six_quotient_auto_judge import _llm_judge

    out = {}
    for g in items[:limit]:
        sid = g["scenario_id"]
        judged = await _llm_judge(
            app_state,
            scenario_id=sid,
            section=str(g.get("section") or ""),
            rubric_focus=str(g.get("response_class") or ""),
            client_says=str(g.get("client_says") or ""),
            response=str(g.get("nate_response") or ""),
        )
        if not judged:
            print(f"FAIL judge: {sid}")
            return None
        out[sid] = {
            "primary": judged["primary"],
            "accuracy": judged["accuracy"],
            "naturalness": judged["naturalness"],
        }
        print(f"judged {sid}: {out[sid]}")
    return out


async def _main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--min-items", type=int, default=50)
    parser.add_argument("--limit", type=int, default=0, help="0 = all scored")
    parser.add_argument("--judge-id", default="grok-judge-v1")
    parser.add_argument(
        "--from-json",
        default="",
        help='JSON map {scenario_id: {primary,accuracy,naturalness}}',
    )
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    import asyncpg

    from app.services.tier1_gold_evidence import (
        KAPPA_METHOD,
        compute_safety_veto,
        load_scored_gold,
        mean_per_dimension_kappa,
        persist_kappa_evidence,
    )

    dsn = os.getenv("DATABASE_URL") or os.getenv("POSTGRES_DSN")
    if not dsn:
        print("FAIL: set DATABASE_URL")
        return 2

    conn = await asyncpg.connect(dsn)
    try:
        items = await load_scored_gold(conn, min_items=max(1, args.min_items))
        limit = args.limit if args.limit > 0 else len(items)
        items = items[:limit]

        if args.from_json:
            raw = json.loads(open(args.from_json, encoding="utf-8").read())
            judge_by = {
                str(k): {
                    "primary": int(v["primary"]),
                    "accuracy": int(v["accuracy"]),
                    "naturalness": int(v["naturalness"]),
                }
                for k, v in raw.items()
            }
        else:
            judge_by = await _judge_all(None, items, limit)
            if judge_by is None:
                return 1

        paired_g = []
        paired_j = []
        used = []
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

        if len(used) < args.min_items:
            print(f"FAIL: paired {len(used)} < min-items {args.min_items}")
            return 1

        agg, per = mean_per_dimension_kappa(paired_g, paired_j)
        ok, miss_n, miss_ids = compute_safety_veto(items, judge_by)
        print(
            f"method={KAPPA_METHOD} n={len(used)} aggregate={agg} "
            f"per={per} safety_veto_ok={ok} misses={miss_n} {miss_ids[:5]}"
        )
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
            notes=f"compute_tier1_gold_kappa; misses={miss_ids}",
        )
        print(f"OK: evidence_id={eid}")
        return 0
    except Exception as e:
        print(f"FAIL: {e}")
        return 2
    finally:
        await conn.close()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_main()))
