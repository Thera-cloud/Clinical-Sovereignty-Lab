"""
HIVE DEFENSE PROTOCOL v3.0 — Certificate Usage Audit (Phase 8C: Third Cord)
Immutable tracking of every certificate use for parallel-usage detection.

Design rationale:
    Every ephemeral birth certificate has a unique ID and a limited scope.
    When a certificate is used to birth a Fibre, the use is logged immutably
    with the source IP, the Fibre born, and the timestamp.

    The critical detection this enables:
        **Parallel Usage** — If the same certificate is used from two different
        IP addresses within any time window, it means the certificate has been
        stolen and is being used by both the legitimate holder and the attacker.
        This is an immediate, automatic revocation trigger.

    Unlike rate-based or heuristic detections, parallel usage from different IPs
    is an absolute indicator — there is no legitimate scenario where the same
    certificate should be used from two distinct network locations simultaneously.

Patent-Pending — Claims 30-56
© 2026 Clinical Sovereignty Lab. All rights reserved.
"""

from __future__ import annotations

import hashlib
import logging
import time
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable, Coroutine, Dict, List, Optional, Set
from uuid import UUID, uuid4

from app.models.hive_defense import (
    DefconLevel,
    EphemeralCertificate,
    ForensicRecord,
    HIVE_EVENT_TOPICS,
)

logger = logging.getLogger("hive.cert_usage_audit")


# =============================================================================
# CONSTANTS
# =============================================================================

#: Maximum usage records kept per certificate in memory
MAX_USAGE_RECORDS_PER_CERT: int = 1000

#: Time window for parallel usage detection (seconds)
#: Same cert from different IPs within this window = parallel usage
PARALLEL_DETECTION_WINDOW_SEC: float = 300.0  # 5 minutes


# =============================================================================
# USAGE RECORD
# =============================================================================

@dataclass
class CertUsageRecord:
    """
    An immutable record of a single certificate use.

    Attributes:
        usage_id:       Unique identifier for this usage event.
        cert_id:        UUID of the certificate used.
        source_ip:      IP address from which the certificate was used.
        fibre_born_id:  UUID of the Fibre that was born from this use.
        timestamp:      When the use occurred.
        record_hash:    SHA-256 hash for immutability chain.
        previous_hash:  Hash of the preceding record.
    """
    usage_id: UUID = field(default_factory=uuid4)
    cert_id: UUID = field(default_factory=uuid4)
    source_ip: str = ""
    fibre_born_id: UUID = field(default_factory=uuid4)
    timestamp: datetime = field(default_factory=datetime.utcnow)
    record_hash: str = ""
    previous_hash: str = ""

    def compute_hash(self, previous_hash: str = "") -> str:
        """
        Compute the SHA-256 hash for this usage record.

        Args:
            previous_hash: Hash of the preceding record in the chain.

        Returns:
            Hex-encoded SHA-256 digest.
        """
        data = (
            f"{self.usage_id}:{self.cert_id}:{self.source_ip}:"
            f"{self.fibre_born_id}:{self.timestamp.isoformat()}:{previous_hash}"
        )
        self.record_hash = hashlib.sha256(data.encode()).hexdigest()
        self.previous_hash = previous_hash
        return self.record_hash


# =============================================================================
# CERTIFICATE USAGE AUDIT
# =============================================================================

