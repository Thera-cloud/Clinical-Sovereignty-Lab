"""
LITTLE NATE — Cloudflare Token Guardian

Background agent that verifies Cloudflare API token health every 30 minutes
and hot-reloads it across all consumers if a roll is performed.

Lifecycle:
    1. Verify worker token via Cloudflare /user/tokens/verify
    2. If ACTIVE → sleep 30 min
    3. If EXPIRED/INVALID → attempt programmatic roll via meta token
       → hot-reload across all CF consumers → log result
    4. If meta token is missing → log warning (manual intervention needed)

Depends on:
    CLOUDFLARE_API_TOKEN  — worker token for Vectorize, Workers AI, D1, etc.
    CLOUDFLARE_META_TOKEN — API Tokens::Edit token for programmatic rolls
    CLOUDFLARE_TOKEN_ID   — UUID of the worker token (for roll API)
    CLOUDFLARE_ACCOUNT_ID — account ID (for Vectorize test)
"""

import asyncio
import logging
import os
from datetime import datetime, timezone
from typing import Optional

import aiohttp

logger = logging.getLogger("nate.cf_token_guardian")

_VERIFY_URL = "https://api.cloudflare.com/client/v4/user/tokens/verify"
_ROLL_URL = "https://api.cloudflare.com/client/v4/user/tokens/{token_id}/value"

CYCLE_SECONDS = 1800  # 30 minutes


