"""Google Calendar session sync orchestrator.

Single helper used by both REST (sessions.py) and WebSocket (bridge_server.py)
booking flows + the Zoom webhook. Encapsulates:

  - Per-user token resolution (refresh if needed)
  - Event payload composition (title/desc/attendees/Zoom link)
  - Push: create / update / delete + persist google_event_id, etag, sync_state
  - Dedup guard: skip create if sync_state == 'synced' and google_event_id set
  - Best-effort: never raises to caller; logs to google_calendar_sync_log

All callers should fire-and-forget via:
    asyncio.create_task(sync_session_to_google(db_pool, user_id, session, action="create"))

Pushes happen for BOTH the coach and the client (each independently connected).
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

try:
    from app.services.skyeye_platform_base import TokenCipher
except ImportError:
    from backend.app.services.skyeye_platform_base import TokenCipher

try:
    from app.services import google_calendar_client as gcc
except ImportError:
    from backend.app.services import google_calendar_client as gcc

logger = logging.getLogger("google_calendar_session_sync")

GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID", "")
GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET", "")

_cipher = TokenCipher.get()


async def _resolve_client_email(pool, client_id: str) -> Optional[str]:
    """Look up registered client's email so COACH sessions also invite the client."""
    if not pool or not client_id:
        return None
    try:
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT profile_data->>'email' AS email FROM users "
                "WHERE hardware_id = $1 OR username = $1 LIMIT 1",
                client_id,
            )
        if not row:
            return None
        em = (row["email"] or "").strip()
        return em if em and "@" in em else None
    except Exception:
        return None


async def _get_connection(pool, user_id: str) -> Optional[Dict[str, Any]]:
    if not pool or not user_id:
        return None
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT user_id, access_token, refresh_token, token_expiry, "
            "       target_calendar_id, sync_enabled "
            "FROM google_calendar_connection WHERE user_id = $1",
            user_id,
        )
    if not row or not row["sync_enabled"]:
        return None
    return dict(row)


async def _ensure_token(pool, conn_row: Dict[str, Any]) -> Optional[str]:
    expiry = conn_row.get("token_expiry")
    now = datetime.now(timezone.utc)
    if expiry and (expiry - now).total_seconds() > 300:
        try:
            return _cipher.decrypt(conn_row["access_token"])
        except Exception:
            return None
    if not (GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET):
        return None
    try:
        refresh = _cipher.decrypt(conn_row["refresh_token"])
        tokens = await gcc.refresh_access_token(GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET, refresh)
    except Exception as e:
        logger.warning("token refresh failed for %s: %s", conn_row["user_id"], e)
        return None
    new_access = tokens.get("access_token")
    new_expiry = now + timedelta(seconds=int(tokens.get("expires_in") or 3600))
    enc = _cipher.encrypt(new_access)
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE google_calendar_connection SET access_token = $1, "
            "token_expiry = $2, error_message = NULL, error_count = 0, updated_at = NOW() "
            "WHERE user_id = $3",
            enc, new_expiry, conn_row["user_id"],
        )
    return new_access


def _build_payload(session: Dict[str, Any],
                   extra_attendee_email: Optional[str] = None) -> Optional[Dict[str, Any]]:
    start = session.get("scheduled_start") or session.get("start_time")
    end = session.get("scheduled_end") or session.get("end_time")
    if not start or not end:
        return None
    coach_name = session.get("coach_name") or session.get("coach_id") or "Coach"
    client_name = session.get("client_name") or session.get("client_id") or "Client"
    session_type = (session.get("session_type") or "session").replace("_", " ").title()
    summary = f"Sanctuary: {session_type} — {coach_name} & {client_name}"
    description_parts = [
        f"Session type: {session_type}",
        f"Coach: {coach_name}",
        f"Client: {client_name}",
    ]
    csubj = (session.get("consultation_subject") or "").strip()
    if csubj:
        description_parts.append(f"Topic: {csubj}")
    notes = session.get("notes") or session.get("description")
    if notes:
        description_parts.append(f"\nNotes: {notes}")
    join_url = (
        session.get("zoom_join_url")
        or session.get("join_url")
        or session.get("zoom_link")
    )
    if join_url:
        description_parts.append(f"\nJoin: {join_url}")
    description = "\n".join(description_parts)

    # Compose attendee list: external consultee (if any) + registered client (if any).
    attendee_set = []
    consultation_email = (session.get("consultation_email") or "").strip()
    if consultation_email and "@" in consultation_email:
        attendee_set.append(consultation_email)
    if extra_attendee_email and "@" in extra_attendee_email:
        if extra_attendee_email.lower() not in {a.lower() for a in attendee_set}:
            attendee_set.append(extra_attendee_email)
    attendees = attendee_set or None

    payload = gcc._build_event_payload(
        summary=summary,
        description=description,
        start_iso=start,
        end_iso=end,
        timezone_str=session.get("timezone") or "America/New_York",
        location=join_url or None,
        attendees=attendees,
        conference_link=None,
        source_session_id=session.get("session_id"),
    )
    return payload


def _send_updates_for_payload(payload: Optional[Dict[str, Any]]) -> Optional[str]:
    """Notify attendees when the event includes guest emails (e.g. consultations)."""
    if payload and payload.get("attendees"):
        return "all"
    return None


