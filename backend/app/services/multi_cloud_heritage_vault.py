"""
HIVE DEFENSE v4.3 — Multi-Cloud Heritage Vault
Triple-redundant storage for Heritage Vault data across:

1. Azure Blob Storage (primary cloud)
2. AWS S3 (secondary cloud)
3. Local NAS / filesystem (tertiary / air-gap fallback)

Heritage data includes: Legacy recordings, family vault snapshots,
longitudinal research data, and signed guardian fibre snapshots.

Replication is async and non-blocking. If one backend fails, the
others continue independently. Integrity is verified via SHA-256
manifest hashes.
"""

import asyncio
import hashlib
import json
import logging
import os
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

_logger = logging.getLogger("multi_cloud_heritage_vault")

# ─── Configuration ────────────────────────────────────────────────────────────

AZURE_STORAGE_ACCOUNT = os.getenv("AZURE_STORAGE_ACCOUNT", "")
AZURE_STORAGE_KEY = os.getenv("AZURE_STORAGE_KEY", "")
AZURE_CONTAINER = os.getenv("HERITAGE_AZURE_CONTAINER", "heritage-vault")

AWS_ACCESS_KEY = os.getenv("AWS_ACCESS_KEY_ID", "")
AWS_SECRET_KEY = os.getenv("AWS_SECRET_ACCESS_KEY", "")
AWS_BUCKET = os.getenv("HERITAGE_AWS_BUCKET", "heritage-vault")
AWS_REGION = os.getenv("HERITAGE_AWS_REGION", "us-east-1")

LOCAL_NAS_ROOT = Path(os.getenv("HERITAGE_LOCAL_NAS_PATH", "/mnt/heritage-vault"))

# Minimum required successful backends for a write to be considered durable
MIN_DURABLE_BACKENDS = 2


class ReplicationResult:
    """Result of a replication operation across all backends."""

    def __init__(self):
        self.azure_ok: bool = False
        self.aws_ok: bool = False
        self.local_ok: bool = False
        self.errors: Dict[str, str] = {}
        self.manifest_hash: str = ""

    @property
    def durable(self) -> bool:
        """Data is durable if >= MIN_DURABLE_BACKENDS succeeded."""
        return self.success_count >= MIN_DURABLE_BACKENDS

    @property
    def success_count(self) -> int:
        return sum([self.azure_ok, self.aws_ok, self.local_ok])

    def to_dict(self) -> Dict[str, Any]:
        return {
            "azure": self.azure_ok,
            "aws": self.aws_ok,
            "local": self.local_ok,
            "durable": self.durable,
            "success_count": self.success_count,
            "manifest_hash": self.manifest_hash,
            "errors": self.errors,
        }


