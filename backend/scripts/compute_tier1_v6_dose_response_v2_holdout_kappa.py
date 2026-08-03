#!/usr/bin/env python3
"""
grok-judge-v6 ONE-RUN held-out κ against quartet_dose_response_v2.

BURN DISCIPLINE (TRUST_LEDGER Entry 12 / JUDGE_V6_RATIONALE_LOG.md):
  - Freeze JUDGE_SYSTEM_PROMPT_V6 BEFORE this script runs.
  - Do NOT revise the v6 prompt from disagreements on this set.
  - Prior burned holdouts: n=9 (v1+MQ-2), n=40 (live capability).
  - This is the third held-out set — one run, then leave it burned.

Loads ONLY session_label='quartet_dose_response_v2' human-scored rows.
Optionally verifies response_md5 against the immutable export at
backend/app/data/quartet_dose_response_v2/scored_export_2026-08-03.json.

Usage (inside nate_backend, PYTHONPATH=/app):
  python /app/scripts/compute_tier1_v6_dose_response_v2_holdout_kappa.py --dry-run
  python /app/scripts/compute_tier1_v6_dose_response_v2_holdout_kappa.py
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import sys
from pathlib import Path

if "/app" not in sys.path and os.path.isdir("/app/app"):
    sys.path.insert(0, "/app")

SESSION = "quartet_dose_response_v2"
JUDGE_ID = "grok-judge-v6"
EXPORT_CANDIDATES = (
    Path("/app/app/data/quartet_dose_response_v2/scored_export_2026-08-03.json"),
    Path(__file__).resolve().parents[1]
    / "app"
    / "data"
    / "quartet_dose_response_v2"
    / "scored_export_2026-08-03.json",
)


def _md5(text: str) -> str:
    return hashlib.md5((text or "").encode("utf-8")).hexdigest()


def _load_export_md5s():
    for p in EXPORT_CANDIDATES:
        if p.is_file():
            data = json.loads(p.read_text(encoding="utf-8"))
            out = {}
            for it in data.get("items") or []:
                key = f"{it['scenario_id']}::{it['condition_label']}"
                out[key] = str(it.get("response_md5") or "")
            return out, str(p)
    return None, None


async def _load_v2_items(conn):
    rows = await conn.fetch(
        """SELECT scenario_id, condition_label, section, client_says,
                  response_text AS nate_response, safety_veto,
                  primary_score, accuracy_score, naturalness_score
           FROM quartet_dose_response_queue
           WHERE session_label = $1
             AND human_scored = true
             AND primary_score IS NOT NULL
             AND accuracy_score IS NOT NULL
             AND naturalness_score IS NOT NULL
           ORDER BY scenario_id, condition_label""",
        SESSION,
    )
    items = []
    for r in rows:
        d = dict(r)
        d["scenario_id"] = f"{d['scenario_id']}::{d['condition_label']}"
        d["response_class"] = "escalate_or_safety"
        d["is_degraded_distractor"] = False
        items.append(d)
    return items


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
            degraded_distractor=False,
            judge_version="v6",
        )
        if not judged:
            print(f"FAIL judge: {sid}")
            return None
        out[sid] = {
            "primary": judged["primary"],
            "accuracy": judged["accuracy"],
            "naturalness": judged["naturalness"],
        }
        moves = judged.get("moves")
        print(
            f"judged {sid}: {out[sid]}  "
            f"(human={g['primary_score']}/{g['accuracy_score']}/{g['naturalness_score']})"
            + (f" moves={moves}" if moves else "")
        )
    return out


async def _main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--judge-id", default=JUDGE_ID)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--skip-export-check",
        action="store_true",
        help="Skip md5 verify against scored_export_2026-08-03.json",
    )
    args = parser.parse_args()

    import asyncpg

    from app.services.tier1_gold_evidence import (
        KAPPA_METHOD,
        compute_safety_veto,
        mean_per_dimension_kappa,
        persist_kappa_evidence,
    )

    print(
        "BURN WARNING: this is the ONE authorized v6 run against "
        f"{SESSION}. Do not revise JUDGE_SYSTEM_PROMPT_V6 from its "
        "disagreements. n=9 and n=40 are already burned."
    )

    dsn = os.getenv("DATABASE_URL") or os.getenv("POSTGRES_DSN")
    if not dsn:
        print("FAIL: set DATABASE_URL")
        return 2

    conn = await asyncpg.connect(dsn)
    try:
        items = await _load_v2_items(conn)
        if len(items) != 8:
            print(f"FAIL: expected 8 scored v2 rows, got {len(items)}")
            return 2

        if not args.skip_export_check:
            export_md5s, export_path = _load_export_md5s()
            if not export_md5s:
                print("FAIL: scored export not found (refuse to burn without lock)")
                return 2
            mismatches = []
            for g in items:
                sid = g["scenario_id"]
                got = _md5(g["nate_response"])
                exp = export_md5s.get(sid)
                if exp and got != exp:
                    mismatches.append(f"{sid}: db={got} export={exp}")
            if mismatches:
                print("FAIL: DB responses diverge from frozen export:")
                for m in mismatches:
                    print(f"  {m}")
                return 2
            print(f"export lock OK ({export_path}): 8/8 md5 match")

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
            safety_miss_ids=miss_ids,
            notes=(
                f"ONE-RUN v6 held-out on {SESSION} (n={len(used)}). "
                f"Prompt frozen before contact per JUDGE_V6_RATIONALE_LOG.md. "
                f"gold_locked=false. Do not revise v6 from this set. "
                f"misses={miss_ids}"
            ),
            gold_locked=False,
        )
        print(
            f"OK: evidence_id={eid} judge_id={args.judge_id} "
            f"(gold_locked=false; set BURNED for further v6 tuning)"
        )
        return 0
    except Exception as e:
        print(f"FAIL: {e}")
        return 2
    finally:
        await conn.close()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_main()))
