#!/usr/bin/env python3
"""
Read-only clinical AGI-class gate check (Tier 1).

Usage (on GREEN host or with DATABASE_URL):
  python3 backend/scripts/clinical_agi_class_gate_check.py

Exit 0 = all hard gates pass (sparse soft gates may WARN).
Exit 1 = hard gate fail.
Exit 2 = DB/env error.
"""

from __future__ import annotations

import asyncio
import os
import sys


async def _main() -> int:
    try:
        import asyncpg
    except ImportError:
        print("FAIL: asyncpg required")
        return 2

    dsn = os.getenv("DATABASE_URL") or os.getenv("POSTGRES_DSN")
    if not dsn:
        # Docker-style fallback for host-side checks
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
    warns = []

    try:
        conn = await asyncpg.connect(dsn)
    except Exception as e:
        print(f"FAIL: connect: {e}")
        return 2

    try:
        nightly = os.getenv("SIX_QUOTIENT_NIGHTLY_MEASURE", "false").lower() in (
            "1", "true", "yes", "on",
        )
        accel = os.getenv("ENABLE_SIX_QUOTIENT_ACCELERATION", "false").lower() in (
            "1", "true", "yes", "on",
        )
        weekly = os.getenv("SIX_QUOTIENT_WEEKLY_LIVE", "false").lower() in (
            "1", "true", "yes", "on",
        )

        trend_n = await conn.fetchval("SELECT COUNT(*) FROM six_quotient_theta_trend")
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

        print("=== Clinical AGI-class gate (Tier 1) ===")
        print(f"NIGHTLY_MEASURE={nightly} ACCELERATION={accel} WEEKLY_LIVE={weekly}")
        print(f"trend_rows={trend_n} bank_approved={approved} held_out={held_out}")
        print(f"cycle_pending={pending_pred} cycle_resolved={resolved_pred} ability_theta={ability}")

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

        if int(held_out or 0) < 5:
            print("HARD FAIL: held_out bank < 5")
            hard_ok = False
        else:
            print("PASS: held_out >= 5")

        if int(trend_n or 0) < 1:
            warns.append("trend_rows=0 — trigger POST /nightly/trigger once")
        if int(pending_pred or 0) + int(resolved_pred or 0) < 1:
            warns.append("no cycle_predictions yet — sweep may need more history")
        if weekly:
            if int(trend_n or 0) < 7:
                warns.append("WEEKLY_LIVE on with <7 trend rows — premature act")
        else:
            print("INFO: WEEKLY_LIVE still false (correct until soak)")

        for w in warns:
            print(f"WARN: {w}")

        if hard_ok and not warns:
            print("RESULT: GREEN — hard gates pass, no warnings")
            return 0
        if hard_ok:
            print("RESULT: YELLOW — hard gates pass, see WARN")
            return 0
        print("RESULT: RED — hard gate failure")
        return 1
    finally:
        await conn.close()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_main()))
