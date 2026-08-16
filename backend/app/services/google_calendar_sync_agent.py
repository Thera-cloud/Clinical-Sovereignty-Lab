"""Google Calendar Sync Agent — pulls Google events every 5 minutes for all
connected users (coaches and clients). Pushes happen inline at booking time.

Cycle (every POLL_INTERVAL_SECONDS):
  1. Query google_calendar_connection WHERE sync_enabled = true,
     then google_workspace_connection (revoked_at IS NULL) for users
     not already covered by an enabled 183 row.
  2. For each user, refresh access token if needed (183 vs GOOGLE_WS_*).
  3. Incremental list events using stored sync_token (or bounded full sync).
  4. Reconcile with coaching_sessions:
       - Mirror Sanctuary events (extendedProperties.private.sanctuary_session_id)
         if user edited time → update coaching_sessions.
       - If event was cancelled in Google → set status='cancelled_by_google'.
       - Update coach_busy_cache for non-Sanctuary events (so availability
         queries can subtract them).
  5. Persist next_sync_token + last_sync_at.

This agent NEVER creates Google events — that's the schedule flow's job.
This agent ONLY pulls (Google → Sanctuary) and updates the busy cache.
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

try:
    from app.services.skyeye_platform_base import TokenCipher
except ImportError:
    from backend.app.services.skyeye_platform_base import TokenCipher

try:
    from app.services import google_calendar_client as gcc
except ImportError:
    from backend.app.services import google_calendar_client as gcc

logger = logging.getLogger("google_calendar_sync_agent")

POLL_INTERVAL_SECONDS = 5 * 60  # 5 minutes
STARTUP_DELAY_SECONDS = 120  # let other services come up first
PER_USER_TIMEOUT_SECONDS = 30  # bound each user's pull
MAX_ERROR_COUNT = 10  # auto-disable sync after this many consecutive errors

import os

GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID", "")
GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET", "")
GOOGLE_WS_CLIENT_ID = os.getenv("GOOGLE_WS_CLIENT_ID", "")
GOOGLE_WS_CLIENT_SECRET = os.getenv("GOOGLE_WS_CLIENT_SECRET", "")

_ALLOWED_TOKEN_TABLES = frozenset({
    "google_calendar_connection",
    "google_workspace_connection",
})

_cipher = TokenCipher.get()


def merge_pull_sources(
    calendar_rows: List[Dict[str, Any]],
    workspace_rows: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """183 first; Workspace-only coaches fill gaps. Never mix refresh tokens."""
    seen = set()
    out: List[Dict[str, Any]] = []
    for r in calendar_rows:
        d = dict(r)
        uid = d.get("user_id")
        if not uid:
            continue
        d["_token_table"] = "google_calendar_connection"
        d["token_app"] = d.get("token_app") or "calendar_183"
        seen.add(uid)
        out.append(d)
    for r in workspace_rows:
        d = dict(r)
        uid = d.get("user_id")
        if not uid or uid in seen:
            continue
        d["_token_table"] = "google_workspace_connection"
        d["token_app"] = d.get("token_app") or "workspace_ws"
        if not d.get("target_calendar_id"):
            d["target_calendar_id"] = "primary"
        out.append(d)
    return out


def _oauth_creds_for(row: Dict[str, Any]) -> tuple:
    if (row.get("token_app") or "") == "workspace_ws":
        return GOOGLE_WS_CLIENT_ID, GOOGLE_WS_CLIENT_SECRET
    return GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET


def _token_table(row: Dict[str, Any]) -> str:
    table = row.get("_token_table") or (
        "google_workspace_connection"
        if (row.get("token_app") or "") == "workspace_ws"
        else "google_calendar_connection"
    )
    return table if table in _ALLOWED_TOKEN_TABLES else "google_calendar_connection"


class GoogleCalendarSyncAgent:
    """Background agent that pulls Google Calendar events for all connected users."""

    def __init__(self, db_pool=None, app_state=None):
        self._pool = db_pool
        self._app_state = app_state
        self._running = False
        self._task: Optional[asyncio.Task] = None
        # In-memory cache of busy windows per user (used by availability queries).
        # Schema: { user_id: [ {"start": iso, "end": iso}, ... ] }
        self.coach_busy_cache: Dict[str, List[Dict[str, str]]] = {}

    async def start(self):
        if not self._pool:
            logger.warning("GoogleCalendarSyncAgent: no db_pool, skipping start")
            return
        has_183 = bool(GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET)
        has_ws = bool(GOOGLE_WS_CLIENT_ID and GOOGLE_WS_CLIENT_SECRET)
        if not (has_183 or has_ws):
            logger.warning(
                "GoogleCalendarSyncAgent: no GOOGLE_* or GOOGLE_WS_* credentials — agent inactive"
            )
            return
        self._running = True
        self._task = asyncio.create_task(self._run_loop())
        logger.info("GoogleCalendarSyncAgent: started (5min cycle)")

    async def stop(self):
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("GoogleCalendarSyncAgent: stopped")

    # ── Main loop ───────────────────────────────────────────────────────
    async def _run_loop(self):
        await asyncio.sleep(STARTUP_DELAY_SECONDS)
        while self._running:
            try:
                await self._run_one_cycle()
            except Exception as e:
                logger.error("GoogleCalendarSyncAgent: cycle error: %s", e)
            await asyncio.sleep(POLL_INTERVAL_SECONDS)

    async def _run_one_cycle(self):
        users = await self._list_active_users()
        if not users:
            return
        pulled = 0
        errors = 0
        for u in users:
            try:
                await asyncio.wait_for(
                    self._pull_user_row(u),
                    timeout=PER_USER_TIMEOUT_SECONDS,
                )
                pulled += 1
            except asyncio.TimeoutError:
                errors += 1
                logger.warning("GoogleCalendarSyncAgent: timeout for %s", u.get("user_id"))
            except Exception as e:
                errors += 1
                logger.warning("GoogleCalendarSyncAgent: pull failed for %s: %s",
                               u.get("user_id"), e)
        logger.info("GoogleCalendarSyncAgent: cycle complete — %d pulled, %d errors", pulled, errors)

    # ── Public single-user trigger (used by sync-now endpoint) ─────────
    async def pull_user(self, user_id: str) -> Dict[str, Any]:
        if not self._pool:
            return {"status": "error", "error": "no db_pool"}
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT user_id, user_role, access_token, refresh_token, token_expiry, "
                "       target_calendar_id, sync_token, error_count, "
                "       COALESCE(token_app, 'calendar_183') AS token_app "
                "FROM google_calendar_connection "
                "WHERE user_id = $1 AND sync_enabled = true",
                user_id,
            )
            if row:
                d = dict(row)
                d["_token_table"] = "google_calendar_connection"
                return await self._pull_user_row(d)
            ws = await conn.fetchrow(
                """
                SELECT user_id, user_role, access_token, refresh_token, token_expiry,
                       COALESCE(target_calendar_id, 'primary') AS target_calendar_id,
                       sync_token, error_count,
                       COALESCE(token_app, 'workspace_ws') AS token_app
                FROM google_workspace_connection
                WHERE (user_id = $1 OR hardware_id = $1)
                  AND revoked_at IS NULL
                LIMIT 1
                """,
                user_id,
            )
        if not ws:
            return {"status": "skipped", "reason": "not connected or sync disabled"}
        d = dict(ws)
        d["_token_table"] = "google_workspace_connection"
        return await self._pull_user_row(d)

    # ── Internals ───────────────────────────────────────────────────────
    async def _list_active_users(self) -> List[Dict[str, Any]]:
        async with self._pool.acquire() as conn:
            cal = await conn.fetch(
                "SELECT user_id, user_role, access_token, refresh_token, token_expiry, "
                "       target_calendar_id, sync_token, error_count, "
                "       COALESCE(token_app, 'calendar_183') AS token_app "
                "FROM google_calendar_connection "
                "WHERE sync_enabled = true AND error_count < $1",
                MAX_ERROR_COUNT,
            )
            try:
                ws = await conn.fetch(
                    """
                    SELECT user_id, user_role, access_token, refresh_token, token_expiry,
                           COALESCE(target_calendar_id, 'primary') AS target_calendar_id,
                           sync_token, error_count,
                           COALESCE(token_app, 'workspace_ws') AS token_app
                    FROM google_workspace_connection
                    WHERE revoked_at IS NULL AND error_count < $1
                    """,
                    MAX_ERROR_COUNT,
                )
            except Exception as e:
                logger.warning("GoogleCalendarSyncAgent: workspace list skipped: %s", e)
                ws = []
        return merge_pull_sources([dict(r) for r in cal], [dict(r) for r in ws])

    async def _ensure_valid_token(self, row: Dict[str, Any]) -> Optional[str]:
        expiry = row.get("token_expiry")
        now = datetime.now(timezone.utc)
        if expiry and (expiry - now).total_seconds() > 300:
            try:
                return _cipher.decrypt(row["access_token"])
            except Exception:
                return None
        cid, csec = _oauth_creds_for(row)
        if not (cid and csec):
            await self._record_error(row["user_id"], "oauth client missing for token_app", row)
            return None
        try:
            refresh = _cipher.decrypt(row["refresh_token"])
            tokens = await gcc.refresh_access_token(cid, csec, refresh)
        except Exception as e:
            await self._record_error(row["user_id"], f"refresh failed: {e}", row)
            return None
        new_access = tokens.get("access_token")
        new_expiry = now + timedelta(seconds=int(tokens.get("expires_in") or 3600))
        enc = _cipher.encrypt(new_access)
        table = _token_table(row)
        async with self._pool.acquire() as conn:
            await conn.execute(
                f"UPDATE {table} SET access_token = $1, "
                "token_expiry = $2, error_message = NULL, error_count = 0, updated_at = NOW() "
                "WHERE user_id = $3",
                enc, new_expiry, row["user_id"],
            )
        return new_access

    async def _pull_user_row(self, row: Dict[str, Any]) -> Dict[str, Any]:
        user_id = row["user_id"]
        calendar_id = row.get("target_calendar_id") or "primary"
        access_token = await self._ensure_valid_token(row)
        if not access_token:
            return {"status": "error", "error": "could not refresh token"}

        sync_token = row.get("sync_token")
        events, next_token = await gcc.list_events_incremental(
            access_token, calendar_id, sync_token=sync_token,
        )
        table = _token_table(row)
        if next_token is None and sync_token is not None:
            # 410 — sync token invalidated; try a bounded full resync next cycle
            async with self._pool.acquire() as conn:
                await conn.execute(
                    f"UPDATE {table} SET sync_token = NULL, "
                    "updated_at = NOW() WHERE user_id = $1",
                    user_id,
                )
            return {"status": "resync_needed", "events": 0}

        applied = 0
        external_busy: List[Dict[str, str]] = []
        external_rows: List[Dict[str, Any]] = []
        for ev in events:
            if await self._apply_event(user_id, ev, calendar_id):
                applied += 1
            # Track busy windows (skip cancelled and all-day)
            if ev.get("status") == "cancelled":
                continue
            start = (ev.get("start") or {}).get("dateTime")
            end = (ev.get("end") or {}).get("dateTime")
            if start and end and not self._is_sanctuary_event(ev):
                external_busy.append({"start": start, "end": end})
                external_rows.append({
                    "event_id": ev.get("id") or "",
                    "summary": ev.get("summary") or "",
                    "start": start,
                    "end": end,
                })

        # Update in-process busy cache (only useful within the backend process)
        self.coach_busy_cache[user_id] = external_busy
        # Persist to PG so the bridge (separate container) can also subtract these.
        await self._persist_external_busy(user_id, calendar_id, external_rows)

        async with self._pool.acquire() as conn:
            await conn.execute(
                f"UPDATE {table} SET sync_token = $1, "
                "last_sync_at = NOW(), error_message = NULL, error_count = 0, "
                "updated_at = NOW() WHERE user_id = $2",
                next_token, user_id,
            )
        await self._log(user_id, "pull", "noop" if applied == 0 else "update",
                        session_id=None, google_event_id=None,
                        status=f"events={len(events)} applied={applied}")
        return {"status": "ok", "events": len(events), "applied": applied}

    @staticmethod
    def _is_sanctuary_event(ev: Dict[str, Any]) -> bool:
        ext = (ev.get("extendedProperties") or {}).get("private") or {}
        return bool(ext.get("sanctuary_session_id"))

    async def _apply_event(self, user_id: str, ev: Dict[str, Any], calendar_id: str) -> bool:
        """Apply one Google event to coaching_sessions if it's a Sanctuary-mirrored event."""
        ext = (ev.get("extendedProperties") or {}).get("private") or {}
        session_id = ext.get("sanctuary_session_id")
        google_event_id = ev.get("id")
        if not session_id:
            return False  # external event — busy-cache only, no DB write
        try:
            async with self._pool.acquire() as conn:
                row = await conn.fetchrow(
                    "SELECT session_id, status, google_etag FROM coaching_sessions "
                    "WHERE session_id = $1",
                    session_id,
                )
                if not row:
                    return False
                etag = ev.get("etag")
                if etag and row["google_etag"] == etag:
                    return False  # unchanged
                if ev.get("status") == "cancelled":
                    await conn.execute(
                        "UPDATE coaching_sessions SET status = 'cancelled_by_google', "
                        "google_etag = $1, google_last_synced = NOW(), "
                        "sync_state = 'synced' WHERE session_id = $2",
                        etag, session_id,
                    )
                else:
                    start_iso = (ev.get("start") or {}).get("dateTime")
                    end_iso = (ev.get("end") or {}).get("dateTime")
                    if not start_iso or not end_iso:
                        return False
                    await conn.execute(
                        "UPDATE coaching_sessions SET scheduled_start = $1, "
                        "scheduled_end = $2, google_etag = $3, "
                        "google_last_synced = NOW(), sync_state = 'synced' "
                        "WHERE session_id = $4",
                        start_iso, end_iso, etag, session_id,
                    )
            return True
        except Exception as e:
            logger.warning("apply_event failed for session %s: %s", session_id, e)
            return False

    async def _persist_external_busy(self, user_id: str, calendar_id: str,
                                       rows: List[Dict[str, Any]]):
        """Replace this user's external busy windows in PG.

        Strategy: delete this user's existing rows, insert the fresh set. The
        cache is small per user (only forward-looking events), so a full
        replace is simpler than diffing. If a sync_token-based incremental
        pull returned no events, we still call this with an empty list — that
        means no changes since last token, NOT 'no events at all'. Skip the
        delete in that case to avoid wiping known-good state.
        """
        if not rows:
            return
        try:
            async with self._pool.acquire() as conn:
                async with conn.transaction():
                    for r in rows:
                        try:
                            start_dt = datetime.fromisoformat(r["start"].replace("Z", "+00:00"))
                            end_dt = datetime.fromisoformat(r["end"].replace("Z", "+00:00"))
                        except Exception:
                            continue
                        await conn.execute(
                            "INSERT INTO google_external_busy "
                            "(user_id, google_event_id, calendar_id, summary, start_at, end_at, updated_at) "
                            "VALUES ($1, $2, $3, $4, $5, $6, NOW()) "
                            "ON CONFLICT (user_id, google_event_id) DO UPDATE SET "
                            "calendar_id = EXCLUDED.calendar_id, summary = EXCLUDED.summary, "
                            "start_at = EXCLUDED.start_at, end_at = EXCLUDED.end_at, "
                            "updated_at = NOW()",
                            user_id, r["event_id"], calendar_id, r["summary"][:200],
                            start_dt, end_dt,
                        )
                    # Drop stale rows (not in the current pull AND in the past or far-future window)
                    event_ids = [r["event_id"] for r in rows if r.get("event_id")]
                    if event_ids:
                        await conn.execute(
                            "DELETE FROM google_external_busy "
                            "WHERE user_id = $1 AND end_at >= NOW() AND google_event_id != ALL($2::text[])",
                            user_id, event_ids,
                        )
        except Exception as e:
            logger.warning("persist_external_busy failed for %s: %s", user_id, e)

    async def _record_error(self, user_id: str, message: str, row: Optional[Dict[str, Any]] = None):
        table = _token_table(row or {})
        try:
            async with self._pool.acquire() as conn:
                await conn.execute(
                    f"UPDATE {table} SET error_message = $1, "
                    "error_count = error_count + 1, updated_at = NOW() "
                    "WHERE user_id = $2",
                    message[:500], user_id,
                )
        except Exception:
            pass

    async def _log(self, user_id: str, direction: str, action: str,
                    session_id: Optional[str] = None,
                    google_event_id: Optional[str] = None,
                    status: str = "ok",
                    error_message: Optional[str] = None):
        try:
            async with self._pool.acquire() as conn:
                await conn.execute(
                    "INSERT INTO google_calendar_sync_log "
                    "(user_id, direction, action, session_id, google_event_id, status, error_message) "
                    "VALUES ($1, $2, $3, $4, $5, $6, $7)",
                    user_id, direction, action, session_id, google_event_id,
                    status, error_message,
                )
        except Exception:
            pass


__all__ = ["GoogleCalendarSyncAgent", "merge_pull_sources"]
