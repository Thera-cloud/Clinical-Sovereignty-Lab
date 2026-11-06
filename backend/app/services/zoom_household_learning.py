"""Live-session learning for the booked client and Sovereign Circle household.

Spouses and dependents on the same family plan receive the session summary,
transcript crystals, and chat context. Other families stay isolated.
Payment columns are never written here.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

HOUSEHOLD_TIERS = frozenset({
    "TOP_TIER",
    "SOVEREIGN_CIRCLE",
    "SOVEREIGN",
    "SOVEREIGN_CIRCLE_ANNUAL",
})
_COLLECTED = frozenset({
    "paid", "waived", "complimentary", "refunded", "no_charge", "comp",
})
_FROZEN_STATUS = frozenset({
    "cancelled", "canceled", "rescheduled", "no_show", "completed",
})


def canonical_zoom_meeting_id(payload: Optional[Dict[str, Any]]) -> str:
    """Numeric Zoom meeting id. Summary events carry it on meeting_id, not id."""
    obj = ((payload or {}).get("payload") or {}).get("object") or {}
    if not isinstance(obj, dict):
        return ""
    for key in ("id", "meeting_id"):
        raw = str(obj.get(key) or "").strip()
        if raw.isdigit():
            return raw
    return ""


def summary_text_from_webhook(payload: Optional[Dict[str, Any]]) -> str:
    obj = ((payload or {}).get("payload") or {}).get("object") or {}
    if not isinstance(obj, dict):
        return ""
    from app.services.zoom_session_folder import _summary_text_from_api_payload

    return _summary_text_from_api_payload(obj)


def status_after_start(current: str) -> str:
    cur = (current or "").strip().lower()
    if cur in ("scheduled", "confirmed", ""):
        return "active"
    return (current or "active").strip() or "active"


def status_after_end(current: str, payment_status: str) -> str:
    """Complete only after money is settled. Pending stays chargeable (active)."""
    cur = (current or "").strip().lower()
    if cur in _FROZEN_STATUS:
        return cur or "completed"
    pay = (payment_status or "").strip().lower()
    if pay in _COLLECTED:
        return "completed"
    return "active"


def _add(ids: List[str], value: Any) -> None:
    text = str(value or "").strip()
    if text and text not in ids:
        ids.append(text)


async def learning_subject_ids(db_pool, viewer_id: str) -> List[str]:
    """Viewer plus Sovereign Circle household client ids (hardware id and username)."""
    ids: List[str] = []
    _add(ids, viewer_id)
    if not db_pool or not (viewer_id or "").strip():
        return ids
    try:
        async with db_pool.acquire() as conn:
            me = await conn.fetchrow(
                """
                SELECT hardware_id, username,
                       COALESCE(profile_data->>'family_id', '') AS fam,
                       UPPER(COALESCE(
                           NULLIF(profile_data->>'tier', ''),
                           NULLIF(tier::text, ''),
                           ''
                       )) AS tier
                FROM users
                WHERE hardware_id = $1 OR LOWER(username) = LOWER($1)
                LIMIT 1
                """,
                viewer_id,
            )
            if not me:
                return ids
            _add(ids, me["hardware_id"])
            _add(ids, me["username"])
            fam = (me["fam"] or "").strip()
            if not fam:
                return ids
            rows = await conn.fetch(
                """
                SELECT hardware_id, username, role,
                       UPPER(COALESCE(
                           NULLIF(profile_data->>'tier', ''),
                           NULLIF(tier::text, ''),
                           ''
                       )) AS tier
                FROM users
                WHERE role = 'CLIENT'
                  AND COALESCE(profile_data->>'family_id', '') = $1
                """,
                fam,
            )
        tiers = {(me["tier"] or "").upper()}
        for row in rows:
            tiers.add((row["tier"] or "").upper())
        if not tiers.intersection(HOUSEHOLD_TIERS):
            return ids
        for row in rows:
            _add(ids, row["hardware_id"])
            _add(ids, row["username"])
    except Exception as exc:
        logger.warning("learning_subject_ids failed: %s", exc)
    return ids


async def household_crystal_targets(db_pool, client_id: str) -> List[Dict[str, str]]:
    """Booked client always. Sovereign Circle family CLIENT rows are added."""
    targets: List[Dict[str, str]] = []
    seen = set()

    def push(hw: str, name: str, primary: bool) -> None:
        hw = (hw or "").strip()
        if not hw or hw in seen:
            return
        seen.add(hw)
        targets.append({
            "hardware_id": hw,
            "name": (name or "").strip() or hw,
            "primary": "1" if primary else "0",
        })

    if not db_pool or not (client_id or "").strip():
        push(client_id, "", True)
        return targets
    try:
        async with db_pool.acquire() as conn:
            me = await conn.fetchrow(
                """
                SELECT hardware_id, username,
                       COALESCE(NULLIF(profile_data->>'name', ''), username, '') AS name,
                       COALESCE(profile_data->>'family_id', '') AS fam,
                       UPPER(COALESCE(
                           NULLIF(profile_data->>'tier', ''),
                           NULLIF(tier::text, ''),
                           ''
                       )) AS tier
                FROM users
                WHERE hardware_id = $1 OR LOWER(username) = LOWER($1)
                LIMIT 1
                """,
                client_id,
            )
            if not me:
                push(client_id, "", True)
                return targets
            primary_hw = (me["hardware_id"] or client_id).strip()
            push(primary_hw, me["name"], True)
            fam = (me["fam"] or "").strip()
            if not fam:
                return targets
            rows = await conn.fetch(
                """
                SELECT hardware_id,
                       COALESCE(NULLIF(profile_data->>'name', ''), username, '') AS name,
                       UPPER(COALESCE(
                           NULLIF(profile_data->>'tier', ''),
                           NULLIF(tier::text, ''),
                           ''
                       )) AS tier
                FROM users
                WHERE role = 'CLIENT'
                  AND COALESCE(profile_data->>'family_id', '') = $1
                """,
                fam,
            )
        tiers = {(me["tier"] or "").upper()}
        for row in rows:
            tiers.add((row["tier"] or "").upper())
        if not tiers.intersection(HOUSEHOLD_TIERS):
            return targets
        for row in rows:
            push(row["hardware_id"], row["name"], row["hardware_id"] == primary_hw)
    except Exception as exc:
        logger.warning("household_crystal_targets failed: %s", exc)
        if not targets:
            push(client_id, "", True)
    return targets


async def share_live_session_learning(
    db_pool,
    client_id: str,
    client_name: str,
    user_text: str,
    nate_line: str,
    *,
    origin_surface: str,
    session_id: str = "",
    min_score: int = 0,
    include_primary: bool = True,
) -> int:
    """Forge one user-scoped crystal per household learner. Never global."""
    text = (user_text or "").strip()
    if not db_pool or not text:
        return 0
    targets = await household_crystal_targets(db_pool, client_id)
    if not targets:
        return 0
    primary_name = client_name or next(
        (t["name"] for t in targets if t["primary"] == "1"), ""
    )
    written = 0
    try:
        from app.websocket.crystal_recall_bridge import crystallize_from_conversation
    except Exception as exc:
        logger.warning("share_live_session_learning import: %s", exc)
        return 0
    for target in targets:
        if target["primary"] == "1" and not include_primary:
            continue
        body = text
        if target["primary"] != "1":
            body = (
                f"Household live session (Sovereign Circle) with {primary_name}. "
                f"Walk with them from the live session they had with their coach.\n{text}"
            )
        try:
            await crystallize_from_conversation(
                db_pool,
                target["hardware_id"],
                body[:4000],
                nate_line,
                user_name=target["name"],
                domain="clinical",
                min_score=min_score,
                origin_surface=origin_surface,
            )
            written += 1
        except Exception as exc:
            logger.warning(
                "household crystal failed session=%s member=%s: %s",
                session_id, target["hardware_id"], exc,
            )
    if session_id and len(targets) > 1:
        try:
            async with db_pool.acquire() as conn:
                await conn.execute(
                    """
                    UPDATE coaching_sessions
                    SET session_data = COALESCE(session_data, '{}'::jsonb)
                        || jsonb_build_object(
                            'household_learning', 'true',
                            'household_member_ids', $2::jsonb
                        ),
                        updated_at = NOW()
                    WHERE session_id = $1
                    """,
                    session_id,
                    json.dumps([t["hardware_id"] for t in targets]),
                )
        except Exception as exc:
            logger.warning("household_learning flag failed for %s: %s", session_id, exc)
    return written


async def stamp_family_from_client(db_pool, meeting_id: str) -> int:
    """Fill empty coaching_sessions.family_id from the booked client's profile."""
    if not db_pool or not meeting_id:
        return 0
    try:
        async with db_pool.acquire() as conn:
            result = await conn.execute(
                """
                UPDATE coaching_sessions cs
                SET family_id = u.profile_data->>'family_id',
                    updated_at = NOW()
                FROM users u
                WHERE cs.zoom_meeting_id = $1
                  AND COALESCE(cs.family_id, '') = ''
                  AND (u.hardware_id = cs.client_id OR LOWER(u.username) = LOWER(cs.client_id))
                  AND COALESCE(u.profile_data->>'family_id', '') <> ''
                """,
                meeting_id,
            )
        try:
            return int(str(result).split()[-1])
        except Exception:
            return 0
    except Exception as exc:
        logger.warning("stamp_family_from_client failed: %s", exc)
        return 0


