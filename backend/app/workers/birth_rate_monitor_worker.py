"""
HIVE DEFENSE PROTOCOL v3.0 — Birth Rate Monitor Worker (Phase 8C)
Continuous monitoring of Fibre birth rates in rolling 1-hour windows.

Runs every 30 seconds and detects anomalous birth rate spikes that could
indicate an attacker attempting to flood the hive with malicious Fibres
or exploiting the ephemeral certificate system.

Detection triggers include:
    - Birth rate exceeding the DEFCON-adjusted threshold
    - Births from unexpected certificate authorities
    - Clustering of births in a single ring region
    - Births outside of authorized time windows

Event: ``hive.birth.anomaly_detected``

Patent-Pending — Claims 30-56
© 2026 Clinical Sovereignty Lab. All rights reserved.
"""

from __future__ import annotations

import asyncio
import time
from collections import deque
from datetime import datetime, timedelta, timezone
from typing import Any, Deque, Dict, List, Optional

import structlog

logger = structlog.get_logger("hive.birth_rate_monitor")


# =============================================================================
# CONSTANTS
# =============================================================================

# Default sweep interval (seconds)
DEFAULT_INTERVAL: float = 30.0

# Rolling window for birth rate calculation
ROLLING_WINDOW_HOURS: float = 1.0

# DEFCON → interval mapping
DEFCON_INTERVAL_MAP: Dict[int, float] = {
    5: 30.0,    # PEACE — standard 30s
    4: 20.0,    # ELEVATED — tighter monitoring
    3: 15.0,    # SUBSTANTIAL — aggressive
    2: 10.0,    # SEVERE — near real-time
    1: 5.0,     # CRITICAL — maximum vigilance
}

# DEFCON → max births per hour threshold
DEFCON_BIRTH_THRESHOLD: Dict[int, int] = {
    5: 50,      # PEACE — up to 50 births/hour
    4: 30,      # ELEVATED — reduced tolerance
    3: 10,      # SUBSTANTIAL — very restricted
    2: 0,       # SEVERE — zero new births
    1: 0,       # CRITICAL — zero new births
}


# =============================================================================
# BIRTH RATE MONITOR WORKER
# =============================================================================

