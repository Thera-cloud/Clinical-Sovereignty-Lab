#!/usr/bin/env python3
"""
Read-only Phase 2 audit for subscription vs purchased token buckets.

Requires migration 194 (subscription_token_balance, purchased_token_balance).
Does NOT modify any rows — human review before adjustments.

Usage (from repo root, with DATABASE_URL set):
  PYTHONPATH=backend python3 backend/scripts/monthly_token_backfill_audit.py
"""

from __future__ import annotations

import os
import sys

# Repo layout: backend/scripts → append backend parent for `app` imports
_SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))
_BACKEND_ROOT = os.path.abspath(os.path.join(_SCRIPTS_DIR, ".."))
if _BACKEND_ROOT not in sys.path:
    sys.path.insert(0, _BACKEND_ROOT)

_ROOT = os.path.abspath(os.path.join(_SCRIPTS_DIR, "..", ".."))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)


def main() -> None:
    try:
        import asyncpg
    except ImportError:
        print("asyncpg required", file=sys.stderr)
        sys.exit(1)

    url = os.getenv("DATABASE_URL")
    if not url:
        print("Set DATABASE_URL", file=sys.stderr)
        sys.exit(1)

    from app.constants.tiers import TIER_MONTHLY_TOKENS, normalize_tier

    async def run():
        conn = await asyncpg.connect(url)
        try:
            mismatch = await conn.fetch(
                """
                SELECT username,
                       COALESCE(token_balance, 0) AS token_balance,
                       COALESCE(subscription_token_balance, 0) AS sub_bal,
                       COALESCE(purchased_token_balance, 0) AS purch_bal
                FROM users
                WHERE COALESCE(token_balance, 0) !=
                      COALESCE(subscription_token_balance, 0)
                      + COALESCE(purchased_token_balance, 0)
                ORDER BY username
                """
            )
            print("=== token_balance != sub + purch (fix migration sync or drift) ===")
            for r in mismatch:
                print(
                    dict(r),
                    "delta",
                    r["token_balance"] - (r["sub_bal"] + r["purch_bal"]),
                )
            if not mismatch:
                print("(none)")

            subs = await conn.fetch(
                """
                SELECT u.username,
                       u.tier,
                       u.subscription_status,
                       COALESCE(u.token_balance, 0) AS token_balance,
                       COALESCE(u.subscription_token_balance, 0) AS subscription_token_balance,
                       COALESCE(u.purchased_token_balance, 0) AS purchased_token_balance,
                       s.status AS stripe_sub_status,
                       s.current_period_start,
                       s.current_period_end
                FROM users u
                INNER JOIN subscriptions s ON s.user_id = u.id
                WHERE s.status = 'ACTIVE'
                  AND u.role = 'CLIENT'
                ORDER BY u.username
                """
            )
            print("\n=== ACTIVE Stripe subscriptions — tier caps vs subscription bucket ===")
            for r in subs:
                tier = normalize_tier(r["tier"])
                cap = TIER_MONTHLY_TOKENS.get(tier, 0)
                sub_b = int(r["subscription_token_balance"] or 0)
                shortfall = max(0, cap - sub_b) if cap else 0
                print(
                    {
                        "username": r["username"],
                        "tier": tier,
                        "monthly_cap": cap,
                        "subscription_bucket": sub_b,
                        "purchased_bucket": int(r["purchased_token_balance"] or 0),
                        "total": int(r["token_balance"] or 0),
                        "shortfall_to_cap": shortfall,
                        "period_end": str(r["current_period_end"]),
                    }
                )
        finally:
            await conn.close()

    import asyncio

    asyncio.run(run())


if __name__ == "__main__":
    main()
