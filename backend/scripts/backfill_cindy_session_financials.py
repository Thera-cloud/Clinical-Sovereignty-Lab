#!/usr/bin/env python3
"""One-shot: mirror Cindy default PM + obligation_created for SES_20260807_9BF92B."""

from __future__ import annotations

import asyncio
import json
import os
import sys


async def main() -> int:
    import asyncpg
    import stripe

    from app.services.session_financial_records import (
        mirror_default_payment_method,
        record_approval_obligation,
    )

    stripe.api_key = os.environ.get("STRIPE_SECRET_KEY", "")
    dsn = os.environ.get("DATABASE_URL")
    if not dsn or not stripe.api_key:
        print("MISSING_ENV")
        return 1

    pool = await asyncpg.create_pool(dsn, min_size=1, max_size=2)
    try:
        mirrored = await mirror_default_payment_method(
            pool,
            user_key="cindyjoy",
            payment_method_id="pm_1U1sc1DY11zQpvls3ufpekaQ",
            stripe_customer_id="cus_V1tEE5MD3VQ91x",
        )
        print("mirror", mirrored)

        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                """SELECT session_id, client_id, coach_id, client_name, price_cents,
                          session_data
                   FROM coaching_sessions WHERE session_id = $1""",
                "SES_20260807_9BF92B",
            )
        if not row:
            print("SESSION_MISSING")
            return 2

        sd = row["session_data"] or {}
        if isinstance(sd, str):
            sd = json.loads(sd)
        session = {
            "session_id": row["session_id"],
            "client_id": row["client_id"],
            "coach_id": row["coach_id"],
            "client_name": row["client_name"],
            "price_cents": row["price_cents"],
            "coach_fee": sd.get("coach_fee", 175),
            "platform_fee": sd.get("platform_fee", 52.5),
            "coach_payout": sd.get("coach_payout", 122.5),
            "approved_at": sd.get("approved_at") or "2026-08-07 19:11:35.752106",
            "approved_by": "CoachN",
        }
        ok = await record_approval_obligation(pool, session, approved_by="CoachN")
        print("obligation", ok)

        async with pool.acquire() as conn:
            events = await conn.fetch(
                """SELECT spe.event_type, spe.amount_cents, spe.metadata
                   FROM session_payment_events spe
                   JOIN coaching_sessions cs ON cs.id = spe.session_id
                   WHERE cs.session_id = $1
                   ORDER BY spe.created_at""",
                "SES_20260807_9BF92B",
            )
            for e in events:
                print("event", e["event_type"], e["amount_cents"], e["metadata"])
            cindy = await conn.fetchrow(
                """SELECT profile_data->>'default_payment_method_id' AS pm,
                          profile_data->>'payment_method_last4' AS last4
                   FROM users WHERE username = 'cindyjoy'"""
            )
            print("cindy_profile", dict(cindy) if cindy else None)
            coach_bc = await conn.fetchval(
                """SELECT profile_data->'billing_clients'->'cindyjoy'
                   FROM users WHERE username = 'CoachN'"""
            )
            print("coach_billing_clients_cindy", coach_bc)
            sd2 = await conn.fetchval(
                "SELECT session_data FROM coaching_sessions WHERE session_id = $1",
                "SES_20260807_9BF92B",
            )
            if isinstance(sd2, str):
                sd2 = json.loads(sd2)
            print(
                "session_patch",
                {
                    "approved_by": (sd2 or {}).get("approved_by"),
                    "client_default_pm_id": (sd2 or {}).get("client_default_pm_id"),
                    "billing_obligation": (sd2 or {}).get("billing_obligation"),
                },
            )
    finally:
        await pool.close()
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