async def apply_meeting_started(db_pool, meeting_id: str, start_iso: str = "") -> int:
    if not db_pool or not meeting_id:
        return 0
    await stamp_family_from_client(db_pool, meeting_id)
    n = 0
    try:
        async with db_pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT session_id, status
                FROM coaching_sessions
                WHERE zoom_meeting_id = $1
                """,
                meeting_id,
            )
            for row in rows:
                cur = (row["status"] or "").strip().lower()
                if cur in _FROZEN_STATUS:
                    continue
                await conn.execute(
                    """
                    UPDATE coaching_sessions
                    SET actual_start = COALESCE(actual_start, COALESCE($2::timestamptz, NOW())),
                        status = $3,
                        updated_at = NOW()
                    WHERE session_id = $1
                    """,
                    row["session_id"],
                    start_iso or None,
                    status_after_start(row["status"] or ""),
                )
                n += 1
    except Exception as exc:
        logger.warning("apply_meeting_started failed: %s", exc)
    return n


async def apply_meeting_ended(
    db_pool,
    meeting_id: str,
    end_iso: str = "",
    duration_minutes: int = 0,
) -> int:
    if not db_pool or not meeting_id:
        return 0
    await stamp_family_from_client(db_pool, meeting_id)
    n = 0
    try:
        async with db_pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT session_id, status, payment_status, duration_minutes
                FROM coaching_sessions
                WHERE zoom_meeting_id = $1
                """,
                meeting_id,
            )
            for row in rows:
                cur = (row["status"] or "").strip().lower()
                if cur in ("cancelled", "canceled", "rescheduled"):
                    continue
                new_status = status_after_end(row["status"] or "", row["payment_status"] or "")
                dur = int(duration_minutes or 0)
                if dur <= 0:
                    dur = int(row["duration_minutes"] or 0)
                await conn.execute(
                    """
                    UPDATE coaching_sessions
                    SET actual_end = COALESCE(actual_end, COALESCE($2::timestamptz, NOW())),
                        duration_minutes = CASE
                            WHEN COALESCE(duration_minutes, 0) = 0 AND $4::int > 0 THEN $4::int
                            ELSE duration_minutes
                        END,
                        status = $3,
                        updated_at = NOW()
                    WHERE session_id = $1
                    """,
                    row["session_id"],
                    end_iso or None,
                    new_status,
                    dur,
                )
                n += 1
    except Exception as exc:
        logger.warning("apply_meeting_ended failed: %s", exc)
    return n


