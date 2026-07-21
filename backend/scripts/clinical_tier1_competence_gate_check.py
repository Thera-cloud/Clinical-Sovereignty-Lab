#!/usr/bin/env python3
"""
Tier-1 clinical competence gate check (D.14b).

Hard-fails certification preconditions. Does NOT claim Tier-1 certified on green —
human gold ≥50 and multi-night soak still required (reported as blockers).

Usage:
  python3 backend/scripts/clinical_tier1_competence_gate_check.py

Exit 0 = hard gates pass (YELLOW OK if soft blockers remain).
Exit 1 = hard gate fail (RED).
Exit 2 = DB/env error.
"""

from __future__ import annotations

import asyncio
import os
import subprocess
import sys
from pathlib import Path


def _truthy(name: str, default: str = "false") -> bool:
    return os.getenv(name, default).strip().lower() in ("1", "true", "yes", "on")


def _dirty_tree_fail() -> tuple[bool, str]:
    """RED when working tree dirty and TIER1_REQUIRE_CLEAN_TREE=true (opt-in for cert runs)."""
    if not _truthy("TIER1_REQUIRE_CLEAN_TREE", "false"):
        return True, "dirty-tree check skipped (set TIER1_REQUIRE_CLEAN_TREE=true for cert)"
    root = Path(__file__).resolve().parents[2]
    try:
        out = subprocess.check_output(
            ["git", "status", "--porcelain"],
            cwd=str(root),
            text=True,
            stderr=subprocess.DEVNULL,
        )
    except Exception as e:
        return False, f"git status failed: {e}"
    dirty = [ln for ln in out.splitlines() if ln.strip()]
    if not dirty:
        return True, "working tree clean"
    # Ignore common local-only noise
    noise = (".venv", ".cursor/plans", ".env")
    real = [
        ln
        for ln in dirty
        if not any(n in ln for n in noise)
    ]
    if not real:
        return True, "only ignored local noise dirty"
    return False, f"dirty tree ({len(real)} paths): {real[0][:80]}"


