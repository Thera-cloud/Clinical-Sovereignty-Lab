"""
HIVE DEFENSE PROTOCOL — Certificate Pinning Configuration (Phase 8B)
TLS certificate management: provides SHA-256 pin hashes for the Flutter
app, mutual-TLS configuration for internal services, DNSSEC/CAA record
definitions, and certificate verification/rotation utilities.

Patent-Pending — Claims 30-56
© 2026 Clinical Sovereignty Lab. All rights reserved.
"""

from __future__ import annotations

import base64
import hashlib
import json
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import structlog

logger = structlog.get_logger("hive.cert_pinning")


# =============================================================================
# CONSTANTS
# =============================================================================

# Minimum TLS version allowed across the platform.
MINIMUM_TLS_VERSION: str = "1.3"

# Certificate Transparency log servers that must be honoured.
CT_LOG_SERVERS: List[str] = [
    "ct.googleapis.com/logs/argon2025",
    "ct.cloudflare.com/logs/nimbus2025",
    "yeti2025.ct.digicert.com/log",
]

# CAA records restrict which CAs can issue certificates for our domains.
CAA_RECORDS: List[Dict[str, str]] = [
    {"flag": "0", "tag": "issue", "value": "letsencrypt.org"},
    {"flag": "0", "tag": "issuewild", "value": ";"},  # Deny wildcard from others
    {"flag": "0", "tag": "iodef", "value": "mailto:security@sovereignsanctuary.net"},
]

# Internal service endpoints that use mutual TLS.
MTLS_INTERNAL_SERVICES: List[str] = [
    "nate_backend",
    "nate_bridge",
    "nate_admin",
    "nate_postgres",
    "nate_redis",
]


# =============================================================================
# CERT PINNING CONFIG
# =============================================================================

