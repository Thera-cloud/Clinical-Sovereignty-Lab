"""
LITTLE NATE — Token Audit Agent
Independent auditor that verifies the Token Renewal Agent's actions.

Runs every 30 minutes (offset from the renewal agent) and:
  1. Audits recent token_renewal_* events against actual platform state.
  2. Independently checks ALL platform tokens via adapter.authenticate().
  3. Verifies notifications were sent for expired tokens.
  4. Checks that failed posts on now-valid platforms have been re-queued.
  5. Logs discrepancies to the immutable audit_log table.
"""

import asyncio
import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from app.services.token_alert_policy import (
    social_token_outbound_alerts_allowed_for_platform,
)

logger = logging.getLogger("skyeye.token_audit_agent")


class TokenAuditAgent:
    """Background agent: audits Token Renewal Agent actions and flags discrepancies."""

    def __init__(self, db_pool, interval_seconds: int = 1800,
                 notification_system=None, admin_phone: str = "",
                 admin_email: str = ""):
        self.db_pool = db_pool
        self.interval = interval_seconds
        self.notifications = notification_system
        self.admin_phone = admin_phone
        self.admin_email = admin_email
        self._task: Optional[asyncio.Task] = None
        self._running = False

    async def start(self):
        if self._task and not self._task.done():
            return
        self._running = True
        self._task = asyncio.create_task(self._loop())
        logger.info(f"Token Audit Agent started (interval={self.interval}s)")

    async def stop(self):
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("Token Audit Agent stopped")

    async def _loop(self):
        await asyncio.sleep(60)
        while self._running:
            try:
                await self._audit_cycle()
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.error(f"Token Audit Agent cycle failed: {e}")
            await asyncio.sleep(self.interval)

    # =========================================================================
    # MAIN AUDIT CYCLE
    # =========================================================================

    async def _audit_cycle(self):
        report = {
            "platforms_checked": 0,
            "discrepancies": 0,
            "missed_notifications": 0,
            "stuck_queue_items": 0,
            "details": [],
        }

        await self._audit_renewal_events(report)
        await self._independent_health_check(report)
        await self._notification_gap_check(report)
        await self._queue_integrity_check(report)
        await self._write_report(report)

        logger.info(
            f"Token Audit: {report['platforms_checked']} checked, "
            f"{report['discrepancies']} discrepancies, "
            f"{report['missed_notifications']} missed notifications, "
            f"{report['stuck_queue_items']} stuck queue items"
        )

    # =========================================================================
    # 1. AUDIT RENEWAL EVENTS
    # =========================================================================

    async def _audit_renewal_events(self, report: dict):
        try:
            async with self.db_pool.acquire() as conn:
                events = await conn.fetch("""
                    SELECT id, platform, type, content, severity, created_at
                    FROM skyeye_activity
                    WHERE type LIKE 'token_renewal_%'
                      AND created_at > NOW() - INTERVAL '2 hours'
                    ORDER BY created_at DESC
                """)
        except Exception as e:
            logger.error(f"Failed to query renewal events: {e}")
            return

        for event in events:
            if event["type"] == "token_renewal_validated":
                actual_ok = await self._verify_platform_live(event["platform"])
                if not actual_ok:
                    report["discrepancies"] += 1
                    detail = (
                        f"DISCREPANCY: {event['platform']} was marked validated "
                        f"at {event['created_at']}, but independent check fails"
                    )
                    report["details"].append(detail)
                    await self._log_discrepancy(
                        event["platform"],
                        f"Renewal agent claimed validation success, but authenticate() returns False",
                        event_id=event["id"]
                    )

    # =========================================================================
    # 2. INDEPENDENT HEALTH CHECK
    # =========================================================================

    async def _independent_health_check(self, report: dict):
        from app.services.platforms import get_all_adapters

        adapters = get_all_adapters(self.db_pool)
        for platform_name, adapter in adapters.items():
            report["platforms_checked"] += 1
            try:
                db_status = await self._get_db_token_status(platform_name)
                if not db_status or db_status.get("status") == "no_tokens":
                    continue

                live_ok = await adapter.authenticate()
                db_ok = db_status.get("status") == "connected"

                if live_ok and not db_ok:
                    report["discrepancies"] += 1
                    detail = f"{platform_name}: live auth succeeds but DB says '{db_status.get('status')}'"
                    report["details"].append(detail)
                    await self._log_discrepancy(platform_name, detail)

                elif not live_ok and db_ok:
                    report["discrepancies"] += 1
                    detail = f"{platform_name}: DB says connected but live auth fails"
                    report["details"].append(detail)
                    await self._log_discrepancy(platform_name, detail)

            except Exception as e:
                logger.warning(f"Audit health check for {platform_name}: {e}")

    # =========================================================================
    # 3. NOTIFICATION GAP CHECK
    # =========================================================================

    async def _notification_gap_check(self, report: dict):
        try:
            async with self.db_pool.acquire() as conn:
                expired_platforms = await conn.fetch("""
                    SELECT platform, updated_at
                    FROM skyeye_platform_tokens
                    WHERE status = 'expired'
                      AND updated_at < NOW() - INTERVAL '30 minutes'
                """)

                for row in expired_platforms:
                    plat = row["platform"]
                    if not social_token_outbound_alerts_allowed_for_platform(plat):
                        continue

                    notified = await conn.fetchval("""
                        SELECT COUNT(*) FROM skyeye_activity
                        WHERE platform = $1
                          AND type = 'token_renewal_notification'
                          AND created_at > $2
                    """, plat, row["updated_at"])

                    if notified == 0:
                        report["missed_notifications"] += 1
                        detail = (
                            f"NOTIFICATION GAP: {plat} expired since "
                            f"{row['updated_at']} but no notification was sent"
                        )
                        report["details"].append(detail)
                        await self._log_discrepancy(plat, detail)

                        if self._notification_system_available():
                            await self._send_gap_notification(plat)

        except Exception as e:
            logger.error(f"Notification gap check failed: {e}")

    # =========================================================================
    # 4. QUEUE INTEGRITY CHECK
    # =========================================================================

    MAX_POST_RETRIES = 3

    async def _queue_integrity_check(self, report: dict):
        try:
            async with self.db_pool.acquire() as conn:
                connected_platforms = await conn.fetch("""
                    SELECT platform FROM skyeye_platform_tokens
                    WHERE status = 'connected'
                """)
                connected_set = {r["platform"] for r in connected_platforms}

                stuck = await conn.fetch("""
                    SELECT id, platform, content_text
                    FROM skyeye_content_queue
                    WHERE status = 'failed'
                      AND platform = ANY($1::text[])
                """, list(connected_set))

                report["stuck_queue_items"] = len(stuck)

                if stuck:
                    platforms_affected = set(r["platform"] for r in stuck)
                    detail = (
                        f"QUEUE STUCK: {len(stuck)} failed posts on now-connected platforms: "
                        f"{', '.join(platforms_affected)}"
                    )
                    report["details"].append(detail)

                    # Re-queue eligible items (under retry cap, failed > 30 min ago)
                    result = await conn.execute("""
                        UPDATE skyeye_content_queue
                        SET status = 'approved',
                            error_message = NULL,
                            updated_at = NOW(),
                            cross_thread_refs = jsonb_set(
                                COALESCE(cross_thread_refs, '{}'::jsonb),
                                '{retry_count}',
                                to_jsonb(COALESCE((cross_thread_refs->>'retry_count')::int, 0) + 1)
                            )
                        WHERE status = 'failed'
                          AND platform = ANY($1::text[])
                          AND COALESCE((cross_thread_refs->>'retry_count')::int, 0) < $2
                          AND updated_at < NOW() - INTERVAL '30 minutes'
                    """, list(connected_set), self.MAX_POST_RETRIES)
                    requeued = int(result.split()[-1]) if result else 0
                    exhausted = len(stuck) - requeued

                    if requeued > 0:
                        report["details"].append(
                            f"AUDIT FIX: Re-queued {requeued} stuck posts for retry"
                        )
                        logger.info("Token Audit: re-queued %d stuck posts", requeued)

                    if exhausted > 0:
                        report["details"].append(
                            f"EXHAUSTED: {exhausted} posts exceeded max retries ({self.MAX_POST_RETRIES})"
                        )
                        await self._log_discrepancy(
                            "system",
                            f"{exhausted} failed posts exceeded {self.MAX_POST_RETRIES} retries "
                            f"on platforms: {', '.join(platforms_affected)}"
                        )

        except Exception as e:
            logger.error(f"Queue integrity check failed: {e}")

    # =========================================================================
    # HELPERS
    # =========================================================================

    async def _verify_platform_live(self, platform: str) -> bool:
        try:
            from app.services.platforms import get_adapter
            adapter = get_adapter(platform, self.db_pool)
            if not adapter:
                return False
            return await adapter.authenticate()
        except Exception:
            return False

    async def _get_db_token_status(self, platform: str) -> dict:
        try:
            async with self.db_pool.acquire() as conn:
                row = await conn.fetchrow(
                    "SELECT platform, status, token_expiry FROM skyeye_platform_tokens WHERE platform = $1",
                    platform
                )
                return dict(row) if row else {"status": "no_tokens"}
        except Exception:
            return {"status": "error"}

    async def _log_discrepancy(self, platform: str, detail: str, event_id: int = None):
        try:
            async with self.db_pool.acquire() as conn:
                await conn.execute("""
                    INSERT INTO audit_log
                        (action_type, target_type, description, compliance_flags)
                    VALUES
                        ('SECURITY', 'token_audit',
                         $1, ARRAY['AUDIT'])
                """, f"[{platform}] {detail}"[:1000])
        except Exception as e:
            logger.error(f"Failed to write audit log: {e}")

    async def _write_report(self, report: dict):
        severity = "success" if report["discrepancies"] == 0 and report["missed_notifications"] == 0 else "warning"
        summary = (
            f"Audit complete: {report['platforms_checked']} platforms checked, "
            f"{report['discrepancies']} discrepancies, "
            f"{report['missed_notifications']} missed notifications, "
            f"{report['stuck_queue_items']} stuck queue items"
        )

        try:
            async with self.db_pool.acquire() as conn:
                await conn.execute("""
                    INSERT INTO skyeye_activity (platform, type, content, severity, metadata, created_at)
                    VALUES ('system', 'token_audit_report', $1, $2, $3::jsonb, NOW())
                """, summary, severity, json.dumps({"details": report["details"][:20]}))

                action_type = "APPROVE" if report["discrepancies"] == 0 else "SECURITY"
                await conn.execute("""
                    INSERT INTO audit_log
                        (action_type, target_type, description, compliance_flags)
                    VALUES
                        ($1, 'token_audit',
                         $2, ARRAY['AUDIT'])
                """, action_type, summary[:1000])
        except Exception as e:
            logger.error(f"Failed to write audit report: {e}")

    def _notification_system_available(self) -> bool:
        return self.notifications is not None and (self.admin_phone or self.admin_email)

    async def _send_gap_notification(self, platform: str):
        if not self.notifications:
            return
        msg = (
            f"Sovereign Sanctuary AUDIT: {platform} token is expired but "
            f"the renewal agent never sent a notification. Investigate."
        )
        try:
            if self.admin_phone:
                await self.notifications.send_sms(self.admin_phone, msg)
            if self.admin_email:
                await self.notifications._send_email(
                    self.admin_email,
                    f"Audit Alert — {platform} Missed Notification",
                    f"<p>{msg}</p>",
                    notification_type="security"
                )
        except Exception as e:
            logger.error(f"Audit gap notification failed: {e}")
