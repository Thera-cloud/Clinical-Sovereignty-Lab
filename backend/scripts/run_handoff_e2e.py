#!/usr/bin/env python3
"""One-shot production smoke: client-initiated coach handoff dispatch."""
import asyncio
import json
import os
import sys
import time

import asyncpg


async def main() -> int:
    turn_id = os.environ.get("HANDOFF_TURN_ID") or f"e2e-handoff-{int(time.time())}"
    client_username = os.environ.get("HANDOFF_CLIENT", "audit_client")
    coach_username = os.environ.get("HANDOFF_COACH", "CoachN")

    pool = await asyncpg.create_pool(os.environ["DATABASE_URL"], min_size=1, max_size=2)
    try:
        client = await pool.fetchrow(
            "SELECT username, hardware_id, profile_data FROM users WHERE username=$1",
            client_username,
        )
        if not client:
            print(json.dumps({"error": "client_not_found", "client": client_username}))
            return 1

        pd = client["profile_data"] or {}
        if isinstance(pd, str):
            pd = json.loads(pd)
        profile = {
            "username": client["username"],
            "hardware_id": client["hardware_id"],
            "assigned_coach": coach_username,
            **pd,
        }

        await pool.execute(
            """
            INSERT INTO conversation_history
                (user_id, user_text, ai_text, session_id, metadata, created_at)
            VALUES ($1, $2, $3, $4, $5::jsonb, NOW())
            ON CONFLICT DO NOTHING
            """,
            client_username,
            "I would like to talk to my coach about what we discussed.",
            "Would you like me to reach out to your coach for you?",
            "e2e-handoff-session",
            json.dumps({"turn_id": turn_id}),
        )

        from app.services.coach_handoff import process_coach_handoff_accepted

        result = await process_coach_handoff_accepted(pool, profile, turn_id)

        notif = await pool.fetchrow(
            """
            SELECT id, urgency, subject, left(message, 280) AS message_prefix, channels
              FROM coach_escalation_notifications
             WHERE coach_username = $1
             ORDER BY id DESC
             LIMIT 1
            """,
            coach_username,
        )

        audit = await pool.fetchrow(
            """
            SELECT id, payload_json
              FROM sensitive_bridge_log
             WHERE user_id = $1
               AND event_type = 'coach_handoff_emitted'
               AND payload_json->>'turn_id' = $2
             ORDER BY id DESC
             LIMIT 1
            """,
            client_username,
            turn_id,
        )

        print(
            json.dumps(
                {
                    "turn_id": turn_id,
                    "result": result,
                    "notification": dict(notif) if notif else None,
                    "audit_id": audit["id"] if audit else None,
                },
                default=str,
            )
        )
        return 0 if result.get("status") == "accepted" and notif else 1
    finally:
        await pool.close()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
