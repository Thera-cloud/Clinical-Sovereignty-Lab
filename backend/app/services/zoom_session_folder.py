"""
Place Zoom AI session summaries into the coach FOLDER tab + LN memory.

Triggered from recording webhook archive, drip poller, or manual admin/coach endpoint.
"""

from __future__ import annotations

import asyncio
import datetime as dt
import json
import logging
import os
import re
from typing import Any, Dict, Optional, Tuple

logger = logging.getLogger(__name__)

_FILE_TYPE = "session_summary"
_SOURCE_TAG = "zoom_hub_ai_summary"


def resolve_meeting_uuid_from_events(
    meeting_id: str,
    session_data: Optional[Dict[str, Any]] = None,
) -> str:
    """Return zoom_meeting_uuid from session_data or local zoom_events.json webhook log."""
    sd = _session_data_dict(session_data) if session_data is not None else {}
    cached = _as_str(sd.get("zoom_meeting_uuid"))
    if cached:
        return cached
    mid = _as_str(meeting_id)
    if not mid:
        return ""
    try:
        from pathlib import Path

        from app.config import settings

        events_path = Path(getattr(settings, "DATA_DIR", "/app/data")) / "zoom_events.json"
        if not events_path.is_file():
            return ""
        raw = json.loads(events_path.read_text(encoding="utf-8"))
        events = raw if isinstance(raw, list) else (raw.get("events") or [])
        found = ""
        for ev in reversed(events):
            if _as_str(ev.get("meeting_id")) != mid:
                continue
            obj = (((ev.get("payload") or {}).get("payload") or {}).get("object") or {})
            u = _as_str(obj.get("uuid"))
            if not u:
                continue
            found = u
            if ev.get("event") in ("meeting.ended", "recording.completed"):
                return u
        return found
    except Exception as e:
        logger.debug("resolve_meeting_uuid_from_events %s: %s", mid, e)
        return ""


def _session_data_dict(raw: Any) -> Dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str) and raw.strip():
        try:
            return json.loads(raw)
        except Exception:
            return {}
    return {}


def _flag_is_set(val: Any) -> bool:
    if val is True or val == 1:
        return True
    if isinstance(val, str):
        return val.strip().lower() in ("true", "1", "yes")
    return False


def _as_str(val: Any) -> str:
    if val is None or isinstance(val, bool):
        return ""
    return str(val).strip()


def _ascii_safe(text: str) -> str:
    return (
        (text or "")
        .replace("\u2014", "-")
        .replace("\u2013", "-")
        .replace("\u2018", "'")
        .replace("\u2019", "'")
        .replace("\u201c", '"')
        .replace("\u201d", '"')
        .encode("latin-1", errors="replace")
        .decode("latin-1")
    )


def _summary_text_from_api_payload(payload: Optional[Dict[str, Any]]) -> str:
    if not payload:
        return ""
    content = payload.get("summary_content")
    if isinstance(content, str) and content.strip():
        return content.strip()
    parts: list[str] = []
    overview = payload.get("summary_overview")
    if isinstance(overview, str) and overview.strip():
        parts.append(overview.strip())
    details = payload.get("summary_details")
    if isinstance(details, list):
        for item in details:
            if not isinstance(item, dict):
                continue
            label = (item.get("label") or "").strip()
            text = (item.get("summary") or "").strip()
            if text:
                parts.append(f"### {label}\n{text}" if label else text)
    steps = payload.get("next_steps")
    if isinstance(steps, list) and steps:
        parts.append("### Next steps\n" + "\n".join(f"- {s}" for s in steps if str(s).strip()))
    summary_block = payload.get("summary")
    if isinstance(summary_block, dict):
        for key in ("summary_details", "summary_overview", "overview"):
            val = summary_block.get(key)
            if isinstance(val, str) and val.strip():
                parts.append(val.strip())
    for key in ("summary_details", "summary_overview", "overview"):
        val = payload.get(key)
        if isinstance(val, str) and val.strip():
            parts.append(val.strip())
    return "\n\n".join(parts).strip()


def _build_markdown_document(
    *,
    client_name: str,
    session_id: str,
    meeting_id: str,
    summary_body: str,
    zoom_doc_url: str = "",
    scheduled_start: Optional[dt.datetime] = None,
) -> str:
    date_label = (
        scheduled_start.strftime("%Y-%m-%d")
        if scheduled_start and hasattr(scheduled_start, "strftime")
        else dt.datetime.utcnow().strftime("%Y-%m-%d")
    )
    lines = [
        f"# Session Summary — {client_name or 'Client'}",
        "",
        f"- **Session ID:** {session_id}",
        f"- **Zoom meeting:** {meeting_id}",
        f"- **Date:** {date_label}",
        "",
        "## AI Companion Summary",
        "",
        (summary_body or "").strip(),
    ]
    if zoom_doc_url:
        lines.extend(["", f"[Open in Zoom Hub]({zoom_doc_url})"])
    return "\n".join(lines).strip()


