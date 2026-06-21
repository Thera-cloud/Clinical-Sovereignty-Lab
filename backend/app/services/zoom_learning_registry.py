"""
Path A + Path B Zoom session learning — surfaces, coach context, GAP audit.

Central registry for origin_surface values and verification that every
learning injection point receives data from archived summaries + transcripts.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# Crystals counted as lived wisdom in nate_agent_api metrics
LIVED_ORIGIN_SURFACES: Tuple[str, ...] = (
    "bridge_chat",
    "voice_call",
    "family_sanctuary",
    "group_coaching",
    "private_coaching",
    "coached_response",
    "growth_engine",
    "clinical_edge_seed",
    "zoom_session_summary",
    "zoom_session_transcript",
    "zoom_cross_reference",
)

ZOOM_PATH_A_SURFACES = ("zoom_session_summary",)
ZOOM_PATH_B_SURFACES = (
    "zoom_session_transcript",
    "zoom_cross_reference",
    "classroom_zoom",
)


def lived_origin_sql_in() -> str:
    """SQL fragment: 'a','b',... for origin_surface IN (...)"""
    return ",".join(f"'{s}'" for s in LIVED_ORIGIN_SURFACES)


def _check(id_: str, name: str, path: str, ok: bool, detail: str) -> Dict[str, Any]:
    return {
        "id": id_,
        "name": name,
        "path": path,
        "ok": bool(ok),
        "detail": detail,
        "gap": "" if ok else f"Missing: {name}",
    }


async def queue_transcript_crystal(
    db_pool,
    client_id: str,
    client_name: str,
    vtt_text: str,
    session_id: str,
    max_excerpt: int = 1200,
) -> bool:
    """Path B: crystallize dialogue excerpt as zoom_session_transcript."""
    if not db_pool or not client_id or not (vtt_text or "").strip():
        return False
    try:
        from app.services.zoom_transcript_context import vtt_to_dialogue_excerpt
        from app.websocket.crystal_recall_bridge import crystallize_from_conversation

        excerpt = vtt_to_dialogue_excerpt(vtt_text, max_chars=max_excerpt)
        if len(excerpt.strip()) < 80:
            return False
        user_text = f"Session {session_id} transcript excerpt:\n{excerpt[:max_excerpt]}"
        await crystallize_from_conversation(
            db_pool,
            client_id,
            user_text,
            "Archived live session dialogue for therapeutic recall.",
            user_name=client_name or "",
            domain="clinical",
            min_score=0,
            origin_surface="zoom_session_transcript",
        )
        logger.info("[Zoom] Transcript crystal queued for session %s", session_id)
        return True
    except Exception as e:
        logger.warning("[Zoom] Transcript crystal failed for %s: %s", session_id, e)
        return False


async def queue_cross_reference_crystal(
    db_pool,
    client_id: str,
    client_name: str,
    session_id: str,
    zoom_summary_text: str,
) -> bool:
    """Path B cross-modal crystal when both summary and transcript exist."""
    if not db_pool or not client_id or not (zoom_summary_text or "").strip():
        return False
    try:
        from app.routers.sessions import CLASSROOM_AVAILABLE, _classroom_analyzer
        from app.websocket.crystal_recall_bridge import crystallize_from_conversation

        nate_summary = ""
        if CLASSROOM_AVAILABLE and _classroom_analyzer:
            ana = _classroom_analyzer.get_session_analysis(session_id)
            if isinstance(ana, dict):
                nate_summary = (ana.get("transcript_excerpt") or "")[:500]
        if not nate_summary:
            from app.services.zoom_transcript_context import load_session_transcript_excerpt

            async with db_pool.acquire() as conn:
                sd_row = await conn.fetchval(
                    "SELECT session_data FROM coaching_sessions WHERE session_id = $1",
                    session_id,
                )
            excerpt, _ = await load_session_transcript_excerpt(sd_row)
            nate_summary = (excerpt or "")[:500]
        cross_ref = (
            f"Zoom AI observed: {zoom_summary_text[:500]}\n"
            f"Little Nate observed: {nate_summary[:500]}"
        )
        await crystallize_from_conversation(
            db_pool,
            client_id,
            cross_ref,
            "Cross-modal session intelligence",
            user_name=client_name or "",
            domain="clinical",
            min_score=0,
            origin_surface="zoom_cross_reference",
        )
        return True
    except Exception as e:
        logger.warning("queue_cross_reference_crystal(%s): %s", session_id, e)
        return False


async def backfill_classroom_pg_from_analyzer(
    db_pool,
    session_id: str,
) -> bool:
    """Upsert classroom_session_analyses from in-container ClassroomAnalyzer vault."""
    if not db_pool or not session_id:
        return False
    try:
        from app.routers.sessions import CLASSROOM_AVAILABLE, _classroom_analyzer
        from app.services.pg_data_helpers import upsert_classroom_analysis_pg

        if not CLASSROOM_AVAILABLE or not _classroom_analyzer:
            return False
        analysis = _classroom_analyzer.get_session_analysis(session_id)
        if not isinstance(analysis, dict) or not analysis.get("session_id"):
            return False
        return await upsert_classroom_analysis_pg(db_pool, analysis)
    except Exception as e:
        logger.warning("backfill_classroom_pg_from_analyzer(%s): %s", session_id, e)
        return False


async def build_coach_nate_zoom_context(
    db_pool,
    client_id: str,
    coach_id: Optional[str] = None,
) -> str:
    """Auto-inject Path A + B blocks for Coach Nate chat when client_id is known."""
    if not db_pool or not client_id:
        return ""
    blocks: List[str] = []
    try:
        from app.services.zoom_session_folder import get_folder_session_summaries_context_pg

        folder_ctx = await get_folder_session_summaries_context_pg(db_pool, client_id, limit=2)
        if folder_ctx:
            blocks.append(folder_ctx)
    except Exception as e:
        logger.debug("coach nate folder ctx: %s", e)
    try:
        from app.services.zoom_transcript_context import get_zoom_transcript_context_pg

        tx_ctx = await get_zoom_transcript_context_pg(db_pool, client_id, limit=2)
        if tx_ctx:
            blocks.append(tx_ctx)
    except Exception as e:
        logger.debug("coach nate transcript ctx: %s", e)
    if coach_id:
        try:
            from app.services.pg_data_helpers import get_classroom_lived_wisdom_pg

            lw = await get_classroom_lived_wisdom_pg(
                db_pool, coach_id, client_id=client_id, limit=3
            )
            if lw:
                blocks.append(lw)
        except Exception as e:
            logger.debug("coach nate lived wisdom: %s", e)
    return "\n\n".join(blocks)


async def enrich_presession_brief_zoom(
    db_pool,
    client_id: str,
    brief: Dict[str, Any],
) -> Dict[str, Any]:
    """Add Path A/B zoom learning fields to presession brief payload."""
    out = dict(brief)
    if not db_pool or not client_id:
        return out
    try:
        from app.services.zoom_transcript_context import (
            get_sessions_with_transcripts_pg,
            load_session_transcript_excerpt,
        )
        from app.services.zoom_session_folder import get_folder_session_summaries_context_pg

        folder_ctx = await get_folder_session_summaries_context_pg(db_pool, client_id, limit=1)
        if folder_ctx:
            out["zoom_folder_summary_context"] = folder_ctx[:2000]
        rows = await get_sessions_with_transcripts_pg(db_pool, client_id, limit=1)
        if rows:
            row = rows[0]
            sd = row.get("session_data")
            excerpt, raw_len = await load_session_transcript_excerpt(sd, max_chars=1500)
            if excerpt:
                out["zoom_transcript_excerpt"] = excerpt
                out["zoom_transcript_meta"] = {
                    "session_id": row.get("session_id"),
                    "raw_chars": raw_len,
                }
    except Exception as e:
        logger.debug("enrich_presession_brief_zoom: %s", e)
    return out


async def enrich_coach_briefing_zoom(
    db_pool,
    client_id: str,
    briefing: Dict[str, Any],
    coach_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Add zoom learning bundle to coach_get_client_briefing payload."""
    out = dict(briefing)
    ctx = await build_coach_nate_zoom_context(db_pool, client_id, coach_id=coach_id)
    if ctx:
        out["zoom_session_learning"] = ctx[:8000]
    return out


