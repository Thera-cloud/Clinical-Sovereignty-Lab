"""
SOVEREIGN SWARM — Vault Integrity Worker
Periodic integrity checks on Legacy Vault data.
"""

from __future__ import annotations

import asyncio
from typing import Any

import structlog

logger = structlog.get_logger(__name__)


class VaultIntegrityWorker:
    """Background worker: vault data integrity verification."""

    def __init__(
        self,
        vault: Any,
        db_pool: Any = None,
        interval: int = 86400,  # Daily
    ) -> None:
        self.vault = vault
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
                await self._check_all_vaults()
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.error("vault_integrity_error", error=str(e))
            await asyncio.sleep(self.interval)

    async def _check_all_vaults(self) -> None:
        """Run integrity checks on all user vaults."""
        if not self.db_pool:
            return
        try:
            async with self.db_pool.acquire() as conn:
                users = await conn.fetch(
                    """SELECT DISTINCT user_id FROM me2me_consent_records
                    WHERE status = 'active'"""
                )
                issues_found = 0
                for row in users:
                    result = await self.vault.check_integrity(row["user_id"])
                    if result.get("issues"):
                        issues_found += 1
                        logger.warning(
                            "vault_integrity_issue",
                            user_id=row["user_id"],
                            issues=result["issues"],
                        )
                if issues_found:
                    logger.warning("vault_integrity_complete", issues_found=issues_found)
                else:
                    logger.info("vault_integrity_complete", issues_found=0, users_checked=len(users))
        except Exception as e:
            logger.warning("vault_integrity_query_failed", error=str(e))