class CertUsageAudit:
    """
    Immutable certificate usage tracking with parallel-usage detection.

    Every certificate use is logged to an immutable hash chain. The system
    watches for parallel usage — the same certificate used from different
    IP addresses — which is an absolute indicator of certificate theft.

    When parallel usage is detected:
        1. The certificate is immediately revoked
        2. All Fibres born from the compromised certificate are quarantined
        3. DEFCON is escalated
        4. The incident is logged to the forensic chain

    Integration Points:
        - EphemeralCertificates — provides certificate lifecycle
        - BirthRateAnomalyDetector — coordinates birth pausing
        - DefconController — escalates on parallel usage
        - ForensicLogger — logs to immutable evidence chain

    Usage::

        audit = CertUsageAudit(db_pool=pool)

        # Log every certificate use
        await audit.log_usage(cert_id, source_ip, fibre_born_id)

        # Check for parallel usage
        is_parallel = await audit.detect_parallel_usage(cert_id)

        # Get usage history
        history = await audit.get_usage_history(cert_id)

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
        Initialize the Certificate Usage Audit.

        Args:
            db_pool:            asyncpg connection pool for persistence.
            event_callback:     Async callback for hive event bus.
            forensic_logger:    ForensicLogger for immutable evidence chain.
            defcon_controller:  DefconController for escalation.
        """
        self._db_pool = db_pool
        self._event_callback = event_callback
        self._forensic_logger = forensic_logger
        self._defcon_controller = defcon_controller

        # Usage records per certificate: cert_id → list of CertUsageRecord
        self._usage_log: Dict[UUID, List[CertUsageRecord]] = defaultdict(list)

        # IP tracking per certificate: cert_id → set of IPs
        self._cert_ips: Dict[UUID, Set[str]] = defaultdict(set)

        # Fibres born per certificate: cert_id → set of fibre_ids
        self._cert_fibres: Dict[UUID, Set[UUID]] = defaultdict(set)

        # Revoked certificates (from parallel usage detection)
        self._revoked_certs: Set[UUID] = set()

        # Chain state
        self._chain_head: str = hashlib.sha256(b"cert_audit_genesis").hexdigest()

        # Statistics
        self._total_usages: int = 0
        self._parallel_detections: int = 0

        logger.info("CertUsageAudit initialized")

    # =========================================================================
    # USAGE LOGGING
    # =========================================================================

    async def log_usage(
        self,
        cert_id: UUID,
        source_ip: str,
        fibre_born_id: UUID,
    ) -> CertUsageRecord:
        """
        Log a certificate usage event immutably.

        Records the use, chains it cryptographically, and immediately checks
        for parallel usage (same cert from different IP).

        Args:
            cert_id:        UUID of the certificate being used.
            source_ip:      IP address of the usage origin.
            fibre_born_id:  UUID of the Fibre born from this use.

        Returns:
            The created CertUsageRecord.
        """
        record = CertUsageRecord(
            cert_id=cert_id,
            source_ip=source_ip,
            fibre_born_id=fibre_born_id,
        )
        record.compute_hash(self._chain_head)
        self._chain_head = record.record_hash

        # Store in memory
        self._usage_log[cert_id].append(record)
        if len(self._usage_log[cert_id]) > MAX_USAGE_RECORDS_PER_CERT:
            self._usage_log[cert_id] = self._usage_log[cert_id][
                -MAX_USAGE_RECORDS_PER_CERT:
            ]

        self._cert_ips[cert_id].add(source_ip)
        self._cert_fibres[cert_id].add(fibre_born_id)
        self._total_usages += 1

        logger.debug(
            "Certificate usage logged: cert=%s ip=%s fibre=%s hash=%s…",
            cert_id, source_ip, fibre_born_id, record.record_hash[:16],
        )

        # Persist
        await self._persist_usage(record)

        # Check for parallel usage immediately
        if len(self._cert_ips[cert_id]) > 1:
            await self._handle_parallel_usage(cert_id, source_ip)

        return record

    # =========================================================================
    # PARALLEL USAGE DETECTION
    # =========================================================================

    async def detect_parallel_usage(self, cert_id: UUID) -> bool:
        """
        Check whether a certificate has been used from multiple IP addresses.

        Examines the usage records within the parallel detection window
        to determine if the same certificate was used from different IPs.

        Args:
            cert_id: UUID of the certificate to check.

        Returns:
            True if parallel usage (different IPs) is detected.
        """
        records = self._usage_log.get(cert_id, [])
        if not records:
            return False

        # Check within the detection window
        now = datetime.utcnow()
        recent_ips: Set[str] = set()

        for record in reversed(records):
            age_sec = (now - record.timestamp).total_seconds()
            if age_sec > PARALLEL_DETECTION_WINDOW_SEC:
                break
            if record.source_ip:
                recent_ips.add(record.source_ip)

        is_parallel = len(recent_ips) > 1

        if is_parallel:
            logger.warning(
                "Parallel usage detected for cert %s — IPs: %s",
                cert_id, recent_ips,
            )

        return is_parallel

    async def _handle_parallel_usage(
        self,
        cert_id: UUID,
        latest_ip: str,
    ) -> None:
        """
        Handle a parallel usage detection — immediate revocation and escalation.

        Args:
            cert_id:    UUID of the compromised certificate.
            latest_ip:  The most recent IP that triggered the detection.
        """
        if cert_id in self._revoked_certs:
            return  # Already handled

        self._revoked_certs.add(cert_id)
        self._parallel_detections += 1

        all_ips = list(self._cert_ips.get(cert_id, set()))
        all_fibres = list(self._cert_fibres.get(cert_id, set()))

        logger.critical(
            "⚠ PARALLEL CERT USAGE — cert=%s IPs=%s — "
            "IMMEDIATE REVOCATION. %d Fibres born from this cert.",
            cert_id, all_ips, len(all_fibres),
        )

        # Log to forensic chain
        if self._forensic_logger:
            try:
                await self._forensic_logger.log_event(
                    event_type="cert_parallel_usage",
                    evidence={
                        "cert_id": str(cert_id),
                        "source_ips": all_ips,
                        "latest_ip": latest_ip,
                        "fibres_born": [str(f) for f in all_fibres],
                        "total_usages": len(self._usage_log.get(cert_id, [])),
                    },
                )
            except Exception as exc:
                logger.error("Forensic log failed: %s", exc)

        # Escalate DEFCON
        if self._defcon_controller:
            try:
                await self._defcon_controller.escalate(
                    DefconLevel.SEVERE,
                    f"Parallel certificate usage: cert={cert_id} "
                    f"from IPs {all_ips}",
                )
            except Exception as exc:
                logger.error("DEFCON escalation failed: %s", exc)

        # Broadcast event
        await self._broadcast_event(
            "hive.cert.parallel_usage",
            {
                "cert_id": str(cert_id),
                "source_ips": all_ips,
                "fibres_affected": [str(f) for f in all_fibres],
                "action": "immediate_revocation",
                "timestamp": datetime.utcnow().isoformat(),
            },
        )

    # =========================================================================
    # USAGE HISTORY
    # =========================================================================

    async def get_usage_history(
        self,
        cert_id: UUID,
    ) -> List[Dict[str, Any]]:
        """
        Return the usage history for a certificate.

        Args:
            cert_id: UUID of the certificate.

        Returns:
            List of usage record dicts, most recent first.
        """
        records = self._usage_log.get(cert_id, [])
        return [
            {
                "usage_id": str(r.usage_id),
                "cert_id": str(r.cert_id),
                "source_ip": r.source_ip,
                "fibre_born_id": str(r.fibre_born_id),
                "timestamp": r.timestamp.isoformat(),
                "record_hash": r.record_hash[:16] + "…",
            }
            for r in reversed(records)
        ]

    async def get_cert_summary(self, cert_id: UUID) -> Dict[str, Any]:
        """
        Return a summary of a certificate's usage.

        Args:
            cert_id: UUID of the certificate.

        Returns:
            Summary dict with usage counts, IPs, and status.
        """
        return {
            "cert_id": str(cert_id),
            "total_usages": len(self._usage_log.get(cert_id, [])),
            "unique_ips": list(self._cert_ips.get(cert_id, set())),
            "fibres_born": [
                str(f) for f in self._cert_fibres.get(cert_id, set())
            ],
            "is_revoked": cert_id in self._revoked_certs,
            "parallel_detected": len(self._cert_ips.get(cert_id, set())) > 1,
        }

    # =========================================================================
    # ADMIN
    # =========================================================================

    def summary(self) -> Dict[str, Any]:
        """Return a summary dict for admin dashboards."""
        return {
            "total_usages": self._total_usages,
            "unique_certs_used": len(self._usage_log),
            "parallel_detections": self._parallel_detections,
            "revoked_certs": len(self._revoked_certs),
            "chain_head": self._chain_head[:16] + "…",
        }

    # =========================================================================
    # PERSISTENCE
    # =========================================================================

    async def _persist_usage(self, record: CertUsageRecord) -> None:
        """Persist a usage record to the database."""
        if not self._db_pool:
            return

        try:
            async with self._db_pool.acquire() as conn:
                await conn.execute(
                    """
                    INSERT INTO cert_usage_log (
                        usage_id, cert_id, source_ip, fibre_born_id,
                        record_hash, previous_hash, created_at
                    ) VALUES ($1, $2, $3, $4, $5, $6, $7)
                    """,
                    record.usage_id,
                    record.cert_id,
                    record.source_ip,
                    record.fibre_born_id,
                    record.record_hash,
                    record.previous_hash,
                    record.timestamp,
                )
        except Exception as exc:
            logger.error(
                "Failed to persist cert usage %s: %s",
                record.usage_id, exc,
            )

    async def load_from_db(self) -> int:
        """
        Load certificate usage records from the database on startup.

        Returns:
            Number of usage records loaded.
        """
        if not self._db_pool:
            return 0

        try:
            async with self._db_pool.acquire() as conn:
                rows = await conn.fetch(
                    """
                    SELECT usage_id, cert_id, source_ip, fibre_born_id,
                           record_hash, previous_hash, created_at
                    FROM cert_usage_log
                    ORDER BY created_at ASC
                    """
                )

            loaded = 0
            for row in rows:
                record = CertUsageRecord(
                    usage_id=row["usage_id"],
                    cert_id=row["cert_id"],
                    source_ip=row["source_ip"] or "",
                    fibre_born_id=row["fibre_born_id"],
                    record_hash=row["record_hash"] or "",
                    previous_hash=row["previous_hash"] or "",
                    timestamp=row["created_at"],
                )
                self._usage_log[record.cert_id].append(record)
                self._cert_ips[record.cert_id].add(record.source_ip)
                self._cert_fibres[record.cert_id].add(record.fibre_born_id)
                self._chain_head = record.record_hash or self._chain_head
                loaded += 1

            logger.info(
                "Loaded %d cert usage records from database", loaded,
            )
            return loaded

        except Exception as exc:
            logger.error("Failed to load cert usage records: %s", exc)
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
