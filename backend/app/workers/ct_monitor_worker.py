"""
HIVE DEFENSE PROTOCOL v3.0 — Certificate Transparency Monitor Worker (Phase 8C)
Background scanning of CT logs for unauthorized certificate issuance.

Runs every 15 minutes, querying public Certificate Transparency logs
for any certificates issued against Sovereign Sanctuary domains.  If
an unauthorized certificate is detected (issuer not in the approved set),
an immediate alert is fired.

This worker drives the :class:`CTMonitor` service on a recurring schedule.

Patent-Pending — Claims 30-56
© 2026 Clinical Sovereignty Lab. All rights reserved.
"""

from __future__ import annotations

import asyncio
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set

import structlog

logger = structlog.get_logger("hive.ct_monitor_worker")


# =============================================================================
# CONSTANTS
# =============================================================================

# Default scan interval (seconds) — every 15 minutes
DEFAULT_INTERVAL: float = 900.0  # 15 minutes

# DEFCON → interval mapping
DEFCON_INTERVAL_MAP: Dict[int, float] = {
    5: 900.0,    # PEACE — 15 min
    4: 600.0,    # ELEVATED — 10 min
    3: 300.0,    # SUBSTANTIAL — 5 min
    2: 120.0,    # SEVERE — 2 min
    1: 60.0,     # CRITICAL — 1 min
}

# Domains to monitor
MONITORED_DOMAINS: List[str] = [
    "sovereignsanctuary.net",
    "app.sovereignsanctuary.net",
    "coach.sovereignsanctuary.net",
    "command.sovereignsanctuary.net",
    "api.sovereignsanctuary.net",
]

# Authorized certificate issuers
AUTHORIZED_ISSUERS: Set[str] = {
    "Let's Encrypt",
    "R3",                           # Let's Encrypt intermediate
    "E1",                           # Let's Encrypt ECDSA intermediate
    "ISRG Root X1",                 # Let's Encrypt root
    "DigiCert Inc",
    "DigiCert Global Root G2",
}


# =============================================================================
# CT MONITOR WORKER
# =============================================================================

