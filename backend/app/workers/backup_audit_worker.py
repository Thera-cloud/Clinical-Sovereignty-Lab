"""
HIVE DEFENSE PROTOCOL — Backup Audit Worker (Phase 8B)
Daily backup integrity verification and freshness monitoring.

Runs once per day (default 24h interval), iterates over all known
backups, verifies SHA-256 integrity, checks freshness against RPO
requirements, and alerts on stale or corrupted backups.

Patent-Pending — Claims 30-56
© 2026 Clinical Sovereignty Lab. All rights reserved.
"""

from __future__ import annotations

import asyncio
import json
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

import structlog

logger = structlog.get_logger("hive.backup_audit")


# =============================================================================
# CONSTANTS
# =============================================================================

# Default audit interval (seconds) — once per day.
DEFAULT_INTERVAL: float = 86400.0  # 24 hours

# Maximum backup age before alerting (hours).
FRESHNESS_THRESHOLD_HOURS: int = 24

# Minimum number of backup copies required.
MIN_BACKUP_COPIES: int = 2

# Alert severity levels.
SEVERITY_CRITICAL: str = "critical"
SEVERITY_HIGH: str = "high"
SEVERITY_MEDIUM: str = "medium"
SEVERITY_LOW: str = "low"


# =============================================================================
# BACKUP AUDIT WORKER
# =============================================================================

