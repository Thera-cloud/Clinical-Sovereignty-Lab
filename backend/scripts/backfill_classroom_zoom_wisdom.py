#!/usr/bin/env python3
"""Attach classroom_zoom wisdom to coaching_sessions.id for existing live sessions.

Never charges. Does not print transcript or summary bodies.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def _sd(raw) -> dict:
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str) and raw.strip():
        try:
            parsed = json.loads(raw)
            return parsed if isinstance(parsed, dict) else {}
        except Exception:
            return {}
    return {}


async def main_async(args: argparse.Namespace) -> int:
    import asyncpg
    from app.services.zoom_learning_registry import (
        classroom_zoom_wisdom_count,
        record_classroom_zoom_wisdom,
    )

    url = args.database_url or os.getenv("DATABASE_URL") or ""
    if not url:
        print("DATABASE_URL missing", file=sys.stderr)
        return 2
    pool = await asyncpg.create_pool(url, min_size=1, max_size=4)
    wrote = 0
    scanned = 0
    skipped = 0
    try:
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT session_id, coach_id, client_id, client_name, session_data
                  FROM coaching_sessions
                 WHERE LOWER(COALESCE(status, '')) IN
                       ('completed', 'active', 'scheduled')
                   AND (
                        COALESCE(session_data->>'zoom_folder_doc_placed', '')
                            IN ('true', 'True', '1')
                     OR length(COALESCE(session_data->>'zoom_ai_summary_text', '')) > 40
                     OR length(COALESCE(session_data->>'transcript_location', '')) > 0
                   )
                 ORDER BY COALESCE(actual_end, scheduled_start, scheduled_at) DESC NULLS LAST
                 LIMIT $1
                """,
                int(args.limit),
            )
        for row in rows:
            scanned += 1
            sid = str(row["session_id"] or "").strip()
            if not sid:
                continue
            already = await classroom_zoom_wisdom_count(pool, sid)
            if already > 0 and not args.force:
                skipped += 1
                print(f"skip {sid} already={already}")
                continue
            sd = _sd(row["session_data"])
            body = (sd.get("zoom_ai_summary_text") or "").strip()
            if len(body) < 40:
                loc = (sd.get("transcript_location") or "").strip()
                if loc.startswith("/") and Path(loc).is_file():
                    raw = Path(loc).read_text(encoding="utf-8", errors="ignore")[:8000]
                    body = raw.strip()
            if len(body) < 40:
                skipped += 1
                print(f"skip {sid} no_summary")
                continue
            if args.dry_run:
                print(f"dry-run {sid} chars={len(body)}")
                continue
            n = await record_classroom_zoom_wisdom(
                pool,
                session_id=sid,
                coach_id=str(row["coach_id"] or ""),
                client_id=str(row["client_id"] or ""),
                content=body,
                client_name=str(row["client_name"] or ""),
            )
            wrote += n
            print(f"write {sid} rows={n}")
    finally:
        await pool.close()
    print(f"scanned={scanned} skipped={skipped} inserted={wrote}")
    return 0


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--database-url", default="")
    p.add_argument("--limit", type=int, default=500)
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--force", action="store_true")
    args = p.parse_args()
    raise SystemExit(asyncio.run(main_async(args)))