def _markdown_to_pdf_bytes(markdown_text: str, title: str) -> bytes:
    try:
        from fpdf import FPDF
    except ImportError:
        return (markdown_text or "").encode("utf-8")

    pdf = FPDF()
    pdf.set_left_margin(15)
    pdf.set_right_margin(15)
    pdf.set_auto_page_break(auto=True, margin=20)
    pdf.add_page()
    width = pdf.w - pdf.l_margin - pdf.r_margin

    pdf.set_font("Helvetica", "B", 14)
    pdf.multi_cell(width, 8, _ascii_safe(title or "Session Summary"))
    pdf.ln(4)
    pdf.set_font("Helvetica", "", 10)

    for line in (markdown_text or "").splitlines():
        if pdf.get_y() > 270:
            pdf.add_page()
        chunk = _ascii_safe(line) if line.strip() else " "
        pdf.multi_cell(width, 5, chunk)
    return bytes(pdf.output())


async def _resolve_client_username(db_pool, client_hardware_id: str) -> Tuple[str, str]:
    if not db_pool or not client_hardware_id:
        return "", ""
    try:
        from app.services.pg_data_helpers import find_user_pg, find_user_by_username_pg

        profile = await find_user_pg(db_pool, client_hardware_id)
        if not profile:
            profile = await find_user_by_username_pg(db_pool, client_hardware_id)
        if not profile:
            # UUID fallback (legacy End Session INSERT used users.id)
            try:
                async with db_pool.acquire() as conn:
                    row = await conn.fetchrow(
                        """SELECT username, COALESCE(name, '') AS name, hardware_id
                           FROM users WHERE id::text = $1 AND deleted_at IS NULL LIMIT 1""",
                        client_hardware_id,
                    )
                if row:
                    un = (row["username"] or "").strip() or client_hardware_id
                    return un, (row["name"] or "").strip() or un
            except Exception:
                pass
            return client_hardware_id, client_hardware_id
        username = (profile.get("username") or "").strip() or client_hardware_id
        name = (profile.get("name") or "").strip() or username
        return username, name
    except Exception as e:
        logger.warning("resolve_client_username failed: %s", e)
        return client_hardware_id, client_hardware_id


async def _patch_session_data(conn, session_id: str, patch: Dict[str, Any]) -> None:
    if not session_id or not patch:
        return
    await conn.execute(
        """
        UPDATE coaching_sessions
        SET session_data = COALESCE(session_data, '{}'::jsonb) || $2::jsonb,
            updated_at = NOW()
        WHERE session_id = $1
        """,
        session_id,
        json.dumps(patch, default=str),
    )


async def _find_coach_folder_id(
    conn,
    coach_id: str,
    client_username: str,
    client_hardware_id: str,
    client_name: str,
) -> Optional[Any]:
    for entity_id in (client_username, client_hardware_id):
        if not entity_id:
            continue
        row = await conn.fetchrow(
            """SELECT id FROM coach_folders
               WHERE coach_id = $1 AND entity_id = $2 AND folder_type = 'client'
               LIMIT 1""",
            coach_id,
            entity_id,
        )
        if row:
            return row["id"]
    entity_id = client_username or client_hardware_id
    if not entity_id:
        return None
    row = await conn.fetchrow(
        """INSERT INTO coach_folders (coach_id, folder_type, entity_id, entity_name)
           VALUES ($1, 'client', $2, $3)
           ON CONFLICT DO NOTHING
           RETURNING id""",
        coach_id,
        entity_id,
        client_name or entity_id,
    )
    if row:
        return row["id"]
    row = await conn.fetchrow(
        """SELECT id FROM coach_folders
           WHERE coach_id = $1 AND entity_id = $2 AND folder_type = 'client'
           LIMIT 1""",
        coach_id,
        entity_id,
    )
    return row["id"] if row else None


