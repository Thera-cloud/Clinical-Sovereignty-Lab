#!/usr/bin/env python3
"""
Judge-v4 held-out evaluation (D.14b certification remediation, step 1 of 3).

Runs judge v4, frozen as-is (no prompt changes), against data it was never
scored against during the v2->v3->v4 prompt-iteration cycle:

  - 8 quartet dose-response rows (AQ-1, AQ-2, AQ-G07, AQ-G08 x before/after
    conditions), human-scored at move-level in quartet_dose_response_queue.
  - 1 live-track capability row (six_quotient_human_gold.live_* columns,
    scenario MQ-2), which used a fresh nate_response_live generation scored
    separately from the original locked-gold nate_response.

IMPORTANT CAVEAT (do not drop this when reporting the result):
All 5 underlying scenario_ids (AQ-1, AQ-2, AQ-G07, AQ-G08, MQ-2) ARE part of
the 50-item locked gold worksheet the judge prompt was iteratively tuned
against (v2->v3->v4 revisions cite specific human-gold evidence by id).
So this is a same-scenario/different-generation holdout, not a
never-seen-scenario holdout: the judge has seen these clinical scenarios
and their scoring rubric before, but has never seen -- and was never tuned
against -- these particular response texts or their scores. That is a
real, meaningful holdout for overfitting-to-response-text, just a narrower
one than "fully novel scenario." Report both facts, not just the number.

n=9 is small; this run is a directional overfit smoke test, not a
replacement for the certification-track kappa. It is logged with
gold_locked=false so the certification gate (WHERE gold_locked=true) never
counts it.

BURNED SET WARNING (TRUST_LEDGER.md Entry 6): this exact n=9 set was used
to diagnose v4's failure mechanism, so it is no longer a valid held-out
set for any later judge version. six_quotient_auto_judge._llm_judge now
scores with JUDGE_SYSTEM_PROMPT_V5 unconditionally (v4 is a frozen,
non-invocable text record, not a live option -- see that module's
docstring), so re-running this script no longer reproduces the v4/0.033
result; it would silently score these burned rows with v5 instead. Do
not re-run this script and report its output as either "the v4 result"
(it isn't, once v5 lands) or "a fresh v5 held-out result" (the set is
burned). The v4/0.033 number is a closed DB record (evidence_id=8);
read it, don't regenerate it. New held-out evaluation of v5+ must draw
from a set these nine rows are not part of (earlier capability-track
scored rows, or dose-response-v2 rows once generated) via a new script
or an updated query in this one.

Usage (inside nate_backend, PYTHONPATH=/app):
  python /app/scripts/compute_tier1_holdout_kappa.py --dry-run
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys

if "/app" not in sys.path and os.path.isdir("/app/app"):
    sys.path.insert(0, "/app")


async def _load_holdout_items(conn):
    """Returns list of dicts shaped like load_scored_gold() rows so the
    same judge-call and kappa/veto helpers work unmodified."""
    items = []

    quartet_rows = await conn.fetch(
        """SELECT scenario_id, condition_label, section, client_says,
                  response_text AS nate_response, safety_veto,
                  primary_score, accuracy_score, naturalness_score
           FROM quartet_dose_response_queue
           WHERE human_scored = true
             AND primary_score IS NOT NULL
             AND accuracy_score IS NOT NULL
             AND naturalness_score IS NOT NULL
           ORDER BY scenario_id, condition_label"""
    )
    for r in quartet_rows:
        d = dict(r)
        # Composite id: two rows share scenario_id (before/after), so the
        # judge-by-scenario_id dict used downstream needs a unique key.
        d["scenario_id"] = f"{d['scenario_id']}::{d['condition_label']}"
        d["response_class"] = "escalate_or_safety"
        d["is_degraded_distractor"] = False
        items.append(d)

    live_rows = await conn.fetch(
        """SELECT scenario_id, section, client_says,
                  nate_response_live AS nate_response, response_class,
                  is_degraded_distractor,
                  live_primary_score AS primary_score,
                  live_accuracy_score AS accuracy_score,
                  live_naturalness_score AS naturalness_score,
                  live_safety_veto AS safety_veto
           FROM six_quotient_human_gold
           WHERE live_human_scored = true
             AND live_primary_score IS NOT NULL
             AND live_accuracy_score IS NOT NULL
             AND live_naturalness_score IS NOT NULL
             AND COALESCE(nate_response_live, '') <> ''
           ORDER BY scenario_id"""
    )
    for r in live_rows:
        d = dict(r)
        d["scenario_id"] = f"{d['scenario_id']}::live"
        items.append(d)

    return items


async def _judge_all(app_state, items):
    from app.services.six_quotient_auto_judge import _llm_judge

    out = {}
    for g in items:
        sid = g["scenario_id"]
        judged = await _llm_judge(
            app_state,
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
        print(f"judged {sid}: {out[sid]}  (human={g['primary_score']}/{g['accuracy_score']}/{g['naturalness_score']})")
    return out


async def _main() -> int:
    parser = argparse.ArgumentParser()
    # TRUST_LEDGER.md Entry 6: this label must match what _llm_judge actually
    # scores with (v5, unconditionally) or every future run of this script
    # mislabels its own evidence rows with a retired judge id.
    parser.add_argument("--judge-id", default="grok-judge-v5")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

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
        items = await _load_holdout_items(conn)
        if not items:
            print("FAIL: 0 held-out items found (nothing to evaluate)")
            return 2

        n_quartet = sum(1 for it in items if "::live" not in it["scenario_id"])
        n_live = len(items) - n_quartet
        print(f"held-out set: {n_quartet} quartet rows + {n_live} live-track row(s) = {len(items)} total")
        print(
            "CAVEAT: scenario_ids AQ-1/AQ-2/AQ-G07/AQ-G08/MQ-2 are all in the "
            "50-item locked gold set the judge prompt was tuned against. "
            "This validates response-text generalization, not scenario novelty."
        )

        judge_by = await _judge_all(None, items)
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
                f"HELD-OUT eval (D.14b remediation step 1/3, not certification "
                f"evidence): {n_quartet} quartet dose-response rows + {n_live} "
                f"live-track row. CAVEAT: scenario_ids overlap the locked "
                f"50-item gold set (same-scenario/different-generation "
                f"holdout, not novel-scenario). misses={miss_ids}"
            ),
            gold_locked=False,
        )
        print(f"OK: evidence_id={eid} (gold_locked=false, excluded from certification gate)")
        return 0
    except Exception as e:
        print(f"FAIL: {e}")
        return 2
    finally:
        await conn.close()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_main()))