async def mark_cloud_recording(
    db_pool,
    meeting_id: str,
    *,
    started: bool,
    at_iso: str = "",
) -> int:
    """Record that a cloud video exists. Stopped sessions wait for the transcript."""
    if not db_pool or not meeting_id:
        return 0
    patch = {
        "recording_cloud": "true",
        "recording_started_at" if started else "recording_stopped_at": at_iso or "",
    }
    if not started:
        patch["transcript_pending"] = "true"
        patch["transcript_enqueue_reason"] = "recording_stopped"
    try:
        async with db_pool.acquire() as conn:
            result = await conn.execute(
                """
                UPDATE coaching_sessions
                SET session_data = COALESCE(session_data, '{}'::jsonb) || $2::jsonb,
                    updated_at = NOW()
                WHERE zoom_meeting_id = $1
                """,
                meeting_id,
                json.dumps(patch),
            )
        try:
            return int(str(result).split()[-1])
        except Exception:
            return 0
    except Exception as exc:
        logger.warning("mark_cloud_recording failed: %s", exc)
        return 0


async def live_session_awareness_context(db_pool, viewer_id: str, limit: int = 2) -> str:
    """Summary + video flag for LN chat. Most recent live session is first."""
    if not db_pool or not viewer_id:
        return ""
    ids = await learning_subject_ids(db_pool, viewer_id)
    if not ids:
        return ""
    try:
        async with db_pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT session_id, client_id, client_name,
                       scheduled_start, actual_start, actual_end, session_data
                FROM coaching_sessions
                WHERE client_id = ANY($1::text[])
                  AND (
                    COALESCE(session_data->>'zoom_ai_summary_text', '') <> ''
                    OR COALESCE(session_data->>'recording_cloud', '') IN ('true', '1')
                    OR COALESCE(session_data->>'transcript_location', '') <> ''
                  )
                ORDER BY COALESCE(actual_end, actual_start, scheduled_start) DESC NULLS LAST
                LIMIT $2
                """,
                ids,
                limit,
            )
    except Exception as exc:
        logger.warning("live_session_awareness_context failed: %s", exc)
        return ""
    if not rows:
        return ""
    from app.services.zoom_transcript_context import resolve_live_session_display

    parts = [
        "[LATEST LIVE SESSIONS — most recent first]",
        "The first block is the current live session. Earlier blocks are older sessions. "
        "Do not treat an older session as the one that just happened.",
        "Cloud video is the Zoom recording. Use the summary and transcript, not a guess.",
    ]
    viewer = (viewer_id or "").strip()
    for row in rows:
        sd = row["session_data"]
        if isinstance(sd, str):
            try:
                sd = json.loads(sd)
            except Exception:
                sd = {}
        if not isinstance(sd, dict):
            sd = {}
        dates = resolve_live_session_display(
            actual_start=row["actual_start"],
            actual_end=row["actual_end"],
            scheduled_start=row["scheduled_start"],
            session_data=sd,
            session_id=row["session_id"],
        )
        label = dates.get("display_label") or "recent"
        billed = (row["client_id"] or "").strip()
        who = (row["client_name"] or "the client").strip()
        head = label
        if billed and billed != viewer and viewer not in (billed,):
            head = f"{label} — household live session with {who}"
        summary = (sd.get("zoom_ai_summary_text") or "").strip()
        video = (sd.get("recording_cloud") or "") in ("true", "1", True)
        lines = [head]
        if video:
            lines.append("Cloud video recording is on file for this session.")
        if summary:
            lines.append(summary[:1500])
        elif (sd.get("transcript_location") or "").strip():
            lines.append("Transcript is archived for this session.")
        parts.append("\n".join(lines))
    parts.append(
        "Walk with the client and their coach from this record. "
        "Household members on Sovereign Circle share this live session only, not other clients."
    )
    return "\n\n".join(parts)
