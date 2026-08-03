#!/usr/bin/env python3
"""
G0→G2 governance flip (CEO-authorized, one-shot).

Sets ENABLE_LN7_AUTO_PROMOTE and DUAL_COO_MECHANICAL_PROMOTE to true
together in `ln7_feature_flags` — the single product-rule change that moves
the flywheel from "CEO activate is the promote path" (G0/G1) to "Dual-COO
mechanical checklist agreement is promote authority, CEO surface becomes
transparency + one-click reverse only" (G2). See the flywheel plan's
"Governance transition" table and `docs/ln7/TRUST_LEDGER.md` for the full
model — this script performs only the mechanical flip described there, it
does not itself decide whether the flip should happen.

Precondition (re-verified here, not just trusted from docs): the Step 0
fence must be green (`ln7_frozen_config.boot_fence_check()` — manifest_ok,
no mismatches). This script refuses to flip if the fence is red, even if
called with `--force-authorized` — a fence mismatch means the frozen
config the checklist relies on may not match what's actually running, and
G2 hands promote authority to that checklist.

Uses `ln7_feature_flags.flip_g2_governance()` (the WELD_FLIP_KEYS path,
requires `allow_weld_flip=True` — enforced both in Python and by the
`ln7_feature_flags_weld_guard` PG trigger via `SET LOCAL
ln7.allow_weld_flip = 'on'`). This is intentionally the ONLY code path in
the repo that sets `allow_weld_flip=True` — do not add a second one.

Usage (inside nate_backend, PYTHONPATH=/app):
  python /app/scripts/flip_g2_governance.py --dry-run
  python /app/scripts/flip_g2_governance.py --reason "CEO-authorized 2026-08-03"
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys

if "/app" not in sys.path and os.path.isdir("/app/app"):
    sys.path.insert(0, "/app")

_WELD_KEYS = ("ENABLE_LN7_AUTO_PROMOTE", "DUAL_COO_MECHANICAL_PROMOTE")


async def _main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--reason",
        default="CEO-authorized 2026-08-03 — Step 0 fence green, gate 1/gate 2 closed",
    )
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    import asyncpg

    from app.services.ln7_feature_flags import flag_enabled, flip_g2_governance
    from app.services.ln7_frozen_config import boot_fence_check

    dsn = os.getenv("DATABASE_URL") or os.getenv("POSTGRES_DSN")
    if not dsn:
        print("FAIL: set DATABASE_URL")
        return 2

    conn_pool = await asyncpg.create_pool(dsn, min_size=1, max_size=2)
    try:
        print("Checking Step 0 fence (boot_fence_check)...")
        fence = await boot_fence_check(db_pool=conn_pool)
        if not fence.get("ok"):
            print(f"FAIL: Step 0 fence is RED, refusing to flip G2. mismatches={fence.get('mismatches')}")
            return 2
        print("OK: Step 0 fence is GREEN (manifest_ok, 0 mismatches).")

        before = {}
        for k in _WELD_KEYS:
            before[k] = await flag_enabled(conn_pool, k, default=False)
        print(f"Before: {before}")

        if any(before.values()):
            print(
                "WARNING: one or both weld keys are already true — this run "
                "would be a no-op re-confirmation, not a fresh flip."
            )

        if args.dry_run:
            print(f"DRY-RUN: would flip {list(_WELD_KEYS)} to true, reason={args.reason!r}")
            return 0

        ok = await flip_g2_governance(conn_pool, reason=args.reason)
        if not ok:
            print("FAIL: flip_g2_governance() returned False — check logs for weld-guard/trigger rejection")
            return 2

        after = {}
        for k in _WELD_KEYS:
            after[k] = await flag_enabled(conn_pool, k, default=False)
        print(f"After:  {after}")

        if all(after.values()):
            print(
                "OK: G2 flip complete. ENABLE_LN7_AUTO_PROMOTE and "
                "DUAL_COO_MECHANICAL_PROMOTE are both true. CEO promote "
                "path is now reverse-only for LN7/Queens promote decisions "
                "per the plan's Governance model (rev 3)."
            )
            return 0
        print("FAIL: post-flip read-back does not show both keys true — investigate before relying on G2 state.")
        return 2
    finally:
        await conn_pool.close()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_main()))
