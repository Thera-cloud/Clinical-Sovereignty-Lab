"""Next-day session operations reconciler.

Accountant / admin pass over the next 36 hours:
  - PG cancelled (or future hide-as-reference) while Google still has the event
    → delete Google
  - Google cancelled while PG still scheduled → cancel PG
  - Unpaid sessions inside 24h still sitting as scheduled → flag
  - Missing cancel emails → notify client + coach and prompt reschedule

Feature flag: ENABLE_SESSION_OPS_RECONCILE (default true).
Clone nodes skip. Cycle every 30 minutes; digest email at 06:00 and 20:00 US/Eastern.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional
from zoneinfo import ZoneInfo

logger = logging.getLogger("nate.session_ops_reconcile")

DEAD_STATUSES = frozenset(
    {"cancelled", "canceled", "cancelled_by_google", "rescheduled"}
)
ACTIVE_STATUSES = frozenset({"scheduled", "active", "pending_approval"})
OPS_EMAIL = os.getenv("SESSION_OPS_EMAIL", "support@sovereignsanctuary.net")
DIGEST_HOURS_ET = frozenset({6, 20})


def _is_clone_node() -> bool:
    return os.getenv("IS_CLONE", "").lower() in ("true", "1", "yes")


def reconcile_enabled() -> bool:
    return os.getenv("ENABLE_SESSION_OPS_RECONCILE", "true").lower() in (
        "1", "true", "yes",
    )


def _as_dt(value: Any) -> Optional[datetime]:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    raw = str(value).strip().replace("Z", "+00:00")
    if not raw:
        return None
    try:
        dt = datetime.fromisoformat(raw)
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _hidden(row: Dict[str, Any]) -> bool:
    sd = row.get("session_data") or {}
    if isinstance(sd, str):
        try:
            sd = json.loads(sd) if sd else {}
        except Exception:
            sd = {}
    v = (sd or {}).get("schedule_link_hidden", row.get("schedule_link_hidden"))
    if v is True:
        return True
    return str(v or "").lower() in ("true", "1", "yes")


def _notify_sent(row: Dict[str, Any]) -> bool:
    sd = row.get("session_data") or {}
    if isinstance(sd, str):
        try:
            sd = json.loads(sd) if sd else {}
        except Exception:
            sd = {}
    return bool((sd or {}).get("cancel_notify_sent"))


def classify_session(row: Dict[str, Any], now: datetime) -> List[str]:
    """Pure classifier — used by tests and the live cycle."""
    status = str(row.get("status") or "").lower()
    start = _as_dt(row.get("scheduled_start") or row.get("scheduled_at"))
    future = bool(start and start > now)
    has_gcal = bool(row.get("google_event_id"))
    pay = str(row.get("payment_status") or "").lower()
    actions: List[str] = []
    if not future and status in ACTIVE_STATUSES:
        return actions
    if future and status in DEAD_STATUSES and has_gcal:
        sync = str(row.get("sync_state") or "").lower()
        if sync != "deleted":
            actions.append("delete_gcal")
    if future and _hidden(row) and status in ("completed", "scheduled", "active"):
        actions.append("cancel_hidden_future")
        if has_gcal:
            actions.append("delete_gcal")
    if future and status in DEAD_STATUSES and not _notify_sent(row):
        actions.append("notify")
    if (
        future
        and start
        and start <= now + timedelta(hours=24)
        and pay in ("pending", "unpaid")
        and status in ACTIVE_STATUSES
        and (int(row.get("price_cents") or 0) > 0)
    ):
        actions.append("unpaid_risk")
    if future and status in ACTIVE_STATUSES and pay == "paid":
        actions.append("billable")
    return sorted(set(actions))


class SessionOpsReconcileAgent:
    def __init__(self, db_pool=None, app_state=None):
        self.db_pool = db_pool
        self.app_state = app_state
        self._task: Optional[asyncio.Task] = None
        self._running = False
        self._last_digest_key = ""

    async def start(self):
        if _is_clone_node() or not reconcile_enabled():
            logger.info("SessionOpsReconcileAgent: skipped (clone or flag off)")
            return
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._run_loop())
        logger.info("SessionOpsReconcileAgent: started (30min cycle)")

    async def stop(self):
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("SessionOpsReconcileAgent: stopped")

    async def _run_loop(self):
        await asyncio.sleep(90)
        while self._running:
            try:
                await self.run_cycle()
            except Exception as e:
                logger.error("SessionOpsReconcileAgent: cycle error: %s", e)
            await asyncio.sleep(1800)

    async def run_cycle(self) -> Dict[str, Any]:
        if not self.db_pool:
            return {"ok": False, "reason": "no pool"}
        now = datetime.now(timezone.utc)
        window_end = now + timedelta(hours=36)
        rows = await self._load_window(now - timedelta(hours=2), window_end)
        healed: List[Dict[str, Any]] = []
        flags: List[Dict[str, Any]] = []
        for row in rows:
            actions = classify_session(row, now)
            if not actions:
                continue
            item = {
                "session_id": row.get("session_id"),
                "client_name": row.get("client_name") or row.get("client_id"),
                "coach_id": row.get("coach_id"),
                "status": row.get("status"),
                "payment_status": row.get("payment_status"),
                "scheduled_start": str(row.get("scheduled_start") or ""),
                "actions": actions,
            }
            if "cancel_hidden_future" in actions:
                await self._cancel_hidden_future(row)
                item["healed"] = "cancelled_hidden_future"
                healed.append(item)
            elif "delete_gcal" in actions:
                await self._delete_gcal(row)
                item["healed"] = "gcal_deleted"
                healed.append(item)
            if "notify" in actions:
                await self._notify_cancel(row)
                item["notified"] = True
                healed.append(item)
            if "unpaid_risk" in actions or "billable" in actions:
                flags.append(item)
        digest = {"healed": healed, "flags": flags, "scanned": len(rows)}
        await self._maybe_digest(digest, now)
        logger.info(
            "SessionOpsReconcileAgent: scanned=%s healed=%s flags=%s",
            len(rows), len(healed), len(flags),
        )
        return digest

    async def _load_window(self, start: datetime, end: datetime) -> List[Dict[str, Any]]:
        async with self.db_pool.acquire() as conn:
            recs = await conn.fetch(
                """
                SELECT session_id, client_id, coach_id, client_name, status,
                       payment_status, price_cents, google_event_id, sync_state,
                       scheduled_start, scheduled_end, session_data
                FROM coaching_sessions
                WHERE COALESCE(scheduled_start, scheduled_at) >= $1
                  AND COALESCE(scheduled_start, scheduled_at) < $2
                ORDER BY scheduled_start ASC
                LIMIT 500
                """,
                start, end,
            )
        return [dict(r) for r in recs]

    async def _cancel_hidden_future(self, row: Dict[str, Any]) -> None:
        sid = row.get("session_id")
        if not sid:
            return
        reason = "Removed from Schedule without a formal cancel — reconciled."
        async with self.db_pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE coaching_sessions
                SET status = 'cancelled',
                    payment_status = CASE
                        WHEN LOWER(COALESCE(payment_status,'')) = 'paid'
                        THEN payment_status ELSE 'cancelled' END,
                    session_data = COALESCE(session_data, '{}'::jsonb)
                      || jsonb_build_object(
                           'cancellation_reason', $2::text,
                           'schedule_link_hidden', false,
                           'calendar_reference_only', false,
                           'reconciled_by', 'session_ops_reconcile'
                         ),
                    updated_at = NOW()
                WHERE session_id = $1
                """,
                sid, reason,
            )
        row["status"] = "cancelled"
        row["cancellation_reason"] = reason
        await self._delete_gcal(row)
        await self._notify_cancel(row)

    async def _delete_gcal(self, row: Dict[str, Any]) -> None:
        try:
            from app.services.google_calendar_session_sync import (
                sync_session_for_participants,
            )
            await sync_session_for_participants(self.db_pool, row, action="delete")
        except Exception as e:
            logger.warning(
                "SessionOpsReconcileAgent: GCal delete failed sid=%s: %s",
                row.get("session_id"), e,
            )

    async def _notify_cancel(self, row: Dict[str, Any]) -> None:
        if _notify_sent(row):
            return
        notify_sys = (
            getattr(self.app_state, "notification_system", None)
            if self.app_state
            else None
        )
        pay = str(row.get("payment_status") or "").lower()
        unpaid = pay in ("pending", "unpaid", "cancelled") and int(
            row.get("price_cents") or 0
        ) > 0 and str(row.get("status") or "").lower() in DEAD_STATUSES
        row.setdefault(
            "cancellation_reason",
            "Payment was not received before the 24-hour deadline."
            if unpaid
            else "This session was cancelled.",
        )
        try:
            from app.services.session_approval import (
                notify_client_of_coach_cancel,
                notify_coach_of_client_cancel,
            )
            tmpl = "session_cancelled_unpaid" if unpaid else "session_cancelled_client"
            await notify_client_of_coach_cancel(
                self.db_pool, row, notification_system=notify_sys, template=tmpl,
            )
            await notify_coach_of_client_cancel(
                self.db_pool, row, notification_system=notify_sys,
            )
        except Exception as e:
            logger.warning(
                "SessionOpsReconcileAgent: notify failed sid=%s: %s",
                row.get("session_id"), e,
            )
        try:
            async with self.db_pool.acquire() as conn:
                await conn.execute(
                    """
                    UPDATE coaching_sessions
                    SET session_data = COALESCE(session_data, '{}'::jsonb)
                      || '{"cancel_notify_sent": true}'::jsonb
                    WHERE session_id = $1
                    """,
                    row.get("session_id"),
                )
        except Exception:
            pass

    async def _maybe_digest(self, digest: Dict[str, Any], now: datetime) -> None:
        try:
            et = now.astimezone(ZoneInfo("America/New_York"))
        except Exception:
            et = now
        if et.hour not in DIGEST_HOURS_ET:
            return
        key = et.strftime("%Y-%m-%d-%H")
        if key == self._last_digest_key:
            return
        issues = (digest.get("healed") or []) + [
            f for f in (digest.get("flags") or []) if "unpaid_risk" in (f.get("actions") or [])
        ]
        self._last_digest_key = key
        await self._send_digest(digest, issues, et)

    async def _send_digest(
        self, digest: Dict[str, Any], issues: List[Dict[str, Any]], et: datetime,
    ) -> None:
        if not issues and not digest.get("flags"):
            return
        rows_html = []
        for item in issues or digest.get("flags") or []:
            rows_html.append(
                "<tr>"
                f"<td style='padding:6px 12px;'>{item.get('client_name') or ''}</td>"
                f"<td style='padding:6px 12px;'>{item.get('scheduled_start') or ''}</td>"
                f"<td style='padding:6px 12px;'>{item.get('status') or ''} / "
                f"{item.get('payment_status') or ''}</td>"
                f"<td style='padding:6px 12px;'>{', '.join(item.get('actions') or [])}</td>"
                "</tr>"
            )
        table = (
            "<table style='width:100%;background:#0a0a0a;border-radius:6px;color:#cbd5e1;'>"
            "<tr><td style='padding:6px 12px;color:#94a3b8;'>Client</td>"
            "<td style='padding:6px 12px;color:#94a3b8;'>When</td>"
            "<td style='padding:6px 12px;color:#94a3b8;'>Status</td>"
            "<td style='padding:6px 12px;color:#94a3b8;'>Actions</td></tr>"
            + "".join(rows_html)
            + "</table>"
        )
        coaches = sorted({
            str(i.get("coach_id") or "") for i in (digest.get("healed") or []) + (digest.get("flags") or [])
            if i.get("coach_id")
        })
        dests = {OPS_EMAIL.lower()}
        if self.db_pool and coaches:
            try:
                async with self.db_pool.acquire() as conn:
                    recs = await conn.fetch(
                        """
                        SELECT DISTINCT LOWER(COALESCE(profile_data->>'email','')) AS email
                        FROM users
                        WHERE hardware_id = ANY($1::text[])
                          AND COALESCE(profile_data->>'email','') LIKE '%@%'
                        """,
                        coaches,
                    )
                for r in recs:
                    if r["email"]:
                        dests.add(r["email"])
            except Exception as e:
                logger.warning("SessionOpsReconcileAgent: coach emails skipped: %s", e)
        try:
            from app.services.notifications_service import EmailService
            sender = EmailService().send_email
            ctx = {
                "issue_count": len(issues) or len(digest.get("flags") or []),
                "issue_count_plural": "" if (len(issues) == 1) else "s",
                "digest_html": (
                    f"<p>Window: {et.strftime('%Y-%m-%d %H:%M %Z')} · "
                    f"scanned {digest.get('scanned', 0)} sessions.</p>{table}"
                ),
            }
            for dest in dests:
                try:
                    await sender(dest, "session_ops_digest", ctx)
                except Exception as e:
                    logger.warning("SessionOpsReconcileAgent: digest to %s failed: %s", dest, e)
        except Exception as e:
            logger.warning("SessionOpsReconcileAgent: digest send failed: %s", e)
        try:
            async with self.db_pool.acquire() as conn:
                await conn.execute(
                    """
                    INSERT INTO skyeye_activity (type, content, platform)
                    VALUES ('session_ops_reconcile_sent', $1, 'ops')
                    """,
                    json.dumps(digest, default=str)[:8000],
                )
        except Exception:
            pass
