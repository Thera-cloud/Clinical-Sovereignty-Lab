#!/usr/bin/env python3
"""Replay stored Zoom webhooks into coaching_sessions. Counts only — no session text.

  python3 /app/scripts/backfill_zoom_live_learning.py /app/data/zoom_events.json
"""

from __future__ import annotations

import asyncio
import json
import os
import sys

import asyncpg

sys.path.insert(0, "/app")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def _meeting_id(ev: dict) -> str:
    from app.services.zoom_household_learning import canonical_zoom_meeting_id

    mid = canonical_zoom_meeting_id(ev.get("payload") or {})
    if mid:
        return mid
    stored = str(ev.get("meeting_id") or "").strip()
    return stored if stored.isdigit() else ""


async def _replay(pool, events) -> None:
    from app.services.zoom_household_learning import (
        apply_meeting_ended,
        apply_meeting_started,
        mark_cloud_recording,
        stamp_family_from_client,
        summary_text_from_webhook,
    )
    from app.services.zoom_session_folder import try_place_session_summary_in_coach_folder

    counts = {
        "started": 0,
        "ended": 0,
        "recording": 0,
        "summaries": 0,
        "summary_no_session": 0,
    }
    ordered = sorted(events, key=lambda e: str(e.get("received_at") or ""))
    for ev in ordered:
        name = str(ev.get("event") or "")
        if name not in (
            "meeting.started",
            "meeting.ended",
            "recording.started",
            "recording.stopped",
            "meeting.summary_completed",
            "meeting.summary_shared",
            "meeting.summary_recovered",
        ):
            continue
        received = str(ev.get("received_at") or "")
        if received and received < "2026-09-01":
            continue
        mid = _meeting_id(ev)
        if not mid:
            continue
        payload = ev.get("payload") or {}
        obj = ((payload.get("payload") or {}).get("object") or {})
        if name == "meeting.started":
            counts["started"] += await apply_meeting_started(
                pool, mid, str(obj.get("start_time") or "")
            )
        elif name == "meeting.ended":
            counts["ended"] += await apply_meeting_ended(
                pool, mid, str(obj.get("end_time") or ""), int(obj.get("duration") or 0)
            )
        elif name == "recording.started":
            counts["recording"] += await mark_cloud_recording(
                pool, mid, started=True, at_iso=str(obj.get("start_time") or received)
            )
        elif name == "recording.stopped":
            counts["recording"] += await mark_cloud_recording(
                pool, mid, started=False, at_iso=str(obj.get("end_time") or received)
            )
        elif name.startswith("meeting.summary"):
            text = summary_text_from_webhook(payload)
            if len(text) < 40:
                continue
            await stamp_family_from_client(pool, mid)
            async with pool.acquire() as conn:
                row = await conn.fetchrow(
                    """
                    SELECT session_id, coach_id, client_id, client_name, session_type,
                           scheduled_start, actual_start, actual_end, session_data,
                           zoom_meeting_id, nate_summary, coach_notes
                    FROM coaching_sessions
                    WHERE zoom_meeting_id = $1
                    ORDER BY COALESCE(actual_end, scheduled_start) DESC NULLS LAST
                    LIMIT 1
                    """,
                    mid,
                )
                if not row:
                    counts["summary_no_session"] += 1
                    continue
                pg_row = dict(row)
                sd = pg_row.get("session_data") or {}
                if isinstance(sd, str):
                    try:
                        sd = json.loads(sd)
                    except Exception:
                        sd = {}
                if not isinstance(sd, dict):
                    sd = {}
                if (sd.get("zoom_ai_summary_text") or "").strip() and str(sd.get("zoom_folder_doc_placed") or "").lower() in ("true", "1"):
                    continue
                uuid = str(obj.get("uuid") or obj.get("meeting_uuid") or "").strip()
                patch = {
                    "zoom_ai_summary_text": text[:50000],
                    "zoom_summary_source": "zoom_webhook",
                }
                if uuid:
                    patch["zoom_meeting_uuid"] = uuid
                await conn.execute(
                    """
                    UPDATE coaching_sessions
                    SET session_data = COALESCE(session_data, '{}'::jsonb) || $2::jsonb,
                        updated_at = NOW()
                    WHERE session_id = $1
                    """,
                    pg_row["session_id"],
                    json.dumps(patch),
                )
                sd.update(patch)
                pg_row["session_data"] = sd
            file_id = await try_place_session_summary_in_coach_folder(
                pool, pg_row, mid, summary_text=text
            )
            if file_id:
                counts["summaries"] += 1
    counts["household"] = await _share_household(pool)
    current = asyncio.current_task()
    pending = [task for task in asyncio.all_tasks() if task is not current]
    if pending:
        await asyncio.gather(*pending, return_exceptions=True)
    print(
        "backfill "
        f"started={counts['started']} ended={counts['ended']} "
        f"recording={counts['recording']} summaries={counts['summaries']} "
        f"summary_no_session={counts['summary_no_session']} "
        f"household={counts['household']}"
    )


async def _share_household(pool) -> int:
    """Forge household crystals where a summary exists and the flag was never set."""
    from app.services.zoom_household_learning import share_live_session_learning

    written = 0
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT session_id, client_id, client_name,
                   LEFT(COALESCE(session_data->>'zoom_ai_summary_text', ''), 4000) AS summary
            FROM coaching_sessions
            WHERE COALESCE(session_data->>'zoom_ai_summary_text', '') <> ''
              AND COALESCE(session_data->>'household_learning', '') = ''
              AND COALESCE(actual_end, scheduled_start) >= TIMESTAMPTZ '2026-09-01'
            """
        )
    for row in rows:
        summary = (row["summary"] or "").strip()
        if len(summary) < 40:
            continue
        written += await share_live_session_learning(
            pool,
            row["client_id"],
            row["client_name"] or "",
            summary,
            "Zoom session AI summary archived for coach review.",
            origin_surface="zoom_session_summary",
            session_id=row["session_id"],
            min_score=0,
        )
    return written


async def main() -> None:
    path = sys.argv[1] if len(sys.argv) > 1 else "/app/data/zoom_events.json"
    url = os.environ.get("DATABASE_URL")
    if not url:
        print("DATABASE_URL missing")
        sys.exit(1)
    with open(path, "r", encoding="utf-8") as fh:
        events = json.load(fh)
    if not isinstance(events, list):
        print("events file is not a list")
        sys.exit(1)
    pool = await asyncpg.create_pool(url, min_size=1, max_size=2)
    try:
        await _replay(pool, events)
    finally:
        await pool.close()


if __name__ == "__main__":
    asyncio.run(main())
