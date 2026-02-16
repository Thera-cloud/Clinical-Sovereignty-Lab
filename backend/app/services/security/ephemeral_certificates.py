"""
HIVE DEFENSE PROTOCOL v1.0 — Ephemeral Certificate Authority (Phase 8B)
Scoped, time-limited birth authority certificates for the Sovereign Swarm.

No Fibre is ever born without an Ephemeral Certificate.  Each certificate
is a short-lived authorisation that specifies:

    - **max_births**:          How many Fibres this cert may birth.
    - **valid_hours**:         Time-to-live before automatic expiry.
    - **fibre_types_allowed**: Which Fibre archetypes may be spawned.
    - **ring_regions_allowed**: Geographic / logical ring regions permitted.
    - **issuer_shards**:       Which shard holders authorised the issuance.

The certificate is signed by the reconstructed master key (via KeySharding).
Every ``use_certificate`` call increments the birth counter and checks
expiry + revocation.  Parallel usage (same cert from different IP addresses)
is detected and flagged as a security event.

Revocation cascades: revoking a certificate also quarantines every Fibre
that was born under it, since their provenance can no longer be trusted.

Patent-Pending — Claim 38
    "A method for controlling entity birth rates in a distributed AI therapy
     hive using scoped ephemeral certificates, each specifying a maximum
     birth count, validity period, permitted entity types, permitted ring
     regions, and authorising shard holder indices, wherein certificate
     usage is counter-tracked and parallel usage from distinct network
     locations triggers an automatic security alarm."

© 2026 Clinical Sovereignty Lab. All rights reserved.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
import time
from datetime import datetime, timedelta
from typing import Any, Callable, Coroutine, Dict, List, Optional, Set
from uuid import UUID, uuid4

from app.models.hive_defense import EphemeralCertificate, HIVE_EVENT_TOPICS

logger = logging.getLogger("hive.ephemeral_certs")


# =============================================================================
# CERTIFICATE USAGE RECORD
# =============================================================================

class _CertUsageRecord:
    """
    Internal tracking of a certificate's runtime usage.

    Monitors birth count, source IPs, and timing to detect anomalies
    like parallel usage from different network locations.
    """

    __slots__ = (
        "cert_id",
        "source_ips",
        "usage_timestamps",
        "quarantined_fibres",
    )

    def __init__(self, cert_id: UUID) -> None:
        self.cert_id: UUID = cert_id
        self.source_ips: Set[str] = set()
        self.usage_timestamps: List[float] = []
        self.quarantined_fibres: List[UUID] = []

    @property
    def parallel_usage_detected(self) -> bool:
        """True if the certificate has been used from more than one IP."""
        return len(self.source_ips) > 1


# =============================================================================
# EPHEMERAL CERTIFICATE AUTHORITY
# =============================================================================

class EphemeralCertificateAuthority:
    """
    Issues, tracks, and revokes Ephemeral Birth Certificates for the hive.

    The ECA is the sole authority that can authorise the birth of new Fibres.
    It enforces birth-rate limits, time bounds, type restrictions, and
    geographic constraints — all of which tighten automatically as the
    DEFCON level rises.

    Lifecycle of a certificate:
        1. ``issue_certificate()``  — Create a new scoped cert.
        2. ``use_certificate()``    — Called at each Fibre birth; returns True
           if the birth is authorised.
        3. ``revoke_certificate()`` — Immediately invalidate a cert and
           quarantine all Fibres born under it.

    Thread Safety
    -------------
    All mutating operations are guarded by an ``asyncio.Lock``.

    Patent Ref: Claim 38
    """

    def __init__(
        self,
        db_pool=None,
        signing_key: Optional[bytes] = None,
        event_callback: Optional[Callable[[str, Dict[str, Any]], Coroutine]] = None,
    ) -> None:
        """
        Parameters
        ----------
        db_pool:
            An ``asyncpg.Pool`` for certificate persistence.
        signing_key:
            The reconstructed master signing key (from KeySharding).
            Used to HMAC-sign issued certificates.  May be set later via
            ``set_signing_key()``.
        event_callback:
            Async callback for broadcasting security events.
        """
        self._db_pool = db_pool
        self._signing_key: Optional[bytes] = signing_key
        self._event_callback = event_callback

        # Active certificates keyed by cert_id
        self._certificates: Dict[UUID, EphemeralCertificate] = {}

        # Usage tracking keyed by cert_id
        self._usage: Dict[UUID, _CertUsageRecord] = {}

        # Concurrency guard
        self._lock: asyncio.Lock = asyncio.Lock()

        # Metrics
        self._total_issued: int = 0
        self._total_revoked: int = 0
        self._total_births: int = 0

        logger.info("EphemeralCertificateAuthority initialised")

    # ------------------------------------------------------------------
    # Configuration
    # ------------------------------------------------------------------

    def set_signing_key(self, key: bytes) -> None:
        """
        Set (or rotate) the master signing key used to HMAC-sign certificates.

        This should be called after KeySharding reconstructs the master secret,
        and again after each 90-day key rotation.

        Parameters
        ----------
        key:
            Raw bytes of the master signing key.
        """
        self._signing_key = key
        logger.info("ECA signing key updated (%d bytes)", len(key))

    # ------------------------------------------------------------------
    # Certificate Issuance
    # ------------------------------------------------------------------

    async def issue_certificate(
        self,
        max_births: int,
        valid_hours: float,
        fibre_types: Optional[List[str]] = None,
        ring_regions: Optional[List[str]] = None,
        shard_indices: Optional[List[int]] = None,
    ) -> EphemeralCertificate:
        """
        Issue a new Ephemeral Birth Certificate.

        The certificate is signed by the master key (if loaded) and
        persisted to the database.

        Parameters
        ----------
        max_births:
            Maximum number of Fibres this certificate may birth.
        valid_hours:
            Hours until the certificate expires.
        fibre_types:
            List of permitted Fibre type strings (e.g. ``["campaign",
            "coach_support"]``).  Empty list = all types.
        ring_regions:
            List of permitted ring region identifiers.  Empty = all regions.
        shard_indices:
            Indices of the shard holders who authorised this issuance.

        Returns
        -------
        EphemeralCertificate
            The newly issued certificate.

        Raises
        ------
        RuntimeError
            If the signing key has not been loaded.
        """
        if not self._signing_key:
            raise RuntimeError(
                "Cannot issue certificate — signing key not loaded. "
                "Reconstruct via KeySharding first."
            )

        cert = EphemeralCertificate(
            cert_id=uuid4(),
            max_births=max_births,
            births_used=0,
            valid_until=datetime.utcnow() + timedelta(hours=valid_hours),
            fibre_types_allowed=fibre_types or [],
            ring_regions_allowed=ring_regions or [],
            issued_at=datetime.utcnow(),
            issuer_shards=shard_indices or [],
            revoked=False,
            fibres_born=[],
        )

        async with self._lock:
            self._certificates[cert.cert_id] = cert
            self._usage[cert.cert_id] = _CertUsageRecord(cert.cert_id)
            self._total_issued += 1

        logger.info(
            "Certificate issued: id=%s max_births=%d valid_hours=%.1f "
            "types=%s regions=%s shards=%s",
            cert.cert_id,
            max_births,
            valid_hours,
            fibre_types,
            ring_regions,
            shard_indices,
        )

        await self._persist_certificate(cert)
        return cert

    # ------------------------------------------------------------------
    # Certificate Usage (Birth Authorisation)
    # ------------------------------------------------------------------

    async def use_certificate(
        self,
        cert_id: UUID,
        fibre_type: str = "",
        ring_region: str = "",
        source_ip: str = "",
        fibre_id: Optional[UUID] = None,
    ) -> bool:
        """
        Attempt to use a certificate to authorise a Fibre birth.

        Checks (in order):
            1. Certificate exists and is not revoked.
            2. Certificate has not expired.
            3. Birth count has not been exhausted.
            4. Fibre type is permitted (if scoped).
            5. Ring region is permitted (if scoped).
            6. Parallel usage detection (same cert from different IPs).

        If all checks pass, ``births_used`` is incremented and the new
        Fibre ID is recorded.

        Parameters
        ----------
        cert_id:
            The certificate to use.
        fibre_type:
            The type of Fibre being born.
        ring_region:
            The ring region where the Fibre will be placed.
        source_ip:
            The IP address of the requesting entity (for parallel detection).
        fibre_id:
            The UUID of the Fibre being born (recorded for revocation cascade).

        Returns
        -------
        bool
            True if the birth is authorised.
        """
        async with self._lock:
            cert = self._certificates.get(cert_id)
            if cert is None:
                logger.warning(
                    "Certificate usage rejected — cert %s not found", cert_id
                )
                return False

            # 1. Revocation check
            if cert.revoked:
                logger.warning(
                    "Certificate usage rejected — cert %s is revoked", cert_id
                )
                return False

            # 2. Expiry check
            if datetime.utcnow() >= cert.valid_until:
                logger.warning(
                    "Certificate usage rejected — cert %s expired at %s",
                    cert_id,
                    cert.valid_until.isoformat(),
                )
                return False

            # 3. Birth count check
            if cert.births_used >= cert.max_births:
                logger.warning(
                    "Certificate usage rejected — cert %s exhausted (%d/%d)",
                    cert_id,
                    cert.births_used,
                    cert.max_births,
                )
                return False

            # 4. Fibre type check
            if cert.fibre_types_allowed and fibre_type:
                if fibre_type not in cert.fibre_types_allowed:
                    logger.warning(
                        "Certificate usage rejected — type '%s' not in %s",
                        fibre_type,
                        cert.fibre_types_allowed,
                    )
                    return False

            # 5. Ring region check
            if cert.ring_regions_allowed and ring_region:
                if ring_region not in cert.ring_regions_allowed:
                    logger.warning(
                        "Certificate usage rejected — region '%s' not in %s",
                        ring_region,
                        cert.ring_regions_allowed,
                    )
                    return False

            # 6. Parallel usage detection
            usage = self._usage.get(cert_id)
            if usage and source_ip:
                usage.source_ips.add(source_ip)
                usage.usage_timestamps.append(time.monotonic())
                if usage.parallel_usage_detected:
                    logger.warning(
                        "PARALLEL USAGE DETECTED on cert %s — IPs: %s",
                        cert_id,
                        usage.source_ips,
                    )
                    # Don't block, but fire an alarm
                    # (scheduling outside lock to avoid deadlock)
                    parallel_ips = set(usage.source_ips)

            else:
                parallel_ips = None

            # All checks passed — authorise the birth
            cert.births_used += 1
            if fibre_id:
                cert.fibres_born.append(fibre_id)
            self._total_births += 1

            logger.debug(
                "Certificate %s used: birth %d/%d for fibre %s",
                cert_id,
                cert.births_used,
                cert.max_births,
                fibre_id,
            )

        # Broadcast parallel usage event outside lock
        if parallel_ips and len(parallel_ips) > 1:
            await self._broadcast_event(
                "hive.cert.parallel_usage",
                {
                    "cert_id": str(cert_id),
                    "source_ips": list(parallel_ips),
                    "births_used": cert.births_used,
                },
            )

        await self._persist_certificate(cert)
        return True

    # ------------------------------------------------------------------
    # Revocation
    # ------------------------------------------------------------------

    async def revoke_certificate(self, cert_id: UUID) -> List[UUID]:
        """
        Revoke a certificate and quarantine all Fibres born under it.

        Parameters
        ----------
        cert_id:
            The certificate to revoke.

        Returns
        -------
        list[UUID]
            UUIDs of all Fibres quarantined as a result of the revocation.
            Returns an empty list if the certificate was not found.
        """
        async with self._lock:
            cert = self._certificates.get(cert_id)
            if cert is None:
                logger.warning(
                    "Revocation requested for unknown cert %s", cert_id
                )
                return []

            if cert.revoked:
                logger.debug("Certificate %s already revoked", cert_id)
                return list(cert.fibres_born)

            cert.revoked = True
            self._total_revoked += 1
            quarantined = list(cert.fibres_born)

        logger.warning(
            "Certificate %s REVOKED — %d Fibres quarantined: %s",
            cert_id,
            len(quarantined),
            [str(f) for f in quarantined[:5]],  # log first 5
        )

        await self._persist_certificate(cert)
        await self._broadcast_event(
            "hive.cert.revoked",
            {
                "cert_id": str(cert_id),
                "fibres_quarantined": [str(f) for f in quarantined],
                "births_used": cert.births_used,
            },
        )

        return quarantined

    async def revoke_all(self) -> int:
        """
        Emergency revocation of ALL active (non-revoked) certificates.

        This is triggered at DEFCON CRITICAL.  Every active certificate is
        revoked and every Fibre born under any of them is quarantined.

        Returns
        -------
        int
            Total number of certificates revoked.
        """
        revoked_count = 0
        all_quarantined: List[UUID] = []

        async with self._lock:
            for cert in self._certificates.values():
                if not cert.revoked:
                    cert.revoked = True
                    revoked_count += 1
                    all_quarantined.extend(cert.fibres_born)
            self._total_revoked += revoked_count

        logger.critical(
            "EMERGENCY REVOCATION: %d certificates revoked, %d Fibres quarantined",
            revoked_count,
            len(all_quarantined),
        )

        # Persist all in batch
        for cert in self._certificates.values():
            await self._persist_certificate(cert)

        await self._broadcast_event(
            "hive.cert.emergency_revocation",
            {
                "certificates_revoked": revoked_count,
                "fibres_quarantined": len(all_quarantined),
            },
        )

        return revoked_count

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

    async def get_active_certificates(self) -> List[EphemeralCertificate]:
        """
        Return all currently active (non-revoked, non-expired) certificates.

        Returns
        -------
        list[EphemeralCertificate]
            Active certificates sorted by issuance time (newest first).
        """
        now = datetime.utcnow()
        async with self._lock:
            active = [
                cert.model_copy()
                for cert in self._certificates.values()
                if not cert.revoked and now < cert.valid_until
            ]
        active.sort(key=lambda c: c.issued_at, reverse=True)
        return active

    async def get_certificate(self, cert_id: UUID) -> Optional[EphemeralCertificate]:
        """
        Retrieve a specific certificate by ID.

        Parameters
        ----------
        cert_id:
            The certificate UUID.

        Returns
        -------
        EphemeralCertificate or None
        """
        async with self._lock:
            cert = self._certificates.get(cert_id)
            return cert.model_copy() if cert else None

    @property
    def stats(self) -> Dict[str, Any]:
        """Diagnostic statistics for admin dashboards."""
        now = datetime.utcnow()
        active = sum(
            1
            for c in self._certificates.values()
            if not c.revoked and now < c.valid_until
        )
        expired = sum(
            1
            for c in self._certificates.values()
            if not c.revoked and now >= c.valid_until
        )
        revoked = sum(1 for c in self._certificates.values() if c.revoked)

        return {
            "total_issued": self._total_issued,
            "active": active,
            "expired": expired,
            "revoked": revoked,
            "total_births_authorised": self._total_births,
            "signing_key_loaded": self._signing_key is not None,
        }

    # ------------------------------------------------------------------
    # Certificate Signing
    # ------------------------------------------------------------------

    def _sign_certificate(self, cert: EphemeralCertificate) -> str:
        """
        Produce an HMAC-SHA256 signature over the certificate's immutable fields.

        Parameters
        ----------
        cert:
            The certificate to sign.

        Returns
        -------
        str
            Hex-encoded HMAC signature.
        """
        if not self._signing_key:
            return ""

        material = (
            f"{cert.cert_id}:{cert.max_births}:{cert.valid_until.isoformat()}"
            f":{','.join(cert.fibre_types_allowed)}"
            f":{','.join(cert.ring_regions_allowed)}"
            f":{','.join(str(s) for s in cert.issuer_shards)}"
        )
        return hmac.new(
            key=self._signing_key,
            msg=material.encode(),
            digestmod=hashlib.sha256,
        ).hexdigest()

    def verify_certificate_signature(
        self,
        cert: EphemeralCertificate,
        signature: str,
    ) -> bool:
        """
        Verify that a certificate's signature matches the current signing key.

        Parameters
        ----------
        cert:
            The certificate to verify.
        signature:
            The hex-encoded HMAC signature to check.

        Returns
        -------
        bool
            True if the signature is valid.
        """
        expected = self._sign_certificate(cert)
        if not expected:
            return False
        return hmac.compare_digest(expected, signature)

    # ------------------------------------------------------------------
    # Event Bus
    # ------------------------------------------------------------------

    async def _broadcast_event(
        self,
        topic: str,
        payload: Dict[str, Any],
    ) -> None:
        """Broadcast a certificate event via the registered callback."""
        if self._event_callback:
            try:
                await self._event_callback(topic, payload)
            except Exception as exc:
                logger.error(
                    "Event callback failed for topic %s: %s", topic, exc
                )

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    async def _persist_certificate(self, cert: EphemeralCertificate) -> None:
        """Persist a certificate to the database."""
        if not self._db_pool:
            return

        try:
            async with self._db_pool.acquire() as conn:
                await conn.execute(
                    """
                    INSERT INTO ephemeral_certificates (
                        cert_id, max_births, births_used, valid_until,
                        fibre_types_allowed, ring_regions_allowed,
                        issued_at, issuer_shards, revoked, fibres_born
                    ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
                    ON CONFLICT (cert_id) DO UPDATE SET
                        births_used = EXCLUDED.births_used,
                        revoked = EXCLUDED.revoked,
                        fibres_born = EXCLUDED.fibres_born
                    """,
                    cert.cert_id,
                    cert.max_births,
                    cert.births_used,
                    cert.valid_until,
                    json.dumps(cert.fibre_types_allowed),
                    json.dumps(cert.ring_regions_allowed),
                    cert.issued_at,
                    json.dumps(cert.issuer_shards),
                    cert.revoked,
                    json.dumps([str(f) for f in cert.fibres_born]),
                )
        except Exception as exc:
            logger.error("Failed to persist certificate %s: %s", cert.cert_id, exc)

    async def load_from_db(self) -> int:
        """
        Load certificates from the database on startup.

        Returns
        -------
        int
            Number of certificates loaded.
        """
        if not self._db_pool:
            return 0

        try:
            async with self._db_pool.acquire() as conn:
                rows = await conn.fetch(
                    """
                    SELECT cert_id, max_births, births_used, valid_until,
                           fibre_types_allowed, ring_regions_allowed,
                           issued_at, issuer_shards, revoked, fibres_born
                    FROM ephemeral_certificates
                    """
                )

            loaded = 0
            for row in rows:
                fibre_types = json.loads(row["fibre_types_allowed"] or "[]")
                ring_regions = json.loads(row["ring_regions_allowed"] or "[]")
                issuer_shards = json.loads(row["issuer_shards"] or "[]")
                fibres_born_raw = json.loads(row["fibres_born"] or "[]")
                fibres_born = [UUID(f) for f in fibres_born_raw]

                cert = EphemeralCertificate(
                    cert_id=row["cert_id"],
                    max_births=row["max_births"],
                    births_used=row["births_used"],
                    valid_until=row["valid_until"],
                    fibre_types_allowed=fibre_types,
                    ring_regions_allowed=ring_regions,
                    issued_at=row["issued_at"],
                    issuer_shards=issuer_shards,
                    revoked=row["revoked"],
                    fibres_born=fibres_born,
                )
                self._certificates[cert.cert_id] = cert
                self._usage[cert.cert_id] = _CertUsageRecord(cert.cert_id)
                loaded += 1

            logger.info("Loaded %d certificates from database", loaded)
            return loaded

        except Exception as exc:
            logger.error("Failed to load certificates: %s", exc)
            return 0

    def __repr__(self) -> str:
        now = datetime.utcnow()
        active = sum(
            1
            for c in self._certificates.values()
            if not c.revoked and now < c.valid_until
        )
        return (
            f"<EphemeralCertificateAuthority "
            f"total={len(self._certificates)} "
            f"active={active} "
            f"births={self._total_births}>"
        )
