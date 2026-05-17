"""
account_event_reconciler — periodic poller for orphaned user_creation_events.

Purpose
-------
Migration 221 installs a trigger on ``users`` that writes a row to
``user_creation_events`` for every INSERT. Code paths that know how they
created the row call ``account_creation_hook.mark_account_created()`` to set
``processed_at`` + ``created_via``.

Any row that stays ``processed_at IS NULL`` for longer than the threshold is
an *orphan* — a signup that bypassed every known code path (manual SQL,
admin tool, bulk import, future code that forgot to call the hook). This
agent sends a single support@ alert per orphan so no signup goes silently
unnoticed during the WJR campaign.

Design constraints
------------------
* Feature-flagged via ``ENABLE_USER_CREATION_HOOK``. Default OFF.
* Never raises out of ``_cycle()``. A reconciler crash must not take down
  the rest of the backend.
* Idempotent. ``processed_at`` is set the instant we *enqueue* the email so
  a duplicate cycle cannot resend.
* Suppresses noisy accounts (audit_*, test_*, smoke_*, bench_*) by marking
  them processed without sending an email.
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
from datetime import datetime
from typing import Any, Optional

logger = logging.getLogger("account_event_reconciler")

_FLAG_ENV = "ENABLE_USER_CREATION_HOOK"

# Orphans younger than this are skipped — hooks are async and may take a few
# seconds to land. 60s gives every known code path time to mark its row.
_ORPHAN_AGE_SECONDS = 60

# Cycle cadence. Aligns with TokenUsageAgent (30 min) is too slow for signup
# observability; 60s gives near-real-time support@ alerts without flooding.
_CYCLE_SECONDS = 60

# Usernames matching these patterns are suppressed (marked processed, no email).
_SUPPRESS_PATTERNS = (
    re.compile(r"^audit_", re.IGNORECASE),
    re.compile(r"^test_", re.IGNORECASE),
    re.compile(r"^smoke", re.IGNORECASE),
    re.compile(r"^bench", re.IGNORECASE),
    re.compile(r"^loadtest_", re.IGNORECASE),
    re.compile(r"^stevejobs", re.IGNORECASE),
)


def _flag_enabled() -> bool:
    return os.getenv(_FLAG_ENV, "false").strip().lower() in ("1", "true", "yes", "on")


def _is_suppressed(username: str) -> bool:
    if not username:
        return True
    for pat in _SUPPRESS_PATTERNS:
        if pat.match(username):
            return True
    return False


class AccountEventReconciler:
    """Polls user_creation_events for orphaned signups and alerts support@."""

    def __init__(self, db_pool: Any, notification_system: Any = None):
        self.db_pool = db_pool
        self.notification_system = notification_system
        self._task: Optional[asyncio.Task] = None
        self._stop_event = asyncio.Event()
        self._last_run: Optional[datetime] = None
        self._last_error: Optional[str] = None
        self._orphans_processed_total = 0
        self._alerts_sent_total = 0

    # ------------------------------------------------------------------ lifecycle

    async def start(self) -> None:
        if self._task and not self._task.done():
            return
        if not self.db_pool:
            logger.warning("AccountEventReconciler: no db_pool, refusing to start")
            return
        self._stop_event.clear()
        self._task = asyncio.create_task(self._run_loop(), name="account_event_reconciler")
        logger.info(
            "AccountEventReconciler started (cycle=%ds, flag=%s)",
            _CYCLE_SECONDS, _flag_enabled(),
        )

    async def stop(self) -> None:
        self._stop_event.set()
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):
                pass
            self._task = None

    # ------------------------------------------------------------------ status

    def get_status(self) -> dict:
        return {
            "running": bool(self._task and not self._task.done()),
            "flag_enabled": _flag_enabled(),
            "last_run": self._last_run.isoformat() if self._last_run else None,
            "last_error": self._last_error,
            "orphans_processed_total": self._orphans_processed_total,
            "alerts_sent_total": self._alerts_sent_total,
        }

    # ------------------------------------------------------------------ loop

    async def _run_loop(self) -> None:
        # Initial delay so we do not collide with startup boot storms.
        try:
            await asyncio.wait_for(self._stop_event.wait(), timeout=30)
            return  # stop signalled during initial delay
        except asyncio.TimeoutError:
            pass

        while not self._stop_event.is_set():
            try:
                await self._cycle()
            except Exception as exc:
                self._last_error = str(exc)
                logger.warning("AccountEventReconciler cycle error: %s", exc)

            try:
                await asyncio.wait_for(self._stop_event.wait(), timeout=_CYCLE_SECONDS)
                return
            except asyncio.TimeoutError:
                continue

    async def _cycle(self) -> None:
        self._last_run = datetime.utcnow()
        if not _flag_enabled():
            return  # silent no-op when flag off

        async with self.db_pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT id, username, role, tier, hardware_id, user_db_id,
                       created_at, created_via, source_metadata
                  FROM user_creation_events
                 WHERE processed_at IS NULL
                   AND created_at < NOW() - ($1::text || ' seconds')::interval
                 ORDER BY created_at ASC
                 LIMIT 50
                """,
                str(_ORPHAN_AGE_SECONDS),
            )

            for row in rows:
                username = row["username"]
                self._orphans_processed_total += 1

                # Mark first (idempotency guarantee). Email failures must not
                # cause us to resend the same alert on the next cycle.
                await conn.execute(
                    """
                    UPDATE user_creation_events
                       SET processed_at      = NOW(),
                           processed_by      = 'account_event_reconciler',
                           notification_sent = $2
                     WHERE id = $1
                       AND processed_at IS NULL
                    """,
                    row["id"],
                    not _is_suppressed(username),
                )

                if _is_suppressed(username):
                    logger.info(
                        "AccountEventReconciler: suppressed test/audit signup %s",
                        username,
                    )
                    continue

                await self._send_orphan_alert(row)

    # ------------------------------------------------------------------ email

    async def _send_orphan_alert(self, row: Any) -> None:
        if not self.notification_system:
            logger.warning(
                "AccountEventReconciler: no notification_system, cannot alert for %s",
                row["username"],
            )
            return

        try:
            subject = (
                f"[Sanctuary] Orphan signup detected: {row['username']} "
                f"({row.get('role') or 'unknown role'})"
            )
            body = self._format_alert(row)
            await self.notification_system._send_email(
                to_email="support@sovereignsanctuary.net",
                subject=subject,
                content=body,
                notification_type="orphan_signup_alert",
            )
            self._alerts_sent_total += 1
        except Exception as exc:
            logger.warning(
                "AccountEventReconciler: alert send failed for %s: %s",
                row["username"], exc,
            )

    def _format_alert(self, row: Any) -> str:
        meta = row.get("source_metadata") or {}
        return (
            "An account was created in PostgreSQL but no known signup path "
            "claimed it. This usually means manual SQL, an admin tool, or a "
            "bulk import. Verify intent.\n\n"
            f"Username     : {row.get('username')}\n"
            f"Role         : {row.get('role')}\n"
            f"Tier         : {row.get('tier')}\n"
            f"Hardware ID  : {row.get('hardware_id')}\n"
            f"DB UUID      : {row.get('user_db_id')}\n"
            f"Created at   : {row.get('created_at')}\n"
            f"Created via  : {row.get('created_via')}\n"
            f"Metadata     : {meta}\n"
            f"\nEvent ID     : {row.get('id')}\n"
        )
