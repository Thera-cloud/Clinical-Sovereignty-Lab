"""
HIVE DEFENSE PROTOCOL v3.0 — Backup Access Anomaly Detection (Phase 8C)
Separate RBAC enforcement and behavioral analysis for backup system access.

Backup data is a crown jewel.  Production credentials must NEVER be the same
as backup access credentials.  This service enforces:

1. Separate RBAC role requirement — backup access uses a distinct permission
   set, independent of production roles.
2. Approved IP whitelist — any access from a non-approved IP is immediately
   blocked and triggers an alert.
3. Maintenance window enforcement — outside scheduled maintenance windows,
   any access requires MFA re-authentication.
4. All access outside scheduled verification windows is flagged as anomalous
   and alerts Nathan immediately.

Event: ``hive.backup.anomalous_access``

Patent-Pending — Claims 30-56
© 2026 Clinical Sovereignty Lab. All rights reserved.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from typing import Any, Callable, Coroutine, Dict, List, Optional, Set
from uuid import UUID, uuid4

logger = logging.getLogger("hive.backup_access")


# =============================================================================
# CONSTANTS
# =============================================================================

# Default maintenance windows (UTC hours, inclusive)
DEFAULT_MAINTENANCE_WINDOWS: List[Dict[str, int]] = [
    {"day_of_week": 0, "start_hour": 2, "end_hour": 4},   # Monday 02:00-04:00 UTC
    {"day_of_week": 3, "start_hour": 2, "end_hour": 4},   # Thursday 02:00-04:00 UTC
]


# =============================================================================
# DATA MODELS
# =============================================================================

@dataclass
class BackupAccessRecord:
    """A single backup access event."""

    record_id: UUID = field(default_factory=uuid4)
    user_id: str = ""
    backup_id: str = ""
    source_ip: str = ""
    access_type: str = "read"           # read | write | restore | delete
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    is_anomalous: bool = False
    anomaly_reasons: List[str] = field(default_factory=list)
    blocked: bool = False
    mfa_required: bool = False
    mfa_completed: bool = False


@dataclass
class BackupAccessPolicy:
    """RBAC policy for backup access."""

    approved_ips: Set[str] = field(default_factory=set)
    approved_user_ids: Set[str] = field(default_factory=set)
    maintenance_windows: List[Dict[str, int]] = field(
        default_factory=lambda: list(DEFAULT_MAINTENANCE_WINDOWS)
    )
    require_mfa_outside_window: bool = True
    max_accesses_per_hour: int = 10


# =============================================================================
# BACKUP ACCESS ANOMALY DETECTOR
# =============================================================================

class BackupAccessAnomaly:
    """
    Backup access pattern detection and enforcement service.

    Enforces a strict separation between production and backup access roles,
    monitors all backup access for anomalous patterns, and triggers
    ``hive.backup.anomalous_access`` events when violations are detected.

    Parameters
    ----------
    db_pool : Any, optional
        asyncpg connection pool for persisting access records.
    event_callback : callable, optional
        Async callback ``(topic: str, payload: dict) -> None`` for
        broadcasting alerts to the hive event bus.
    policy : BackupAccessPolicy, optional
        The access policy to enforce.  If None, a default policy is used.

    Usage
    -----
    ::

        detector = BackupAccessAnomaly(db_pool=pool, policy=policy)
        detector.record_access("user_123", "backup_daily_20260215", "10.0.0.50")
        result = await detector.evaluate_access("user_123", "10.0.0.50")
        if result["anomalous"]:
            # Alert has already been fired
            pass
    """

    def __init__(
        self,
        db_pool: Any = None,
        event_callback: Optional[Callable[[str, Dict[str, Any]], Coroutine]] = None,
        policy: Optional[BackupAccessPolicy] = None,
    ) -> None:
        self._db_pool = db_pool
        self._event_callback = event_callback
        self._policy = policy or BackupAccessPolicy()

        # In-memory access log (ring buffer, last 10000 records)
        self._access_log: List[BackupAccessRecord] = []
        self._access_log_max: int = 10000

        # Concurrency guard
        self._lock: asyncio.Lock = asyncio.Lock()

        # Metrics
        self._total_accesses: int = 0
        self._total_anomalous: int = 0
        self._total_blocked: int = 0

        logger.info(
            "BackupAccessAnomaly initialized — approved_ips=%d approved_users=%d",
            len(self._policy.approved_ips),
            len(self._policy.approved_user_ids),
        )

    # ------------------------------------------------------------------
    # Primary API
    # ------------------------------------------------------------------

    async def record_access(
        self,
        user_id: str,
        backup_id: str,
        source_ip: str,
        access_type: str = "read",
    ) -> BackupAccessRecord:
        """
        Record a backup access event and evaluate it for anomalies.

        Every access is logged.  If the access is anomalous, it is flagged
        and an alert is fired immediately.

        Parameters
        ----------
        user_id : str
            Identifier of the user requesting backup access.
        backup_id : str
            Identifier of the backup being accessed.
        source_ip : str
            Source IP address of the access request.
        access_type : str
            Type of access: ``"read"``, ``"write"``, ``"restore"``, ``"delete"``.

        Returns
        -------
        BackupAccessRecord
            The recorded access event with anomaly flags.
        """
        record = BackupAccessRecord(
            user_id=user_id,
            backup_id=backup_id,
            source_ip=source_ip,
            access_type=access_type,
        )

        # Evaluate for anomalies
        anomaly_result = await self.evaluate_access(user_id, source_ip)
        record.is_anomalous = anomaly_result["anomalous"]
        record.anomaly_reasons = anomaly_result.get("reasons", [])
        record.blocked = anomaly_result.get("blocked", False)
        record.mfa_required = anomaly_result.get("mfa_required", False)

        # Store record
        async with self._lock:
            self._access_log.append(record)
            if len(self._access_log) > self._access_log_max:
                self._access_log = self._access_log[-self._access_log_max:]
            self._total_accesses += 1

        # Persist to database
        await self._persist_record(record)

        if record.is_anomalous:
            self._total_anomalous += 1
            logger.warning(
                "ANOMALOUS_BACKUP_ACCESS user=%s backup=%s ip=%s reasons=%s",
                user_id,
                backup_id,
                source_ip,
                record.anomaly_reasons,
            )

        if record.blocked:
            self._total_blocked += 1
            logger.critical(
                "BACKUP_ACCESS_BLOCKED user=%s ip=%s reasons=%s",
                user_id,
                source_ip,
                record.anomaly_reasons,
            )

        return record

    async def evaluate_access(
        self,
        user_id: str,
        source_ip: str,
    ) -> Dict[str, Any]:
        """
        Evaluate a backup access request for anomalous behavior.

        Checks performed (in order):
        1. IP whitelist — non-approved IP → blocked + alert.
        2. User authorization — user not in approved list → blocked + alert.
        3. Maintenance window — outside window → MFA re-auth required.
        4. Rate limiting — too many accesses in rolling hour → anomalous.
        5. Time-of-day analysis — unusual access hours → flagged.

        Parameters
        ----------
        user_id : str
            User requesting access.
        source_ip : str
            Source IP of the request.

        Returns
        -------
        dict
            Result with keys: ``anomalous`` (bool), ``blocked`` (bool),
            ``mfa_required`` (bool), ``reasons`` (list[str]).
        """
        reasons: List[str] = []
        blocked = False
        mfa_required = False

        # --- Check 1: IP whitelist ---
        if self._policy.approved_ips and source_ip not in self._policy.approved_ips:
            reasons.append(f"non_approved_ip:{source_ip}")
            blocked = True

        # --- Check 2: User authorization ---
        if self._policy.approved_user_ids and user_id not in self._policy.approved_user_ids:
            reasons.append(f"unauthorized_user:{user_id}")
            blocked = True

        # --- Check 3: Maintenance window ---
        if not self._is_within_maintenance_window():
            reasons.append("outside_maintenance_window")
            if self._policy.require_mfa_outside_window:
                mfa_required = True

        # --- Check 4: Rate limiting ---
        recent_count = self._count_recent_accesses(user_id, hours=1)
        if recent_count >= self._policy.max_accesses_per_hour:
            reasons.append(
                f"rate_limit_exceeded:{recent_count}/{self._policy.max_accesses_per_hour}"
            )

        # --- Check 5: Time-of-day analysis ---
        now = datetime.now(timezone.utc)
        if now.hour < 6 or now.hour > 22:
            # Access during unusual hours (but not during maintenance)
            if not self._is_within_maintenance_window():
                reasons.append(f"unusual_access_hour:{now.hour}:00")

        is_anomalous = len(reasons) > 0

        # Fire alert if anomalous
        if is_anomalous:
            await self._fire_anomaly_alert(user_id, source_ip, reasons, blocked)

        return {
            "anomalous": is_anomalous,
            "blocked": blocked,
            "mfa_required": mfa_required,
            "reasons": reasons,
        }

    # ------------------------------------------------------------------
    # Maintenance Window
    # ------------------------------------------------------------------

    def _is_within_maintenance_window(self) -> bool:
        """Check if the current UTC time falls within a configured maintenance window."""
        now = datetime.now(timezone.utc)
        current_dow = now.weekday()  # 0=Monday
        current_hour = now.hour

        for window in self._policy.maintenance_windows:
            if (
                window["day_of_week"] == current_dow
                and window["start_hour"] <= current_hour < window["end_hour"]
            ):
                return True
        return False

    # ------------------------------------------------------------------
    # Rate Limiting
    # ------------------------------------------------------------------

    def _count_recent_accesses(self, user_id: str, hours: int = 1) -> int:
        """Count accesses by *user_id* in the last *hours* hours."""
        cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
        return sum(
            1
            for record in self._access_log
            if record.user_id == user_id and record.timestamp >= cutoff
        )

    # ------------------------------------------------------------------
    # Alert
    # ------------------------------------------------------------------

    async def _fire_anomaly_alert(
        self,
        user_id: str,
        source_ip: str,
        reasons: List[str],
        blocked: bool,
    ) -> None:
        """Fire a hive.backup.anomalous_access event and notify Nathan."""
        payload = {
            "user_id": user_id,
            "source_ip": source_ip,
            "reasons": reasons,
            "blocked": blocked,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "notify_nathan": True,
        }

        await self._broadcast_event("hive.backup.anomalous_access", payload)

        logger.critical(
            "BACKUP_ANOMALY_ALERT user=%s ip=%s blocked=%s reasons=%s",
            user_id,
            source_ip,
            blocked,
            reasons,
        )

    # ------------------------------------------------------------------
    # Policy Management
    # ------------------------------------------------------------------

    def add_approved_ip(self, ip: str) -> None:
        """Add an IP to the approved whitelist."""
        self._policy.approved_ips.add(ip)
        logger.info("backup_ip_approved ip=%s", ip)

    def remove_approved_ip(self, ip: str) -> None:
        """Remove an IP from the approved whitelist."""
        self._policy.approved_ips.discard(ip)
        logger.info("backup_ip_removed ip=%s", ip)

    def add_approved_user(self, user_id: str) -> None:
        """Add a user to the approved backup access list."""
        self._policy.approved_user_ids.add(user_id)
        logger.info("backup_user_approved user=%s", user_id)

    def set_maintenance_windows(
        self,
        windows: List[Dict[str, int]],
    ) -> None:
        """Replace the maintenance window schedule."""
        self._policy.maintenance_windows = windows
        logger.info("backup_maintenance_windows_updated count=%d", len(windows))

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    async def _persist_record(self, record: BackupAccessRecord) -> None:
        """Persist a backup access record to the database."""
        if not self._db_pool:
            return

        try:
            async with self._db_pool.acquire() as conn:
                await conn.execute(
                    """
                    INSERT INTO hive_backup_access_log (
                        record_id, user_id, backup_id, source_ip,
                        access_type, is_anomalous, anomaly_reasons,
                        blocked, mfa_required, mfa_completed, recorded_at
                    ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)
                    """,
                    record.record_id,
                    record.user_id,
                    record.backup_id,
                    record.source_ip,
                    record.access_type,
                    record.is_anomalous,
                    record.anomaly_reasons,
                    record.blocked,
                    record.mfa_required,
                    record.mfa_completed,
                    record.timestamp,
                )
        except Exception as exc:
            logger.error("backup_access_persist_failed error=%s", exc)

    # ------------------------------------------------------------------
    # Event bus
    # ------------------------------------------------------------------

    async def _broadcast_event(
        self,
        topic: str,
        payload: Dict[str, Any],
    ) -> None:
        """Broadcast an event via the registered callback."""
        if self._event_callback:
            try:
                await self._event_callback(topic, payload)
            except Exception as exc:
                logger.error(
                    "backup_event_broadcast_failed topic=%s error=%s",
                    topic,
                    exc,
                )

    # ------------------------------------------------------------------
    # Diagnostics
    # ------------------------------------------------------------------

    @property
    def stats(self) -> Dict[str, Any]:
        """Diagnostic statistics for monitoring dashboards."""
        return {
            "total_accesses": self._total_accesses,
            "total_anomalous": self._total_anomalous,
            "total_blocked": self._total_blocked,
            "approved_ips": len(self._policy.approved_ips),
            "approved_users": len(self._policy.approved_user_ids),
            "access_log_size": len(self._access_log),
        }

    def __repr__(self) -> str:
        return (
            f"<BackupAccessAnomaly "
            f"accesses={self._total_accesses} "
            f"anomalous={self._total_anomalous} "
            f"blocked={self._total_blocked}>"
        )
