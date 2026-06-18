#!/usr/bin/env python3
"""Smoke: Daily Reconnect locked rows → main-chat memory pipeline.

Uses client1 (CLIENT_001) + sweet2noend@yahoo.com (same family).
Creates a closed ritual session, verifies read-through + ingest, then deletes all smoke rows.

Usage (inside nate_backend):
  python /app/scripts/reconnect_memory_smoke.py
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import uuid
from datetime import datetime, timezone

sys.path.insert(0, "/app")

# Force flags ON for this run only (do not persist to compose).
os.environ["ENABLE_RECONNECT_CHAT_MEMORY"] = "true"
os.environ["ENABLE_RECONNECT_MEMORY_INGEST"] = "true"

USER_A = "client1"
USER_B = "sweet2noend@yahoo.com"
SMOKE_TAG = f"SMOKE_RECONNECT_MEM_{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}"
TURN_A = f"{SMOKE_TAG} I appreciate how you listened when I was overwhelmed."
TURN_B = f"{SMOKE_TAG} I need more patience when money comes up."


async def main() -> int:
    import asyncpg

    dsn = os.environ.get("DATABASE_URL", "").replace("postgresql+asyncpg", "postgresql")
    if not dsn:
        print("FAIL: DATABASE_URL not set")
        return 1
    db_pool = await asyncpg.create_pool(dsn=dsn, min_size=1, max_size=2, command_timeout=30)

    session_id = str(uuid.uuid4())
    family_id = None
    ch_sid = f"reconnect:{session_id}"

    async with db_pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT COALESCE(family_id::text, profile_data->>'family_id') AS fid
            FROM users WHERE username = $1
            """,
            USER_A,
        )
        family_id = (row["fid"] if row else None) or None
        if not family_id:
            print(f"FAIL: no family_id for {USER_A}")
            return 1

        b_row = await conn.fetchrow(
            "SELECT username FROM users WHERE username = $1 AND "
            "COALESCE(family_id::text, profile_data->>'family_id') = $2",
            USER_B, family_id,
        )
        if not b_row:
            print(f"FAIL: {USER_B} not in family {family_id}")
            return 1

        await conn.execute(
            """
            INSERT INTO daily_reconnect_session
                (id, family_id, state, total_reconnects, closed_at, created_at, updated_at)
            VALUES ($1::uuid, $2, 'CLOSED', 1, NOW(), NOW(), NOW())
            """,
            session_id, family_id,
        )
        for user_id, kind, content in (
            (USER_A, "appreciation", TURN_A),
            (USER_B, "feeling_need", TURN_B),
        ):
            await conn.execute(
                """
                INSERT INTO daily_reconnect_turn
                    (session_id, user_id, prompt_index, prompt_kind, content, created_at)
                VALUES ($1::uuid, $2, 0, $3, $4, NOW())
                """,
                session_id, user_id, kind, content,
            )

    # Reload module so flags apply
    import importlib
    import app.services.daily_reconnect_chat_context as rcc
    importlib.reload(rcc)

    ctx = await rcc.build_reconnect_chat_context(db_pool, USER_A)
    if SMOKE_TAG not in ctx:
        print(f"FAIL: read-through block missing smoke tag. ctx_len={len(ctx)}")
        await _cleanup(db_pool, session_id, ch_sid)
        return 1
    print(f"PASS: read-through ({len(ctx)} chars) contains locked turns")

    n = await rcc.ingest_closed_session_for_memory(db_pool, session_id)
    if n < 2:
        print(f"FAIL: ingest returned {n}, expected >= 2")
        await _cleanup(db_pool, session_id, ch_sid)
        return 1
    print(f"PASS: ingest wrote {n} derived conversation_history rows")

    async with db_pool.acquire() as conn:
        cnt = await conn.fetchval(
            """
            SELECT COUNT(*) FROM conversation_history
            WHERE session_id = $1 AND user_text LIKE '%' || $2 || '%'
            """,
            ch_sid, SMOKE_TAG,
        )
    if cnt < 2:
        print(f"FAIL: conversation_history count={cnt}")
        await _cleanup(db_pool, session_id, ch_sid)
        return 1
    print(f"PASS: conversation_history has {cnt} smoke rows")

    await _cleanup(db_pool, session_id, ch_sid)
    print("PASS: cleanup complete — smoke rows removed")
    await db_pool.close()
    return 0


async def _cleanup(db_pool, session_id: str, ch_sid: str) -> None:
    async with db_pool.acquire() as conn:
        await conn.execute(
            "DELETE FROM conversation_history WHERE session_id = $1",
            ch_sid,
        )
        await conn.execute(
            "DELETE FROM daily_reconnect_event WHERE session_id = $1::uuid",
            session_id,
        )
        await conn.execute(
            "DELETE FROM daily_reconnect_turn WHERE session_id = $1::uuid",
            session_id,
        )
        await conn.execute(
            "DELETE FROM daily_reconnect_session WHERE id = $1::uuid",
            session_id,
        )
        # Derived crystals (best-effort; match smoke tag in text)
        await conn.execute(
            """
            DELETE FROM nate_intelligence_crystals
            WHERE crystal_text LIKE '%' || $1 || '%'
            """,
            SMOKE_TAG,
        )


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
