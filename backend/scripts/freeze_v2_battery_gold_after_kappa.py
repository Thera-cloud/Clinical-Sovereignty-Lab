#!/usr/bin/env python3
"""Snapshot + freeze v2 Judge-track human gold after a κ sitting (TRUST_LEDGER Entry 40).

1) Export score vectors + nate_response for all scored v2 rows
2) Write docs/ln7/evidence/v2_battery_gold_lock_<UTC>.json (+ sha256)
3) Stamp score_entry_source = v2_battery_gold_frozen_<sha8> so Principal-Review
   refuses post-hoc re-score (principal_review_api.py).
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

V2_BATTERY_ID_RE = r"-V(0[1-9]|1[0-2])$"


async def _main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--evidence-id", type=int, required=True)
    parser.add_argument("--judge-id", required=True)
    parser.add_argument("--aggregate-kappa", type=float, required=True)
    parser.add_argument(
        "--out-dir",
        default="",
        help="Host path for evidence JSON (default: /app/../docs/ln7/evidence or cwd)",
    )
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    import asyncpg

    dsn = os.getenv("DATABASE_URL") or os.getenv("POSTGRES_DSN")
    if not dsn:
        print("FAIL: set DATABASE_URL")
        return 2

    conn = await asyncpg.connect(dsn)
    try:
        rows = await conn.fetch(
            f"""SELECT scenario_id, section, client_says, nate_response,
                       primary_score, accuracy_score, naturalness_score,
                       safety_veto, notes, rater_id, scored_at,
                       gold_admin_run_id, score_entry_source, provenance
                FROM six_quotient_human_gold
                WHERE scenario_id ~ '{V2_BATTERY_ID_RE}'
                  AND human_scored = true
                  AND pairs_locked = true
                ORDER BY scenario_id"""
        )
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
            "scope": V2_BATTERY_ID_RE,
            "items": items,
        }
        raw = json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str)
        sha = hashlib.sha256(raw.encode("utf-8")).hexdigest()
        stamp = f"v2_battery_gold_frozen_{sha[:8]}"
        ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")

        out_dir = Path(args.out_dir) if args.out_dir else Path("/tmp")
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / f"v2_battery_gold_lock_{ts}.json"
        out_path.write_text(raw + "\n", encoding="utf-8")
        (out_dir / f"v2_battery_gold_lock_{ts}.sha256").write_text(
            f"{sha}  {out_path.name}\n", encoding="utf-8"
        )
        print(f"snapshot={out_path}")
        print(f"sha256={sha}")
        print(f"stamp={stamp}")

        if args.dry_run:
            print("DRY-RUN: no DB stamp")
            return 0

        updated = await conn.execute(
            f"""UPDATE six_quotient_human_gold
                SET score_entry_source = $1
                WHERE scenario_id ~ '{V2_BATTERY_ID_RE}'
                  AND human_scored = true
                  AND pairs_locked = true""",
            stamp,
        )
        print(f"DB stamp: {updated}")
        return 0
    finally:
        await conn.close()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_main()))
