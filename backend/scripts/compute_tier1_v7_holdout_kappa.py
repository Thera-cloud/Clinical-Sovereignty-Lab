#!/usr/bin/env python3
"""
grok-judge-v7 ONE-RUN held-out κ against Entry-42 CQ/AQ pack.

BURN DISCIPLINE (TRUST_LEDGER Entry 40/41/43 + JUDGE_V7_RATIONALE_LOG.md):
  - Freeze JUDGE_SYSTEM_PROMPT_V7 BEFORE this script runs against these rows.
  - Do NOT revise the v7 prompt from disagreements on this set.
  - v2 battery remains burned — this script never loads *-V01…V11.
  - Scope is ONLY the 16 ids in six_quotient_v7_holdout_stems_v1.json.

Usage (inside nate_backend, PYTHONPATH=/app):
  python /app/scripts/compute_tier1_v7_holdout_kappa.py --dry-run
  python /app/scripts/compute_tier1_v7_holdout_kappa.py
  python /app/scripts/compute_tier1_v7_holdout_kappa.py --gold-locked  # deliberate
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

if "/app" not in sys.path and os.path.isdir("/app/app"):
    sys.path.insert(0, "/app")

JUDGE_ID = "grok-judge-v7"
JUDGE_VERSION = "v7"
EXPECTED_N = 16
STEMS_CANDIDATES = (
    Path("/app/app/data/six_quotient_v7_holdout_stems_v1.json"),
    Path(__file__).resolve().parents[1]
    / "app"
    / "data"
    / "six_quotient_v7_holdout_stems_v1.json",
)


def _load_holdout_ids() -> list:
    for p in STEMS_CANDIDATES:
        if p.is_file():
            data = json.loads(p.read_text(encoding="utf-8"))
            ids = [str(s["scenario_id"]) for s in (data.get("stems") or [])]
            return ids
    raise FileNotFoundError("six_quotient_v7_holdout_stems_v1.json not found")


async def _load_scored_items(conn, ids: list):
    rows = await conn.fetch(
        """SELECT scenario_id, section, client_says, nate_response,
                  response_class, difficulty, is_degraded_distractor,
                  primary_score, accuracy_score, naturalness_score,
                  provenance
           FROM six_quotient_human_gold
           WHERE scenario_id = ANY($1::text[])
             AND human_scored = true
             AND pairs_locked = true
             AND primary_score IS NOT NULL
             AND accuracy_score IS NOT NULL
             AND naturalness_score IS NOT NULL
             AND COALESCE(nate_response, '') <> ''
             AND nate_response NOT ILIKE '%DRY-RUN%'
             AND nate_response NOT ILIKE '%Placeholder Nate reply%'
           ORDER BY scenario_id""",
        ids,
    )
    return [dict(r) for r in rows]


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
            judge_version=JUDGE_VERSION,
        )
        if not judged:
            print(f"FAIL judge: {sid}")
            return None
        out[sid] = {
            "primary": judged["primary"],
            "accuracy": judged["accuracy"],
            "naturalness": judged["naturalness"],
        }
        struct = judged.get("structural") or {}
        moves = judged.get("moves")
        print(
            f"judged {sid}: {out[sid]}  "
            f"(human={g['primary_score']}/{g['accuracy_score']}/{g['naturalness_score']})"
            + (f" structural={struct}" if struct else "")
            + (f" moves={moves}" if moves else "")
        )
    return out


async def _main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--judge-id", default=JUDGE_ID)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--gold-locked",
        action="store_true",
        help="Opt into D.14b certification gate. Default off.",
    )
    parser.add_argument("--min-items", type=int, default=EXPECTED_N)
    args = parser.parse_args()

    jid = (args.judge_id or "").strip()
    if "v7" not in jid.lower():
        print(f"FAIL: --judge-id must contain 'v7' (got {jid!r}) — Entry 4 hygiene")
        return 2

    import asyncpg

    from app.services.tier1_gold_evidence import (
        KAPPA_METHOD,
        compute_safety_veto,
        mean_per_dimension_kappa,
        persist_kappa_evidence,
    )

    print(
        "BURN WARNING: ONE authorized v7 run against Entry-42 holdout "
        f"(expected n={EXPECTED_N}). Do not revise JUDGE_SYSTEM_PROMPT_V7 "
        "from its disagreements. v2 battery stays burned."
    )

    try:
        holdout_ids = _load_holdout_ids()
    except FileNotFoundError as e:
        print(f"FAIL: {e}")
        return 2
    if len(holdout_ids) != EXPECTED_N:
        print(f"FAIL: stems file has {len(holdout_ids)} ids, expected {EXPECTED_N}")
        return 2
    # V12 strata eveners allowed; refuse burned V01–V11 bleed
    bad = [
        i
        for i in holdout_ids
        if any(i.endswith(f"-V{n:02d}") for n in range(1, 12))
    ]
    if bad:
        print(f"FAIL: burned v2 ids in holdout pack: {bad}")
        return 2

    dsn = os.getenv("DATABASE_URL") or os.getenv("POSTGRES_DSN")
    if not dsn:
        print("FAIL: set DATABASE_URL")
        return 2

    conn = await asyncpg.connect(dsn)
    try:
        items = await _load_scored_items(conn, holdout_ids)
        print(
            f"v7 holdout: {len(items)}/{EXPECTED_N} scored+locked+non-placeholder; "
            f"judge_id={jid} judge_version={JUDGE_VERSION} "
            f"gold_locked={bool(args.gold_locked)}"
        )
        missing = sorted(set(holdout_ids) - {g["scenario_id"] for g in items})
        if missing:
            print(f"FAIL: missing scored rows: {missing}")
            return 1
        if len(items) < args.min_items:
            print(f"FAIL: {len(items)} < --min-items {args.min_items}")
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
            judge_id=jid,
            aggregate_kappa=agg,
            per_dimension=per,
            n_items=len(used),
            safety_veto_ok=ok,
            safety_miss_count=miss_n,
            safety_miss_ids=miss_ids,
            notes=(
                f"ONE-RUN v7 held-out Entry-42 pack (n={len(used)}). "
                f"Prompt frozen before contact per JUDGE_V7_RATIONALE_LOG.md. "
                f"gold_locked={bool(args.gold_locked)}. "
                f"Do not revise v7 from this set. misses={miss_ids}"
            ),
            gold_locked=bool(args.gold_locked),
        )
        print(
            f"OK: evidence_id={eid} judge_id={jid} "
            f"gold_locked={bool(args.gold_locked)} "
            f"(set BURNED for further v7 prompt tuning)"
        )
        return 0
    except Exception as e:
        print(f"FAIL: {e}")
        return 2
    finally:
        await conn.close()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_main()))
