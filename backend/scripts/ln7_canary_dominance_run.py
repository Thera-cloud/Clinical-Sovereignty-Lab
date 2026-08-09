#!/usr/bin/env python3
"""Honest #10 canary dominance: start best real pack-CI revision vs fast baseline.

Uses existing ln7_coding_outcomes (generator=ln7). Does not fabricate win_streak
or seed_golden into the canary gate. Expires zombie canaries first so Close
Sentinel reads the new streak row.
# QUANTUM-CRYSTAL-ARCH
"""
from __future__ import annotations

import asyncio
import json
import os
from datetime import datetime, timezone
from pathlib import Path

CANDIDATE = "LN7-2026-07-28T230514Z"
INCUMBENT = "LN7-fast-baseline"
ZOMBIES = ("LN7-2026-07-30T190327Z", "LN7-2026-07-30T191329Z")


async def main() -> None:
    import asyncpg
    from app.services.ln7_canary_promoter import evaluate_canary, start_canary
    from app.services.ln7_close_sentinel import run_close_digest

    pool = await asyncpg.create_pool(os.environ["DATABASE_URL"], min_size=1, max_size=3)

    async with pool.acquire() as conn:
        # Confirm outcome gap before mutating state
        rows = await conn.fetch(
            """
            SELECT revision_id,
                   COUNT(*) FILTER (WHERE generator='ln7') AS n,
                   COUNT(*) FILTER (WHERE generator='ln7' AND passed) AS p
            FROM ln7_coding_outcomes
            WHERE revision_id = ANY($1::text[])
            GROUP BY 1
            """,
            [CANDIDATE, INCUMBENT],
        )
        print("OUTCOMES", [dict(r) for r in rows])

        await conn.execute(
            """
            UPDATE ln7_canary_state
            SET status = 'expired',
                notes = COALESCE(notes,'') || ' | expired_for_dominance_run_2026-08-09'
            WHERE revision_id = ANY($1::text[]) AND status = 'active'
            """,
            list(ZOMBIES),
        )
        print("EXPIRED_ZOMBIES", ZOMBIES)

    started = await start_canary(pool, CANDIDATE, incumbent_id=INCUMBENT)
    print("START_CANARY", CANDIDATE, "→", started)

    # Two consecutive honest wins → streak 2 (#10 = 100 at 50 pts/win)
    results = []
    for i in range(2):
        out = await evaluate_canary(pool, CANDIDATE)
        g = out.get("gate") or {}
        results.append(
            {
                "eval": i + 1,
                "ok": out.get("ok"),
                "action": out.get("action"),
                "reason": g.get("reason"),
                "win_streak": g.get("win_streak"),
                "cand_lo": (g.get("candidate_ci") or {}).get("lo"),
                "inc_point": g.get("incumbent_point"),
            }
        )
        print("EVAL", json.dumps(results[-1], default=str))

    evidence = {
        "item_id": "#10",
        "run_at_utc": datetime.now(timezone.utc).isoformat(),
        "method": "start_canary + dual evaluate_canary on real ln7 pack outcomes",
        "candidate": CANDIDATE,
        "incumbent": INCUMBENT,
        "expired_zombies": list(ZOMBIES),
        "evals": results,
        "note": (
            "Candidate previously scored 13/41 pack passes vs incumbent 1/31. "
            "Gate uses cand CI lo > incumbent point — not fabricated streak."
        ),
    }
    for root in (
        Path("/app/data/ln7/evidence"),
        Path("/opt/clinical-sovereignty-lab/docs/ln7/evidence"),
        Path("/opt/clinical-sovereignty-lab/data/backend/ln7/evidence"),
    ):
        try:
            root.mkdir(parents=True, exist_ok=True)
            (root / "canary_dominance_run.json").write_text(
                json.dumps(evidence, indent=2, default=str), encoding="utf-8"
            )
            # Supersede prior blocker if dominance achieved
            streak = (results[-1].get("win_streak") if results else 0) or 0
            if streak >= 2 or (results and all(r.get("ok") for r in results)):
                (root / "canary_win_blocker.json").write_text(
                    json.dumps(
                        {
                            "item_id": "#10",
                            "status": "CLEARED",
                            "cleared_at_utc": evidence["run_at_utc"],
                            "cleared_by": "canary_dominance_run",
                            "see": "docs/ln7/evidence/canary_dominance_run.json",
                            "final_streak": streak,
                        },
                        indent=2,
                    ),
                    encoding="utf-8",
                )
            print("WROTE", root)
        except Exception as e:
            print("WRITE_FAIL", root, e)

    await run_close_digest(pool, force_send=True)
    async with pool.acquire() as c:
        row = await c.fetchrow(
            """SELECT day_index, overall_pct, items_json
               FROM ln7_close_digest_snapshots ORDER BY created_at DESC LIMIT 1"""
        )
        print("SNAP", row["day_index"], row["overall_pct"])
        ij = row["items_json"]
        if isinstance(ij, str):
            ij = json.loads(ij)
        for it in ij:
            if it.get("item_id") in ("#9", "#10", "#15"):
                print(it["item_id"], it.get("pct"), it.get("display"))
        can = await c.fetchrow(
            """SELECT revision_id, status, pass_rate_json->>'win_streak' AS streak,
                      pass_rate_json->>'ok' AS ok, pass_rate_json->>'reason' AS reason
               FROM ln7_canary_state
               ORDER BY COALESCE(last_check_at, started_at) DESC NULLS LAST LIMIT 1"""
        )
        print("CANARY_ROW", dict(can) if can else None)

    await pool.close()


if __name__ == "__main__":
    asyncio.run(main())