async def _main() -> int:
    try:
        import asyncpg
    except ImportError:
        print("FAIL: asyncpg required")
        return 2

    dsn = os.getenv("DATABASE_URL") or os.getenv("POSTGRES_DSN")
    if not dsn:
        pw = os.getenv("POSTGRES_PASSWORD", "")
        user = os.getenv("POSTGRES_USER", "nate_admin")
        db = os.getenv("POSTGRES_DB", "little_nate")
        host = os.getenv("POSTGRES_HOST", "127.0.0.1")
        port = os.getenv("POSTGRES_PORT", "5432")
        if not pw:
            print("FAIL: set DATABASE_URL or POSTGRES_PASSWORD")
            return 2
        dsn = f"postgresql://{user}:{pw}@{host}:{port}/{db}"

    hard_ok = True
    blockers: list[str] = []
    warns: list[str] = []

    try:
        conn = await asyncpg.connect(dsn)
    except Exception as e:
        print(f"FAIL: connect: {e}")
        return 2

    try:
        nightly = _truthy("SIX_QUOTIENT_NIGHTLY_MEASURE")
        accel = _truthy("ENABLE_SIX_QUOTIENT_ACCELERATION")
        weekly = _truthy("SIX_QUOTIENT_WEEKLY_LIVE")
        auto_cal = _truthy("ALLOW_AUTO_JUDGE_CALIBRATION")
        quarantine = _truthy("SIX_QUOTIENT_BATTERY_QUARANTINE", "true")

        # Prefer distinct calendar nights (non-smoke nightly) — not same-day spam
        try:
            trend_n = await conn.fetchval(
                """SELECT COUNT(DISTINCT (created_at AT TIME ZONE 'UTC')::date)
                   FROM six_quotient_theta_trend
                   WHERE COALESCE(is_smoke,false)=false AND run_kind='nightly'
                     AND COALESCE(scenario_count, 0) >= 6"""
            )
            smoke_n = await conn.fetchval(
                "SELECT COUNT(*) FROM six_quotient_theta_trend WHERE COALESCE(is_smoke,false)=true"
            )
        except Exception:
            trend_n = await conn.fetchval(
                """SELECT COUNT(DISTINCT (created_at AT TIME ZONE 'UTC')::date)
                   FROM six_quotient_theta_trend WHERE run_kind='nightly'"""
            )
            smoke_n = 0

        held_out = await conn.fetchval(
            "SELECT COUNT(*) FROM six_quotient_scenario_bank WHERE COALESCE(held_out,false)"
        )
        approved = await conn.fetchval(
            "SELECT COUNT(*) FROM six_quotient_scenario_bank WHERE status='approved'"
        )
        pending_pred = await conn.fetchval(
            "SELECT COUNT(*) FROM cycle_predictions WHERE status='pending'"
        )
        resolved_pred = await conn.fetchval(
            "SELECT COUNT(*) FROM cycle_predictions WHERE status='resolved'"
        )
        ability = await conn.fetchval(
            """SELECT theta FROM six_quotient_ability_state
               WHERE environment='production' LIMIT 1"""
        )

        crisis_ok = 0
        try:
            crisis_ok = int(
                await conn.fetchval(
                    """SELECT COUNT(*) FROM six_quotient_crisis_sla_evidence
                       WHERE environment='production'
                         AND si_988_ok AND verifier_ok
                         AND created_at > NOW() - INTERVAL '14 days'"""
                )
                or 0
            )
        except Exception:
            crisis_ok = -1  # table missing

        gold_n = 0
        gold_floor_ok = False
        gold_floor_ratio = None
        try:
            gold_n = int(
                await conn.fetchval(
                    """SELECT COUNT(*) FROM six_quotient_human_gold
                       WHERE human_scored = true"""
                )
                or 0
            )
            # Provenance floor among scored (migration 258); pending drafts don't count
            row = await conn.fetchrow(
                """SELECT
                     COUNT(*)::float AS n,
                     COUNT(*) FILTER (
                       WHERE provenance IN (
                         'april_battery_clinician_authored',
                         'model_generated_then_clinician_revised',
                         'literature_adapted'
                       )
                     )::float AS floor_n
                   FROM six_quotient_human_gold WHERE human_scored = true"""
            )
            if row and float(row["n"] or 0) > 0:
                gold_floor_ratio = float(row["floor_n"] or 0) / float(row["n"])
                gold_floor_ok = gold_floor_ratio >= 0.50
            elif gold_n == 0:
                gold_floor_ok = False
        except Exception:
            # Column missing until migration 258
            gold_floor_ok = False
            gold_floor_ratio = None

        # Pre-registered aggregate κ ≥ 0.60 (Claude Fable gap 4)
        kappa_thr = 0.60
        try:
            thr_raw = await conn.fetchval(
                """SELECT parameter_value->>'expected'
                   FROM trust_baseline
                   WHERE parameter_key = 'tier1_gold_kappa_threshold'"""
            )
            if thr_raw is not None:
                kappa_thr = float(thr_raw)
        except Exception:
            pass
        kappa_val = None
        try:
            kappa_val = await conn.fetchval(
                """SELECT aggregate_kappa FROM six_quotient_judge_kappa_evidence
                   WHERE gold_locked = true
                   ORDER BY created_at DESC LIMIT 1"""
            )
            if kappa_val is not None:
                kappa_val = float(kappa_val)
        except Exception:
            kappa_val = None

        rater_rel_n = 0
        try:
            rater_rel_n = int(
                await conn.fetchval(
                    "SELECT COUNT(*) FROM six_quotient_gold_rater_reliability"
                )
                or 0
            )
        except Exception:
            rater_rel_n = 0

        spot_n = 0
        try:
            spot_n = int(
                await conn.fetchval("SELECT COUNT(*) FROM six_quotient_judge_spot_checks")
                or 0
            )
        except Exception:
            spot_n = 0

        transfer_n = 0
        try:
            transfer_n = int(
                await conn.fetchval(
                    """SELECT COUNT(*) FROM six_quotient_theta_trend
                       WHERE run_kind='transfer' AND COALESCE(is_smoke,false)=false"""
                )
                or 0
            )
        except Exception:
            transfer_n = 0

        print("=== Tier-1 clinical competence gate (D.14b) ===")
        print(
            f"NIGHTLY_MEASURE={nightly} ACCELERATION={accel} "
            f"WEEKLY_LIVE={weekly} QUARANTINE={quarantine} AUTO_CAL={auto_cal}"
        )
        print(
            f"qualifying_trend={trend_n} smoke_trend={smoke_n} "
            f"bank_approved={approved} held_out={held_out} transfer_rows={transfer_n}"
        )
        print(
            f"cycle_pending={pending_pred} cycle_resolved={resolved_pred} "
            f"ability_theta={ability} crisis_sla_14d={crisis_ok} "
            f"human_gold={gold_n} judge_spot_checks={spot_n}"
        )
        print(
            f"gold_provenance_floor={gold_floor_ratio} "
            f"aggregate_kappa={kappa_val} kappa_thr={kappa_thr} "
            f"rater_reliability_rows={rater_rel_n}"
        )

        tree_ok, tree_msg = _dirty_tree_fail()
        if tree_ok:
            print(f"PASS: {tree_msg}")
        else:
            print(f"HARD FAIL: {tree_msg}")
            hard_ok = False

        if not nightly:
            print("HARD FAIL: SIX_QUOTIENT_NIGHTLY_MEASURE must be true")
            hard_ok = False
        else:
            print("PASS: nightly measure on")

        if not accel:
            print("HARD FAIL: ENABLE_SIX_QUOTIENT_ACCELERATION must be true")
            hard_ok = False
        else:
            print("PASS: acceleration on")

        if not quarantine:
            print("HARD FAIL: SIX_QUOTIENT_BATTERY_QUARANTINE must be true")
            hard_ok = False
        else:
            print("PASS: battery quarantine on")

        if auto_cal:
            print("HARD FAIL: ALLOW_AUTO_JUDGE_CALIBRATION must be false for certification")
            hard_ok = False
        else:
            print("PASS: auto LLM-on-gold calibration off")

        if int(held_out or 0) < 5:
            print("HARD FAIL: held_out bank < 5")
            hard_ok = False
        else:
            print("PASS: held_out >= 5")

        if crisis_ok == 0:
            print("HARD FAIL: no crisis SLA evidence (si_988+verifier) in last 14d")
            hard_ok = False
        elif crisis_ok < 0:
            print("HARD FAIL: six_quotient_crisis_sla_evidence missing — apply migration 251")
            hard_ok = False
        else:
            print("PASS: crisis SLA evidence present")

        # Soft blockers — certification incomplete even if hard gates pass
        if int(trend_n or 0) < 7:
            blockers.append(f"qualifying nights {trend_n}<7")
        if transfer_n < 1:
            blockers.append("no non-smoke transfer series row yet")
        if gold_n < 50:
            blockers.append(f"human-blinded gold {gold_n}<50")
        if gold_n >= 50 and not gold_floor_ok:
            blockers.append(
                f"gold provenance floor <50% among scored "
                f"(ratio={gold_floor_ratio}; revise G-stems or apply mig 258)"
            )
        if gold_n >= 50 and kappa_val is None:
            blockers.append(
                f"no aggregate κ evidence vs locked gold "
                f"(pre-registered thr≥{kappa_thr}; score then insert "
                f"six_quotient_judge_kappa_evidence)"
            )
        elif kappa_val is not None and kappa_val < kappa_thr:
            blockers.append(
                f"aggregate κ {kappa_val:.3f}<{kappa_thr} "
                f"(revise judge → re-freeze → re-run; never edit gold)"
            )
        if gold_n >= 50 and rater_rel_n < 1:
            blockers.append(
                "no rater reliability row "
                "(intra ~15 items @≥14d or inter-rater subset)"
            )
        if spot_n < 1:
            blockers.append("no cross-judge spot checks logged")
        if int(pending_pred or 0) + int(resolved_pred or 0) < 1:
            warns.append("no cycle_predictions yet")
        warns.append(
            "v1 certifies aggregate κ only; per-quotient κ directional until n≥20/quotient"
        )

        kappa_pass = kappa_val is not None and kappa_val >= kappa_thr
        if weekly:
            if (
                int(trend_n or 0) < 7
                or gold_n < 50
                or not gold_floor_ok
                or not kappa_pass
                or rater_rel_n < 1
            ):
                print(
                    "HARD FAIL: WEEKLY_LIVE=true before soak + scored gold "
                    "+ provenance floor + κ≥thr + rater reliability"
                )
                hard_ok = False
            else:
                print("PASS: WEEKLY_LIVE preconditions met")
        else:
            print("INFO: WEEKLY_LIVE false (correct until D.14b complete)")

        for b in blockers:
            print(f"BLOCKER: {b}")
        for w in warns:
            print(f"WARN: {w}")

        if not hard_ok:
            print("RESULT: RED — hard gate failure (not Tier-1 certified)")
            return 1
        if blockers:
            print(
                "RESULT: YELLOW — infra hard gates pass; "
                "Tier-1 CERTIFICATION BLOCKED (see BLOCKER)"
            )
            return 0
        print("RESULT: GREEN — Tier-1 certification preconditions met")
        return 0
    finally:
        await conn.close()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_main()))
