"""
LITTLE NATE — Token Guardian
Background service that keeps all social media platform tokens alive.

Runs on a configurable interval (default: every 45 minutes) and for each
platform with stored tokens:
  1. Checks token_expiry — if within the refresh window, proactively refreshes.
  2. Calls authenticate() to verify the token is still valid.
  3. If authenticate fails, attempts refresh_token().
  4. Logs all results to skyeye_activity so the dashboard reflects reality.

This prevents tokens from silently expiring between SkyEye sessions.
"""

import asyncio
import logging
from datetime import datetime, timedelta, timezone

logger = logging.getLogger("skyeye.token_guardian")


class TokenGuardian:
    """Persistent background agent that maintains platform OAuth connections."""

    def __init__(self, db_pool, interval_seconds: int = 2700):
        self.db_pool = db_pool
        self.interval = interval_seconds  # 45 min default
        self._task = None
        self._running = False
        self._refresh_window = timedelta(minutes=30)

    async def start(self):
        if self._task and not self._task.done():
            return
        self._running = True
        self._task = asyncio.create_task(self._loop())
        logger.info(f"Token Guardian started (interval={self.interval}s)")

    def stop(self):
        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()
        logger.info("Token Guardian stopped")

    async def _loop(self):
        await asyncio.sleep(10)
        while self._running:
            try:
                await self._check_all_platforms()
            except Exception as e:
                logger.error(f"Token Guardian sweep failed: {e}")
            await asyncio.sleep(self.interval)

    async def _check_all_platforms(self):
        from app.services.platforms import get_all_adapters

        adapters = get_all_adapters(self.db_pool)
        now = datetime.now(timezone.utc)
        results = {}

        for platform_name, adapter in adapters.items():
            try:
                result = await self._check_platform(platform_name, adapter, now)
                results[platform_name] = result
            except Exception as e:
                logger.error(f"Token Guardian: {platform_name} check crashed: {e}")
                results[platform_name] = f"error: {e}"

        connected = [p for p, r in results.items() if r == "connected"]
        refreshed = [p for p, r in results.items() if r == "refreshed"]
        failed = [
            p for p, r in results.items()
            if r not in ("connected", "refreshed", "no_tokens", "skipped", "still_expired")
        ]
        no_tokens = [p for p, r in results.items() if r == "no_tokens"]

        logger.info(
            f"Token Guardian sweep: "
            f"{len(connected)} connected, {len(refreshed)} refreshed, "
            f"{len(failed)} failed, {len(no_tokens)} unconfigured"
        )

        if refreshed:
            await self._log_activity(
                "system", "token_guardian_refresh",
                f"Proactively refreshed tokens: {', '.join(refreshed)}"
            )
        if failed:
            await self._log_activity(
                "system", "token_guardian_alert",
                f"Token refresh failed — manual re-auth needed: {', '.join(failed)}",
                severity="warning"
            )

    async def _check_platform(self, name: str, adapter, now: datetime) -> str:
        token_row = await self._get_token_row(name)
        if not token_row or not token_row.get("access_token"):
            return "no_tokens"

        status = token_row.get("status", "")
        expiry = token_row.get("token_expiry")

        if expiry:
            if expiry.tzinfo is None:
                expiry = expiry.replace(tzinfo=timezone.utc)

            if expiry < now + self._refresh_window:
                logger.info(f"Token Guardian: {name} expires at {expiry}, refreshing proactively")
                refreshed = await adapter.refresh_token()
                if refreshed:
                    logger.info(f"Token Guardian: {name} token refreshed successfully")
                    return "refreshed"
                else:
                    logger.warning(f"Token Guardian: {name} refresh failed, trying full re-auth")
                    authed = await adapter.authenticate()
                    if authed:
                        return "connected"
                    return await self._mark_needs_reauth(name, adapter.last_error)

        authed = await adapter.authenticate()
        if authed:
            return "connected"

        logger.warning(f"Token Guardian: {name} auth failed, attempting refresh")
        refreshed = await adapter.refresh_token()
        if refreshed:
            logger.info(f"Token Guardian: {name} recovered via refresh")
            return "refreshed"

        return await self._mark_needs_reauth(name, adapter.last_error)

    async def _get_token_row(self, platform: str):
        try:
            async with self.db_pool.acquire() as conn:
                row = await conn.fetchrow(
                    "SELECT platform, status, token_expiry, access_token, refresh_token "
                    "FROM skyeye_platform_tokens WHERE platform = $1",
                    platform
                )
                return dict(row) if row else None
        except Exception:
            return None

    async def _mark_needs_reauth(self, platform: str, error_msg: str = None) -> str:
        msg = (error_msg or "Token expired, manual re-authorization required")[:500]
        try:
            async with self.db_pool.acquire() as conn:
                result = await conn.execute(
                    """
                    UPDATE skyeye_platform_tokens
                    SET status = 'expired', error_message = $2, updated_at = NOW()
                    WHERE platform = $1
                      AND status IS DISTINCT FROM 'expired'
                    """,
                    platform,
                    msg,
                )
                n = int(str(result).split()[-1])
                if n == 0:
                    await conn.execute(
                        """
                        UPDATE skyeye_platform_tokens
                        SET error_message = $2
                        WHERE platform = $1
                          AND status = 'expired'
                          AND COALESCE(error_message, '') IS DISTINCT FROM $2
                        """,
                        platform,
                        msg,
                    )
                    return "still_expired"
                return "needs_reauth"
        except Exception as e:
            logger.error(f"Token Guardian: Failed to mark {platform} as expired: {e}")
            return "still_expired"

    async def get_platform_status(self) -> dict:
        """Return a snapshot of token health for all platforms (used by audit agent)."""
        from app.services.platforms import get_all_adapters
        adapters = get_all_adapters(self.db_pool)
        status = {}
        for name in adapters:
            row = await self._get_token_row(name)
            if row:
                status[name] = {
                    "status": row.get("status"),
                    "token_expiry": row.get("token_expiry"),
                    "has_access_token": bool(row.get("access_token")),
                    "has_refresh_token": bool(row.get("refresh_token")),
                }
            else:
                status[name] = {"status": "no_tokens", "token_expiry": None,
                                "has_access_token": False, "has_refresh_token": False}
        return status

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