class CertPinningConfig:
    """
    TLS certificate pinning and mutual-TLS configuration manager.

    Provides:
    * SHA-256 SPKI pin hashes for Flutter app certificate pinning.
    * Mutual-TLS (mTLS) configuration for internal service-to-service comms.
    * DNSSEC and CAA record definitions for DNS-level certificate control.
    * Certificate verification against expected pin hashes.
    * Pin rotation when certificates are renewed.

    Parameters
    ----------
    db_pool : Any, optional
        asyncpg connection pool for pin-hash persistence and audit logging.
    forensic_logger : Any, optional
        Reference to :class:`ForensicLogger` for immutable audit records.
    """

    def __init__(
        self,
        db_pool: Any = None,
        forensic_logger: Any = None,
    ) -> None:
        self.db_pool = db_pool
        self.forensic_logger = forensic_logger

        # In-memory pin store (domain → list of SHA-256 base64 pin hashes)
        self._pin_hashes: Dict[str, List[str]] = {}

        # mTLS certificate paths (service_name → cert/key paths)
        self._mtls_certs: Dict[str, Dict[str, str]] = {}

        # Audit trail
        self._rotation_history: List[Dict[str, Any]] = []

    # ------------------------------------------------------------------
    # Flutter Pin Hashes
    # ------------------------------------------------------------------

    async def get_flutter_pin_hashes(self) -> List[Dict[str, Any]]:
        """Return SHA-256 SPKI pin hashes for the Flutter mobile app.

        These hashes are embedded in the Flutter ``http_certificate_pinning``
        configuration to ensure the app only communicates with servers
        presenting the expected certificate chain.

        Returns
        -------
        list[dict]
            Each entry: ``domain``, ``pin_sha256`` (base64), ``backup_pin``
            (base64), ``include_subdomains``, ``max_age``.
        """
        # Load from DB if available
        pins = await self._load_pins_from_db()
        if pins:
            return pins

        # Fallback: return configured pins from memory
        results: List[Dict[str, Any]] = []
        for domain, hashes in self._pin_hashes.items():
            entry = {
                "domain": domain,
                "pin_sha256": hashes[0] if hashes else "",
                "backup_pin": hashes[1] if len(hashes) > 1 else "",
                "include_subdomains": True,
                "max_age": 2592000,  # 30 days
                "report_uri": "https://app.sovereignsanctuary.net/api/hpkp-report",
            }
            results.append(entry)

        logger.info("flutter_pins_retrieved", domains=len(results))
        return results

    async def register_pin(
        self,
        domain: str,
        pin_sha256: str,
        backup_pin: Optional[str] = None,
    ) -> None:
        """Register a pin hash for a domain.

        Parameters
        ----------
        domain : str
            The domain (e.g. ``"app.sovereignsanctuary.net"``).
        pin_sha256 : str
            Base64-encoded SHA-256 SPKI pin hash.
        backup_pin : str, optional
            A secondary backup pin hash.
        """
        hashes = [pin_sha256]
        if backup_pin:
            hashes.append(backup_pin)
        self._pin_hashes[domain] = hashes

        if self.db_pool:
            try:
                async with self.db_pool.acquire() as conn:
                    await conn.execute(
                        """
                        INSERT INTO cert_pin_hashes (domain, pin_sha256, backup_pin, updated_at)
                        VALUES ($1, $2, $3, NOW())
                        ON CONFLICT (domain) DO UPDATE
                        SET pin_sha256 = $2, backup_pin = $3, updated_at = NOW()
                        """,
                        domain, pin_sha256, backup_pin,
                    )
            except Exception as exc:
                logger.debug("pin_register_db_failed", error=str(exc))

        logger.info("pin_registered", domain=domain, pin=pin_sha256[:16])

    # ------------------------------------------------------------------
    # Mutual TLS Configuration
    # ------------------------------------------------------------------

    async def get_mtls_config(self) -> Dict[str, Any]:
        """Return the mutual-TLS configuration for internal services.

        Returns
        -------
        dict
            ``services`` (per-service cert/key paths and CA),
            ``minimum_tls_version``, ``cipher_suites``, ``require_client_cert``.
        """
        services: Dict[str, Any] = {}

        for service in MTLS_INTERNAL_SERVICES:
            cert_info = self._mtls_certs.get(service, {})
            services[service] = {
                "cert_path": cert_info.get("cert_path", f"/etc/ssl/certs/{service}.pem"),
                "key_path": cert_info.get("key_path", f"/etc/ssl/private/{service}-key.pem"),
                "ca_path": cert_info.get("ca_path", "/etc/ssl/certs/sanctuary-ca.pem"),
                "verify_peer": True,
                "verify_hostname": True,
            }

        config = {
            "services": services,
            "minimum_tls_version": MINIMUM_TLS_VERSION,
            "cipher_suites": [
                "TLS_AES_256_GCM_SHA384",
                "TLS_CHACHA20_POLY1305_SHA256",
                "TLS_AES_128_GCM_SHA256",
            ],
            "require_client_cert": True,
            "cert_rotation_days": 90,
            "ocsp_stapling": True,
            "ct_log_servers": CT_LOG_SERVERS,
        }

        logger.info("mtls_config_retrieved", services=len(services))
        return config

    def register_mtls_cert(
        self,
        service_name: str,
        cert_path: str,
        key_path: str,
        ca_path: Optional[str] = None,
    ) -> None:
        """Register mTLS certificate paths for an internal service."""
        self._mtls_certs[service_name] = {
            "cert_path": cert_path,
            "key_path": key_path,
            "ca_path": ca_path or "/etc/ssl/certs/sanctuary-ca.pem",
        }
        logger.info("mtls_cert_registered", service=service_name)

    # ------------------------------------------------------------------
    # DNSSEC / CAA Records
    # ------------------------------------------------------------------

    async def get_dnssec_records(self) -> Dict[str, Any]:
        """Return the DNSSEC and CAA record configuration.

        Returns
        -------
        dict
            ``caa_records``, ``dnssec_enabled``, ``ds_records``,
            ``dane_tlsa_records``.
        """
        return {
            "dnssec_enabled": True,
            "caa_records": CAA_RECORDS,
            "ds_records": [
                {
                    "key_tag": "auto",
                    "algorithm": 13,  # ECDSAP256SHA256
                    "digest_type": 2,  # SHA-256
                    "digest": "managed_by_registrar",
                },
            ],
            "dane_tlsa_records": [
                {
                    "usage": 3,        # DANE-EE
                    "selector": 1,     # SubjectPublicKeyInfo
                    "matching_type": 1, # SHA-256
                    "certificate_association_data": "computed_from_live_cert",
                },
            ],
            "domains": [
                "sovereignsanctuary.net",
                "app.sovereignsanctuary.net",
                "coach.sovereignsanctuary.net",
                "command.sovereignsanctuary.net",
            ],
        }

    # ------------------------------------------------------------------
    # Certificate Verification
    # ------------------------------------------------------------------

    async def verify_certificate(
        self, cert_pem: str, expected_pin: str,
    ) -> Dict[str, Any]:
        """Verify a PEM-encoded certificate against an expected pin hash.

        Computes the SHA-256 hash of the certificate's Subject Public Key
        Info (SPKI) and compares it against ``expected_pin`` (base64).

        Parameters
        ----------
        cert_pem : str
            PEM-encoded certificate.
        expected_pin : str
            Base64-encoded SHA-256 SPKI pin hash.

        Returns
        -------
        dict
            ``valid``, ``computed_pin``, ``expected_pin``, ``match``.
        """
        try:
            computed_pin = self._compute_spki_pin(cert_pem)
        except Exception as exc:
            logger.error("cert_pin_computation_failed", error=str(exc))
            return {
                "valid": False,
                "error": str(exc),
                "expected_pin": expected_pin,
            }

        match = computed_pin == expected_pin
        result = {
            "valid": match,
            "computed_pin": computed_pin,
            "expected_pin": expected_pin,
            "match": match,
            "verified_at": datetime.now(tz=timezone.utc).isoformat(),
        }

        if not match:
            logger.warning(
                "cert_pin_mismatch",
                computed=computed_pin[:16],
                expected=expected_pin[:16],
            )
            # Log forensic evidence
            if self.forensic_logger:
                try:
                    await self.forensic_logger.log_event(
                        event_type="hive.cert.pin_mismatch",
                        evidence={
                            "computed_pin": computed_pin,
                            "expected_pin": expected_pin,
                        },
                    )
                except Exception as log_exc:
                    logger.debug("forensic_log_failed", error=str(log_exc))

        return result

    # ------------------------------------------------------------------
    # Pin Rotation
    # ------------------------------------------------------------------

    async def rotate_pins(
        self,
        new_cert_pem: str,
        domain: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Rotate pin hashes for an upcoming certificate change.

        The old pin is demoted to backup and the new pin becomes primary.
        This should be executed *before* the certificate is deployed so
        that Flutter apps can accept both the old and new certificate
        during the rollover window.

        Parameters
        ----------
        new_cert_pem : str
            PEM-encoded new certificate.
        domain : str, optional
            The domain to update.  If ``None``, updates all registered domains.

        Returns
        -------
        dict
            ``domain``, ``old_pin``, ``new_pin``, ``rotated_at``.
        """
        new_pin = self._compute_spki_pin(new_cert_pem)
        results: List[Dict[str, Any]] = []

        target_domains = [domain] if domain else list(self._pin_hashes.keys())

        for d in target_domains:
            old_hashes = self._pin_hashes.get(d, [])
            old_primary = old_hashes[0] if old_hashes else ""

            # New primary = new cert, backup = old primary
            self._pin_hashes[d] = [new_pin, old_primary] if old_primary else [new_pin]

            # Persist
            if self.db_pool:
                try:
                    async with self.db_pool.acquire() as conn:
                        await conn.execute(
                            """
                            INSERT INTO cert_pin_hashes (domain, pin_sha256, backup_pin, updated_at)
                            VALUES ($1, $2, $3, NOW())
                            ON CONFLICT (domain) DO UPDATE
                            SET pin_sha256 = $2, backup_pin = $3, updated_at = NOW()
                            """,
                            d, new_pin, old_primary,
                        )
                except Exception as exc:
                    logger.debug("pin_rotation_db_failed", error=str(exc))

            rotation_record = {
                "domain": d,
                "old_pin": old_primary,
                "new_pin": new_pin,
                "rotated_at": datetime.now(tz=timezone.utc).isoformat(),
            }
            results.append(rotation_record)
            self._rotation_history.append(rotation_record)

        logger.info(
            "pins_rotated",
            domains=len(results),
            new_pin=new_pin[:16],
        )

        return {
            "rotations": results,
            "total_rotated": len(results),
        }

    # ------------------------------------------------------------------
    # Internal: SPKI pin computation
    # ------------------------------------------------------------------

    @staticmethod
    def _compute_spki_pin(cert_pem: str) -> str:
        """Compute the SHA-256 SPKI pin hash from a PEM certificate.

        This extracts the DER-encoded SubjectPublicKeyInfo from the PEM
        certificate, hashes it with SHA-256, and returns the base64-encoded
        result — the standard format for HTTP Public Key Pinning (HPKP)
        and certificate pinning in mobile apps.

        Parameters
        ----------
        cert_pem : str
            PEM-encoded certificate string.

        Returns
        -------
        str
            Base64-encoded SHA-256 hash of the SPKI.
        """
        try:
            # Try using cryptography library if available
            from cryptography import x509
            from cryptography.hazmat.primitives.serialization import (
                Encoding,
                PublicFormat,
            )

            cert = x509.load_pem_x509_certificate(cert_pem.encode("utf-8"))
            spki_der = cert.public_key().public_bytes(
                Encoding.DER,
                PublicFormat.SubjectPublicKeyInfo,
            )
            digest = hashlib.sha256(spki_der).digest()
            return base64.b64encode(digest).decode("ascii")

        except ImportError:
            # Fallback: hash the entire PEM-decoded DER (less precise but functional)
            logger.warning(
                "cryptography_library_unavailable",
                msg="Falling back to full-cert hash (install 'cryptography' for SPKI extraction)",
            )
            # Strip PEM headers and decode
            pem_lines = cert_pem.strip().splitlines()
            der_lines = [
                ln for ln in pem_lines
                if not ln.startswith("-----")
            ]
            der_bytes = base64.b64decode("".join(der_lines))
            digest = hashlib.sha256(der_bytes).digest()
            return base64.b64encode(digest).decode("ascii")

    # ------------------------------------------------------------------
    # Internal: load pins from DB
    # ------------------------------------------------------------------

    async def _load_pins_from_db(self) -> List[Dict[str, Any]]:
        """Load pin hashes from the database."""
        if not self.db_pool:
            return []

        try:
            async with self.db_pool.acquire() as conn:
                rows = await conn.fetch("""
                    SELECT domain, pin_sha256, backup_pin, updated_at
                    FROM cert_pin_hashes
                    WHERE active = true
                    ORDER BY domain
                """)
                results = []
                for row in rows:
                    results.append({
                        "domain": row["domain"],
                        "pin_sha256": row["pin_sha256"],
                        "backup_pin": row["backup_pin"] or "",
                        "include_subdomains": True,
                        "max_age": 2592000,
                        "report_uri": "https://app.sovereignsanctuary.net/api/hpkp-report",
                        "updated_at": row["updated_at"].isoformat() if row["updated_at"] else None,
                    })
                return results
        except Exception as exc:
            logger.debug("pin_load_db_failed", error=str(exc))
            return []

    # ------------------------------------------------------------------
    # Diagnostics
    # ------------------------------------------------------------------

    @property
    def stats(self) -> Dict[str, Any]:
        """Diagnostic statistics."""
        return {
            "domains_pinned": len(self._pin_hashes),
            "mtls_services": len(self._mtls_certs),
            "rotations_performed": len(self._rotation_history),
        }

    def __repr__(self) -> str:
        return (
            f"<CertPinningConfig "
            f"domains={len(self._pin_hashes)} "
            f"mtls_services={len(self._mtls_certs)}>"
        )
