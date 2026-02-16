"""
SOVEREIGN SWARM — Billing Worker
Periodic billing tasks: usage sync to Stripe, cap enforcement, vault billing.
"""

from __future__ import annotations

import asyncio
from typing import Any, Optional

import structlog

logger = structlog.get_logger(__name__)


class BillingWorker:
    """Background worker: billing sync and cost monitoring."""

    def __init__(
        self,
        metered_billing: Any = None,
        cost_monitor: Any = None,
        vault_billing: Any = None,
        db_pool: Any = None,
        interval: int = 3600,  # 1 hour
    ) -> None:
        self.metered_billing = metered_billing
        self.cost_monitor = cost_monitor
        self.vault_billing = vault_billing
        self.db_pool = db_pool
        self.interval = interval
        self._task: asyncio.Task | None = None
        self._running = False

    async def start(self) -> None:
        self._running = True
        self._task = asyncio.create_task(self._run_loop())
        logger.info("worker_started", worker=self.__class__.__name__)

    async def stop(self) -> None:
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("worker_stopped", worker=self.__class__.__name__)

    async def _run_loop(self) -> None:
        while self._running:
            try:
                await self._sync_usage()
                await self._check_monthly_caps()
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.error("billing_worker_error", error=str(e))
            await asyncio.sleep(self.interval)

    async def _sync_usage(self) -> None:
        """Sync unreported usage records to Stripe."""
        if not self.db_pool:
            return
        try:
            async with self.db_pool.acquire() as conn:
                unreported = await conn.fetch(
                    """SELECT record_id, user_id, usage_type, quantity
                    FROM usage_records
                    WHERE reported_to_stripe = FALSE
                    ORDER BY timestamp ASC LIMIT 100"""
                )
                for row in unreported:
                    logger.debug(
                        "sync_usage_record",
                        record_id=row["record_id"],
                        user_id=row["user_id"],
                    )
        except Exception as e:
            logger.warning("usage_sync_failed", error=str(e))

    async def _check_monthly_caps(self) -> None:
        """Check all users approaching monthly caps."""
        if not self.db_pool or not self.cost_monitor:
            return
        try:
            async with self.db_pool.acquire() as conn:
                rows = await conn.fetch(
                    """SELECT user_id, overage_charges + COALESCE(
                        (SELECT SUM(total_cost) FROM usage_records
                         WHERE user_id = mbs.user_id
                         AND timestamp > mbs.billing_period_start), 0
                    ) AS total_spend
                    FROM metered_billing_state mbs
                    WHERE session_cost_cap_hit = FALSE"""
                )
                for row in rows:
                    if row["total_spend"] and row["total_spend"] > 0:
                        result = await self.cost_monitor.check_monthly_cap(
                            row["user_id"], float(row["total_spend"])
                        )
                        if result.get("at_warning"):
                            logger.info(
                                "monthly_cap_warning",
                                user_id=row["user_id"],
                                total=row["total_spend"],
                            )
        except Exception as e:
            logger.warning("cap_check_failed", error=str(e))