class BackupAuditWorker:
    """Background worker: daily backup integrity and freshness verification.

    Responsibilities
    ----------------
    * Iterate over all backup records in the ``backup_metadata`` table.
    * Verify SHA-256 integrity of each accessible backup file.
    * Check backup freshness against the RPO threshold.
    * Ensure the minimum number of backup copies exists.
    * Generate an audit report and persist it to the database.
    * Alert on stale, corrupted, or missing backups.

    Parameters
    ----------
    backup_manager : Any
        Reference to :class:`BackupEncryptionManager`.
    db_pool : Any, optional
        asyncpg connection pool.
    forensic_logger : Any, optional
        :class:`ForensicLogger` for evidence-chain logging.
    notification_service : Any, optional
        Service for sending alerts (email, Slack, etc.).
    base_interval : float
        Audit interval in seconds.
    """

    def __init__(
        self,
        backup_manager: Any,
        db_pool: Any = None,
        forensic_logger: Any = None,
        notification_service: Any = None,
        base_interval: float = DEFAULT_INTERVAL,
    ) -> None:
        self.backup_manager = backup_manager
        self.db_pool = db_pool
        self.forensic_logger = forensic_logger
        self.notification_service = notification_service
        self.base_interval = base_interval

        self._task: Optional[asyncio.Task] = None
        self._running: bool = False

        # Last audit result
        self._last_audit: Optional[Dict[str, Any]] = None
        self._last_audit_at: Optional[float] = None

        # Cumulative metrics
        self._total_audits: int = 0
        self._total_backups_verified: int = 0
        self._total_integrity_failures: int = 0
        self._total_freshness_alerts: int = 0

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Start the backup audit loop."""
        self._running = True
        self._task = asyncio.create_task(self._run_loop())
        logger.info("worker_started", worker="BackupAuditWorker")

    async def stop(self) -> None:
        """Gracefully stop the audit loop."""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info(
            "worker_stopped",
            worker="BackupAuditWorker",
            total_audits=self._total_audits,
            total_verified=self._total_backups_verified,
            total_failures=self._total_integrity_failures,
            total_freshness_alerts=self._total_freshness_alerts,
        )

    # ------------------------------------------------------------------
    # Main loop
    # ------------------------------------------------------------------

    async def _run_loop(self) -> None:
        """Primary loop: run audit at the configured interval.

        The first audit runs immediately on startup, then repeats
        at ``base_interval`` intervals.
        """
        # Run first audit immediately
        try:
            await self._run_audit()
        except Exception as exc:
            logger.error("initial_backup_audit_error", error=str(exc), exc_info=True)

        while self._running:
            cycle_start = time.monotonic()
            try:
                await asyncio.sleep(self.base_interval)
                if not self._running:
                    break
                await self._run_audit()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.error(
                    "backup_audit_error",
                    error=str(exc),
                    exc_info=True,
                )

    # ------------------------------------------------------------------
    # Audit execution
    # ------------------------------------------------------------------

    async def _run_audit(self) -> Dict[str, Any]:
        """Execute a complete backup audit cycle.

        Steps:
        1. Retrieve all known backup records.
        2. Verify integrity of each backup.
        3. Check overall freshness (most recent backup age).
        4. Verify minimum copy count.
        5. Generate and persist the audit report.
        6. Alert on any failures.
        """
        self._total_audits += 1
        now = datetime.now(tz=timezone.utc)
        audit_start = time.monotonic()

        logger.info("backup_audit_started", audit_number=self._total_audits)

        # Collect all backup records
        backups = await self._fetch_backup_records()
        alerts: List[Dict[str, Any]] = []
        integrity_results: List[Dict[str, Any]] = []

        # --- 1. Integrity verification ---
        for backup in backups:
            path = backup.get("backup_path")
            if not path:
                continue

            try:
                result = await self.backup_manager.verify_backup_integrity(path)
                integrity_results.append(result)
                self._total_backups_verified += 1

                if not result.get("valid", True):
                    self._total_integrity_failures += 1
                    alerts.append({
                        "type": "integrity_failure",
                        "severity": SEVERITY_CRITICAL,
                        "backup_path": path,
                        "detail": (
                            f"Backup integrity check failed: "
                            f"expected={result.get('expected_hash', 'N/A')[:16]}, "
                            f"computed={result.get('computed_hash', 'N/A')[:16]}"
                        ),
                    })
            except Exception as exc:
                alerts.append({
                    "type": "verification_error",
                    "severity": SEVERITY_HIGH,
                    "backup_path": path,
                    "detail": f"Could not verify backup: {exc}",
                })

        # --- 2. Freshness check ---
        freshness = await self._check_freshness()
        if not freshness.get("fresh", True):
            self._total_freshness_alerts += 1
            alerts.append({
                "type": "stale_backup",
                "severity": SEVERITY_HIGH,
                "detail": (
                    f"Most recent backup is {freshness.get('age_hours', '?')}h old "
                    f"(threshold: {FRESHNESS_THRESHOLD_HOURS}h)"
                ),
                "latest_backup_at": freshness.get("latest_backup_at"),
            })

        # --- 3. Minimum copy count ---
        if len(backups) < MIN_BACKUP_COPIES:
            alerts.append({
                "type": "insufficient_copies",
                "severity": SEVERITY_MEDIUM,
                "detail": (
                    f"Only {len(backups)} backup(s) found "
                    f"(minimum required: {MIN_BACKUP_COPIES})"
                ),
            })

        # --- 4. Generate report ---
        elapsed = time.monotonic() - audit_start
        report = {
            "audit_number": self._total_audits,
            "timestamp": now.isoformat(),
            "duration_seconds": round(elapsed, 2),
            "backups_found": len(backups),
            "backups_verified": len(integrity_results),
            "integrity_pass": sum(1 for r in integrity_results if r.get("valid")),
            "integrity_fail": sum(1 for r in integrity_results if not r.get("valid")),
            "freshness": freshness,
            "alerts": alerts,
            "alert_count": len(alerts),
            "status": "healthy" if not alerts else "degraded",
        }

        self._last_audit = report
        self._last_audit_at = time.time()

        # --- 5. Persist report ---
        await self._persist_audit_report(report)

        # --- 6. Send alerts ---
        if alerts:
            await self._send_alerts(alerts)

        # Forensic evidence for non-healthy audits
        if alerts and self.forensic_logger:
            try:
                await self.forensic_logger.log_event(
                    event_type="hive.backup.audit_alert",
                    evidence={
                        "audit_number": self._total_audits,
                        "alert_count": len(alerts),
                        "alerts": alerts,
                    },
                )
            except Exception as exc:
                logger.debug("forensic_log_failed", error=str(exc))

        log_fn = logger.warning if alerts else logger.info
        log_fn(
            "backup_audit_complete",
            audit_number=self._total_audits,
            backups=len(backups),
            verified=len(integrity_results),
            alerts=len(alerts),
            duration_s=round(elapsed, 2),
        )

        return report

    # ------------------------------------------------------------------
    # Data access
    # ------------------------------------------------------------------

    async def _fetch_backup_records(self) -> List[Dict[str, Any]]:
        """Retrieve all known backup records from the database."""
        if not self.db_pool:
            return []

        try:
            async with self.db_pool.acquire() as conn:
                rows = await conn.fetch("""
                    SELECT backup_path, sha256_hash, file_size,
                           status, created_at, updated_at
                    FROM backup_metadata
                    WHERE status = 'completed'
                    ORDER BY created_at DESC
                """)
                return [dict(r) for r in rows]
        except Exception as exc:
            logger.warning("backup_records_fetch_failed", error=str(exc))
            return []

    async def _check_freshness(self) -> Dict[str, Any]:
        """Check backup freshness via the backup manager."""
        try:
            if hasattr(self.backup_manager, "check_backup_freshness"):
                return await self.backup_manager.check_backup_freshness()
        except Exception as exc:
            logger.debug("freshness_check_failed", error=str(exc))

        return {"fresh": True, "age_hours": 0, "checked_at": datetime.now(tz=timezone.utc).isoformat()}

    # ------------------------------------------------------------------
    # Alerting
    # ------------------------------------------------------------------

    async def _send_alerts(self, alerts: List[Dict[str, Any]]) -> None:
        """Dispatch alerts to the notification service.

        Falls back to structured logging if no notification service is
        configured.
        """
        for alert in alerts:
            if self.notification_service and hasattr(self.notification_service, "send_alert"):
                try:
                    await self.notification_service.send_alert(
                        title=f"Backup Alert: {alert['type']}",
                        message=alert["detail"],
                        severity=alert["severity"],
                        source="backup_audit_worker",
                    )
                except Exception as exc:
                    logger.error("alert_dispatch_failed", error=str(exc))
            else:
                # Fallback: structured log
                log_fn = logger.critical if alert["severity"] == SEVERITY_CRITICAL else logger.warning
                log_fn(
                    "backup_alert",
                    alert_type=alert["type"],
                    severity=alert["severity"],
                    detail=alert["detail"],
                )

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    async def _persist_audit_report(self, report: Dict[str, Any]) -> None:
        """Persist the audit report to the database."""
        if not self.db_pool:
            return

        try:
            async with self.db_pool.acquire() as conn:
                await conn.execute(
                    """
                    INSERT INTO hive_backup_audit_reports
                        (audit_number, backups_found, backups_verified,
                         integrity_pass, integrity_fail, alert_count,
                         status, report_data, audited_at)
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8, NOW())
                    """,
                    report["audit_number"],
                    report["backups_found"],
                    report["backups_verified"],
                    report["integrity_pass"],
                    report["integrity_fail"],
                    report["alert_count"],
                    report["status"],
                    json.dumps(report),
                )
        except Exception as exc:
            logger.debug("audit_report_persist_failed", error=str(exc))

    # ------------------------------------------------------------------
    # Diagnostics
    # ------------------------------------------------------------------

    @property
    def stats(self) -> Dict[str, Any]:
        """Diagnostic statistics for monitoring."""
        return {
            "running": self._running,
            "total_audits": self._total_audits,
            "total_backups_verified": self._total_backups_verified,
            "total_integrity_failures": self._total_integrity_failures,
            "total_freshness_alerts": self._total_freshness_alerts,
            "last_audit_at": (
                datetime.fromtimestamp(self._last_audit_at, tz=timezone.utc).isoformat()
                if self._last_audit_at else None
            ),
            "last_audit_status": self._last_audit.get("status") if self._last_audit else None,
        }

    @property
    def last_audit_report(self) -> Optional[Dict[str, Any]]:
        """The most recent audit report, or ``None`` if no audit has run yet."""
        return self._last_audit

    def __repr__(self) -> str:
        return (
            f"<BackupAuditWorker "
            f"audits={self._total_audits} "
            f"verified={self._total_backups_verified} "
            f"failures={self._total_integrity_failures}>"
        )