async def _fetch_summary_content(
    db_pool,
    pg_row: Dict[str, Any],
    meeting_id: str,
    summary_text: Optional[str],
) -> Tuple[str, str, str]:
    """Returns (summary_body, zoom_doc_url, zoom_doc_file_id)."""
    sd = _session_data_dict(pg_row.get("session_data"))
    body = (summary_text or "").strip()
    doc_url = (sd.get("zoom_doc_url") or "").strip()
    doc_file_id = (sd.get("zoom_doc_file_id") or "").strip()
    meeting_uuid = (sd.get("zoom_meeting_uuid") or "").strip()
    if not meeting_uuid:
        meeting_uuid = resolve_meeting_uuid_from_events(str(meeting_id), sd)
        if meeting_uuid:
            sd["zoom_meeting_uuid"] = meeting_uuid

    if not body:
        try:
            from app.services.zoom_client import ZoomClient

            zc = ZoomClient.from_env()
            payload = await zc.get_meeting_summary(
                meeting_id=str(meeting_id),
                meeting_uuid=meeting_uuid or None,
            )
            body = _summary_text_from_api_payload(payload)
            if payload:
                doc_url = (payload.get("summary_doc_url") or doc_url or "").strip()
                if doc_url and "/doc/" in doc_url:
                    doc_file_id = doc_url.rstrip("/").split("/doc/")[-1] or doc_file_id
        except Exception as e:
            logger.debug("meeting_summary fetch: %s", e)

    if not body:
        body = (sd.get("zoom_ai_summary_text") or "").strip()

    # QUANTUM-CRYSTAL-ARCH — End Session / coach-notes fallback (all tiers, incl. COACH_ONLY)
    if not body:
        body = (pg_row.get("nate_summary") or "").strip()
    if not body:
        notes = (pg_row.get("coach_notes") or pg_row.get("session_notes") or "").strip()
        if notes:
            body = f"Coach session notes:\n{notes}"

    if not body:
        session_id = (pg_row.get("session_id") or "").strip()
        try:
            from app.services.zoom_docs_client import ZoomDocsClient

            docs = ZoomDocsClient.from_env()
            if docs.is_configured():
                if not doc_file_id and session_id:
                    found = await docs.find_doc_by_session_id(session_id)
                    if found:
                        doc_file_id = found.get("file_id") or ""
                        doc_url = found.get("doc_url") or doc_url
                if doc_file_id:
                    md = await docs.get_file_markdown(doc_file_id)
                    if md:
                        body = md.strip()
        except Exception as e:
            logger.debug("Zoom Docs fetch: %s", e)

    if doc_file_id and not doc_url:
        doc_url = f"https://docs.zoom.us/doc/{doc_file_id}"
    return body, doc_url, doc_file_id


