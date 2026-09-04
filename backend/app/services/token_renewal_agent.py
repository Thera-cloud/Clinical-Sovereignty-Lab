"""
LITTLE NATE — Token Renewal Agent
Autonomous background agent that detects expired/expiring platform tokens,
attempts auto-refresh, and notifies the admin when human re-authorization
is required. After a successful renewal, validates the new token and
re-queues any failed content.

Loop interval: 15 minutes
Notification cooldown: 2 hours per platform
"""

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

logger = logging.getLogger("skyeye.token_renewal_agent")


class TokenRenewalAgent:
    """Detects token failures, auto-refreshes when possible, notifies admin otherwise."""

    NOTIFY_COOLDOWN = timedelta(hours=2)
    EXPIRY_LOOKAHEAD = timedelta(minutes=30)

    def __init__(
        self,
        db_pool,
        notification_system=None,
        admin_phone: str = "",
        admin_email: str = "",
        interval_seconds: int = 900,
    ):
        self.db_pool = db_pool
        self.notifications = notification_system
        self.admin_phone = admin_phone
        self.admin_email = admin_email
        self.interval = interval_seconds
        self._task: Optional[asyncio.Task] = None
        self._running = False
        self._pending_renewals: Dict[str, Dict[str, Any]] = {}

    # ── lifecycle ────────────────────────────────────────────────────────

    async def start(self):
        if self._task and not self._task.done():
            return
        self._running = True
        self._task = asyncio.create_task(self._run_loop())
        logger.info("TokenRenewalAgent started (interval=%ds)", self.interval)

    async def stop(self):
        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("TokenRenewalAgent stopped")

    # ── main loop ────────────────────────────────────────────────────────

    async def _run_loop(self):
        await asyncio.sleep(30)  # stagger vs Token Guardian
        while self._running:
            try:
                await self._sweep()
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.error("TokenRenewalAgent sweep error: %s", e, exc_info=True)
            await asyncio.sleep(self.interval)

    async def _sweep(self):
        from app.services.platforms import get_all_adapters

        now = datetime.now(timezone.utc)
        await self._seed_cooldowns_from_db(now)
        adapters = get_all_adapters(self.db_pool)
        failing = await self._detect_failing_platforms(now)

        if not failing:
            logger.info("TokenRenewalAgent: all platforms healthy")
            return

        logger.info("TokenRenewalAgent: %d platform(s) need attention: %s",
                     len(failing), ", ".join(failing))

        for platform_name, row in failing.items():
            adapter = adapters.get(platform_name)
            if not adapter:
                logger.warning("TokenRenewalAgent: no adapter for %s", platform_name)
                continue

            resolved = await self._attempt_auto_refresh(platform_name, adapter)
            if resolved:
                await self._on_renewal_success(platform_name, adapter, now)
                continue

            await self._notify_admin(platform_name, now)

        await self._check_pending_resolutions(adapters, now)

    # ── step 0: seed cooldowns from DB so they survive restarts ─────────

    async def _seed_cooldowns_from_db(self, now: datetime):
        """Load recent notification timestamps from skyeye_activity so
        the 2-hour cooldown survives container restarts."""
        if self._pending_renewals:
            return  # already populated from a previous sweep
        try:
            async with self.db_pool.acquire() as conn:
                rows = await conn.fetch("""
                    SELECT DISTINCT ON (platform) platform, created_at
                    FROM skyeye_activity
                    WHERE type = 'token_renewal_notification'
                      AND created_at > $1
                    ORDER BY platform, created_at DESC
                """, now - self.NOTIFY_COOLDOWN)
            for row in rows:
                plat = row["platform"]
                notified_at = row["created_at"]
                if notified_at.tzinfo is None:
                    notified_at = notified_at.replace(tzinfo=timezone.utc)
                self._pending_renewals[plat] = {
                    "notified_at": notified_at,
                    "attempts": 1,
                }
            if self._pending_renewals:
                logger.info(
                    "TokenRenewalAgent: seeded cooldowns from DB for %s",
                    ", ".join(self._pending_renewals.keys()),
                )
        except Exception as e:
            logger.warning("TokenRenewalAgent: failed to seed cooldowns: %s", e)

    # ── step 1: detect ───────────────────────────────────────────────────

    async def _detect_failing_platforms(self, now: datetime) -> Dict[str, dict]:
        threshold = now + self.EXPIRY_LOOKAHEAD
        try:
            async with self.db_pool.acquire() as conn:
                rows = await conn.fetch("""
                    SELECT platform, status, token_expiry, error_message
                    FROM skyeye_platform_tokens
                    WHERE status = 'expired'
                       OR (token_expiry IS NOT NULL AND token_expiry < $1)
                """, threshold)
            return {r["platform"]: dict(r) for r in rows}
        except Exception as e:
            logger.error("TokenRenewalAgent: detect query failed: %s", e)
            return {}

    # ── step 2: auto-refresh ─────────────────────────────────────────────

    async def _attempt_auto_refresh(self, platform: str, adapter) -> bool:
        try:
            refreshed = await adapter.refresh_token()
            if refreshed:
                logger.info("TokenRenewalAgent: %s auto-refreshed", platform)
                return True
        except Exception as e:
            logger.warning("TokenRenewalAgent: %s refresh exception: %s", platform, e)
        return False

    # ── step 3: notify admin ─────────────────────────────────────────────

    async def _notify_admin(self, platform: str, now: datetime):
        from app.services.token_alert_policy import (
            social_token_outbound_alerts_allowed_for_platform,
        )

        # Paused in ops — no renewal SMS/email; Token Audit must treat this as intentional
        # (not a “missed notification” gap).
        if not social_token_outbound_alerts_allowed_for_platform(platform):
            logger.debug(
                "TokenRenewalAgent: outbound token alerts suppressed for %s "
                "(global flag off or SKYEYE_TOKEN_ALERT_PAUSED_PLATFORMS), skipping notify",
                platform,
            )
            return

        pending = self._pending_renewals.get(platform)
        if pending:
            last_notified = pending.get("notified_at")
            if last_notified and (now - last_notified) < self.NOTIFY_COOLDOWN:
                logger.debug("TokenRenewalAgent: %s cooldown active, skipping notification", platform)
                return

        from app.config import settings as _settings

        base_url = _settings.PUBLIC_BASE_URL or "https://api.sovereignsanctuary.net"
        oauth_url = f"{base_url}/api/skyeye/platforms/{platform}/connect"

        sms_body = (
            f"Sovereign Sanctuary: {platform} token expired. "
            f"Re-authorize: {oauth_url}"
        )
        email_subject = f"Token Renewal Required — {platform.title()}"
        email_body = (
            f"<p>The <strong>{platform}</strong> OAuth token has expired and "
            f"could not be auto-refreshed.</p>"
            f"<p><a href=\"{oauth_url}\">Click here to re-authorize {platform}</a></p>"
            f"<p>Until re-authorized, scheduled posts for {platform} will be held.</p>"
        )

        attempts = (pending or {}).get("attempts", 0) + 1
        self._pending_renewals[platform] = {
            "notified_at": now,
            "attempts": attempts,
        }

        sms_sent = False
        email_sent = False

        if self.notifications:
            if self.admin_phone:
                try:
                    sms_sent = await self.notifications.send_sms(self.admin_phone, sms_body)
                except Exception as e:
                    logger.error("TokenRenewalAgent: SMS failed for %s: %s", platform, e)
            if self.admin_email:
                try:
                    email_sent = await self.notifications._send_email(
                        self.admin_email, email_subject, email_body,
                        notification_type="security"
                    )
                except Exception as e:
                    logger.error("TokenRenewalAgent: email failed for %s: %s", platform, e)

        await self._log_activity(
            platform, "token_renewal_notification",
            f"Admin notified — attempt #{attempts} (sms={sms_sent}, email={email_sent})",
            severity="warning"
        )

        logger.info("TokenRenewalAgent: notified admin for %s (attempt #%d)", platform, attempts)

    # ── step 4: check if pending renewals resolved ───────────────────────

    async def _check_pending_resolutions(self, adapters, now: datetime):
        for platform in list(self._pending_renewals.keys()):
            try:
                async with self.db_pool.acquire() as conn:
                    row = await conn.fetchrow(
                        "SELECT status FROM skyeye_platform_tokens WHERE platform = $1",
                        platform
                    )
                if row and row["status"] == "connected":
                    adapter = adapters.get(platform)
                    if adapter:
                        await self._on_renewal_success(platform, adapter, now)
                    # Success path pops inside _on_renewal_success. Keep cooldown on failed auth.
            except Exception as e:
                logger.error("TokenRenewalAgent: resolution check failed for %s: %s", platform, e)

    # ── step 5: validate after renewal ───────────────────────────────────

    async def _on_renewal_success(self, platform: str, adapter, now: datetime):
        valid = False
        try:
            valid = await adapter.authenticate()
        except Exception as e:
            logger.warning("TokenRenewalAgent: validation call failed for %s: %s", platform, e)

        if valid:
            await self._log_activity(
                platform, "token_renewal_validated",
                f"Token validated — platform operational",
                severity="success"
            )
            logger.info("TokenRenewalAgent: %s validated ✓", platform)
            self._pending_renewals.pop(platform, None)
            await self._retry_failed_posts(platform)
        else:
            await self._log_activity(
                platform, "token_renewal_validation_failed",
                f"Token saved but validation failed — re-entering notification cycle",
                severity="warning"
            )
            logger.warning("TokenRenewalAgent: %s validation failed, re-notifying", platform)
            await self._notify_admin(platform, now)

    # ── step 6: retry failed content ─────────────────────────────────────

    MAX_POST_RETRIES = 3

    async def _retry_failed_posts(self, platform: str):
        try:
            async with self.db_pool.acquire() as conn:
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
                    WHERE platform = $1
                      AND status = 'failed'
                      AND COALESCE((cross_thread_refs->>'retry_count')::int, 0) < $2
                      AND updated_at < NOW() - INTERVAL '30 minutes'
                """, platform, self.MAX_POST_RETRIES)
            count = int(result.split()[-1]) if result else 0
            if count > 0:
                await self._log_activity(
                    platform, "token_renewal_retry",
                    f"Re-queued {count} failed post(s) for retry",
                    severity="info"
                )
                logger.info("TokenRenewalAgent: re-queued %d failed posts for %s", count, platform)
        except Exception as e:
            logger.error("TokenRenewalAgent: retry query failed for %s: %s", platform, e)

    # ── helpers ──────────────────────────────────────────────────────────

    async def _log_activity(self, platform: str, activity_type: str,
                            content: str, severity: str = "info"):
        try:
            async with self.db_pool.acquire() as conn:
                await conn.execute("""
                    INSERT INTO skyeye_activity (platform, type, content, severity, created_at)
                    VALUES ($1, $2, $3, $4, NOW())
                """, platform, activity_type, content, severity)
        except Exception:
            pass