class CTMonitorWorker:
    """Background worker: periodic Certificate Transparency log scanning.

    Responsibilities
    ----------------
    * Drive the ``CTMonitor`` service at DEFCON-adjusted intervals.
    * Scan CT logs for each monitored domain.
    * Aggregate and deduplicate alerts across domains.
    * Emit structured metrics after each scan cycle.

    Parameters
    ----------
    ct_monitor : Any
        Reference to the :class:`CTMonitor` service.
    db_pool : Any, optional
        asyncpg connection pool for metrics persistence.
    defcon_provider : callable, optional
        Async callable returning the current DEFCON level (int 1-5).
    base_interval : float
        Default scan interval in seconds.
    monitored_domains : list[str], optional
        Override the default list of monitored domains.
    authorized_issuers : set[str], optional
        Override the default set of authorized issuers.
    """

    def __init__(
        self,
        ct_monitor: Any,
        db_pool: Any = None,
        defcon_provider: Optional[Any] = None,
        base_interval: float = DEFAULT_INTERVAL,
        monitored_domains: Optional[List[str]] = None,
        authorized_issuers: Optional[Set[str]] = None,
    ) -> None:
        self.ct_monitor = ct_monitor
        self.db_pool = db_pool
        self.defcon_provider = defcon_provider
        self.base_interval = base_interval
        self.monitored_domains = monitored_domains or list(MONITORED_DOMAINS)
        self.authorized_issuers = authorized_issuers or set(AUTHORIZED_ISSUERS)

        self._task: Optional[asyncio.Task] = None
        self._running: bool = False

        # Cumulative metrics
        self._total_scans: int = 0
        self._total_certs_found: int = 0
        self._total_unauthorized: int = 0
        self._last_scan_at: Optional[datetime] = None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Start the CT monitoring loop."""
        self._running = True
        self._task = asyncio.create_task(self._run_loop())
        logger.info(
            "worker_started",
            worker="CTMonitorWorker",
            domains=len(self.monitored_domains),
            issuers=len(self.authorized_issuers),
        )

    async def stop(self) -> None:
        """Gracefully stop the monitoring loop."""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info(
            "worker_stopped",
            worker="CTMonitorWorker",
            total_scans=self._total_scans,
            total_certs=self._total_certs_found,
            total_unauthorized=self._total_unauthorized,
        )

    # ------------------------------------------------------------------
    # Main Loop
    # ------------------------------------------------------------------

    async def _run_loop(self) -> None:
        """Primary loop: scan CT logs at DEFCON-adjusted intervals."""
        while self._running:
            cycle_start = time.monotonic()
            try:
                await self._scan_all_domains()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.error(
                    "ct_scan_error",
                    error=str(exc),
                    exc_info=True,
                )

            interval = await self._current_interval()
            elapsed = time.monotonic() - cycle_start
            sleep_time = max(0.0, interval - elapsed)
            await asyncio.sleep(sleep_time)

    # ------------------------------------------------------------------
    # Scan Logic
    # ------------------------------------------------------------------

    async def _scan_all_domains(self) -> None:
        """Scan CT logs for all monitored domains.

        For each domain:
        1. Call ``ct_monitor.alert_on_unauthorized(domain, issuers)``
        2. Aggregate results across all domains.
        3. Persist scan metrics.
        """
        self._total_scans += 1
        self._last_scan_at = datetime.now(timezone.utc)

        total_certs = 0
        total_alerts = 0

        for domain in self.monitored_domains:
            try:
                alerts = await self.ct_monitor.alert_on_unauthorized(
                    domain,
                    expected_issuers=self.authorized_issuers,
                )

                # Count results from the monitor's stats
                if hasattr(self.ct_monitor, "stats"):
                    monitor_stats = self.ct_monitor.stats
                    total_certs = monitor_stats.get("total_certs_found", 0)

                total_alerts += len(alerts)

                if alerts:
                    logger.critical(
                        "CT_UNAUTHORIZED_CERTS_FOUND",
                        domain=domain,
                        alert_count=len(alerts),
                    )

            except Exception as exc:
                logger.warning(
                    "ct_domain_scan_failed",
                    domain=domain,
                    error=str(exc),
                )

        self._total_certs_found = total_certs
        self._total_unauthorized += total_alerts

        # Persist scan metrics
        await self._persist_scan_metrics(total_certs, total_alerts)

        # Periodic status log
        if self._total_scans % 4 == 0:  # Every ~1 hour at 15min interval
            logger.info(
                "ct_scan_cycle",
                scan_number=self._total_scans,
                domains_scanned=len(self.monitored_domains),
                total_certs=total_certs,
                unauthorized=total_alerts,
            )

    # ------------------------------------------------------------------
    # DEFCON-aware interval
    # ------------------------------------------------------------------

    async def _current_interval(self) -> float:
        """Return the scan interval adjusted for DEFCON level."""
        if self.defcon_provider:
            try:
                level = await self.defcon_provider()
                level_int = int(level.value) if hasattr(level, "value") else int(level)
                return DEFCON_INTERVAL_MAP.get(level_int, self.base_interval)
            except Exception:
                pass
        return self.base_interval

    # ------------------------------------------------------------------
    # Metrics Persistence
    # ------------------------------------------------------------------

    async def _persist_scan_metrics(
        self,
        certs_found: int,
        alerts_generated: int,
    ) -> None:
        """Write scan metrics to the database."""
        if not self.db_pool:
            return

        try:
            async with self.db_pool.acquire() as conn:
                await conn.execute(
                    """
                    INSERT INTO hive_ct_scan_metrics
                        (scan_number, domains_scanned, certs_found,
                         unauthorized_found, scanned_at)
                    VALUES ($1, $2, $3, $4, NOW())
                    """,
                    self._total_scans,
                    len(self.monitored_domains),
                    certs_found,
                    alerts_generated,
                )
        except Exception as exc:
            logger.debug("ct_metrics_persist_failed", error=str(exc))

    # ------------------------------------------------------------------
    # Diagnostics
    # ------------------------------------------------------------------

    @property
    def stats(self) -> Dict[str, Any]:
        """Diagnostic statistics."""
        return {
            "running": self._running,
            "total_scans": self._total_scans,
            "total_certs_found": self._total_certs_found,
            "total_unauthorized": self._total_unauthorized,
            "monitored_domains": len(self.monitored_domains),
            "authorized_issuers": len(self.authorized_issuers),
            "last_scan_at": (
                self._last_scan_at.isoformat() if self._last_scan_at else None
            ),
        }

    def __repr__(self) -> str:
        return (
            f"<CTMonitorWorker "
            f"scans={self._total_scans} "
            f"certs={self._total_certs_found} "
            f"unauthorized={self._total_unauthorized}>"
        )
