"""
Backfill: archive Zoom transcripts for existing coaching_sessions.

Looks up every coaching_sessions row that has a zoom_meeting_id but no
session_data->>'transcript_location'. For each one, asks the Zoom API for the
meeting recording metadata and, if a transcript file (TRANSCRIPT / VTT / TXT)
exists, downloads it and runs the same archive + classroom + wisdom pipeline
the recording.completed webhook uses.

This is the one-time bridge from "rows in PG" → "items in the Classroom
dropdown" for sessions that pre-date the auto-archive wiring.

Usage (inside the backend container):
    docker exec -it nate_backend python3 /app/scripts/backfill_zoom_transcripts.py

Options:
    --dry-run        Only print what would happen, no Zoom calls or PG writes
    --limit N        Process at most N sessions (default 500)
    --meeting ID     Only process the given zoom_meeting_id
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys
from typing import Any, Dict, List, Optional

import asyncpg

sys.path.insert(0, "/app")
sys.path.insert(0, "/opt/clinical-sovereignty-lab/backend")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
log = logging.getLogger("backfill_zoom_transcripts")


async def _build_pool() -> asyncpg.Pool:
    db_url = os.getenv(
        "DATABASE_URL",
        "postgresql://nate_admin:nate_admin_2025@postgres:5432/little_nate",
    )
    return await asyncpg.create_pool(db_url, min_size=1, max_size=4)


async def _candidates(
    pool: asyncpg.Pool, meeting_filter: Optional[str], limit: int
) -> List[Dict[str, Any]]:
    where = (
        "zoom_meeting_id IS NOT NULL "
        "AND zoom_meeting_id <> '' "
        "AND COALESCE(session_data->>'transcript_location', '') = ''"
    )
    params: List[Any] = []
    if meeting_filter:
        where += " AND zoom_meeting_id = $1"
        params.append(str(meeting_filter))
    sql = f"""
        SELECT session_id, coach_id, client_id, client_name,
               zoom_meeting_id, session_data, scheduled_start
        FROM coaching_sessions
        WHERE {where}
        ORDER BY scheduled_start DESC NULLS LAST
        LIMIT {int(limit)}
    """
    async with pool.acquire() as conn:
        rows = await conn.fetch(sql, *params)
    return [dict(r) for r in rows]


async def _backfill_one(
    pool: asyncpg.Pool, row: Dict[str, Any], dry_run: bool
) -> str:
    from app.routers.zoom import (
        _archive_transcript_and_classroom_for_pg_session,
        _pick_transcript_from_recording_files,
    )
    from app.services.zoom_client import ZoomClient

    sid = str(row.get("session_id") or "")
    mid = str(row.get("zoom_meeting_id") or "")
    if not sid or not mid:
        return "skip_no_ids"

    zc = ZoomClient.from_env()
    try:
        rec = await zc.get_meeting_recordings(meeting_id=mid)
    except Exception as e:
        log.warning("zoom recordings lookup failed for %s/%s: %s", sid, mid, e)
        return "zoom_lookup_error"

    files = rec.get("recording_files") or []
    if not files:
        return "no_recording_files"

    t_url, t_ext = _pick_transcript_from_recording_files(files)
    if not t_url:
        if dry_run:
            log.info("DRY RUN would mark transcript_pending for %s/%s", sid, mid)
            return "would_mark_pending"
        try:
            import datetime as _dt
            import json as _json
            patch = {
                "recording_ready": True,
                "transcript_pending": True,
                "zoom_recording_webhook_at": _dt.datetime.utcnow().isoformat(),
            }
            async with pool.acquire() as conn:
                await conn.execute(
                    """
                    UPDATE coaching_sessions
                    SET session_data = COALESCE(session_data, '{}'::jsonb) || $2::jsonb,
                        updated_at = NOW()
                    WHERE session_id = $1
                    """,
                    sid,
                    _json.dumps(patch),
                )
            log.info(
                "no transcript yet for %s/%s — marked transcript_pending for drip poller",
                sid,
                mid,
            )
        except Exception as pe:
            log.warning("failed to mark transcript_pending for %s/%s: %s", sid, mid, pe)
            return "pending_mark_error"
        return "marked_pending"

    if dry_run:
        log.info("DRY RUN would archive %s/%s (ext=%s)", sid, mid, t_ext or "vtt")
        return "would_archive"

    try:
        vtt_bytes = await zc.download_recording_file(download_url=t_url)
    except Exception as e:
        log.warning("transcript download failed for %s/%s: %s", sid, mid, e)
        return "download_error"

    if not vtt_bytes:
        return "empty_transcript"

    try:
        await _archive_transcript_and_classroom_for_pg_session(
            pool, row, vtt_bytes, t_ext or "vtt", mid
        )
    except Exception as e:
        log.error(
            "archive pipeline failed for %s/%s: %s", sid, mid, e, exc_info=True
        )
        return "archive_error"

    return "archived"


async def main() -> int:
    parser = argparse.ArgumentParser(description="Backfill Zoom transcripts")
    parser.add_argument("--dry-run", action="store_true", help="No writes, no downloads")
    parser.add_argument("--limit", type=int, default=500)
    parser.add_argument("--meeting", type=str, default=None, help="Single zoom_meeting_id")
    args = parser.parse_args()

    pool = await _build_pool()
    try:
        rows = await _candidates(pool, args.meeting, args.limit)
        log.info("Found %d candidate session(s) without transcript_location", len(rows))
        if not rows:
            return 0

        counters: Dict[str, int] = {}
        for r in rows:
            try:
                outcome = await _backfill_one(pool, r, args.dry_run)
            except Exception as e:
                outcome = "exception"
                log.exception(
                    "Backfill exception for session %s / meeting %s: %s",
                    r.get("session_id"),
                    r.get("zoom_meeting_id"),
                    e,
                )
            counters[outcome] = counters.get(outcome, 0) + 1
            log.info(
                "session=%s meeting=%s -> %s",
                r.get("session_id"),
                r.get("zoom_meeting_id"),
                outcome,
            )

        log.info("Backfill summary: %s", counters)
        return 0
    finally:
        await pool.close()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