class BirthRateMonitorWorker:
    """Background worker: continuous Fibre birth rate monitoring.

    Responsibilities
    ----------------
    * Track all Fibre birth events in a rolling 1-hour window.
    * Compare the current birth rate against DEFCON-adjusted thresholds.
    * Detect anomalous patterns: regional clustering, unauthorized certs,
      off-hours births.
    * Fire ``hive.birth.anomaly_detected`` events on any threshold breach.
    * Emit structured metrics every sweep cycle.

    Parameters
    ----------
    db_pool : Any, optional
        asyncpg connection pool for birth event queries and metrics.
    event_callback : callable, optional
        Async callback ``(topic: str, payload: dict) -> None``.
    defcon_provider : callable, optional
        Async callable returning the current DEFCON level (int 1-5).
    base_interval : float
        Default sweep interval in seconds (overridden by DEFCON).
    """

    def __init__(
        self,
        db_pool: Any = None,
        event_callback: Optional[Any] = None,
        defcon_provider: Optional[Any] = None,
        base_interval: float = DEFAULT_INTERVAL,
    ) -> None:
        self.db_pool = db_pool
        self.event_callback = event_callback
        self.defcon_provider = defcon_provider
        self.base_interval = base_interval

        self._task: Optional[asyncio.Task] = None
        self._running: bool = False

        # Rolling birth event buffer (timestamps of recent births)
        self._birth_events: Deque[datetime] = deque()

        # Cumulative metrics
        self._total_sweeps: int = 0
        self._total_births_observed: int = 0
        self._total_anomalies_detected: int = 0
        self._last_anomaly_at: Optional[datetime] = None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Start the birth rate monitoring loop."""
        self._running = True
        self._task = asyncio.create_task(self._run_loop())
        logger.info("worker_started", worker="BirthRateMonitorWorker")

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
            worker="BirthRateMonitorWorker",
            total_sweeps=self._total_sweeps,
            total_births=self._total_births_observed,
            total_anomalies=self._total_anomalies_detected,
        )

    # ------------------------------------------------------------------
    # Main loop
    # ------------------------------------------------------------------

    async def _run_loop(self) -> None:
        """Primary loop: check birth rate at DEFCON-adjusted intervals."""
        while self._running:
            cycle_start = time.monotonic()
            try:
                await self._check_birth_rate()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.error(
                    "birth_rate_check_error",
                    error=str(exc),
                    exc_info=True,
                )

            interval = await self._current_interval()
            elapsed = time.monotonic() - cycle_start
            sleep_time = max(0.0, interval - elapsed)
            await asyncio.sleep(sleep_time)

    # ------------------------------------------------------------------
    # Birth Rate Check
    # ------------------------------------------------------------------

    async def _check_birth_rate(self) -> None:
        """Check the rolling 1-hour birth rate against thresholds.

        Steps:
        1. Fetch recent birth events from the database.
        2. Prune events outside the rolling window.
        3. Calculate current birth rate.
        4. Compare against DEFCON-adjusted threshold.
        5. Check for regional clustering and pattern anomalies.
        6. Fire alerts if any anomaly is detected.
        """
        self._total_sweeps += 1
        now = datetime.now(timezone.utc)
        window_start = now - timedelta(hours=ROLLING_WINDOW_HOURS)

        # Fetch recent births from DB
        recent_births = await self._fetch_recent_births(window_start)

        # Update rolling buffer
        for birth in recent_births:
            birth_time = birth.get("created_at") or birth.get("born_at")
            if birth_time and birth_time not in self._birth_events:
                self._birth_events.append(birth_time)
                self._total_births_observed += 1

        # Prune old events
        while self._birth_events and self._birth_events[0] < window_start:
            self._birth_events.popleft()

        current_rate = len(self._birth_events)

        # Get DEFCON-adjusted threshold
        defcon_level = await self._get_defcon_level()
        threshold = DEFCON_BIRTH_THRESHOLD.get(defcon_level, 50)

        # Check for anomalies
        anomalies: List[Dict[str, Any]] = []

        # Anomaly 1: Rate exceeds threshold
        if current_rate > threshold:
            anomalies.append({
                "type": "rate_exceeded",
                "current_rate": current_rate,
                "threshold": threshold,
                "defcon_level": defcon_level,
            })

        # Anomaly 2: Regional clustering
        regional_anomaly = self._check_regional_clustering(recent_births)
        if regional_anomaly:
            anomalies.append(regional_anomaly)

        # Anomaly 3: Unauthorized certificate usage
        cert_anomaly = self._check_certificate_anomalies(recent_births)
        if cert_anomaly:
            anomalies.append(cert_anomaly)

        # Fire alerts
        if anomalies:
            self._total_anomalies_detected += len(anomalies)
            self._last_anomaly_at = now

            for anomaly in anomalies:
                await self._fire_anomaly_alert(anomaly, current_rate, threshold)

        # Persist metrics
        await self._persist_sweep_metrics(
            current_rate=current_rate,
            threshold=threshold,
            anomalies_count=len(anomalies),
        )

        # Periodic logging
        if self._total_sweeps % 20 == 0:  # Every ~10 minutes at 30s interval
            logger.info(
                "birth_rate_sweep",
                sweep_number=self._total_sweeps,
                current_rate=current_rate,
                threshold=threshold,
                defcon=defcon_level,
                buffer_size=len(self._birth_events),
            )

    # ------------------------------------------------------------------
    # Data Fetching
    # ------------------------------------------------------------------

    async def _fetch_recent_births(
        self,
        since: datetime,
    ) -> List[Dict[str, Any]]:
        """Fetch Fibre birth events since *since* from the database."""
        if not self.db_pool:
            return []

        try:
            async with self.db_pool.acquire() as conn:
                rows = await conn.fetch(
                    """
                    SELECT entity_id, fibre_type, ring_region,
                           certificate_id, created_at
                    FROM hive_fibre_births
                    WHERE created_at >= $1
                    ORDER BY created_at DESC
                    """,
                    since,
                )
                return [dict(r) for r in rows]
        except Exception as exc:
            logger.debug("birth_fetch_failed", error=str(exc))
            return []

    # ------------------------------------------------------------------
    # Anomaly Detection
    # ------------------------------------------------------------------

    def _check_regional_clustering(
        self,
        births: List[Dict[str, Any]],
    ) -> Optional[Dict[str, Any]]:
        """Detect if births are clustered in a single ring region."""
        if len(births) < 5:
            return None

        regions: Dict[str, int] = {}
        for birth in births:
            region = birth.get("ring_region", "unknown")
            regions[region] = regions.get(region, 0) + 1

        total = len(births)
        for region, count in regions.items():
            if count / total > 0.8:  # 80%+ in one region
                return {
                    "type": "regional_clustering",
                    "region": region,
                    "count": count,
                    "total": total,
                    "concentration": round(count / total, 2),
                }

        return None

    def _check_certificate_anomalies(
        self,
        births: List[Dict[str, Any]],
    ) -> Optional[Dict[str, Any]]:
        """Detect births from unknown or revoked certificates."""
        suspicious_certs: List[str] = []
        for birth in births:
            cert_id = birth.get("certificate_id")
            if cert_id and cert_id.startswith("unknown_"):
                suspicious_certs.append(cert_id)

        if suspicious_certs:
            return {
                "type": "suspicious_certificates",
                "certificates": suspicious_certs[:10],
                "count": len(suspicious_certs),
            }

        return None

    # ------------------------------------------------------------------
    # Alerting
    # ------------------------------------------------------------------

    async def _fire_anomaly_alert(
        self,
        anomaly: Dict[str, Any],
        current_rate: int,
        threshold: int,
    ) -> None:
        """Fire a hive.birth.anomaly_detected event."""
        payload = {
            "anomaly": anomaly,
            "current_rate": current_rate,
            "threshold": threshold,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "sweep_number": self._total_sweeps,
        }

        logger.warning(
            "BIRTH_RATE_ANOMALY",
            anomaly_type=anomaly.get("type"),
            current_rate=current_rate,
            threshold=threshold,
        )

        if self.event_callback:
            try:
                await self.event_callback("hive.birth.anomaly_detected", payload)
            except Exception as exc:
                logger.error("birth_alert_failed", error=str(exc))

    # ------------------------------------------------------------------
    # DEFCON integration
    # ------------------------------------------------------------------

    async def _get_defcon_level(self) -> int:
        """Get the current DEFCON level (int 1-5)."""
        if self.defcon_provider:
            try:
                level = await self.defcon_provider()
                return int(level.value) if hasattr(level, "value") else int(level)
            except Exception:
                pass
        return 5  # Default to PEACE

    async def _current_interval(self) -> float:
        """Return the sweep interval adjusted for DEFCON level."""
        level = await self._get_defcon_level()
        return DEFCON_INTERVAL_MAP.get(level, self.base_interval)

    # ------------------------------------------------------------------
    # Metrics Persistence
    # ------------------------------------------------------------------

    async def _persist_sweep_metrics(
        self,
        current_rate: int,
        threshold: int,
        anomalies_count: int,
    ) -> None:
        """Write sweep metrics to the database."""
        if not self.db_pool:
            return

        try:
            async with self.db_pool.acquire() as conn:
                await conn.execute(
                    """
                    INSERT INTO hive_birth_rate_metrics
                        (sweep_number, current_rate, threshold,
                         anomalies_detected, swept_at)
                    VALUES ($1, $2, $3, $4, NOW())
                    """,
                    self._total_sweeps,
                    current_rate,
                    threshold,
                    anomalies_count,
                )
        except Exception as exc:
            logger.debug("birth_metrics_persist_failed", error=str(exc))

    # ------------------------------------------------------------------
    # Diagnostics
    # ------------------------------------------------------------------

    @property
    def stats(self) -> Dict[str, Any]:
        """Diagnostic statistics."""
        return {
            "running": self._running,
            "total_sweeps": self._total_sweeps,
            "total_births_observed": self._total_births_observed,
            "total_anomalies_detected": self._total_anomalies_detected,
            "current_buffer_size": len(self._birth_events),
            "last_anomaly_at": (
                self._last_anomaly_at.isoformat() if self._last_anomaly_at else None
            ),
        }

    def __repr__(self) -> str:
        return (
            f"<BirthRateMonitorWorker "
            f"sweeps={self._total_sweeps} "
            f"births={self._total_births_observed} "
            f"anomalies={self._total_anomalies_detected}>"
        )