class MultiCloudHeritageVault:
    """
    Triple-redundant heritage vault with Azure + AWS + Local NAS replication.
    """

    def __init__(self, db_pool=None):
        self._db = db_pool
        self._azure_client = None
        self._s3_client = None
        self._initialized = False

    async def initialize(self) -> Dict[str, bool]:
        """Initialize connections to all three backends."""
        status = {"azure": False, "aws": False, "local": False}

        # Azure Blob Storage
        if AZURE_STORAGE_ACCOUNT and AZURE_STORAGE_KEY:
            try:
                from azure.storage.blob.aio import BlobServiceClient
                conn_str = (
                    f"DefaultEndpointsProtocol=https;"
                    f"AccountName={AZURE_STORAGE_ACCOUNT};"
                    f"AccountKey={AZURE_STORAGE_KEY};"
                    f"EndpointSuffix=core.windows.net"
                )
                self._azure_client = BlobServiceClient.from_connection_string(conn_str)
                status["azure"] = True
                _logger.info("Azure Blob Storage initialized for heritage vault")
            except Exception as exc:
                _logger.warning("Azure Blob init failed (non-fatal): %s", exc)
        else:
            _logger.info("Azure Blob Storage not configured for heritage vault")

        # AWS S3
        if AWS_ACCESS_KEY and AWS_SECRET_KEY:
            try:
                import aiobotocore.session
                session = aiobotocore.session.get_session()
                self._s3_client = session.create_client(
                    "s3",
                    region_name=AWS_REGION,
                    aws_access_key_id=AWS_ACCESS_KEY,
                    aws_secret_access_key=AWS_SECRET_KEY,
                )
                status["aws"] = True
                _logger.info("AWS S3 initialized for heritage vault")
            except Exception as exc:
                _logger.warning("AWS S3 init failed (non-fatal): %s", exc)
        else:
            _logger.info("AWS S3 not configured for heritage vault")

        # Local NAS
        try:
            LOCAL_NAS_ROOT.mkdir(parents=True, exist_ok=True)
            status["local"] = True
            _logger.info("Local NAS initialized at %s", LOCAL_NAS_ROOT)
        except Exception as exc:
            _logger.warning("Local NAS init failed: %s", exc)

        self._initialized = True
        return status

    async def replicate(
        self,
        key: str,
        data: bytes,
        metadata: Optional[Dict[str, str]] = None,
    ) -> ReplicationResult:
        """
        Replicate data to all three backends simultaneously.
        Returns a ReplicationResult with per-backend status.
        """
        result = ReplicationResult()
        result.manifest_hash = hashlib.sha256(data).hexdigest()

        meta = metadata or {}
        meta["manifest_hash"] = result.manifest_hash
        meta["replicated_at"] = datetime.now(timezone.utc).isoformat()

        # Run all three writes concurrently
        azure_task = self._write_azure(key, data, meta)
        aws_task = self._write_aws(key, data, meta)
        local_task = self._write_local(key, data, meta)

        outcomes = await asyncio.gather(
            azure_task, aws_task, local_task,
            return_exceptions=True,
        )

        # Azure
        if isinstance(outcomes[0], Exception):
            result.errors["azure"] = str(outcomes[0])
        else:
            result.azure_ok = outcomes[0]

        # AWS
        if isinstance(outcomes[1], Exception):
            result.errors["aws"] = str(outcomes[1])
        else:
            result.aws_ok = outcomes[1]

        # Local
        if isinstance(outcomes[2], Exception):
            result.errors["local"] = str(outcomes[2])
        else:
            result.local_ok = outcomes[2]

        # Record replication event
        await self._log_replication(key, result)

        if not result.durable:
            _logger.error(
                "HERITAGE VAULT DEGRADED: key=%s success=%d/%d errors=%s",
                key, result.success_count, 3, result.errors,
            )
        else:
            _logger.info(
                "Heritage vault replicated: key=%s backends=%d/3 hash=%s",
                key, result.success_count, result.manifest_hash[:16],
            )

        return result

    async def verify_integrity(self, key: str) -> Dict[str, Any]:
        """
        Verify that the same data exists (by hash) across all backends.
        Returns per-backend hash comparison.
        """
        hashes: Dict[str, Optional[str]] = {}

        # Azure
        try:
            h = await self._hash_azure(key)
            hashes["azure"] = h
        except Exception as exc:
            hashes["azure"] = None
            _logger.debug("Azure hash check failed for %s: %s", key, exc)

        # AWS
        try:
            h = await self._hash_aws(key)
            hashes["aws"] = h
        except Exception as exc:
            hashes["aws"] = None

        # Local
        try:
            h = await self._hash_local(key)
            hashes["local"] = h
        except Exception as exc:
            hashes["local"] = None

        valid_hashes = [v for v in hashes.values() if v is not None]
        consistent = len(set(valid_hashes)) <= 1 if valid_hashes else False

        return {
            "key": key,
            "hashes": hashes,
            "consistent": consistent,
            "backends_available": sum(1 for v in hashes.values() if v is not None),
        }

    async def retrieve(self, key: str) -> Optional[bytes]:
        """
        Retrieve data from the first available backend.
        Tries local first (fastest), then Azure, then AWS.
        """
        # Try local
        try:
            data = await self._read_local(key)
            if data is not None:
                return data
        except Exception:
            pass

        # Try Azure
        try:
            data = await self._read_azure(key)
            if data is not None:
                return data
        except Exception:
            pass

        # Try AWS
        try:
            data = await self._read_aws(key)
            if data is not None:
                return data
        except Exception:
            pass

        return None

    async def list_keys(self, prefix: str = "") -> List[str]:
        """List all keys in the local NAS backend (fastest for enumeration)."""
        keys: List[str] = []
        search_dir = LOCAL_NAS_ROOT / prefix if prefix else LOCAL_NAS_ROOT
        if not search_dir.exists():
            return keys
        for f in search_dir.rglob("*"):
            if f.is_file() and not f.name.endswith(".meta.json"):
                keys.append(str(f.relative_to(LOCAL_NAS_ROOT)))
        return sorted(keys)

    # ─── Azure Backend ─────────────────────────────────────────────────────────

    async def _write_azure(self, key: str, data: bytes, meta: Dict) -> bool:
        if not self._azure_client:
            return False
        try:
            container = self._azure_client.get_container_client(AZURE_CONTAINER)
            blob = container.get_blob_client(key)
            await blob.upload_blob(data, overwrite=True, metadata=meta)
            return True
        except Exception as exc:
            _logger.error("Azure write failed for %s: %s", key, exc)
            raise

    async def _read_azure(self, key: str) -> Optional[bytes]:
        if not self._azure_client:
            return None
        container = self._azure_client.get_container_client(AZURE_CONTAINER)
        blob = container.get_blob_client(key)
        stream = await blob.download_blob()
        return await stream.readall()

    async def _hash_azure(self, key: str) -> Optional[str]:
        data = await self._read_azure(key)
        if data is None:
            return None
        return hashlib.sha256(data).hexdigest()

    # ─── AWS Backend ───────────────────────────────────────────────────────────

    async def _write_aws(self, key: str, data: bytes, meta: Dict) -> bool:
        if not self._s3_client:
            return False
        try:
            async with self._s3_client as client:
                await client.put_object(
                    Bucket=AWS_BUCKET,
                    Key=key,
                    Body=data,
                    Metadata={k: str(v) for k, v in meta.items()},
                )
            return True
        except Exception as exc:
            _logger.error("AWS write failed for %s: %s", key, exc)
            raise

    async def _read_aws(self, key: str) -> Optional[bytes]:
        if not self._s3_client:
            return None
        async with self._s3_client as client:
            resp = await client.get_object(Bucket=AWS_BUCKET, Key=key)
            async with resp["Body"] as stream:
                return await stream.read()

    async def _hash_aws(self, key: str) -> Optional[str]:
        data = await self._read_aws(key)
        if data is None:
            return None
        return hashlib.sha256(data).hexdigest()

    # ─── Local NAS Backend ─────────────────────────────────────────────────────

    async def _write_local(self, key: str, data: bytes, meta: Dict) -> bool:
        try:
            file_path = LOCAL_NAS_ROOT / key
            file_path.parent.mkdir(parents=True, exist_ok=True)

            loop = asyncio.get_event_loop()
            await loop.run_in_executor(None, self._sync_write_local, file_path, data, meta)
            return True
        except Exception as exc:
            _logger.error("Local NAS write failed for %s: %s", key, exc)
            raise

    @staticmethod
    def _sync_write_local(file_path: Path, data: bytes, meta: Dict) -> None:
        """Synchronous write with atomic rename for safety."""
        tmp_path = file_path.with_suffix(".tmp")
        with open(tmp_path, "wb") as f:
            f.write(data)
        shutil.move(str(tmp_path), str(file_path))

        # Write metadata sidecar
        meta_path = file_path.with_suffix(file_path.suffix + ".meta.json")
        with open(meta_path, "w") as f:
            json.dump(meta, f, indent=2)

    async def _read_local(self, key: str) -> Optional[bytes]:
        file_path = LOCAL_NAS_ROOT / key
        if not file_path.exists():
            return None
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, file_path.read_bytes)

    async def _hash_local(self, key: str) -> Optional[str]:
        data = await self._read_local(key)
        if data is None:
            return None
        return hashlib.sha256(data).hexdigest()

    # ─── Audit Logging ─────────────────────────────────────────────────────────

    async def _log_replication(self, key: str, result: ReplicationResult) -> None:
        if not self._db:
            return
        try:
            await self._db.execute(
                """INSERT INTO heritage_vault_replication_log
                   (vault_key, manifest_hash, azure_ok, aws_ok, local_ok,
                    durable, errors, created_at)
                   VALUES ($1, $2, $3, $4, $5, $6, $7, NOW())""",
                key, result.manifest_hash,
                result.azure_ok, result.aws_ok, result.local_ok,
                result.durable, json.dumps(result.errors),
            )
        except Exception as exc:
            _logger.error("Replication log write failed: %s", exc)
