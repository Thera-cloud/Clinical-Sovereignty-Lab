#!/usr/bin/env python3
"""
Probe confusion cell: human pri=1/acc=0 rows — does judge v3 emit pri=1 acc=0?

Does NOT write gold or κ evidence. Read-only on gold; prints judge JSON only.

Usage (nate_backend, PYTHONPATH=/app):
  python /app/scripts/probe_judge_acc_cell.py
  python /app/scripts/probe_judge_acc_cell.py --ids AQ-4,CQ-1,IQ-2,MQ-1
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys

if "/app" not in sys.path and os.path.isdir("/app/app"):
    sys.path.insert(0, "/app")

DEFAULT_IDS = ("AQ-4", "CQ-1", "IQ-2", "MQ-1")


async def _main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--ids", default=",".join(DEFAULT_IDS))
    args = parser.parse_args()
    want = [x.strip() for x in args.ids.split(",") if x.strip()]

    import asyncpg

    from app.services.six_quotient_auto_judge import DEFAULT_EVALUATOR, _llm_judge

    dsn = os.getenv("DATABASE_URL") or os.getenv("POSTGRES_DSN")
    if not dsn:
        print("FAIL: set DATABASE_URL")
        return 2

    conn = await asyncpg.connect(dsn)
    try:
        rows = await conn.fetch(
            """
            SELECT scenario_id, section, client_says, nate_response,
                   response_class, is_degraded_distractor,
                   primary_score, accuracy_score, naturalness_score
            FROM six_quotient_human_gold
            WHERE scenario_id = ANY($1::text[])
              AND pairs_locked AND human_scored
            ORDER BY scenario_id
            """,
            want,
        )
        by = {r["scenario_id"]: dict(r) for r in rows}
        print(f"judge={DEFAULT_EVALUATOR} probe_ids={want}")
        cell_hits = 0
        for sid in want:
            g = by.get(sid)
            if not g:
                print(f"MISSING gold: {sid}")
                continue
            h = (
                f"h_pri={g['primary_score']} h_acc={g['accuracy_score']} "
                f"h_nat={g['naturalness_score']}"
            )
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
                print(f"FAIL judge: {sid} | {h}")
                continue
            jp, ja = int(judged["primary"]), int(judged["accuracy"])
            hit = jp == 1 and ja == 0
            if hit:
                cell_hits += 1
            print(
                f"{sid}: {h} | j_pri={jp} j_acc={ja} j_nat={judged['naturalness']} "
                f"| cell_pri1_acc0={'YES' if hit else 'no'} | notes={judged.get('notes','')[:160]}"
            )
        human_cell = sum(
            1
            for sid in want
            if by.get(sid)
            and int(by[sid]["primary_score"]) == 1
            and int(by[sid]["accuracy_score"]) == 0
        )
        print(
            json.dumps(
                {
                    "human_pri1_acc0_among_probe": human_cell,
                    "judge_pri1_acc0_hits": cell_hits,
                    "construct_landed": cell_hits >= 1 and human_cell == len(want),
                }
            )
        )
        return 0 if cell_hits >= 1 else 1
    finally:
        await conn.close()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_main()))
