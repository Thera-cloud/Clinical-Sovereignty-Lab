#!/usr/bin/env python3
"""
Verify Path B: Little Nate pulls full archived Zoom transcripts for learning.

Usage (backend container):
  python3 /app/scripts/verify_zoom_transcript_path_b.py --session SES_20260612_BA421D4DB964
  python3 /app/scripts/verify_zoom_transcript_path_b.py --meeting 93066514783 --archive-if-missing
  python3 /app/scripts/verify_zoom_transcript_path_b.py --client CLIENT_ZACKS99_ID
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys

import asyncpg

sys.path.insert(0, "/app")
sys.path.insert(0, "/opt/clinical-sovereignty-lab/backend")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
log = logging.getLogger("verify_zoom_transcript_path_b")


async def _pool() -> asyncpg.Pool:
    url = os.getenv(
        "DATABASE_URL",
        "postgresql://nate_admin:nate_admin_2025@postgres:5432/little_nate",
    )
    return await asyncpg.create_pool(url, min_size=1, max_size=3)


async def _resolve_session(
    pool: asyncpg.Pool,
    session_id: str | None,
    meeting_id: str | None,
    client_id: str | None,
) -> dict | None:
    async with pool.acquire() as conn:
        if session_id:
            row = await conn.fetchrow(
                """
                SELECT session_id, coach_id, client_id, client_name,
                       zoom_meeting_id, session_data, scheduled_start
                FROM coaching_sessions WHERE session_id = $1 LIMIT 1
                """,
                session_id,
            )
        elif meeting_id:
            row = await conn.fetchrow(
                """
                SELECT session_id, coach_id, client_id, client_name,
                       zoom_meeting_id, session_data, scheduled_start
                FROM coaching_sessions
                WHERE zoom_meeting_id = $1
                ORDER BY scheduled_start DESC NULLS LAST LIMIT 1
                """,
                str(meeting_id),
            )
        elif client_id:
            row = await conn.fetchrow(
                """
                SELECT session_id, coach_id, client_id, client_name,
                       zoom_meeting_id, session_data, scheduled_start
                FROM coaching_sessions
                WHERE client_id = $1 AND COALESCE(zoom_meeting_id, '') <> ''
                ORDER BY scheduled_start DESC NULLS LAST LIMIT 1
                """,
                client_id,
            )
        else:
            return None
    return dict(row) if row else None


async def main() -> int:
    parser = argparse.ArgumentParser(description="Verify Zoom Path B transcript pull")
    parser.add_argument("--session", default=None)
    parser.add_argument("--meeting", default=None)
    parser.add_argument("--client", default=None, help="client hardware_id or username")
    parser.add_argument(
        "--archive-if-missing",
        action="store_true",
        help="Run archive pipeline when transcript_location is empty",
    )
    args = parser.parse_args()

    pool = await _pool()
    try:
        row = await _resolve_session(pool, args.session, args.meeting, args.client)
        if not row:
            log.error("No coaching_sessions row matched")
            return 1

        session_id = row["session_id"]
        client_id = row["client_id"]
        sd = row.get("session_data") or {}
        if isinstance(sd, str):
            sd = json.loads(sd) if sd else {}

        log.info(
            "Session %s client=%s meeting=%s transcript_location=%s",
            session_id,
            client_id,
            row.get("zoom_meeting_id"),
            (sd.get("transcript_location") or "")[:80],
        )

        if args.archive_if_missing and not (sd.get("transcript_location") or "").strip():
            from app.routers.zoom import (
                _archive_transcript_and_classroom_for_pg_session,
                _pick_transcript_from_recording_files,
                _try_whisper_audio_fallback,
            )
            from app.services.zoom_client import ZoomClient

            mid = str(row.get("zoom_meeting_id") or "")
            zc = ZoomClient.from_env()
            rec = await zc.get_meeting_recordings(meeting_id=mid)
            files = rec.get("recording_files") or []
            t_url, t_ext = _pick_transcript_from_recording_files(files)
            transcript_source = "zoom_native"
            if t_url:
                vtt_bytes = await zc.download_recording_file(download_url=t_url)
            else:
                vtt_bytes, t_ext = await _try_whisper_audio_fallback(files, zc, mid)
                transcript_source = "whisper_fallback"
            if vtt_bytes:
                await _archive_transcript_and_classroom_for_pg_session(
                    pool, row, vtt_bytes, t_ext or "vtt", mid,
                    transcript_source=transcript_source,
                )
                log.info("Archived %d transcript bytes", len(vtt_bytes))
            else:
                log.warning("No transcript available from Zoom yet")
            row = await _resolve_session(pool, session_id, None, None)
            if not row:
                return 1

        from app.services.zoom_transcript_context import (
            get_zoom_transcript_context_pg,
            verify_path_b_transcript_for_client,
        )
        from app.services.pg_data_helpers import get_classroom_context_for_client_pg

        report = await verify_path_b_transcript_for_client(pool, client_id)
        ln_ctx = await get_zoom_transcript_context_pg(pool, client_id, limit=2)
        classroom_ctx = await get_classroom_context_for_client_pg(pool, client_id, limit=2)

        print(json.dumps(report, indent=2, default=str))
        log.info("LN transcript context chars: %d", len(ln_ctx))
        log.info("LN classroom context chars: %d", len(classroom_ctx))
        log.info(
            "Path B transcript in classroom context: %s",
            "ZOOM SESSION TRANSCRIPTS" in (classroom_ctx or ""),
        )

        ok = report.get("path_b_pull_ok") and (
            "ZOOM SESSION TRANSCRIPTS" in (classroom_ctx or "")
            or "ZOOM SESSION TRANSCRIPTS" in (ln_ctx or "")
        )
        if ok:
            log.info("PASS — Little Nate Path B transcript pull verified")
            return 0
        log.error("FAIL — transcript not loaded into LN context")
        return 2
    finally:
        await pool.close()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