async def _resolve_user_keys(db_pool, client_id: str) -> List[str]:
    keys = [client_id] if client_id else []
    try:
        from app.services.zoom_session_folder import _resolve_client_username

        username, hw = await _resolve_client_username(db_pool, client_id)
        for v in (username, hw):
            if v and v not in keys:
                keys.append(v)
    except Exception:
        pass
    try:
        async with db_pool.acquire() as conn:
            uid = await conn.fetchval(
                "SELECT id::text FROM users WHERE hardware_id = $1 OR username = $1 LIMIT 1",
                client_id,
            )
            if uid and uid not in keys:
                keys.append(uid)
    except Exception:
        pass
    return keys


async def _crystal_count(db_pool, origin_surface: str, user_keys: List[str]) -> int:
    uuid_keys: List[str] = []
    try:
        async with db_pool.acquire() as conn:
            for k in user_keys:
                uid = await conn.fetchval(
                    """
                    SELECT id::text FROM users
                    WHERE hardware_id = $1 OR username = $1 OR id::text = $1
                    LIMIT 1
                    """,
                    k,
                )
                if uid and uid not in uuid_keys:
                    uuid_keys.append(uid)
            if uuid_keys:
                return int(
                    await conn.fetchval(
                        """
                        SELECT COUNT(*) FROM nate_intelligence_crystals
                        WHERE origin_surface = $1
                          AND scope != 'archived'
                          AND user_id::text = ANY($2::text[])
                        """,
                        origin_surface,
                        uuid_keys,
                    )
                    or 0
                )
            return int(
                await conn.fetchval(
                    """
                    SELECT COUNT(*) FROM nate_intelligence_crystals
                    WHERE origin_surface = $1 AND scope != 'archived'
                    """,
                    origin_surface,
                )
                or 0
            )
    except Exception:
        return 0


