"""Archive MASTER_CONSULTATION transcripts into the master's assistant folder.

QUANTUM-CRYSTAL-ARCH
"""

from __future__ import annotations

import datetime as dt
import json
import logging
import re
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

_ACTION_PATTERNS = (
    re.compile(r"(?im)^\s*(?:[-*]|\d+[.)])\s+(?:please\s+)?(.{12,180})$"),
    re.compile(r"(?im)^\s*(?:action\s*item|next\s*step|homework|request)\s*[:—-]\s*(.{8,180})$"),
)


async def ensure_assistant_folder(
    conn,
    master_hw: str,
    assistant_username: str,
    assistant_name: str,
) -> Optional[Any]:
    if not master_hw or not assistant_username:
        return None
    row = await conn.fetchrow(
        """SELECT id FROM coach_folders
           WHERE coach_id = $1 AND folder_type = 'assistant' AND entity_id = $2
           LIMIT 1""",
        master_hw,
        assistant_username,
    )
    if row:
        return row["id"]
    row = await conn.fetchrow(
        """INSERT INTO coach_folders (coach_id, folder_type, entity_id, entity_name)
           VALUES ($1, 'assistant', $2, $3)
           RETURNING id""",
        master_hw,
        assistant_username,
        assistant_name or assistant_username,
    )
    return row["id"] if row else None


def extract_action_items(text: str) -> List[str]:
    body = (text or "").strip()
    if not body:
        return []
    found: List[str] = []
    seen = set()
    for pat in _ACTION_PATTERNS:
        for m in pat.finditer(body):
            item = re.sub(r"\s+", " ", (m.group(1) or "").strip(" .;-"))
            key = item.lower()
            if len(item) < 8 or key in seen:
                continue
            if any(bad in key for bad in ("http", "password", "ssn")):
                continue
            seen.add(key)
            found.append(item[:180])
            if len(found) >= 8:
                return found
    return found


def _session_blob(row: Dict[str, Any]) -> str:
    parts = []
    for key in ("nate_summary", "coach_notes", "notes", "transcript_text"):
        val = (row.get(key) or "").strip()
        if val:
            parts.append(val)
    sd = row.get("session_data")
    if isinstance(sd, str):
        try:
            sd = json.loads(sd)
        except Exception:
            sd = {}
    if isinstance(sd, dict):
        for key in ("zoom_ai_summary_text", "transcript", "transcript_text"):
            val = (sd.get(key) or "").strip()
            if val:
                parts.append(val)
    return "\n\n".join(parts).strip()


