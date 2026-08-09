#!/usr/bin/env python3
"""Snapshot + freeze Entry-42 v7 holdout Judge-track gold after κ (TRUST_LEDGER Entry 43).

Same hygiene as freeze_v2_battery_gold_after_kappa.py / f5a13aff:
1) Export score vectors + nate_response for the 16 holdout ids
2) Write docs/ln7/evidence/v7_holdout_gold_lock_<UTC>.json (+ sha256)
3) Stamp score_entry_source = v7_holdout_gold_frozen_<sha8> so Principal-Review
   refuses post-hoc re-score.

Note: six_quotient_judge_kappa_evidence.gold_locked stays false (informational /
excluded from D.14b). This freeze locks *human gold rows*, not the κ gate flag.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

STEMS_CANDIDATES = (
    Path("/app/app/data/six_quotient_v7_holdout_stems_v1.json"),
    Path(__file__).resolve().parents[1]
    / "app"
    / "data"
    / "six_quotient_v7_holdout_stems_v1.json",
)
EXPECTED_N = 16


def _load_holdout_ids() -> list:
    for p in STEMS_CANDIDATES:
        if p.is_file():
            data = json.loads(p.read_text(encoding="utf-8"))
            return [str(s["scenario_id"]) for s in (data.get("stems") or [])]
    raise FileNotFoundError("six_quotient_v7_holdout_stems_v1.json not found")


async def _main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--evidence-id", type=int, required=True)
    parser.add_argument("--judge-id", required=True)
    parser.add_argument("--aggregate-kappa", type=float, required=True)
    parser.add_argument("--out-dir", default="")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    import asyncpg

    dsn = os.getenv("DATABASE_URL") or os.getenv("POSTGRES_DSN")
    if not dsn:
        print("FAIL: set DATABASE_URL")
        return 2

    try:
        holdout_ids = _load_holdout_ids()
    except FileNotFoundError as e:
        print(f"FAIL: {e}")
        return 2
    if len(holdout_ids) != EXPECTED_N:
        print(f"FAIL: expected {EXPECTED_N} holdout ids, got {len(holdout_ids)}")
        return 2

    conn = await asyncpg.connect(dsn)
    try:
        rows = await conn.fetch(
            """SELECT scenario_id, section, client_says, nate_response,
                      primary_score, accuracy_score, naturalness_score,
                      safety_veto, notes, rater_id, scored_at,
                      gold_admin_run_id, score_entry_source, provenance
               FROM six_quotient_human_gold
               WHERE scenario_id = ANY($1::text[])
                 AND human_scored = true
                 AND pairs_locked = true
               ORDER BY scenario_id""",
            holdout_ids,
        )
        if len(rows) != EXPECTED_N:
            missing = sorted(set(holdout_ids) - {r["scenario_id"] for r in rows})
            print(f"FAIL: scored+locked count {len(rows)}/{EXPECTED_N}; missing={missing}")
            return 1

        items = []
        for r in rows:
            d = dict(r)
            if d.get("scored_at"):
                d["scored_at"] = d["scored_at"].isoformat()
            items.append(d)

        payload = {
            "frozen_at_utc": datetime.now(timezone.utc).isoformat(),
            "evidence_id": int(args.evidence_id),
            "judge_id": args.judge_id.strip(),
            "aggregate_kappa": float(args.aggregate_kappa),
            "n_items": len(items),
            "scope": "entry42_v7_holdout",
            "scenario_ids": holdout_ids,
            "kappa_gold_locked_flag": False,
            "note": (
                "Human gold freeze only. "
                "six_quotient_judge_kappa_evidence.gold_locked remains false "
                "(D.14b exclusion). Same hygiene as v2 f5a13aff freeze."
            ),
            "items": items,
        }
        raw = json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str)
        sha = hashlib.sha256(raw.encode("utf-8")).hexdigest()
        stamp = f"v7_holdout_gold_frozen_{sha[:8]}"
        ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")

        out_dir = Path(args.out_dir) if args.out_dir else Path("/tmp")
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / f"v7_holdout_gold_lock_{ts}.json"
        out_path.write_text(raw + "\n", encoding="utf-8")
        (out_dir / f"v7_holdout_gold_lock_{ts}.sha256").write_text(
            f"{sha}  {out_path.name}\n", encoding="utf-8"
        )
        print(f"snapshot={out_path}")
        print(f"sha256={sha}")
        print(f"stamp={stamp}")

        if args.dry_run:
            print("DRY-RUN: no DB stamp")
            return 0

        updated = await conn.execute(
            """UPDATE six_quotient_human_gold
                SET score_entry_source = $1
                WHERE scenario_id = ANY($2::text[])
                  AND human_scored = true
                  AND pairs_locked = true""",
            stamp,
            holdout_ids,
        )
        print(f"DB stamp: {updated}")
        return 0
    finally:
        await conn.close()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_main()))
