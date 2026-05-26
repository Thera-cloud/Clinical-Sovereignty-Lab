#!/usr/bin/env python3
"""Staging smoke: universal SI coach alert dispatch (ENABLE_UNIVERSAL_SI_COACH_ALERT=true)."""
import asyncio
import json
import os
import sys
import time

import asyncpg


async def main() -> int:
    turn_id = os.environ.get("SI_ALERT_TURN_ID") or f"e2e-si-{int(time.time())}"
    client_username = os.environ.get("SI_ALERT_CLIENT", "audit_client")
    coach_username = os.environ.get("SI_ALERT_COACH", "CoachN")
    user_text = os.environ.get(
        "SI_ALERT_TEXT",
        "I want to kill myself and I do not know what to do.",
    )

    if os.getenv("ENABLE_UNIVERSAL_SI_COACH_ALERT", "false").strip().lower() not in (
        "1",
        "true",
        "yes",
    ):
        print(json.dumps({"error": "flag_off", "hint": "set ENABLE_UNIVERSAL_SI_COACH_ALERT=true"}))
        return 1

    pool = await asyncpg.create_pool(os.environ["DATABASE_URL"], min_size=1, max_size=2)
    try:
        client = await pool.fetchrow(
            "SELECT username, hardware_id, profile_data, role FROM users WHERE username=$1",
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
            "role": client["role"] or "CLIENT",
            "assigned_coach": coach_username,
            **pd,
        }

        from app.services.suicide_ideation_coach_alert import maybe_dispatch_si_coach_alert

        first = await maybe_dispatch_si_coach_alert(
            pool, profile, user_text, turn_id=turn_id
        )
        second = await maybe_dispatch_si_coach_alert(
            pool, profile, user_text, turn_id=f"{turn_id}-dup"
        )

        crisis = await pool.fetchrow(
            """
            SELECT ce.id, ce.risk_level, ce.reason, ce.keywords
              FROM crisis_events ce
              JOIN users u ON u.id = ce.user_id
             WHERE u.username = $1
             ORDER BY ce.id DESC
             LIMIT 1
            """,
            client_username,
        )

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
               AND event_type = 'coach_alert_dispatched'
               AND payload_json->>'alert_type' = 'suicidal_ideation_escalation'
               AND payload_json->>'turn_id' = $2
             ORDER BY id DESC
             LIMIT 1
            """,
            client_username,
            turn_id,
        )

        out = {
            "turn_id": turn_id,
            "first": first,
            "second": second,
            "crisis_event": dict(crisis) if crisis else None,
            "notification": dict(notif) if notif else None,
            "audit_id": audit["id"] if audit else None,
        }
        print(json.dumps(out, default=str))

        ok = (
            first.get("status") == "dispatched"
            and second.get("status") == "duplicate"
            and crisis is not None
            and notif is not None
            and audit is not None
        )
        return 0 if ok else 1
    finally:
        await pool.close()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
