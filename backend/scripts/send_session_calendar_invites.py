"""One-shot calendar invite for upcoming scheduled clients.

Does not write reminder_24h / reminder_48h / reminder_72h slots.
Dedup: skyeye_activity type=session_calendar_invite_sent.

Usage (GREEN container):
  python /app/scripts/send_session_calendar_invites.py
  python /app/scripts/send_session_calendar_invites.py --dry-run
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys

import asyncpg

sys.path.insert(0, "/app")


async def _backfill_join(conn) -> int:
    from app.services.calendar_invite import join_from_host_path, safe_join_url

    rows = await conn.fetch(
        """
        SELECT session_id, zoom_link, zoom_host_url
        FROM coaching_sessions
        WHERE LOWER(status) = 'scheduled'
          AND COALESCE(scheduled_start, scheduled_at) > NOW()
          AND (zoom_link IS NULL OR zoom_link = '' OR zoom_link ILIKE '%/s/%' OR zoom_link ILIKE '%zak=%')
        """
    )
    updated = 0
    for row in rows:
        join = safe_join_url(row["zoom_link"]) or join_from_host_path(row["zoom_host_url"] or "")
        if not join:
            continue
        await conn.execute(
            "UPDATE coaching_sessions SET zoom_link = $1 WHERE session_id = $2",
            join,
            row["session_id"],
        )
        updated += 1
        print(f"backfill join {row['session_id']} -> {join}")
    return updated


async def _already_sent(conn, session_id: str) -> bool:
    return bool(
        await conn.fetchval(
            """
            SELECT 1 FROM skyeye_activity
            WHERE type = 'session_calendar_invite_sent'
              AND content ILIKE $1
              AND created_at > NOW() - INTERVAL '30 days'
            LIMIT 1
            """,
            f"%{session_id}%",
        )
    )


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    dsn = os.getenv("DATABASE_URL")
    if not dsn:
        print("DATABASE_URL required")
        return 2

    from app.services.calendar_invite import join_from_host_path, safe_join_url
    from app.services.notifications_service import EmailService
    from app.utils.timezone_resolver import split_session_start_for_profile

    conn = await asyncpg.connect(dsn)
    try:
        backfilled = await _backfill_join(conn)
        rows = await conn.fetch(
            """
            SELECT cs.session_id, cs.client_id, cs.coach_id,
                   COALESCE(cs.scheduled_start, cs.scheduled_at) AS scheduled_start,
                   cs.scheduled_end, cs.zoom_link, cs.zoom_host_url,
                   u.username AS client_username,
                   u.role AS client_role,
                   u.profile_data->>'name' AS client_name,
                   u.profile_data->>'email' AS client_email,
                   u.profile_data->>'timezone' AS client_timezone,
                   cu.profile_data->>'name' AS coach_name
            FROM coaching_sessions cs
            LEFT JOIN users u ON u.hardware_id = cs.client_id
               OR u.id::text = cs.client_id::text
            LEFT JOIN users cu ON cu.hardware_id = cs.coach_id
               OR cu.id::text = cs.coach_id::text
            WHERE LOWER(cs.status) = 'scheduled'
              AND COALESCE(cs.scheduled_start, cs.scheduled_at) > NOW()
            ORDER BY scheduled_start
            """
        )
        email_svc = EmailService()
        sent = 0
        skipped = 0
        for row in rows:
            sid = row["session_id"]
            email = (row["client_email"] or "").strip()
            print(
                f"{sid} | {row['client_username']} | {row['client_role']} | "
                f"{row['client_name']} | {row['scheduled_start']}"
            )
            if await _already_sent(conn, sid):
                print("  skip: already sent")
                skipped += 1
                continue
            if not email or "@" not in email:
                print("  skip: no email")
                skipped += 1
                continue
            if args.dry_run:
                print(f"  dry-run would send to {email}")
                continue
            date_str, time_str, tz_name = split_session_start_for_profile(
                row["scheduled_start"],
                {"timezone": row["client_timezone"]},
            )
            join = safe_join_url(row["zoom_link"]) or join_from_host_path(row["zoom_host_url"] or "")
            ok = await email_svc.send_session_calendar_invite(
                email,
                client_name=row["client_name"] or row["client_username"] or "there",
                date=date_str,
                time=time_str,
                timezone=tz_name,
                coach_name=row["coach_name"] or "your coach",
                join_url=join,
                session_id=sid,
                scheduled_start=row["scheduled_start"],
                scheduled_end=row["scheduled_end"],
                client_id=str(row["client_id"] or ""),
            )
            if ok:
                await conn.execute(
                    """
                    INSERT INTO skyeye_activity (platform, type, content, created_at)
                    VALUES ('sessions', 'session_calendar_invite_sent', $1, NOW())
                    """,
                    json.dumps({"session_id": sid, "email": email[:3] + "***"}),
                )
                sent += 1
                print(f"  sent {email}")
            else:
                print("  send failed")
        print(f"done backfilled={backfilled} sent={sent} skipped={skipped}")
        return 0
    finally:
        await conn.close()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