async def archive_consultation_session(
    db_pool,
    pg_row: Dict[str, Any],
    *,
    summary_text: str = "",
) -> Optional[str]:
    """Write consult transcript into master's assistant folder. Returns file id."""
    if not db_pool or not pg_row:
        return None
    session_type = str(pg_row.get("session_type") or "").upper()
    if session_type not in ("MASTER_CONSULTATION", "CONSULTATION"):
        return None

    session_id = str(pg_row.get("session_id") or "").strip()
    master_hw = str(pg_row.get("coach_id") or "").strip()
    assistant_hw = str(pg_row.get("client_id") or "").strip()
    if not session_id or not master_hw or not assistant_hw:
        return None

    body = (summary_text or "").strip() or _session_blob(pg_row)
    if not body:
        body = f"Consultation session {session_id} completed. Transcript not yet available."

    try:
        async with db_pool.acquire() as conn:
            ids = await conn.fetchrow(
                """SELECT
                     (SELECT username FROM users WHERE hardware_id = $1 LIMIT 1) AS master_username,
                     (SELECT COALESCE(profile_data->>'name', username) FROM users
                      WHERE hardware_id = $1 LIMIT 1) AS master_name,
                     (SELECT username FROM users WHERE hardware_id = $2 LIMIT 1) AS assistant_username,
                     (SELECT COALESCE(profile_data->>'name', username) FROM users
                      WHERE hardware_id = $2 LIMIT 1) AS assistant_name
                """,
                master_hw,
                assistant_hw,
            )
            if not ids or not ids["assistant_username"]:
                return None
            a_user = ids["assistant_username"]
            a_name = ids["assistant_name"] or a_user
            m_user = ids["master_username"] or ""

            folder_id = await ensure_assistant_folder(conn, master_hw, a_user, a_name)
            if not folder_id:
                return None

            existing = await conn.fetchval(
                """SELECT id::text FROM coach_folder_files
                   WHERE folder_id = $1 AND metadata->>'session_id' = $2
                   LIMIT 1""",
                folder_id,
                session_id,
            )
            if existing:
                return existing

            date_slug = dt.datetime.utcnow().strftime("%Y-%m-%d")
            filename = f"Assistant_Consult_{a_user}_{date_slug}.md"
            md = (
                f"# Assistant Consult\n\n"
                f"- Assistant: {a_name} (@{a_user})\n"
                f"- Master: {ids['master_name'] or m_user}\n"
                f"- Session: {session_id}\n"
                f"- Date: {date_slug}\n\n"
                f"## Transcript / notes\n\n{body}\n"
            )
            from app.services.blob_storage import upload_bytes

            rel = f"coach_uploads/{master_hw}/assistants/{a_user}/{session_id}/{filename}"
            _kind, location = upload_bytes(
                rel_path=rel,
                content=md.encode("utf-8"),
                content_type="text/markdown",
            )
            items = extract_action_items(body)
            file_row = await conn.fetchrow(
                """INSERT INTO coach_folder_files
                   (folder_id, filename, file_type, azure_blob_url, storage_url, uploaded_by, metadata)
                   VALUES ($1, $2, 'consult_transcript', $3, $3, $4, $5::jsonb)
                   RETURNING id""",
                folder_id,
                filename,
                location,
                master_hw,
                json.dumps({
                    "source": "assistant_consult_archive",
                    "session_id": session_id,
                    "assistant_username": a_user,
                    "kind": "consult_transcript",
                }),
            )
            file_id = str(file_row["id"]) if file_row else None
            updated = await conn.fetchval(
                """UPDATE coach_consultations
                   SET session_id = COALESCE(session_id, $1),
                       transcript_text = COALESCE(NULLIF(transcript_text, ''), $2),
                       nate_summary = COALESCE(NULLIF(nate_summary, ''), $2),
                       folder_file_id = COALESCE(folder_file_id, $3::uuid),
                       action_items = $4::jsonb,
                       archived_at = NOW(),
                       status = CASE WHEN status = 'scheduled' THEN 'completed' ELSE status END
                   WHERE (session_id = $1)
                      OR (assistant_username = $5 AND master_username = $6
                          AND scheduled_start::date = CURRENT_DATE)
                   RETURNING id""",
                session_id,
                body[:20000],
                file_id,
                json.dumps(items),
                a_user,
                m_user,
            )
            if not updated:
                await conn.execute(
                    """INSERT INTO coach_consultations
                       (assistant_username, master_username, scheduled_start, scheduled_end,
                        status, is_free, session_id, transcript_text, nate_summary,
                        folder_file_id, action_items, archived_at)
                       VALUES ($1, $2, NOW(), NOW() + interval '15 minutes',
                               'completed', true, $3, $4, $4, $5::uuid, $6::jsonb, NOW())""",
                    a_user,
                    m_user,
                    session_id,
                    body[:20000],
                    file_id,
                    json.dumps(items),
                )
            for item in items:
                await conn.execute(
                    """INSERT INTO assistant_consult_action_items
                       (master_username, assistant_username, consult_session_id, item_text)
                       SELECT $1, $2, $3, $4
                       WHERE NOT EXISTS (
                           SELECT 1 FROM assistant_consult_action_items
                           WHERE master_username = $1 AND assistant_username = $2
                             AND lower(item_text) = lower($4)
                             AND status = 'open'
                       )""",
                    m_user,
                    a_user,
                    session_id,
                    item,
                )
            return file_id
    except Exception as e:
        logger.warning("assistant_consult_archive failed: %s", e)
        return None


async def backfill_completed_consults(db_pool, master_hw: str, limit: int = 20) -> int:
    if not db_pool or not master_hw:
        return 0
    placed = 0
    try:
        async with db_pool.acquire() as conn:
            rows = await conn.fetch(
                """SELECT session_id, client_id, coach_id, client_name, session_type,
                          nate_summary, coach_notes, notes, session_data, status
                   FROM coaching_sessions
                   WHERE coach_id::text = $1
                     AND upper(COALESCE(session_type, '')) IN ('MASTER_CONSULTATION', 'CONSULTATION')
                     AND status = 'completed'
                   ORDER BY COALESCE(actual_end, updated_at, created_at) DESC
                   LIMIT $2""",
                master_hw,
                limit,
            )
        for r in rows:
            fid = await archive_consultation_session(db_pool, dict(r))
            if fid:
                placed += 1
    except Exception as e:
        logger.warning("consult backfill failed: %s", e)
    return placed


async def list_consult_actions(
    conn,
    master_username: str,
    assistant_username: str,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    rows = await conn.fetch(
        """SELECT id::text, item_text, status, requested_at, completed_at, consult_session_id
           FROM assistant_consult_action_items
           WHERE master_username = $1 AND assistant_username = $2
           ORDER BY requested_at DESC
           LIMIT 40""",
        master_username,
        assistant_username,
    )
    open_items, done_items = [], []
    for r in rows:
        rec = {
            "id": r["id"],
            "text": r["item_text"],
            "status": r["status"],
            "requested_at": r["requested_at"].isoformat() if r["requested_at"] else None,
            "completed_at": r["completed_at"].isoformat() if r["completed_at"] else None,
        }
        if r["status"] == "completed":
            done_items.append(rec)
        elif r["status"] == "open":
            open_items.append(rec)
    return open_items, done_items
