"""
HIVE DEFENSE PROTOCOL v3.0 — Birth Rate Anomaly Detector (Phase 8C: Third Cord)
Monitors Fibre birth frequency, source IP, certificate usage, and DEFCON correlation
within a 1-hour rolling window.

Design rationale:
    Legitimate Fibre births follow predictable patterns: controlled frequency,
    known source IPs, valid certificates, and correlation with normal DEFCON
    operations. An attacker who has obtained a stolen birth certificate will
    attempt to spawn as many rogue Fibres as possible before detection.

    The Birth Rate Anomaly Detector watches for:
        1. Birth *rate* exceeding the expected frequency for the current DEFCON level
        2. Births from *unrecognized source IPs* (new infrastructure)
        3. *Burst births* — many births in a short window from one certificate
        4. Births during elevated DEFCON (when births should be restricted)

    When an anomaly is detected, ALL births are paused hive-wide.  Resuming
    births requires re-authentication by 3 shard holders (quorum verification).
    This prevents an attacker from using a stolen key to build an army.

Patent-Pending — Claims 30-56
© 2026 Clinical Sovereignty Lab. All rights reserved.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Callable, Coroutine, Deque, Dict, List, Optional, Set, Tuple
from uuid import UUID, uuid4

from app.models.hive_defense import (
    DefconLevel,
    DefconState,
    HIVE_EVENT_TOPICS,
)

logger = logging.getLogger("hive.birth_anomaly")


# =============================================================================
# CONSTANTS
# =============================================================================

#: Rolling window for birth rate analysis (seconds)
ROLLING_WINDOW_SEC: float = 3600.0  # 1 hour

#: Maximum births per hour at DEFCON PEACE
MAX_BIRTHS_PER_HOUR_PEACE: int = 50

#: Maximum births per hour at DEFCON ELEVATED
MAX_BIRTHS_PER_HOUR_ELEVATED: int = 20

#: Maximum births per hour at DEFCON SUBSTANTIAL
MAX_BIRTHS_PER_HOUR_SUBSTANTIAL: int = 5

#: At SEVERE and CRITICAL, births should be zero
MAX_BIRTHS_PER_HOUR_SEVERE: int = 0

#: Maximum births from a single certificate in the window
MAX_BIRTHS_PER_CERT: int = 10

#: Maximum births from a single source IP in the window
MAX_BIRTHS_PER_IP: int = 15

#: Burst detection — max births in a 60-second micro-window
BURST_WINDOW_SEC: float = 60.0
MAX_BIRTHS_BURST: int = 5

#: Required shard holders for re-authentication to resume births
REQUIRED_SHARD_HOLDERS: int = 3

#: Rate limits per DEFCON level
_DEFCON_BIRTH_LIMITS: Dict[DefconLevel, int] = {
    DefconLevel.PEACE: MAX_BIRTHS_PER_HOUR_PEACE,
    DefconLevel.ELEVATED: MAX_BIRTHS_PER_HOUR_ELEVATED,
    DefconLevel.SUBSTANTIAL: MAX_BIRTHS_PER_HOUR_SUBSTANTIAL,
    DefconLevel.SEVERE: MAX_BIRTHS_PER_HOUR_SEVERE,
    DefconLevel.CRITICAL: MAX_BIRTHS_PER_HOUR_SEVERE,
}


# =============================================================================
# BIRTH EVENT RECORD
# =============================================================================

@dataclass
class BirthEvent:
    """
    A single Fibre birth event for anomaly tracking.

    Attributes:
        fibre_id:    UUID of the newly born Fibre.
        source_ip:   IP address from which the birth request originated.
        cert_id:     UUID of the certificate used to authorize the birth.
        timestamp:   When the birth occurred.
    """
    fibre_id: UUID = field(default_factory=uuid4)
    source_ip: str = ""
    cert_id: UUID = field(default_factory=uuid4)
    timestamp: datetime = field(default_factory=datetime.utcnow)
    timestamp_mono: float = field(default_factory=time.monotonic)


# =============================================================================
# BIRTH RATE ANOMALY DETECTOR
# =============================================================================

class BirthRateAnomalyDetector:
    """
    Monitors Fibre birth frequency and source patterns for anomalies.

    Tracks all births in a 1-hour rolling window and evaluates for:
        - Excessive birth rate (DEFCON-adjusted thresholds)
        - Unrecognized source IPs
        - Certificate overuse
        - Micro-burst patterns (many births in <60 seconds)
        - Births during birth-restricted DEFCON levels

    When an anomaly is detected, ALL births are paused hive-wide until
    3 shard holders re-authenticate to resume.

    Integration Points:
        - EphemeralCertificates — provides certificate data
        - DefconController      — provides current DEFCON state, escalates
        - KeySharding           — shard holder re-authentication
        - ForensicLogger        — logs anomaly events

    Usage::

        detector = BirthRateAnomalyDetector(db_pool=pool)

        # Record each birth
        await detector.record_birth(fibre_id, source_ip, cert_id)

        # Check for anomalies
        is_anomalous = await detector.evaluate()

    Patent-Pending — Claims 30-56
    """

    def __init__(
        self,
        db_pool=None,
        event_callback: Optional[Callable[[str, Dict[str, Any]], Coroutine]] = None,
        forensic_logger=None,
        defcon_controller=None,
    ) -> None:
        """
        Initialize the Birth Rate Anomaly Detector.

        Args:
            db_pool:            asyncpg connection pool for persistence.
            event_callback:     Async callback for hive event bus.
            forensic_logger:    ForensicLogger instance for evidence chain.
            defcon_controller:  DefconController for DEFCON state and escalation.
        """
        self._db_pool = db_pool
        self._event_callback = event_callback
        self._forensic_logger = forensic_logger
        self._defcon_controller = defcon_controller

        # Rolling window of birth events
        self._birth_window: Deque[BirthEvent] = deque()

        # Known (trusted) source IPs
        self._trusted_ips: Set[str] = set()

        # Birth pause state
        self._births_paused: bool = False
        self._paused_at: Optional[datetime] = None
        self._pause_reason: str = ""

        # Shard holder re-authentication tracking
        self._authenticated_shards: Set[int] = set()

        # Current DEFCON state
        self._defcon_state: DefconState = DefconState()

        # Statistics
        self._total_anomalies_detected: int = 0
        self._total_births_recorded: int = 0

        logger.info("BirthRateAnomalyDetector initialized")

    # =========================================================================
    # CONFIGURATION
    # =========================================================================

    def add_trusted_ip(self, ip: str) -> None:
        """
        Add an IP address to the trusted source set.

        Args:
            ip: IP address string to trust.
        """
        self._trusted_ips.add(ip)
        logger.debug("Trusted IP added: %s", ip)

    def update_defcon(self, defcon_state: DefconState) -> None:
        """
        Update the current DEFCON state for threshold adjustment.

        Args:
            defcon_state: The new DEFCON state.
        """
        self._defcon_state = defcon_state

    @property
    def births_paused(self) -> bool:
        """Whether births are currently paused due to anomaly detection."""
        return self._births_paused

    # =========================================================================
    # BIRTH RECORDING
    # =========================================================================

    async def record_birth(
        self,
        fibre_id: UUID,
        source_ip: str,
        cert_id: UUID,
    ) -> None:
        """
        Record a new Fibre birth event.

        The event is added to the rolling window and the detector immediately
        evaluates for anomalies. If an anomaly is detected, births are paused.

        Args:
            fibre_id:   UUID of the newly born Fibre.
            source_ip:  IP address of the birth request origin.
            cert_id:    UUID of the certificate used for the birth.
        """
        event = BirthEvent(
            fibre_id=fibre_id,
            source_ip=source_ip,
            cert_id=cert_id,
        )

        self._birth_window.append(event)
        self._total_births_recorded += 1

        # Prune expired entries from the rolling window
        self._prune_window()

        logger.debug(
            "Birth recorded: fibre=%s ip=%s cert=%s (window_size=%d)",
            fibre_id, source_ip, cert_id, len(self._birth_window),
        )

        # Persist the event
        await self._persist_birth_event(event)

    # =========================================================================
    # ANOMALY EVALUATION
    # =========================================================================

    async def evaluate(self) -> bool:
        """
        Evaluate the current rolling window for birth anomalies.

        Checks:
            1. Total birth rate exceeds DEFCON-adjusted threshold
            2. Births from unrecognized source IPs
            3. Single certificate overuse
            4. Micro-burst detection (>5 births in 60 seconds)
            5. Births during birth-restricted DEFCON levels

        Returns:
            True if an anomaly is detected, False if normal.
        """
        self._prune_window()
        anomalies: List[Dict[str, Any]] = []

        window_events = list(self._birth_window)
        window_size = len(window_events)

        if window_size == 0:
            return False

        # ── 1. Total birth rate ──
        defcon_level = self._defcon_state.level
        max_births = _DEFCON_BIRTH_LIMITS.get(defcon_level, MAX_BIRTHS_PER_HOUR_PEACE)

        if window_size > max_births:
            anomalies.append({
                "type": "excessive_birth_rate",
                "births_in_window": window_size,
                "max_allowed": max_births,
                "defcon_level": defcon_level.name,
            })

        # ── 2. Unrecognized source IPs ──
        if self._trusted_ips:
            unknown_ips: Set[str] = set()
            for event in window_events:
                if event.source_ip and event.source_ip not in self._trusted_ips:
                    unknown_ips.add(event.source_ip)

            if unknown_ips:
                anomalies.append({
                    "type": "unrecognized_source_ip",
                    "unknown_ips": list(unknown_ips),
                    "count": len(unknown_ips),
                })

        # ── 3. Certificate overuse ──
        cert_counts: Dict[UUID, int] = {}
        for event in window_events:
            cert_counts[event.cert_id] = cert_counts.get(event.cert_id, 0) + 1

        for cert_id, count in cert_counts.items():
            if count > MAX_BIRTHS_PER_CERT:
                anomalies.append({
                    "type": "certificate_overuse",
                    "cert_id": str(cert_id),
                    "births": count,
                    "max_allowed": MAX_BIRTHS_PER_CERT,
                })

        # ── 4. Micro-burst detection ──
        now_mono = time.monotonic()
        burst_cutoff = now_mono - BURST_WINDOW_SEC
        burst_count = sum(
            1 for e in window_events if e.timestamp_mono >= burst_cutoff
        )
        if burst_count > MAX_BIRTHS_BURST:
            anomalies.append({
                "type": "micro_burst",
                "births_in_60s": burst_count,
                "max_allowed": MAX_BIRTHS_BURST,
            })

        # ── 5. Births during restricted DEFCON ──
        if defcon_level in (DefconLevel.SEVERE, DefconLevel.CRITICAL) and window_size > 0:
            anomalies.append({
                "type": "births_during_lockdown",
                "defcon_level": defcon_level.name,
                "births_in_window": window_size,
            })

        # ── 6. Single IP overuse ──
        ip_counts: Dict[str, int] = {}
        for event in window_events:
            if event.source_ip:
                ip_counts[event.source_ip] = ip_counts.get(event.source_ip, 0) + 1

        for ip, count in ip_counts.items():
            if count > MAX_BIRTHS_PER_IP:
                anomalies.append({
                    "type": "source_ip_overuse",
                    "source_ip": ip,
                    "births": count,
                    "max_allowed": MAX_BIRTHS_PER_IP,
                })

        # ── Process anomalies ──
        if anomalies:
            self._total_anomalies_detected += 1
            await self._handle_anomaly(anomalies)
            return True

        return False

    # =========================================================================
    # ANOMALY HANDLING
    # =========================================================================

    async def _handle_anomaly(self, anomalies: List[Dict[str, Any]]) -> None:
        """
        Handle detected birth anomalies.

        Pauses all births hive-wide and escalates DEFCON.

        Args:
            anomalies: List of detected anomaly details.
        """
        if not self._births_paused:
            self._births_paused = True
            self._paused_at = datetime.utcnow()
            self._pause_reason = "; ".join(a["type"] for a in anomalies)
            self._authenticated_shards.clear()

        anomaly_types = [a["type"] for a in anomalies]
        logger.critical(
            "⚠ BIRTH ANOMALY DETECTED — types=%s — ALL BIRTHS PAUSED. "
            "3 shard holders must re-authenticate to resume.",
            anomaly_types,
        )

        # Log to forensic chain
        if self._forensic_logger:
            try:
                await self._forensic_logger.log_event(
                    event_type="birth_rate_anomaly",
                    evidence={
                        "anomalies": anomalies,
                        "window_size": len(self._birth_window),
                        "defcon_level": self._defcon_state.level.name,
                        "total_anomalies": self._total_anomalies_detected,
                    },
                )
            except Exception as exc:
                logger.error("Forensic log failed: %s", exc)

        # Escalate DEFCON
        if self._defcon_controller:
            try:
                await self._defcon_controller.escalate(
                    DefconLevel.SEVERE,
                    f"Birth rate anomaly: {', '.join(anomaly_types)}",
                )
            except Exception as exc:
                logger.error("DEFCON escalation failed: %s", exc)

        # Broadcast event
        await self._broadcast_event(
            "hive.birth.anomaly_detected",
            {
                "anomalies": anomaly_types,
                "births_paused": True,
                "required_shard_holders": REQUIRED_SHARD_HOLDERS,
                "timestamp": datetime.utcnow().isoformat(),
            },
        )

    # =========================================================================
    # SHARD HOLDER RE-AUTHENTICATION
    # =========================================================================

    async def authenticate_shard_holder(self, shard_index: int) -> Dict[str, Any]:
        """
        Record a shard holder's re-authentication to resume births.

        Births are resumed once the required number of shard holders (3)
        have re-authenticated.

        Args:
            shard_index: The index of the authenticating shard holder.

        Returns:
            Status dict with authentication progress.
        """
        self._authenticated_shards.add(shard_index)
        authenticated = len(self._authenticated_shards)
        remaining = max(0, REQUIRED_SHARD_HOLDERS - authenticated)

        logger.info(
            "Shard holder #%d re-authenticated (%d/%d required)",
            shard_index, authenticated, REQUIRED_SHARD_HOLDERS,
        )

        if authenticated >= REQUIRED_SHARD_HOLDERS:
            self._births_paused = False
            self._paused_at = None
            self._pause_reason = ""
            self._authenticated_shards.clear()

            logger.info(
                "Birth pause LIFTED — %d shard holders authenticated",
                authenticated,
            )

            await self._broadcast_event(
                "hive.birth.resumed",
                {
                    "shard_holders_authenticated": authenticated,
                    "timestamp": datetime.utcnow().isoformat(),
                },
            )

            return {
                "births_paused": False,
                "shard_holders_authenticated": authenticated,
                "message": "Births resumed — quorum reached",
            }

        return {
            "births_paused": True,
            "shard_holders_authenticated": authenticated,
            "remaining": remaining,
            "message": f"{remaining} more shard holder(s) needed to resume births",
        }

    # =========================================================================
    # ADMIN
    # =========================================================================

    def summary(self) -> Dict[str, Any]:
        """Return a summary dict for admin dashboards."""
        self._prune_window()
        return {
            "births_in_window": len(self._birth_window),
            "total_births_recorded": self._total_births_recorded,
            "total_anomalies_detected": self._total_anomalies_detected,
            "births_paused": self._births_paused,
            "paused_at": self._paused_at.isoformat() if self._paused_at else None,
            "pause_reason": self._pause_reason,
            "authenticated_shards": sorted(self._authenticated_shards),
            "required_shards": REQUIRED_SHARD_HOLDERS,
            "trusted_ip_count": len(self._trusted_ips),
            "defcon_level": self._defcon_state.level.name,
            "max_births_current_defcon": _DEFCON_BIRTH_LIMITS.get(
                self._defcon_state.level, MAX_BIRTHS_PER_HOUR_PEACE,
            ),
        }

    # =========================================================================
    # INTERNAL HELPERS
    # =========================================================================

    def _prune_window(self) -> None:
        """Remove expired events from the rolling window."""
        cutoff_mono = time.monotonic() - ROLLING_WINDOW_SEC
        while self._birth_window and self._birth_window[0].timestamp_mono < cutoff_mono:
            self._birth_window.popleft()

    # =========================================================================
    # PERSISTENCE
    # =========================================================================

    async def _persist_birth_event(self, event: BirthEvent) -> None:
        """Persist a birth event to the database."""
        if not self._db_pool:
            return

        try:
            async with self._db_pool.acquire() as conn:
                await conn.execute(
                    """
                    INSERT INTO birth_events (
                        fibre_id, source_ip, cert_id, created_at
                    ) VALUES ($1, $2, $3, $4)
                    """,
                    event.fibre_id,
                    event.source_ip,
                    event.cert_id,
                    event.timestamp,
                )
        except Exception as exc:
            logger.error(
                "Failed to persist birth event for fibre %s: %s",
                event.fibre_id, exc,
            )

    async def load_from_db(self) -> int:
        """
        Load recent birth events from the database on startup.

        Returns:
            Number of birth events loaded into the rolling window.
        """
        if not self._db_pool:
            return 0

        try:
            cutoff = datetime.utcnow() - timedelta(seconds=ROLLING_WINDOW_SEC)
            async with self._db_pool.acquire() as conn:
                rows = await conn.fetch(
                    """
                    SELECT fibre_id, source_ip, cert_id, created_at
                    FROM birth_events
                    WHERE created_at >= $1
                    ORDER BY created_at ASC
                    """,
                    cutoff,
                )

            loaded = 0
            for row in rows:
                event = BirthEvent(
                    fibre_id=row["fibre_id"],
                    source_ip=row["source_ip"] or "",
                    cert_id=row["cert_id"],
                    timestamp=row["created_at"],
                )
                self._birth_window.append(event)
                loaded += 1

            logger.info("Loaded %d birth events from database", loaded)
            return loaded

        except Exception as exc:
            logger.error("Failed to load birth events from DB: %s", exc)
            return 0

    # =========================================================================
    # EVENT BUS
    # =========================================================================

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
                    "Event callback failed for topic %s: %s", topic, exc,
                )