async def try_place_session_summary_in_coach_folder(
    db_pool,
    pg_row: Dict[str, Any],
    meeting_id: str,
    summary_text: Optional[str] = None,
) -> Optional[str]:
    """
    Upload PDF summary to coach folder + patch session_data.
    Returns coach_folder_files.id or None.
    """
    if not db_pool or not pg_row:
        return None

    session_id = (pg_row.get("session_id") or "").strip()
    coach_id = (pg_row.get("coach_id") or "").strip()
    client_hw = (pg_row.get("client_id") or "").strip()
    client_name = (pg_row.get("client_name") or "").strip()
    if not session_id or not coach_id or not client_hw:
        return None

    sd = _session_data_dict(pg_row.get("session_data"))
    existing_file_id = _as_str(sd.get("zoom_folder_file_id"))
    summary_from_zoom = (sd.get("zoom_summary_source") or "") == "zoom_api"
    if _flag_is_set(sd.get("zoom_folder_doc_placed")) and summary_from_zoom and not (summary_text or "").strip():
        return existing_file_id or None

    body, doc_url, doc_file_id = await _fetch_summary_content(
        db_pool, pg_row, meeting_id, summary_text
    )
    if not body:
        logger.info("[ZoomFolder] No summary yet for session %s meeting %s", session_id, meeting_id)
        return None

    client_username, resolved_name = await _resolve_client_username(db_pool, client_hw)
    if not client_name:
        client_name = resolved_name

    scheduled = pg_row.get("scheduled_start")
    md_doc = _build_markdown_document(
        client_name=client_name,
        session_id=session_id,
        meeting_id=str(meeting_id),
        summary_body=body,
        zoom_doc_url=doc_url,
        scheduled_start=scheduled,
    )
    date_slug = (
        scheduled.strftime("%Y-%m-%d")
        if scheduled and hasattr(scheduled, "strftime")
        else dt.datetime.utcnow().strftime("%Y-%m-%d")
    )
    safe_name = re.sub(r"[^\w\s-]", "", client_name or client_username).strip().replace(" ", "_")
    filename = f"Session_Summary_{safe_name}_{date_slug}.pdf"
    pdf_bytes = _markdown_to_pdf_bytes(md_doc, f"Session Summary — {client_name or client_username}")

    from app.services.blob_storage import upload_bytes

    rel_path = f"coach_uploads/{coach_id}/{client_username}/{session_id}/{filename}"
    storage_kind, location = upload_bytes(
        rel_path=rel_path,
        content=pdf_bytes,
        content_type="application/pdf",
    )

    metadata = {
        "source": _SOURCE_TAG,
        "session_id": session_id,
        "zoom_meeting_id": str(meeting_id),
        "client_hardware_id": client_hw,
        "client_username": client_username,
        "zoom_doc_url": doc_url or None,
        "zoom_doc_file_id": doc_file_id or None,
        "summary_preview": body[:4000],
        "markdown": md_doc[:50000],
    }
    now_iso = dt.datetime.utcnow().isoformat()

    file_id: Optional[str] = None
    async with db_pool.acquire() as conn:
        folder_id = await _find_coach_folder_id(
            conn, coach_id, client_username, client_hw, client_name
        )
        if not folder_id:
            logger.warning("[ZoomFolder] No folder for coach=%s client=%s", coach_id, client_username)
            return None
        if existing_file_id and (
            (summary_text or "").strip() or (sd.get("zoom_summary_source") or "") != "zoom_api"
        ):
            row = await conn.fetchrow(
                """UPDATE coach_folder_files
                   SET filename = $2, storage_url = $3, azure_blob_url = $3,
                       file_size_bytes = $4, metadata = $5::jsonb
                   WHERE id = $1::uuid AND folder_id = $6
                   RETURNING id""",
                existing_file_id,
                filename,
                location,
                len(pdf_bytes),
                json.dumps(metadata),
                folder_id,
            )
            file_id = str(row["id"]) if row else None
        else:
            row = await conn.fetchrow(
                """INSERT INTO coach_folder_files
                   (folder_id, filename, file_type, storage_url, azure_blob_url,
                    file_size_bytes, uploaded_by, metadata)
                   VALUES ($1, $2, $3, $4, $4, $5, 'Little Nate', $6::jsonb)
                   RETURNING id""",
                folder_id,
                filename,
                _FILE_TYPE,
                location,
                len(pdf_bytes),
                json.dumps(metadata),
            )
            file_id = str(row["id"]) if row else None
        if file_id:
            patch = {
                "zoom_folder_doc_placed": True,
                "zoom_folder_doc_placed_at": now_iso,
                "zoom_folder_file_id": file_id,
                "zoom_ai_summary_text": body[:50000],
                "zoom_folder_storage": storage_kind,
                "zoom_summary_source": "zoom_api" if not (summary_text or "").strip() else "manual_backfill",
            }
            if doc_url:
                patch["zoom_doc_url"] = doc_url
            if doc_file_id:
                patch["zoom_doc_file_id"] = doc_file_id
            await _patch_session_data(conn, session_id, patch)
            # QUANTUM-CRYSTAL-ARCH: summary without transcript — enqueue Path B fetch
            if file_id and not (sd.get("transcript_location") or "").strip():
                if not _flag_is_set(sd.get("transcript_pending")):
                    await _patch_session_data(
                        conn,
                        session_id,
                        {
                            "transcript_pending": True,
                            "transcript_enqueue_reason": "summary_placed",
                        },
                    )

    if file_id:
        logger.info(
            "[ZoomFolder] Placed session summary for %s → folder file %s (%s bytes)",
            session_id,
            file_id,
            len(pdf_bytes),
        )
        asyncio.create_task(_crystallize_summary(db_pool, client_hw, client_name, body, session_id))

    return file_id


async def _crystallize_summary(
    db_pool,
    client_hardware_id: str,
    client_name: str,
    summary_text: str,
    session_id: str,
) -> None:
    try:
        from app.websocket.crystal_recall_bridge import crystallize_from_conversation

        await crystallize_from_conversation(
            db_pool,
            client_hardware_id,
            summary_text[:2000],
            "Zoom session AI summary archived for coach review.",
            user_name=client_name or "",
            domain="coaching",
            min_score=3,
            origin_surface="zoom_session_summary",
        )
        logger.info("[ZoomFolder] Crystal queued for session %s", session_id)
    except Exception as e:
        logger.warning("[ZoomFolder] crystallize failed for %s: %s", session_id, e)


