#!/usr/bin/env python3
"""
GAP audit: Path A (Zoom AI summary) + Path B (full transcript) learning injection points.

Usage (backend container):
  python3 /app/scripts/verify_zoom_learning_gap_audit.py --session SES_20260612_BA421D4DB964
  python3 /app/scripts/verify_zoom_learning_gap_audit.py --client CLIENT_ZACKS99_ID --backfill-classroom-pg
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
log = logging.getLogger("verify_zoom_learning_gap")


async def _pool() -> asyncpg.Pool:
    url = os.getenv(
        "DATABASE_URL",
        "postgresql://nate_admin:nate_admin_2025@postgres:5432/little_nate",
    )
    return await asyncpg.create_pool(url, min_size=1, max_size=3)


def _print_report(report: dict) -> None:
    print("\n=== ZOOM LEARNING GAP AUDIT ===")
    print(f"Session: {report.get('session_id')}  Client: {report.get('client_id')}")
    print(
        f"Path A: {'PASS' if report.get('path_a_ok') else 'FAIL'}  "
        f"Path B: {'PASS' if report.get('path_b_ok') else 'FAIL'}  "
        f"({report.get('passed')}/{report.get('total')})"
    )
    for c in report.get("checks") or []:
        mark = "PASS" if c.get("ok") else "GAP "
        print(f"  [{mark}] {c.get('path')}-{c.get('id')} {c.get('name')}: {c.get('detail')}")
        if not c.get("ok") and c.get("gap"):
            print(f"         -> {c.get('gap')}")
    print(json.dumps(report, indent=2, default=str))


async def main() -> int:
    parser = argparse.ArgumentParser(description="Zoom Path A+B learning GAP audit")
    parser.add_argument("--session", default=None)
    parser.add_argument("--client", default=None)
    parser.add_argument(
        "--backfill-classroom-pg",
        action="store_true",
        help="Upsert classroom_session_analyses from analyzer vault before audit",
    )
    parser.add_argument(
        "--queue-transcript-crystal",
        action="store_true",
        help="Queue zoom_session_transcript crystal from archived VTT if missing",
    )
    parser.add_argument(
        "--queue-cross-ref-crystal",
        action="store_true",
        help="Queue zoom_cross_reference crystal when summary + transcript exist",
    )
    args = parser.parse_args()

    pool = await _pool()
    try:
        from app.services.zoom_learning_registry import (
            audit_zoom_learning_gaps_pg,
            queue_cross_reference_crystal,
            queue_transcript_crystal,
        )
        from app.services.zoom_transcript_context import load_session_transcript_excerpt

        if args.queue_transcript_crystal and args.session:
            async with pool.acquire() as conn:
                row = await conn.fetchrow(
                    "SELECT client_id, client_name, session_data FROM coaching_sessions WHERE session_id = $1",
                    args.session,
                )
            if row:
                sd = row["session_data"]
                if isinstance(sd, str):
                    sd = json.loads(sd) if sd else {}
                excerpt, _ = await load_session_transcript_excerpt(sd)
                if excerpt:
                    from app.services.blob_storage import download_bytes

                    loc = (sd.get("transcript_location") or "").strip()
                    kind = sd.get("transcript_storage") or "local"
                    raw = download_bytes(location=loc, storage_kind=kind)
                    vtt = raw.decode("utf-8", errors="ignore") if raw else excerpt
                    await queue_transcript_crystal(
                        pool,
                        row["client_id"],
                        row["client_name"] or "",
                        vtt,
                        args.session,
                    )

        if args.queue_cross_ref_crystal and args.session:
            async with pool.acquire() as conn:
                row = await conn.fetchrow(
                    """
                    SELECT client_id, client_name,
                           session_data->>'zoom_ai_summary_text' AS summary_text
                    FROM coaching_sessions WHERE session_id = $1
                    """,
                    args.session,
                )
            if row and (row["summary_text"] or "").strip():
                await queue_cross_reference_crystal(
                    pool,
                    row["client_id"],
                    row["client_name"] or "",
                    args.session,
                    row["summary_text"],
                )

        report = await audit_zoom_learning_gaps_pg(
            pool,
            session_id=args.session,
            client_id=args.client,
            backfill_classroom_pg=args.backfill_classroom_pg,
        )
        _print_report(report)
        if report.get("error"):
            log.error(report["error"])
            return 1
        if report.get("all_ok"):
            log.info("ALL LEARNING POINTS PASS")
            return 0
        log.error("GAP FAILURES — see checks above")
        return 2
    finally:
        await pool.close()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
