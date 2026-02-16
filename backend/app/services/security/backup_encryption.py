"""
HIVE DEFENSE PROTOCOL — Backup Encryption Manager (Phase 8B)
Manages encrypted backups: Azure Key Vault CMK configuration, backup
integrity verification, immutable (WORM) storage settings, access
auditing, and freshness monitoring.

Patent-Pending — Claims 30-56
© 2026 Clinical Sovereignty Lab. All rights reserved.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import structlog

logger = structlog.get_logger("hive.backup_encryption")


# =============================================================================
# CONSTANTS
# =============================================================================

# Maximum age before a backup is considered stale (hours).
BACKUP_FRESHNESS_THRESHOLD_HOURS: int = 24

# Azure Key Vault CMK identifier (placeholder — injected from env).
DEFAULT_KEY_VAULT_URL: str = "https://sanctuary-vault.vault.azure.net"
DEFAULT_CMK_NAME: str = "sanctuary-backup-cmk"
DEFAULT_CMK_VERSION: str = "latest"

# WORM retention period (days).
WORM_RETENTION_DAYS: int = 365

# Supported encryption algorithms.
ENCRYPTION_ALGORITHM: str = "AES-256-GCM"
KEY_WRAP_ALGORITHM: str = "RSA-OAEP-256"


# =============================================================================
# BACKUP ENCRYPTION MANAGER
# =============================================================================

class BackupEncryptionManager:
    """
    Encrypted backup management for the Sovereign Sanctuary.

    Provides:
    * Azure Key Vault Customer-Managed Key (CMK) configuration.
    * SHA-256 integrity verification for backup files.
    * Immutable (WORM) storage configuration for compliance.
    * Access auditing — every backup read/write is logged.
    * Freshness monitoring — alerts when backups exceed age thresholds.

    Parameters
    ----------
    db_pool : Any, optional
        asyncpg connection pool for audit logging and metadata storage.
    forensic_logger : Any, optional
        Reference to :class:`ForensicLogger` for evidence-chain logging.
    key_vault_url : str, optional
        Azure Key Vault URL.  Defaults to env var ``AZURE_KEY_VAULT_URL``
        or the built-in default.
    cmk_name : str, optional
        Customer-Managed Key name in Key Vault.
    """

    def __init__(
        self,
        db_pool: Any = None,
        forensic_logger: Any = None,
        key_vault_url: Optional[str] = None,
        cmk_name: Optional[str] = None,
    ) -> None:
        self.db_pool = db_pool
        self.forensic_logger = forensic_logger

        self._key_vault_url = (
            key_vault_url
            or os.getenv("AZURE_KEY_VAULT_URL", DEFAULT_KEY_VAULT_URL)
        )
        self._cmk_name = cmk_name or os.getenv("BACKUP_CMK_NAME", DEFAULT_CMK_NAME)

        # In-memory backup metadata cache
        self._backup_metadata: Dict[str, Dict[str, Any]] = {}

        # Cumulative audit metrics
        self._total_verifications: int = 0
        self._total_failures: int = 0

    # ------------------------------------------------------------------
    # Encryption Configuration
    # ------------------------------------------------------------------

    async def get_encryption_config(self) -> Dict[str, Any]:
        """Return the Azure Key Vault CMK configuration for backup encryption.

        The returned configuration is consumed by the backup pipeline
        to encrypt data at rest using a Customer-Managed Key stored in
        Azure Key Vault.

        Returns
        -------
        dict
            ``key_vault_url``, ``cmk_name``, ``cmk_version``,
            ``encryption_algorithm``, ``key_wrap_algorithm``, and
            associated settings.
        """
        config = {
            "key_vault_url": self._key_vault_url,
            "cmk_name": self._cmk_name,
            "cmk_version": os.getenv("BACKUP_CMK_VERSION", DEFAULT_CMK_VERSION),
            "encryption_algorithm": ENCRYPTION_ALGORITHM,
            "key_wrap_algorithm": KEY_WRAP_ALGORITHM,
            "key_rotation_days": 90,
            "envelope_encryption": True,
            "data_key_caching": {
                "enabled": True,
                "max_age_seconds": 300,
                "max_messages_encrypted": 1000,
            },
            "managed_identity_auth": True,
            "soft_delete_enabled": True,
            "purge_protection_enabled": True,
            "retrieved_at": datetime.now(tz=timezone.utc).isoformat(),
        }

        logger.info(
            "encryption_config_retrieved",
            vault=self._key_vault_url,
            cmk=self._cmk_name,
        )

        return config

    # ------------------------------------------------------------------
    # Backup Integrity Verification
    # ------------------------------------------------------------------

    async def verify_backup_integrity(self, backup_path: str) -> Dict[str, Any]:
        """Verify the integrity of a backup file using SHA-256 checksums.

        Compares the computed hash against the stored hash (from the
        ``backup_metadata`` table or the sidecar ``.sha256`` file).

        Parameters
        ----------
        backup_path : str
            Path to the backup file to verify.

        Returns
        -------
        dict
            ``valid``, ``computed_hash``, ``expected_hash``, ``file_size``,
            ``verified_at``.
        """
        self._total_verifications += 1
        path = Path(backup_path)

        if not path.exists():
            self._total_failures += 1
            logger.warning("backup_not_found", path=backup_path)
            return {
                "valid": False,
                "error": f"Backup file not found: {backup_path}",
                "backup_path": backup_path,
                "verified_at": datetime.now(tz=timezone.utc).isoformat(),
            }

        # Compute SHA-256 of the backup file
        sha256 = hashlib.sha256()
        file_size = 0
        try:
            with open(path, "rb") as f:
                while True:
                    chunk = f.read(8192)
                    if not chunk:
                        break
                    sha256.update(chunk)
                    file_size += len(chunk)
        except OSError as exc:
            self._total_failures += 1
            logger.error("backup_read_failed", path=backup_path, error=str(exc))
            return {
                "valid": False,
                "error": f"Failed to read backup: {exc}",
                "backup_path": backup_path,
                "verified_at": datetime.now(tz=timezone.utc).isoformat(),
            }

        computed_hash = sha256.hexdigest()

        # Load expected hash
        expected_hash = await self._get_expected_hash(backup_path)

        if expected_hash is None:
            # No stored hash — store the computed one as baseline
            await self._store_hash(backup_path, computed_hash, file_size)
            return {
                "valid": True,
                "computed_hash": computed_hash,
                "expected_hash": None,
                "status": "baseline_stored",
                "file_size": file_size,
                "backup_path": backup_path,
                "verified_at": datetime.now(tz=timezone.utc).isoformat(),
            }

        match = computed_hash == expected_hash
        if not match:
            self._total_failures += 1
            logger.error(
                "backup_integrity_failure",
                path=backup_path,
                computed=computed_hash[:16],
                expected=expected_hash[:16],
            )

            # Log forensic evidence
            if self.forensic_logger:
                try:
                    await self.forensic_logger.log_event(
                        event_type="hive.backup.integrity_failure",
                        source_entity=backup_path,
                        evidence={
                            "computed_hash": computed_hash,
                            "expected_hash": expected_hash,
                            "file_size": file_size,
                        },
                    )
                except Exception as exc:
                    logger.debug("forensic_log_failed", error=str(exc))

        result = {
            "valid": match,
            "computed_hash": computed_hash,
            "expected_hash": expected_hash,
            "match": match,
            "file_size": file_size,
            "backup_path": backup_path,
            "verified_at": datetime.now(tz=timezone.utc).isoformat(),
        }

        logger.info(
            "backup_verified",
            path=backup_path,
            valid=match,
            size=file_size,
        )

        return result

    # ------------------------------------------------------------------
    # Immutable (WORM) Storage Configuration
    # ------------------------------------------------------------------

    async def get_immutable_storage_config(self) -> Dict[str, Any]:
        """Return the Write-Once Read-Many (WORM) storage configuration.

        This configuration is consumed by the backup pipeline to ensure
        that backups cannot be modified or deleted before the retention
        period expires — a compliance requirement for clinical data.

        Returns
        -------
        dict
            ``retention_days``, ``legal_hold``, ``immutability_policy``,
            ``versioning``, ``storage_tier``.
        """
        return {
            "retention_days": WORM_RETENTION_DAYS,
            "legal_hold": {
                "enabled": True,
                "policy_name": "sanctuary_clinical_hold",
            },
            "immutability_policy": {
                "type": "time_based",
                "retention_days": WORM_RETENTION_DAYS,
                "allow_protected_append_writes": True,
                "locked": True,
            },
            "versioning": {
                "enabled": True,
                "max_versions": 30,
            },
            "storage_tier": "hot",
            "replication": {
                "type": "geo_redundant",
                "secondary_region": "eastus2",
            },
            "access_tier_transition": {
                "hot_to_cool_days": 30,
                "cool_to_archive_days": 90,
            },
            "encryption": {
                "scope": "infrastructure",
                "key_source": "customer_managed",
                "key_vault_url": self._key_vault_url,
                "cmk_name": self._cmk_name,
            },
        }

    # ------------------------------------------------------------------
    # Backup Access Audit
    # ------------------------------------------------------------------

    async def audit_backup_access(self, pool: Any = None) -> List[Dict[str, Any]]:
        """Retrieve all backup access events from the audit log.

        Parameters
        ----------
        pool : Any, optional
            asyncpg connection pool.  Falls back to ``self.db_pool``.

        Returns
        -------
        list[dict]
            Each entry: ``backup_path``, ``accessed_by``, ``access_type``,
            ``accessed_at``, ``source_ip``.
        """
        db = pool or self.db_pool
        if not db:
            logger.warning("audit_no_db", msg="No database pool for backup audit")
            return []

        try:
            async with db.acquire() as conn:
                rows = await conn.fetch("""
                    SELECT backup_path, accessed_by, access_type,
                           accessed_at, source_ip, metadata
                    FROM backup_access_log
                    ORDER BY accessed_at DESC
                    LIMIT 1000
                """)
                results = []
                for row in rows:
                    results.append({
                        "backup_path": row["backup_path"],
                        "accessed_by": row["accessed_by"],
                        "access_type": row["access_type"],
                        "accessed_at": row["accessed_at"].isoformat(),
                        "source_ip": row["source_ip"],
                        "metadata": json.loads(row["metadata"]) if row["metadata"] else {},
                    })

                logger.info("backup_audit_retrieved", events=len(results))
                return results

        except Exception as exc:
            logger.error("backup_audit_query_failed", error=str(exc))
            return []

    async def log_backup_access(
        self,
        backup_path: str,
        accessed_by: str,
        access_type: str = "read",
        source_ip: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Log a backup access event to the audit trail.

        Parameters
        ----------
        backup_path : str
            Path of the backup that was accessed.
        accessed_by : str
            Identifier of the user or service accessing the backup.
        access_type : str
            ``"read"``, ``"write"``, ``"verify"``, or ``"restore"``.
        source_ip : str, optional
            IP address of the accessor.
        metadata : dict, optional
            Additional context.
        """
        if not self.db_pool:
            return

        try:
            async with self.db_pool.acquire() as conn:
                await conn.execute(
                    """
                    INSERT INTO backup_access_log
                        (backup_path, accessed_by, access_type, accessed_at,
                         source_ip, metadata)
                    VALUES ($1, $2, $3, NOW(), $4, $5)
                    """,
                    backup_path,
                    accessed_by,
                    access_type,
                    source_ip,
                    json.dumps(metadata) if metadata else None,
                )
        except Exception as exc:
            logger.debug("backup_access_log_failed", error=str(exc))

        # Log anomalous backup access to forensic logger
        if access_type == "restore" and self.forensic_logger:
            try:
                await self.forensic_logger.log_event(
                    event_type="hive.backup.anomalous_access",
                    source_entity=accessed_by,
                    target_entity=backup_path,
                    evidence={
                        "access_type": access_type,
                        "source_ip": source_ip,
                        "metadata": metadata,
                    },
                )
            except Exception as exc:
                logger.debug("forensic_log_failed", error=str(exc))

    # ------------------------------------------------------------------
    # Backup Freshness
    # ------------------------------------------------------------------

    async def check_backup_freshness(self) -> Dict[str, Any]:
        """Verify that backups are recent enough to satisfy RPO requirements.

        Checks the ``backup_metadata`` table for the most recent successful
        backup and compares against ``BACKUP_FRESHNESS_THRESHOLD_HOURS``.

        Returns
        -------
        dict
            ``fresh``, ``latest_backup_at``, ``age_hours``, ``threshold_hours``,
            ``stale_backups`` (list of paths exceeding the threshold).
        """
        now = datetime.now(tz=timezone.utc)
        threshold = timedelta(hours=BACKUP_FRESHNESS_THRESHOLD_HOURS)
        stale_backups: List[Dict[str, Any]] = []
        latest_backup_at: Optional[datetime] = None

        if self.db_pool:
            try:
                async with self.db_pool.acquire() as conn:
                    rows = await conn.fetch("""
                        SELECT backup_path, created_at, file_size, sha256_hash
                        FROM backup_metadata
                        WHERE status = 'completed'
                        ORDER BY created_at DESC
                        LIMIT 50
                    """)
                    for row in rows:
                        created = row["created_at"]
                        if created.tzinfo is None:
                            created = created.replace(tzinfo=timezone.utc)

                        if latest_backup_at is None or created > latest_backup_at:
                            latest_backup_at = created

                        age = now - created
                        if age > threshold:
                            stale_backups.append({
                                "backup_path": row["backup_path"],
                                "created_at": created.isoformat(),
                                "age_hours": round(age.total_seconds() / 3600, 1),
                            })
            except Exception as exc:
                logger.error("backup_freshness_query_failed", error=str(exc))
                return {
                    "fresh": False,
                    "error": str(exc),
                    "checked_at": now.isoformat(),
                }

        # Also check in-memory metadata
        for path, meta in self._backup_metadata.items():
            created_ts = meta.get("created_at")
            if created_ts:
                created = datetime.fromtimestamp(created_ts, tz=timezone.utc)
                if latest_backup_at is None or created > latest_backup_at:
                    latest_backup_at = created

        if latest_backup_at is None:
            logger.warning("no_backups_found")
            return {
                "fresh": False,
                "latest_backup_at": None,
                "age_hours": None,
                "threshold_hours": BACKUP_FRESHNESS_THRESHOLD_HOURS,
                "stale_backups": [],
                "warning": "No completed backups found",
                "checked_at": now.isoformat(),
            }

        age_hours = (now - latest_backup_at).total_seconds() / 3600
        fresh = age_hours <= BACKUP_FRESHNESS_THRESHOLD_HOURS

        result = {
            "fresh": fresh,
            "latest_backup_at": latest_backup_at.isoformat(),
            "age_hours": round(age_hours, 1),
            "threshold_hours": BACKUP_FRESHNESS_THRESHOLD_HOURS,
            "stale_backups": stale_backups,
            "checked_at": now.isoformat(),
        }

        if not fresh:
            logger.warning(
                "backup_stale",
                age_hours=round(age_hours, 1),
                threshold=BACKUP_FRESHNESS_THRESHOLD_HOURS,
            )

        return result

    # ------------------------------------------------------------------
    # Internal: hash storage
    # ------------------------------------------------------------------

    async def _get_expected_hash(self, backup_path: str) -> Optional[str]:
        """Retrieve the expected SHA-256 hash for a backup file."""
        # Check in-memory cache first
        meta = self._backup_metadata.get(backup_path)
        if meta and meta.get("sha256_hash"):
            return meta["sha256_hash"]

        # Check sidecar file
        sidecar = Path(f"{backup_path}.sha256")
        if sidecar.exists():
            try:
                return sidecar.read_text(encoding="utf-8").strip().split()[0]
            except OSError:
                pass

        # Check database
        if self.db_pool:
            try:
                async with self.db_pool.acquire() as conn:
                    row = await conn.fetchrow(
                        "SELECT sha256_hash FROM backup_metadata WHERE backup_path = $1",
                        backup_path,
                    )
                    if row and row["sha256_hash"]:
                        return row["sha256_hash"]
            except Exception:
                pass

        return None

    async def _store_hash(
        self, backup_path: str, sha256_hash: str, file_size: int,
    ) -> None:
        """Store the SHA-256 hash for a backup file."""
        now = time.time()
        self._backup_metadata[backup_path] = {
            "sha256_hash": sha256_hash,
            "file_size": file_size,
            "created_at": now,
        }

        if self.db_pool:
            try:
                async with self.db_pool.acquire() as conn:
                    await conn.execute(
                        """
                        INSERT INTO backup_metadata
                            (backup_path, sha256_hash, file_size, status, created_at)
                        VALUES ($1, $2, $3, 'completed', NOW())
                        ON CONFLICT (backup_path) DO UPDATE
                        SET sha256_hash = $2, file_size = $3, updated_at = NOW()
                        """,
                        backup_path, sha256_hash, file_size,
                    )
            except Exception as exc:
                logger.debug("hash_store_failed", error=str(exc))

    # ------------------------------------------------------------------
    # Diagnostics
    # ------------------------------------------------------------------

    @property
    def stats(self) -> Dict[str, Any]:
        """Diagnostic statistics for monitoring dashboards."""
        return {
            "total_verifications": self._total_verifications,
            "total_failures": self._total_failures,
            "backups_tracked": len(self._backup_metadata),
            "key_vault_url": self._key_vault_url,
            "cmk_name": self._cmk_name,
        }

    def __repr__(self) -> str:
        return (
            f"<BackupEncryptionManager "
            f"verified={self._total_verifications} "
            f"failures={self._total_failures} "
            f"tracked={len(self._backup_metadata)}>"
        )
