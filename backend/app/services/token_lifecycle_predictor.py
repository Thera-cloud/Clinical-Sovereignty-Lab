"""
LITTLE NATE — Token Lifecycle Predictor
Early warning system that watches token expiry dates and sends proactive
notifications at 14-day, 7-day, and 1-day thresholds.

Platforms with no refresh_token are flagged as "manual renewal only" since
they will require a full re-auth flow rather than an automated refresh.

Loop interval: 12 hours
Stagger delay: 80 seconds
"""

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

logger = logging.getLogger("skyeye.token_lifecycle_predictor")

WARN_TIERS = [
    (14, "info"),
    (7, "warning"),
    (1, "urgent"),
]


class TokenLifecyclePredictor:

    def __init__(self, db_pool, notification_system=None,
                 admin_phone: str = "", admin_email: str = "",
                 interval_seconds: int = 43200):
        self.db_pool = db_pool
        self.notifications = notification_system
        self.admin_phone = admin_phone
        self.admin_email = admin_email
        self.interval = interval_seconds
        self._task: Optional[asyncio.Task] = None
        self._running = False

    async def start(self):
        if self._task and not self._task.done():
            return
        self._running = True
        self._task = asyncio.create_task(self._run_loop())
        logger.info("TokenLifecyclePredictor started (interval=%ds)", self.interval)

    async def stop(self):
        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("TokenLifecyclePredictor stopped")

    async def _run_loop(self):
        await asyncio.sleep(80)
        while self._running:
            try:
                await self._scan()
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.error("TokenLifecyclePredictor scan failed: %s", e, exc_info=True)
            await asyncio.sleep(self.interval)

    async def _scan(self):
        now = datetime.now(timezone.utc)
        tokens = await self._fetch_tokens()
        alerts_sent = 0

        for tok in tokens:
            expiry = tok["token_expiry"]
            if expiry is None:
                continue

            if expiry.tzinfo is None:
                expiry = expiry.replace(tzinfo=timezone.utc)

            days_left = (expiry - now).total_seconds() / 86400
            platform = tok["platform"]
            has_refresh = bool(tok.get("refresh_token"))

            for threshold_days, severity in WARN_TIERS:
                if days_left <= threshold_days:
                    if await self._already_notified(platform, threshold_days, now):
                        break
                    await self._send_alert(platform, days_left, threshold_days,
                                           severity, has_refresh)
                    alerts_sent += 1
                    break

            if not has_refresh and tok["status"] == "connected" and days_left <= 30:
                if not await self._already_notified(platform, 30, now):
                    await self._log_activity(
                        platform, "token_expiry_warning",
                        f"{platform}: manual renewal only (no refresh_token). "
                        f"Expires in {days_left:.0f} days.",
                        "warning",
                    )

        newly_connected = await self._check_reconnections()
        for plat in newly_connected:
            await self._send_reconnection_confirmation(plat)

        logger.info("TokenLifecyclePredictor scan done: %d alerts", alerts_sent)

    async def _fetch_tokens(self) -> list:
        try:
            async with self.db_pool.acquire() as conn:
                return await conn.fetch("""
                    SELECT platform, status, token_expiry, refresh_token
                    FROM skyeye_platform_tokens
                    WHERE status != 'disconnected'
                """)
        except Exception as e:
            logger.error("TokenLifecyclePredictor: token fetch failed: %s", e)
            return []

    async def _already_notified(self, platform: str, threshold_days: int,
                                now: datetime) -> bool:
        """Dedup via skyeye_activity — avoid re-sending the same tier alert."""
        try:
            async with self.db_pool.acquire() as conn:
                row = await conn.fetchrow("""
                    SELECT 1 FROM skyeye_activity
                    WHERE platform = $1
                      AND type = 'token_expiry_warning'
                      AND content LIKE $2
                      AND created_at > $3
                    LIMIT 1
                """, platform, f"%{threshold_days}-day%", now - timedelta(days=max(threshold_days, 1)))
            return row is not None
        except Exception:
            return False

    async def _send_alert(self, platform: str, days_left: float,
                          threshold_days: int, severity: str,
                          has_refresh: bool):
        renewal_note = "auto-refresh available" if has_refresh else "MANUAL RE-AUTH REQUIRED"
        msg = (
            f"[{severity.upper()}] {platform} token expires in {days_left:.1f} days "
            f"({threshold_days}-day warning). {renewal_note}."
        )

        await self._log_activity(platform, "token_expiry_warning", msg, severity)

        from app.config import settings as _settings

        if not getattr(_settings, "SKYEYE_SOCIAL_TOKEN_ALERT_EMAILS_ENABLED", True):
            logger.debug(
                "TokenLifecyclePredictor: outbound token alerts disabled "
                "(SKYEYE_SOCIAL_TOKEN_ALERT_EMAILS_ENABLED=false), skipping email/SMS for %s",
                platform,
            )
            logger.info("TokenLifecyclePredictor: %s", msg)
            return

        if severity in ("warning", "urgent") and self.notifications:
            if self.admin_email:
                subject = f"{'URGENT: ' if severity == 'urgent' else ''}{platform} token expiry warning"
                await self.notifications._send_email(self.admin_email, subject, msg)
            if self.admin_phone:
                await self.notifications.send_sms(self.admin_phone, msg[:160])

        logger.info("TokenLifecyclePredictor: %s", msg)

    async def _check_reconnections(self) -> list:
        """Detect platforms that moved to 'connected' in the last scan interval."""
        try:
            async with self.db_pool.acquire() as conn:
                rows = await conn.fetch("""
                    SELECT DISTINCT a.platform
                    FROM skyeye_activity a
                    JOIN skyeye_platform_tokens t ON t.platform = a.platform
                    WHERE a.type IN ('token_refresh_success', 'oauth_callback_success')
                      AND a.created_at > NOW() - INTERVAL '12 hours'
                      AND t.status = 'connected'
                      AND NOT EXISTS (
                          SELECT 1 FROM skyeye_activity a2
                          WHERE a2.platform = a.platform
                            AND a2.type = 'token_reconnection_confirmed'
                            AND a2.created_at > NOW() - INTERVAL '12 hours'
                      )
                """)
            return [r["platform"] for r in rows]
        except Exception:
            return []

    async def _send_reconnection_confirmation(self, platform: str):
        msg = f"{platform}: token is now valid and connected."
        await self._log_activity(platform, "token_reconnection_confirmed", msg, "success")
        if self.notifications and self.admin_email:
            await self.notifications._send_email(
                self.admin_email,
                f"{platform} token reconnected",
                msg,
            )
        logger.info("TokenLifecyclePredictor: reconnection confirmed for %s", platform)

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