class CloudflareTokenGuardian:
    """Verifies and auto-rolls Cloudflare API tokens."""

    def __init__(self, db_pool=None, app_state=None):
        self._db_pool = db_pool
        self._app_state = app_state
        self._running = False
        self._task: Optional[asyncio.Task] = None
        self._consecutive_failures = 0
        self._last_status: str = "unknown"
        self._last_check: Optional[datetime] = None

        self._worker_token = os.getenv("CLOUDFLARE_API_TOKEN", "").strip()
        self._meta_token = os.getenv("CLOUDFLARE_META_TOKEN", "").strip()
        self._token_id = os.getenv("CLOUDFLARE_TOKEN_ID", "").strip()
        self._account_id = os.getenv("CLOUDFLARE_ACCOUNT_ID", "").strip()

    async def start(self):
        if self._task and not self._task.done():
            return
        if not self._worker_token:
            logger.info("CloudflareTokenGuardian: CLOUDFLARE_API_TOKEN not set — disabled")
            return
        self._running = True
        self._task = asyncio.create_task(self._run_loop())
        logger.info("CloudflareTokenGuardian: started (verify every %ds)", CYCLE_SECONDS)

    async def stop(self):
        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("CloudflareTokenGuardian: stopped")

    async def _run_loop(self):
        await asyncio.sleep(60)
        while self._running:
            try:
                await self._check_cycle()
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.error("CloudflareTokenGuardian: cycle failed: %s", e, exc_info=True)
            await asyncio.sleep(CYCLE_SECONDS)

    async def _check_cycle(self):
        self._last_check = datetime.now(timezone.utc)

        status = await self._verify_token(self._worker_token)
        self._last_status = status

        if status == "active":
            self._consecutive_failures = 0
            logger.debug("CloudflareTokenGuardian: worker token ACTIVE")
            return

        logger.warning("CloudflareTokenGuardian: worker token status=%s — attempting recovery", status)
        self._consecutive_failures += 1

        if not self._meta_token or not self._token_id:
            logger.error(
                "CloudflareTokenGuardian: cannot auto-roll — CLOUDFLARE_META_TOKEN or "
                "CLOUDFLARE_TOKEN_ID not configured. Manual intervention required."
            )
            await self._log_activity(
                "cf_token_guardian_alert",
                f"Worker token {status} — no meta token for auto-roll. Manual intervention required.",
            )
            return

        new_token = await self._roll_token()
        if not new_token:
            logger.error("CloudflareTokenGuardian: token roll FAILED")
            await self._log_activity(
                "cf_token_guardian_alert",
                f"Worker token {status} — roll via meta token FAILED after {self._consecutive_failures} attempts.",
            )
            return

        verify_status = await self._verify_token(new_token)
        if verify_status != "active":
            logger.error("CloudflareTokenGuardian: rolled token is NOT active (status=%s)", verify_status)
            await self._log_activity(
                "cf_token_guardian_alert",
                f"Rolled token verification failed — status={verify_status}.",
            )
            return

        self._worker_token = new_token
        self._last_status = "active"
        self._consecutive_failures = 0
        self._hot_reload_all(new_token)

        logger.info("CloudflareTokenGuardian: token rolled and hot-reloaded across all consumers")
        await self._log_activity(
            "cf_token_guardian_rolled",
            "Worker token rolled and hot-reloaded. All CF consumers updated.",
        )

    async def _verify_token(self, token: str) -> str:
        """Verify a token via Cloudflare API. Returns 'active', 'expired', or 'error'."""
        try:
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=10)) as session:
                async with session.get(
                    _VERIFY_URL,
                    headers={"Authorization": f"Bearer {token}"},
                ) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        return data.get("result", {}).get("status", "unknown")
                    elif resp.status == 401:
                        return "expired"
                    else:
                        body = await resp.text()
                        logger.warning("CloudflareTokenGuardian: verify returned %d: %s", resp.status, body[:200])
                        return "error"
        except Exception as e:
            logger.warning("CloudflareTokenGuardian: verify request failed: %s", e)
            return "error"

    async def _roll_token(self) -> Optional[str]:
        """Roll the worker token using the meta token. Returns the new token value or None."""
        url = _ROLL_URL.format(token_id=self._token_id)
        try:
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=15)) as session:
                async with session.put(
                    url,
                    headers={
                        "Authorization": f"Bearer {self._meta_token}",
                        "Content-Type": "application/json",
                    },
                    json={},
                ) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        new_value = data.get("result")
                        if isinstance(new_value, str) and len(new_value) > 10:
                            return new_value
                        logger.warning("CloudflareTokenGuardian: roll returned unexpected result: %s", type(new_value))
                        return None
                    body = await resp.text()
                    logger.warning("CloudflareTokenGuardian: roll returned %d: %s", resp.status, body[:200])
                    return None
        except Exception as e:
            logger.error("CloudflareTokenGuardian: roll request failed: %s", e)
            return None

    def _hot_reload_all(self, new_token: str):
        """Push new token into all Cloudflare service modules."""
        reload_funcs = []
        try:
            from app.services.vectorize_service import reload_cf_token as r1
            reload_funcs.append(("vectorize_service", r1))
        except ImportError:
            pass
        try:
            from app.services.d1_query_service import reload_cf_token as r2
            reload_funcs.append(("d1_query_service", r2))
        except ImportError:
            pass
        try:
            from app.services.d1_sync_agent import reload_cf_token as r3
            reload_funcs.append(("d1_sync_agent", r3))
        except ImportError:
            pass
        try:
            from app.services.r2_analytics_service import reload_cf_token as r4
            reload_funcs.append(("r2_analytics_service", r4))
        except ImportError:
            pass
        try:
            from app.services.iceberg_cdc_agent import reload_cf_token as r5
            reload_funcs.append(("iceberg_cdc_agent", r5))
        except ImportError:
            pass

        for name, fn in reload_funcs:
            try:
                fn(new_token)
            except Exception as e:
                logger.warning("CloudflareTokenGuardian: reload failed for %s: %s", name, e)

        logger.info("CloudflareTokenGuardian: hot-reloaded %d consumers", len(reload_funcs))

    async def _log_activity(self, activity_type: str, detail: str):
        if not self._db_pool:
            return
        try:
            async with self._db_pool.acquire() as conn:
                await conn.execute(
                    "INSERT INTO skyeye_activity (platform, type, content, created_at) "
                    "VALUES ($1, $2, $3, $4)",
                    "system", activity_type, detail, datetime.now(timezone.utc),
                )
        except Exception as e:
            logger.warning("CloudflareTokenGuardian: activity log failed: %s", e)

    def health_status(self) -> dict:
        """Return current guardian status for health checks."""
        return {
            "last_status": self._last_status,
            "last_check": self._last_check.isoformat() if self._last_check else None,
            "consecutive_failures": self._consecutive_failures,
            "meta_token_configured": bool(self._meta_token),
            "token_id_configured": bool(self._token_id),
        }