async def audit_zoom_learning_gaps_pg(
    db_pool,
    session_id: Optional[str] = None,
    client_id: Optional[str] = None,
    backfill_classroom_pg: bool = False,
) -> Dict[str, Any]:
    """
    GAP pass: verify every Path A and Path B learning injection point for a session/client.
    """
    checks: List[Dict[str, Any]] = []
    if not db_pool:
        return {"ok": False, "error": "no db_pool", "checks": []}

    row: Optional[Dict[str, Any]] = None
    async with db_pool.acquire() as conn:
        if session_id:
            r = await conn.fetchrow(
                """
                SELECT session_id, coach_id, client_id, client_name, zoom_meeting_id,
                       session_data, scheduled_start
                FROM coaching_sessions WHERE session_id = $1 LIMIT 1
                """,
                session_id,
            )
        elif client_id:
            r = await conn.fetchrow(
                """
                SELECT session_id, coach_id, client_id, client_name, zoom_meeting_id,
                       session_data, scheduled_start
                FROM coaching_sessions
                WHERE client_id = $1 AND COALESCE(zoom_meeting_id, '') <> ''
                ORDER BY scheduled_start DESC NULLS LAST LIMIT 1
                """,
                client_id,
            )
        else:
            return {"ok": False, "error": "session_id or client_id required", "checks": []}
        row = dict(r) if r else None

    if not row:
        return {"ok": False, "error": "session not found", "checks": []}

    sid = row["session_id"]
    cid = row["client_id"] or client_id or ""
    coach_id = row.get("coach_id") or ""
    sd_raw = row.get("session_data") or {}
    sd = sd_raw if isinstance(sd_raw, dict) else json.loads(sd_raw) if sd_raw else {}

    if backfill_classroom_pg:
        await backfill_classroom_pg_from_analyzer(db_pool, sid)

    user_keys = await _resolve_user_keys(db_pool, cid)

    # --- Path A ---
    summary_text = (sd.get("zoom_ai_summary_text") or "").strip()
    checks.append(
        _check(
            "A1",
            "session_data.zoom_ai_summary_text",
            "A",
            len(summary_text) > 50,
            f"chars={len(summary_text)}",
        )
    )

    folder_file_id = (
        (sd.get("zoom_folder_file_id") or sd.get("coach_folder_summary_file_id") or "").strip()
    )
    if not folder_file_id:
        try:
            async with db_pool.acquire() as conn:
                fid = await conn.fetchval(
                    """
                    SELECT f.id::text FROM coach_folder_files f
                    WHERE f.file_type = 'session_summary'
                      AND f.metadata->>'session_id' = $1
                    LIMIT 1
                    """,
                    sid,
                )
                folder_file_id = (fid or "").strip()
        except Exception:
            pass
    checks.append(
        _check(
            "A2",
            "coach folder summary file id",
            "A",
            bool(folder_file_id),
            f"file_id={folder_file_id or 'none'}",
        )
    )

    try:
        from app.services.zoom_session_folder import get_folder_session_summaries_context_pg

        folder_ctx = await get_folder_session_summaries_context_pg(db_pool, cid, limit=2)
        checks.append(
            _check(
                "A3",
                "folder summary LN context",
                "A",
                len(folder_ctx or "") > 80,
                f"context_chars={len(folder_ctx or '')}",
            )
        )
    except Exception as e:
        checks.append(_check("A3", "folder summary LN context", "A", False, str(e)))

    n_summary = await _crystal_count(db_pool, "zoom_session_summary", user_keys)
    checks.append(
        _check(
            "A4",
            "zoom_session_summary crystal",
            "A",
            n_summary > 0,
            f"count={n_summary}",
        )
    )

    # --- Path B ---
    loc = (sd.get("transcript_location") or "").strip()
    checks.append(
        _check("B1", "transcript_location archived", "B", bool(loc), loc[:80] or "empty")
    )
    checks.append(
        _check(
            "B2",
            "nate_read_transcript_at",
            "B",
            bool((sd.get("nate_read_transcript_at") or "").strip()),
            str(sd.get("nate_read_transcript_at") or "unset"),
        )
    )

    raw_len = 0
    excerpt_len = 0
    try:
        from app.services.zoom_transcript_context import (
            get_zoom_transcript_context_pg,
            load_session_transcript_excerpt,
        )

        excerpt, raw_len = await load_session_transcript_excerpt(sd)
        excerpt_len = len(excerpt or "")
        tx_ctx = await get_zoom_transcript_context_pg(db_pool, cid, limit=2)
        checks.append(
            _check(
                "B3",
                "raw transcript load",
                "B",
                raw_len > 500,
                f"raw_chars={raw_len} source={sd.get('transcript_source')}",
            )
        )
        checks.append(
            _check(
                "B4",
                "LN transcript context block",
                "B",
                len(tx_ctx or "") > 100,
                f"context_chars={len(tx_ctx or '')}",
            )
        )
    except Exception as e:
        checks.append(_check("B3", "raw transcript load", "B", False, str(e)))
        checks.append(_check("B4", "LN transcript context block", "B", False, str(e)))

    csa_row = None
    try:
        async with db_pool.acquire() as conn:
            csa_row = await conn.fetchrow(
                """
                SELECT status, therapeutic_presence_score,
                       COALESCE(length(payload::text), 0) AS payload_len
                FROM classroom_session_analyses WHERE session_id = $1 LIMIT 1
                """,
                sid,
            )
    except Exception:
        pass
    checks.append(
        _check(
            "B5",
            "classroom_session_analyses PG row",
            "B",
            csa_row is not None,
            f"status={csa_row['status'] if csa_row else 'missing'} payload_len={csa_row['payload_len'] if csa_row else 0}",
        )
    )

    n_xref = await _crystal_count(db_pool, "zoom_cross_reference", user_keys)
    checks.append(
        _check(
            "B6",
            "zoom_cross_reference crystal",
            "B",
            n_xref > 0,
            f"count={n_xref}",
        )
    )
    n_tx_crystal = await _crystal_count(db_pool, "zoom_session_transcript", user_keys)
    checks.append(
        _check(
            "B7",
            "zoom_session_transcript crystal",
            "B",
            n_tx_crystal > 0,
            f"count={n_tx_crystal}",
        )
    )

    wisdom_rows = 0
    try:
        async with db_pool.acquire() as conn:
            coach_uid = await conn.fetchval(
                "SELECT id FROM users WHERE hardware_id = $1 OR username = $1 LIMIT 1",
                coach_id,
            )
            if coach_uid:
                wisdom_rows = int(
                    await conn.fetchval(
                        """
                        SELECT COUNT(*) FROM wisdom_extractions
                        WHERE source = 'classroom_zoom' AND user_id = $1
                        """,
                        coach_uid,
                    )
                    or 0
                )
    except Exception:
        pass
    checks.append(
        _check(
            "B8",
            "wisdom_extractions row",
            "B",
            wisdom_rows > 0 or sd.get("classroom_analysis_available"),
            f"rows={wisdom_rows} classroom_flag={sd.get('classroom_analysis_available')}",
        )
    )

    try:
        from app.services.pg_data_helpers import get_classroom_context_for_client_pg

        classroom_ctx = await get_classroom_context_for_client_pg(db_pool, cid, limit=2)
        has_summary = "ZOOM" in (classroom_ctx or "").upper() and "SUMMAR" in (
            classroom_ctx or ""
        ).upper()
        has_transcript = "ZOOM SESSION TRANSCRIPTS" in (classroom_ctx or "")
        checks.append(
            _check(
                "B9",
                "client chat classroom context (summary+transcript)",
                "B",
                has_transcript and (has_summary or len(summary_text) > 0),
                f"classroom_ctx_chars={len(classroom_ctx or '')} summary_in_ctx={has_summary} transcript_in_ctx={has_transcript}",
            )
        )
    except Exception as e:
        checks.append(_check("B9", "client chat classroom context", "B", False, str(e)))

    coach_ctx = await build_coach_nate_zoom_context(db_pool, cid, coach_id=coach_id)
    checks.append(
        _check(
            "B10",
            "coach Nate auto zoom context",
            "B",
            len(coach_ctx or "") > 150,
            f"chars={len(coach_ctx or '')}",
        )
    )

    passed = sum(1 for c in checks if c["ok"])
    total = len(checks)
    path_a_ok = all(c["ok"] for c in checks if c["path"] == "A")
    path_b_ok = all(c["ok"] for c in checks if c["path"] == "B")

    return {
        "session_id": sid,
        "client_id": cid,
        "coach_id": coach_id,
        "zoom_meeting_id": row.get("zoom_meeting_id"),
        "path_a_ok": path_a_ok,
        "path_b_ok": path_b_ok,
        "passed": passed,
        "total": total,
        "all_ok": passed == total,
        "checks": checks,
        "transcript_raw_chars": raw_len,
        "transcript_excerpt_chars": excerpt_len,
        "summary_text_chars": len(summary_text),
    }
