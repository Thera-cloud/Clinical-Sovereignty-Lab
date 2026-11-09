#!/usr/bin/env python3
"""Publish a paid PG session onto JSON + GCal + Zoom probe. Never charges."""
from __future__ import annotations

import argparse
import asyncio
import os
import sys


async def _main(session_id: str, cancel_ids: list[str]) -> int:
    import asyncpg
    from app.services.session_schedule_publish import publish_scheduled_session

    url = os.getenv("DATABASE_URL") or ""
    if not url:
        print("DATABASE_URL missing", file=sys.stderr)
        return 2
    pool = await asyncpg.create_pool(url, min_size=1, max_size=2)
    try:
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                """SELECT session_id, coach_id, client_id, family_id, client_name,
                          status, payment_status, scheduled_start, scheduled_end,
                          zoom_link, zoom_meeting_id, zoom_host_url, google_event_id,
                          price_cents, stripe_payment_intent_id, session_data, notes
                     FROM coaching_sessions WHERE session_id = $1""",
                session_id,
            )
        if not row:
            print(f"session not found: {session_id}", file=sys.stderr)
            return 1
        result = await publish_scheduled_session(
            pool, dict(row), reason="manual_publish", cancel_json_ids=cancel_ids,
        )
        print(result)
        return 0 if result.get("json_ok") else 3
    finally:
        await pool.close()


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("session_id")
    p.add_argument("--cancel", action="append", default=[])
    args = p.parse_args()
    raise SystemExit(asyncio.run(_main(args.session_id, args.cancel)))
