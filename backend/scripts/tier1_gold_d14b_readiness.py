#!/usr/bin/env python3
"""
D.14b readiness snapshot while clinician finishes Principal-Review scoring.

Usage (GREEN / nate_backend):
  python /app/scripts/tier1_gold_d14b_readiness.py
"""

from __future__ import annotations

import asyncio
import os
import sys

if "/app" not in sys.path and os.path.isdir("/app/app"):
    sys.path.insert(0, "/app")


async def _main() -> int:
    import asyncpg

    dsn = os.getenv("DATABASE_URL") or os.getenv("POSTGRES_DSN")
    if not dsn:
        print("FAIL: set DATABASE_URL")
        return 2

    conn = await asyncpg.connect(dsn)
    try:
        prog = await conn.fetchrow(
            """SELECT
                 COUNT(*)::int AS total,
                 COUNT(*) FILTER (WHERE pairs_locked)::int AS locked,
                 COUNT(*) FILTER (WHERE human_scored)::int AS scored,
                 COUNT(*) FILTER (
                   WHERE human_scored
                     AND score_entry_source = 'authenticated_scoring_surface'
                     AND rater_id = 'DrNevedal1'
                     AND COALESCE(score_entry_latency_ms,0) >= 45000
                 )::int AS auth_ok,
                 COUNT(*) FILTER (WHERE is_degraded_distractor)::int AS degraded,
                 COUNT(*) FILTER (
                   WHERE nate_response ILIKE '%DRY-RUN%'
                      OR nate_response ILIKE '%Placeholder Nate reply%'
                 )::int AS dry_run,
                 PERCENTILE_CONT(0.5) WITHIN GROUP (
                   ORDER BY COALESCE(score_entry_latency_ms,0)
                 ) FILTER (WHERE human_scored) AS med_lat
               FROM six_quotient_human_gold"""
        )
        kappa_n = int(
            await conn.fetchval(
                "SELECT COUNT(*) FROM six_quotient_judge_kappa_evidence WHERE gold_locked"
            )
            or 0
        )
        latest_k = await conn.fetchrow(
            """SELECT aggregate_kappa, safety_veto_ok, n_items, kappa_method, created_at
               FROM six_quotient_judge_kappa_evidence
               WHERE gold_locked ORDER BY created_at DESC LIMIT 1"""
        )
        rel_n = 0
        rel_pass = 0
        latest_rel = None
        try:
            rel_n = int(
                await conn.fetchval("SELECT COUNT(*) FROM six_quotient_gold_rater_reliability")
                or 0
            )
            rel_pass = int(
                await conn.fetchval(
                    """SELECT COUNT(*) FROM six_quotient_gold_rater_reliability
                       WHERE meets_threshold AND metric_value >= 0.70 AND n_items >= 15"""
                )
                or 0
            )
            latest_rel = await conn.fetchrow(
                """SELECT metric_value, meets_threshold, n_items, kind, created_at
                   FROM six_quotient_gold_rater_reliability
                   ORDER BY created_at DESC LIMIT 1"""
            )
        except Exception:
            pass

        recheck_tbl = await conn.fetchval(
            """SELECT EXISTS (
                 SELECT 1 FROM information_schema.tables
                 WHERE table_name = 'six_quotient_gold_recheck_scores'
               )"""
        )

        scored = int(prog["scored"] or 0)
        auth_ok = int(prog["auth_ok"] or 0)
        med = float(prog["med_lat"] or 0) if prog["med_lat"] is not None else 0.0
        dry = int(prog["dry_run"] or 0)
        locked = int(prog["locked"] or 0)
        degraded = int(prog["degraded"] or 0)

        print("=== D.14b readiness (Principal-Review) ===")
        print(f"locked={locked} scored={scored}/50 auth_ok_45s={auth_ok} median_lat_ms={med:.0f}")
        print(f"degraded={degraded} dry_run_placeholders={dry} recheck_table={bool(recheck_tbl)}")
        print(f"kappa_evidence_rows={kappa_n} reliability_rows={rel_n} reliability_pass={rel_pass}")
        if latest_k:
            print(
                f"latest_κ={latest_k['aggregate_kappa']} safety_ok={latest_k['safety_veto_ok']} "
                f"n={latest_k['n_items']} method={latest_k['kappa_method']}"
            )
        else:
            print("latest_κ=(none)")
        if latest_rel:
            print(
                f"latest_rel κ={latest_rel['metric_value']} meets={latest_rel['meets_threshold']} "
                f"n={latest_rel['n_items']} kind={latest_rel['kind']}"
            )
        else:
            print("latest_rel=(none)")

        next_steps = []
        if dry:
            next_steps.append("replace DRY-RUN placeholders before more scoring")
        if scored < 50:
            next_steps.append(f"finish Principal-Review scoring ({50 - scored} remaining)")
        elif auth_ok < 50 or med < 45000:
            next_steps.append("score-entry provenance short — check ≥45s latency rows")
        else:
            next_steps.append("scoring floor met")
        if rel_pass < 1:
            next_steps.append(
                "after ≥14d: Recheck ≥15 → Finalize (or TIER1_RECHECK_MIN_GAP_DAYS=0 ops)"
            )
        if kappa_n < 1:
            next_steps.append(
                "κ: Evidence tab async compute, or "
                "python /app/scripts/compute_tier1_gold_kappa.py"
            )
        next_steps.append(
            "gate: python /app/scripts/clinical_tier1_competence_gate_check.py"
        )
        print("--- next ---")
        for i, s in enumerate(next_steps, 1):
            print(f"{i}. {s}")

        # Soft exit: 0 if scoring in progress with no DRY-RUN; 1 if blockers
        if dry:
            return 1
        return 0
    finally:
        await conn.close()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_main()))