async def place_end_session_summary(
    db_pool,
    sess: Dict[str, Any],
    session_id: str,
    nate_summary: str,
    coach_notes: str,
) -> Optional[str]:
    """QUANTUM-CRYSTAL-ARCH — Place End Session summary PDF (all tiers incl. COACH_ONLY)."""
    if not db_pool or not session_id:
        return None
    coach_id = (sess.get("coach_id") or "").strip()
    client_id = (sess.get("client_id") or "").strip()
    if not coach_id or not client_id:
        return None
    body = (nate_summary or "").strip()
    notes = (coach_notes or "").strip()
    if notes:
        body = f"{body}\n\nCoach notes:\n{notes[:4000]}" if body else f"Coach notes:\n{notes[:4000]}"
    if not body:
        return None
    mid = str(sess.get("zoom_meeting_id") or session_id).strip()
    pg_row = {
        "session_id": session_id,
        "coach_id": coach_id,
        "client_id": client_id,
        "client_name": sess.get("client_name") or "",
        "nate_summary": nate_summary or "",
        "coach_notes": notes[:4000],
        "scheduled_start": None,
        "session_data": {},
        "zoom_meeting_id": mid,
    }
    return await try_place_session_summary_in_coach_folder(
        db_pool, pg_row, mid, summary_text=body
    )


async def poll_pending_zoom_session_summaries(db_pool) -> int:
    """
    Place folder summaries for recent Zoom sessions missing zoom_folder_doc_placed.
    Works even when transcript archive has not run yet.
    """
    if not db_pool:
        return 0
    placed = 0
    try:
        async with db_pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT session_id, coach_id, client_id, client_name,
                       zoom_meeting_id, session_data, scheduled_start,
                       nate_summary, coach_notes, session_notes
                FROM coaching_sessions
                WHERE COALESCE(zoom_meeting_id, '') <> ''
                  AND scheduled_start >= NOW() - INTERVAL '96 hours'
                  AND COALESCE(session_data->>'zoom_folder_doc_placed', '') NOT IN ('true', 'True', '1')
                ORDER BY scheduled_start DESC NULLS LAST
                LIMIT 20
                """
            )
        for row in rows:
            r = dict(row)
            mid = str(r.get("zoom_meeting_id") or "").strip()
            if not mid:
                continue
            try:
                fid = await try_place_session_summary_in_coach_folder(db_pool, r, mid)
                if fid:
                    placed += 1
            except Exception as pe:
                logger.warning(
                    "[ZoomFolder] poll failed session %s: %s",
                    r.get("session_id"),
                    pe,
                )
    except Exception as e:
        logger.warning("[ZoomFolder] poll_pending_zoom_session_summaries: %s", e)
    return placed


async def get_folder_session_summaries_context_pg(
    db_pool,
    client_id: str,
    limit: int = 2,
) -> str:
    """Recent Zoom session summaries from coach folders for LN context."""
    if not db_pool or not client_id:
        return ""
    try:
        username, _ = await _resolve_client_username(db_pool, client_id)
        entity_ids = [e for e in (username, client_id) if e]
        if not entity_ids:
            return ""

        async with db_pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT f.filename, f.metadata, f.created_at, cf.entity_name
                FROM coach_folder_files f
                JOIN coach_folders cf ON cf.id = f.folder_id
                WHERE cf.folder_type = 'client'
                  AND cf.entity_id = ANY($1::text[])
                  AND f.file_type = $2
                ORDER BY f.created_at DESC
                LIMIT $3
                """,
                entity_ids,
                _FILE_TYPE,
                limit,
            )
        if not rows:
            return ""

        parts = ["[ZOOM SESSION SUMMARIES — Coach folder archives]"]
        for r in rows:
            meta = r["metadata"]
            if isinstance(meta, str):
                try:
                    meta = json.loads(meta)
                except Exception:
                    meta = {}
            preview = ""
            if isinstance(meta, dict):
                preview = (meta.get("summary_preview") or meta.get("markdown") or "")[:1200]
            dt_label = (
                r["created_at"].strftime("%b %d, %Y")
                if r.get("created_at") and hasattr(r["created_at"], "strftime")
                else "recent"
            )
            sid = (meta.get("session_id") or "") if isinstance(meta, dict) else ""
            booked = None
            if sid:
                try:
                    from app.services.zoom_transcript_context import session_id_calendar_label

                    booked = session_id_calendar_label(sid)
                except Exception:
                    booked = None
            if booked:
                label = booked if booked == dt_label else f"{booked} (archived {dt_label})"
            else:
                label = dt_label
            parts.append(f"{label} — {r.get('filename') or 'summary'}:\n{preview}")
        parts.append(
            "These are verified session summaries from live coaching. "
            "Reference gently; do not quote the coach's private folder notes verbatim."
        )
        return "\n\n".join(parts)
    except Exception as e:
        logger.warning("get_folder_session_summaries_context_pg failed: %s", e)
        return ""
