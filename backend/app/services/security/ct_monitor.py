"""
HIVE DEFENSE PROTOCOL v3.0 — Certificate Transparency Monitor (Phase 8C)
Continuous monitoring of public CT logs for unauthorized certificate issuance.

Certificate Transparency (RFC 6962) logs provide a public, append-only record
of every TLS certificate issued by participating CAs.  This service monitors
those logs in near-real-time to detect rogue or unauthorized certificates
issued against Sovereign Sanctuary domains.

Defense Strategy
----------------
1. CAA DNS records restrict which CAs may issue for our domains.
2. This service watches CT logs for *any* certificate matching our domains.
3. If the issuer is not in the approved set → immediate alert to Nathan.
4. Alert latency target: < 5 minutes from CT log inclusion.

Patent-Pending — Claims 30-56
© 2026 Clinical Sovereignty Lab. All rights reserved.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Coroutine, Dict, List, Optional, Set
from uuid import UUID, uuid4

logger = logging.getLogger("hive.ct_monitor")


# =============================================================================
# CONSTANTS
# =============================================================================

# Public CT log list endpoints (Google, Cloudflare, DigiCert)
DEFAULT_CT_LOG_URLS: List[str] = [
    "https://ct.googleapis.com/logs/us1/argon2025h1/",
    "https://ct.googleapis.com/logs/us1/argon2025h2/",
    "https://ct.cloudflare.com/logs/nimbus2025/",
    "https://ct.googleapis.com/logs/eu1/xenon2025h1/",
]

# Well-known search API for CT log aggregation
CT_SEARCH_API: str = "https://crt.sh"

# Domains we protect
SOVEREIGN_DOMAINS: List[str] = [
    "sovereignsanctuary.net",
    "*.sovereignsanctuary.net",
    "app.sovereignsanctuary.net",
    "coach.sovereignsanctuary.net",
    "command.sovereignsanctuary.net",
    "api.sovereignsanctuary.net",
]


# =============================================================================
# DATA MODELS
# =============================================================================

@dataclass
class CTCertificateEntry:
    """A certificate entry discovered in CT logs."""

    entry_id: UUID = field(default_factory=uuid4)
    domain: str = ""
    issuer_cn: str = ""
    issuer_org: str = ""
    serial_number: str = ""
    not_before: Optional[datetime] = None
    not_after: Optional[datetime] = None
    log_url: str = ""
    log_index: int = -1
    sha256_fingerprint: str = ""
    is_authorized: bool = False
    discovered_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    raw_entry: Dict[str, Any] = field(default_factory=dict)


@dataclass
class CTAlert:
    """An alert generated for an unauthorized certificate."""

    alert_id: UUID = field(default_factory=uuid4)
    certificate: CTCertificateEntry = field(default_factory=CTCertificateEntry)
    alert_type: str = "unauthorized_issuer"
    severity: str = "critical"
    message: str = ""
    acknowledged: bool = False
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


# =============================================================================
# CT MONITOR
# =============================================================================

class CTMonitor:
    """
    Certificate Transparency log monitoring service.

    Watches public CT logs for any certificates issued against Sovereign
    Sanctuary domains and alerts immediately when an unauthorized issuer
    is detected.  Designed to run as a background service called by the
    ``ct_monitor_worker`` at configurable intervals.

    Parameters
    ----------
    db_pool : Any, optional
        asyncpg connection pool for persisting discovered certificates
        and alert history.
    event_callback : callable, optional
        Async callback ``(topic: str, payload: dict) -> None`` for
        broadcasting alerts to the hive event bus.
    expected_issuers : set[str], optional
        Set of authorized issuer common names (CN).  Any certificate
        whose issuer CN is not in this set triggers an alert.
    http_client : Any, optional
        aiohttp or httpx client session for querying CT logs.
        If None, a new session is created per request.

    Attributes
    ----------
    discovered_certs : list[CTCertificateEntry]
        In-memory cache of recently discovered certificates.
    alerts : list[CTAlert]
        In-memory cache of unacknowledged alerts.

    Usage
    -----
    ::

        monitor = CTMonitor(
            db_pool=pool,
            expected_issuers={"Let's Encrypt", "DigiCert Inc"},
        )
        certs = await monitor.check_ct_logs("sovereignsanctuary.net")
        alerts = await monitor.alert_on_unauthorized(
            "sovereignsanctuary.net",
            expected_issuers={"Let's Encrypt", "DigiCert Inc"},
        )
    """

    def __init__(
        self,
        db_pool: Any = None,
        event_callback: Optional[Callable[[str, Dict[str, Any]], Coroutine]] = None,
        expected_issuers: Optional[Set[str]] = None,
        http_client: Any = None,
    ) -> None:
        self._db_pool = db_pool
        self._event_callback = event_callback
        self._expected_issuers: Set[str] = expected_issuers or set()
        self._http_client = http_client

        # In-memory state
        self.discovered_certs: List[CTCertificateEntry] = []
        self.alerts: List[CTAlert] = []

        # Tracking
        self._last_check: Optional[datetime] = None
        self._total_checks: int = 0
        self._total_certs_found: int = 0
        self._total_unauthorized: int = 0

        # Known certificate fingerprints (dedup)
        self._known_fingerprints: Set[str] = set()

        logger.info(
            "CTMonitor initialized — expected_issuers=%s",
            self._expected_issuers or "(not configured)",
        )

    # ------------------------------------------------------------------
    # Primary API
    # ------------------------------------------------------------------

    async def check_ct_logs(
        self,
        domain: str,
        ct_log_urls: Optional[List[str]] = None,
    ) -> List[CTCertificateEntry]:
        """
        Query Certificate Transparency logs for certificates matching *domain*.

        Checks both the CT log list endpoints and the crt.sh aggregation
        API.  Results are deduplicated by SHA-256 fingerprint and cached
        in ``self.discovered_certs``.

        Parameters
        ----------
        domain : str
            The domain to search for (e.g., ``"sovereignsanctuary.net"``).
        ct_log_urls : list[str], optional
            Override the default CT log URL list.

        Returns
        -------
        list[CTCertificateEntry]
            All certificates found for the domain in this scan.
        """
        self._total_checks += 1
        self._last_check = datetime.now(timezone.utc)
        log_urls = ct_log_urls or DEFAULT_CT_LOG_URLS

        logger.info("ct_check_started domain=%s logs=%d", domain, len(log_urls))

        new_entries: List[CTCertificateEntry] = []

        # --- Strategy 1: Query crt.sh aggregation API ---
        crtsh_entries = await self._query_crtsh(domain)
        for entry in crtsh_entries:
            if entry.sha256_fingerprint not in self._known_fingerprints:
                self._known_fingerprints.add(entry.sha256_fingerprint)
                new_entries.append(entry)

        # --- Strategy 2: Query individual CT log endpoints ---
        for log_url in log_urls:
            try:
                log_entries = await self._query_ct_log(domain, log_url)
                for entry in log_entries:
                    if entry.sha256_fingerprint not in self._known_fingerprints:
                        self._known_fingerprints.add(entry.sha256_fingerprint)
                        new_entries.append(entry)
            except Exception as exc:
                logger.warning(
                    "ct_log_query_failed log=%s error=%s",
                    log_url,
                    str(exc),
                )

        # Cache and persist
        self.discovered_certs.extend(new_entries)
        self._total_certs_found += len(new_entries)

        if new_entries:
            await self._persist_certificates(new_entries)

        logger.info(
            "ct_check_complete domain=%s new_certs=%d total_known=%d",
            domain,
            len(new_entries),
            len(self._known_fingerprints),
        )

        return new_entries

    async def alert_on_unauthorized(
        self,
        domain: str,
        expected_issuers: Optional[Set[str]] = None,
    ) -> List[CTAlert]:
        """
        Check CT logs for *domain* and generate alerts for unauthorized issuers.

        This method calls :meth:`check_ct_logs` and then evaluates each
        discovered certificate against the set of expected (authorized)
        issuers.  Any certificate whose issuer is not in the approved set
        triggers a critical alert and an event on the hive bus.

        Parameters
        ----------
        domain : str
            Domain to check.
        expected_issuers : set[str], optional
            Override the instance-level expected issuers set.

        Returns
        -------
        list[CTAlert]
            Alerts generated during this check (empty if all certs are
            from authorized issuers).
        """
        issuers = expected_issuers or self._expected_issuers
        if not issuers:
            logger.warning(
                "alert_on_unauthorized called with no expected_issuers — "
                "all certificates will be flagged"
            )

        # Fetch current CT log entries
        entries = await self.check_ct_logs(domain)

        new_alerts: List[CTAlert] = []
        for entry in entries:
            # Determine authorization
            authorized = self._is_issuer_authorized(entry, issuers)
            entry.is_authorized = authorized

            if not authorized:
                self._total_unauthorized += 1

                alert = CTAlert(
                    certificate=entry,
                    alert_type="unauthorized_issuer",
                    severity="critical",
                    message=(
                        f"UNAUTHORIZED CERTIFICATE DETECTED for {domain}! "
                        f"Issuer: {entry.issuer_cn} ({entry.issuer_org}). "
                        f"Serial: {entry.serial_number}. "
                        f"Fingerprint: {entry.sha256_fingerprint[:16]}…"
                    ),
                )
                new_alerts.append(alert)
                self.alerts.append(alert)

                logger.critical(
                    "UNAUTHORIZED_CERT domain=%s issuer=%s org=%s serial=%s",
                    domain,
                    entry.issuer_cn,
                    entry.issuer_org,
                    entry.serial_number,
                )

                # Broadcast to hive event bus
                await self._broadcast_event(
                    "hive.ct.unauthorized_cert",
                    {
                        "alert_id": str(alert.alert_id),
                        "domain": domain,
                        "issuer_cn": entry.issuer_cn,
                        "issuer_org": entry.issuer_org,
                        "serial_number": entry.serial_number,
                        "fingerprint": entry.sha256_fingerprint,
                        "not_before": entry.not_before.isoformat() if entry.not_before else None,
                        "not_after": entry.not_after.isoformat() if entry.not_after else None,
                        "severity": "critical",
                    },
                )

                # Persist alert
                await self._persist_alert(alert)

        if new_alerts:
            logger.warning(
                "ct_unauthorized_alerts domain=%s count=%d",
                domain,
                len(new_alerts),
            )
        else:
            logger.debug(
                "ct_all_authorized domain=%s certs_checked=%d",
                domain,
                len(entries),
            )

        return new_alerts

    # ------------------------------------------------------------------
    # Issuer Authorization
    # ------------------------------------------------------------------

    def _is_issuer_authorized(
        self,
        entry: CTCertificateEntry,
        expected_issuers: Set[str],
    ) -> bool:
        """
        Check if a certificate's issuer is in the authorized set.

        Performs case-insensitive matching against both CN and organization.
        """
        if not expected_issuers:
            return False

        normalized_issuers = {i.lower().strip() for i in expected_issuers}
        cn = entry.issuer_cn.lower().strip()
        org = entry.issuer_org.lower().strip()

        return cn in normalized_issuers or org in normalized_issuers

    def set_expected_issuers(self, issuers: Set[str]) -> None:
        """Update the set of authorized certificate issuers."""
        self._expected_issuers = issuers
        logger.info("ct_expected_issuers_updated issuers=%s", issuers)

    # ------------------------------------------------------------------
    # CT Log Queries
    # ------------------------------------------------------------------

    async def _query_crtsh(self, domain: str) -> List[CTCertificateEntry]:
        """
        Query the crt.sh CT aggregation API for certificates matching *domain*.

        Returns
        -------
        list[CTCertificateEntry]
            Parsed certificate entries.
        """
        entries: List[CTCertificateEntry] = []

        try:
            if self._http_client:
                # Use injected HTTP client (aiohttp or httpx)
                url = f"{CT_SEARCH_API}/?q=%.{domain}&output=json"
                response = await self._http_client.get(url)

                if hasattr(response, "json"):
                    data = await response.json() if asyncio.iscoroutinefunction(response.json) else response.json()
                else:
                    data = []

                if isinstance(data, list):
                    for record in data:
                        entry = CTCertificateEntry(
                            domain=domain,
                            issuer_cn=record.get("issuer_name", ""),
                            issuer_org=self._extract_org_from_issuer(
                                record.get("issuer_name", "")
                            ),
                            serial_number=record.get("serial_number", ""),
                            not_before=self._parse_datetime(
                                record.get("not_before")
                            ),
                            not_after=self._parse_datetime(
                                record.get("not_after")
                            ),
                            log_url=CT_SEARCH_API,
                            log_index=record.get("id", -1),
                            sha256_fingerprint=self._compute_fingerprint(record),
                            raw_entry=record,
                        )
                        entries.append(entry)
            else:
                logger.debug(
                    "ct_crtsh_skipped reason=no_http_client domain=%s",
                    domain,
                )
        except Exception as exc:
            logger.warning("ct_crtsh_query_failed domain=%s error=%s", domain, exc)

        return entries

    async def _query_ct_log(
        self,
        domain: str,
        log_url: str,
    ) -> List[CTCertificateEntry]:
        """
        Query a specific CT log endpoint for certificates matching *domain*.

        This is a simplified implementation; production deployments should
        use the CT log's ``get-entries`` and ``get-sth`` endpoints with
        proper Merkle audit proof verification.

        Returns
        -------
        list[CTCertificateEntry]
            Parsed certificate entries from this log.
        """
        entries: List[CTCertificateEntry] = []

        if not self._http_client:
            return entries

        try:
            url = f"{log_url}ct/v1/get-sth"
            response = await self._http_client.get(url)

            if hasattr(response, "json"):
                sth = await response.json() if asyncio.iscoroutinefunction(response.json) else response.json()
            else:
                sth = {}

            tree_size = sth.get("tree_size", 0)
            if tree_size > 0:
                logger.debug(
                    "ct_log_sth log=%s tree_size=%d",
                    log_url,
                    tree_size,
                )

        except Exception as exc:
            logger.debug("ct_log_sth_failed log=%s error=%s", log_url, exc)

        return entries

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_org_from_issuer(issuer_name: str) -> str:
        """Extract the O= (Organization) field from an issuer DN string."""
        for part in issuer_name.split(","):
            part = part.strip()
            if part.upper().startswith("O="):
                return part[2:].strip()
        return ""

    @staticmethod
    def _compute_fingerprint(record: Dict[str, Any]) -> str:
        """Compute a SHA-256 fingerprint for deduplication."""
        key_material = (
            f"{record.get('serial_number', '')}:"
            f"{record.get('issuer_name', '')}:"
            f"{record.get('not_before', '')}:"
            f"{record.get('not_after', '')}"
        )
        return hashlib.sha256(key_material.encode()).hexdigest()

    @staticmethod
    def _parse_datetime(value: Any) -> Optional[datetime]:
        """Parse a datetime string from CT log response."""
        if value is None:
            return None
        if isinstance(value, datetime):
            return value
        try:
            return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except (ValueError, TypeError):
            return None

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    async def _persist_certificates(
        self,
        entries: List[CTCertificateEntry],
    ) -> None:
        """Persist discovered certificates to the database."""
        if not self._db_pool:
            return

        try:
            async with self._db_pool.acquire() as conn:
                for entry in entries:
                    await conn.execute(
                        """
                        INSERT INTO hive_ct_certificates (
                            entry_id, domain, issuer_cn, issuer_org,
                            serial_number, not_before, not_after,
                            log_url, sha256_fingerprint, is_authorized,
                            discovered_at
                        ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)
                        ON CONFLICT (sha256_fingerprint) DO NOTHING
                        """,
                        entry.entry_id,
                        entry.domain,
                        entry.issuer_cn,
                        entry.issuer_org,
                        entry.serial_number,
                        entry.not_before,
                        entry.not_after,
                        entry.log_url,
                        entry.sha256_fingerprint,
                        entry.is_authorized,
                        entry.discovered_at,
                    )
            logger.debug("ct_persisted_certs count=%d", len(entries))
        except Exception as exc:
            logger.error("ct_persist_failed error=%s", exc)

    async def _persist_alert(self, alert: CTAlert) -> None:
        """Persist a CT alert to the database."""
        if not self._db_pool:
            return

        try:
            async with self._db_pool.acquire() as conn:
                await conn.execute(
                    """
                    INSERT INTO hive_ct_alerts (
                        alert_id, certificate_fingerprint, alert_type,
                        severity, message, created_at
                    ) VALUES ($1, $2, $3, $4, $5, $6)
                    """,
                    alert.alert_id,
                    alert.certificate.sha256_fingerprint,
                    alert.alert_type,
                    alert.severity,
                    alert.message,
                    alert.created_at,
                )
        except Exception as exc:
            logger.error("ct_alert_persist_failed error=%s", exc)

    # ------------------------------------------------------------------
    # Event bus
    # ------------------------------------------------------------------

    async def _broadcast_event(
        self,
        topic: str,
        payload: Dict[str, Any],
    ) -> None:
        """Broadcast a CT monitoring event via the registered callback."""
        if self._event_callback:
            try:
                await self._event_callback(topic, payload)
            except Exception as exc:
                logger.error("ct_event_broadcast_failed topic=%s error=%s", topic, exc)

    # ------------------------------------------------------------------
    # Diagnostics
    # ------------------------------------------------------------------

    @property
    def stats(self) -> Dict[str, Any]:
        """Diagnostic statistics for monitoring dashboards."""
        return {
            "total_checks": self._total_checks,
            "total_certs_found": self._total_certs_found,
            "total_unauthorized": self._total_unauthorized,
            "known_fingerprints": len(self._known_fingerprints),
            "pending_alerts": len([a for a in self.alerts if not a.acknowledged]),
            "last_check": self._last_check.isoformat() if self._last_check else None,
            "expected_issuers": list(self._expected_issuers),
        }

    def __repr__(self) -> str:
        return (
            f"<CTMonitor checks={self._total_checks} "
            f"certs={self._total_certs_found} "
            f"unauthorized={self._total_unauthorized}>"
        )