async def _persist_sync_result(pool, session_id: str, *,
                                google_event_id: Optional[str],
                                google_etag: Optional[str],
                                calendar_id: Optional[str],
                                state: str = "synced") -> None:
    if not pool or not session_id:
        return
    try:
        async with pool.acquire() as conn:
            await conn.execute(
                "UPDATE coaching_sessions SET google_event_id = COALESCE($1, google_event_id), "
                "google_etag = COALESCE($2, google_etag), "
                "google_calendar_id = COALESCE($3, google_calendar_id), "
                "google_last_synced = NOW(), sync_state = $4, "
                "sync_source = COALESCE(sync_source, 'sanctuary') "
                "WHERE session_id = $5",
                google_event_id, google_etag, calendar_id, state, session_id,
            )
    except Exception as e:
        logger.warning("persist sync result failed for %s: %s", session_id, e)


async def _log(pool, user_id: str, direction: str, action: str,
                session_id: Optional[str], google_event_id: Optional[str],
                status: str = "ok", error_message: Optional[str] = None) -> None:
    if not pool:
        return
    try:
        async with pool.acquire() as conn:
            await conn.execute(
                "INSERT INTO google_calendar_sync_log "
                "(user_id, direction, action, session_id, google_event_id, status, error_message) "
                "VALUES ($1, $2, $3, $4, $5, $6, $7)",
                user_id, direction, action, session_id, google_event_id,
                status, error_message,
            )
    except Exception:
        pass


# ── Public API ──────────────────────────────────────────────────────────

async def sync_session_to_google(pool, user_id: str, session: Dict[str, Any],
                                   action: str = "create") -> Optional[Dict[str, Any]]:
    """Push a session to Google Calendar for one user (coach OR client).

    Dedup guard: if action == 'create' and the session is already synced with a
    google_event_id, this returns immediately without calling Google.
    """
    if not pool or not user_id or not session:
        return None
    session_id = session.get("session_id")

    # Dedup guard — applies to creates only.
    if action == "create" and session.get("sync_state") == "synced" and session.get("google_event_id"):
        return {"status": "skipped", "reason": "already_synced"}

    conn_row = await _get_connection(pool, user_id)
    if not conn_row:
        return None  # User not connected — no-op
    access_token = await _ensure_token(pool, conn_row)
    if not access_token:
        await _log(pool, user_id, "push", "error", session_id, None,
                   status="error", error_message="no valid token")
        return None
    calendar_id = conn_row.get("target_calendar_id") or "primary"

    try:
        if action == "delete":
            event_id = session.get("google_event_id")
            if not event_id:
                return {"status": "skipped", "reason": "no event_id"}
            ok = await gcc.delete_event(access_token, calendar_id, event_id)
            await _persist_sync_result(pool, session_id,
                                        google_event_id=event_id,
                                        google_etag=None,
                                        calendar_id=calendar_id,
                                        state="synced" if ok else "error")
            await _log(pool, user_id, "push", "delete", session_id, event_id,
                       status="ok" if ok else "error")
            return {"status": "ok" if ok else "error"}

        # Resolve client email so coach's GCal event also invites the registered client.
        client_email = await _resolve_client_email(
            pool, (session.get("client_id") or "").strip()
        )
        payload = _build_payload(session, extra_attendee_email=client_email)
        if not payload:
            return {"status": "skipped", "reason": "missing time"}

        if action == "update":
            event_id = session.get("google_event_id")
            etag = session.get("google_etag")
            if not event_id:
                action = "create"  # fall through
            else:
                ev = await gcc.update_event(access_token, calendar_id, event_id, payload, etag=etag)
                if ev is None:
                    # etag stale or other failure — re-create
                    ev = await gcc.create_event(
                        access_token, calendar_id, payload,
                        send_updates=_send_updates_for_payload(payload),
                    )
                    a = "create"
                else:
                    a = "update"
                if ev:
                    await _persist_sync_result(pool, session_id,
                                                google_event_id=ev.get("id"),
                                                google_etag=ev.get("etag"),
                                                calendar_id=calendar_id,
                                                state="synced")
                    await _log(pool, user_id, "push", a, session_id, ev.get("id"))
                    return {"status": "ok", "event_id": ev.get("id")}
                await _log(pool, user_id, "push", "error", session_id, event_id,
                           status="error", error_message="update+recreate failed")
                return {"status": "error"}

        # action == "create"
        ev = await gcc.create_event(
            access_token, calendar_id, payload,
            send_updates=_send_updates_for_payload(payload),
        )
        if not ev:
            await _persist_sync_result(pool, session_id,
                                        google_event_id=None,
                                        google_etag=None,
                                        calendar_id=calendar_id,
                                        state="error")
            await _log(pool, user_id, "push", "error", session_id, None,
                       status="error", error_message="create failed")
            return {"status": "error"}
        await _persist_sync_result(pool, session_id,
                                    google_event_id=ev.get("id"),
                                    google_etag=ev.get("etag"),
                                    calendar_id=calendar_id,
                                    state="synced")
        await _log(pool, user_id, "push", "create", session_id, ev.get("id"))
        return {"status": "ok", "event_id": ev.get("id")}
    except Exception as e:
        logger.warning("sync_session_to_google failed for %s/%s: %s", user_id, session_id, e)
        await _log(pool, user_id, "push", "error", session_id, None,
                   status="error", error_message=str(e)[:500])
        return {"status": "error", "error": str(e)}


async def sync_session_for_participants(pool, session: Dict[str, Any],
                                         action: str = "create") -> None:
    """Convenience: push a session to BOTH the coach's and the client's Google Calendars."""
    coach_id = (session.get("coach_id") or session.get("assigned_coach_id") or "").strip()
    client_id = (session.get("client_id") or session.get("hardware_id") or "").strip()
    for uid in (coach_id, client_id):
        if uid:
            try:
                await sync_session_to_google(pool, uid, session, action=action)
            except Exception:
                pass


__all__ = ["sync_session_to_google", "sync_session_for_participants"]
