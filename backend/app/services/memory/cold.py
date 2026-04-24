"""
SOVEREIGN SWARM — Cold Memory Tier

Storage priority (per r2-cloudflare-storage.mdc):
  1. Cloudflare R2  — primary, zero egress fees
  2. Azure Blob     — secondary fallback (existing data stays readable)
  3. Local in-memory archive — last-resort when both clouds are unreachable

Patent Claim 13: Legacy Vault cold storage.
Patent Claim 22: Evolution journal preservation.
"""

from __future__ import annotations

import asyncio
import json
import os
from typing import Any, Dict, List, Optional

import structlog

logger = structlog.get_logger(__name__)


class ColdMemoryTier:
    """
    Two-cloud cold archive tier (R2 primary, Azure fallback).

    Stores client history, fibre evolution journals, and family legacy data.
    Falls back to a local in-memory archive when both clouds are unreachable.
    """

    def __init__(
        self,
        connection_string: Optional[str] = None,
        container_name: str = "cold-archive",
        r2_bucket: Optional[str] = None,
    ) -> None:
        """
        Args:
            connection_string: Azure Storage connection string. If None, uses env var.
            container_name: Azure blob container name (default "cold-archive").
            r2_bucket: R2 bucket name (default from env R2_COLD_BUCKET → "nate-cold-archive").
        """
        self._conn = connection_string or os.getenv("AZURE_STORAGE_CONNECTION_STRING", "").strip()
        self._container = container_name
        self._r2_bucket = (r2_bucket or os.getenv("R2_COLD_BUCKET", "nate-cold-archive")).strip()
        self._local_archive: Dict[str, bytes] = {}

    def _azure_available(self) -> bool:
        """Check if Azure Blob Storage is configured."""
        return bool(self._conn and self._container)

    def _r2_available(self) -> bool:
        """Check if Cloudflare R2 is configured."""
        try:
            from app.services import r2_storage
            return r2_storage.is_r2_configured() and bool(self._r2_bucket)
        except Exception:
            return False

    async def archive(
        self,
        path: str,
        data: bytes,
        metadata: Optional[Dict[str, str]] = None,
    ) -> str:
        """
        Upload data to Azure Blob Storage cool tier.

        Args:
            path: Blob path (e.g. "legacy/family_123.json").
            data: Raw bytes to archive.
            metadata: Optional blob metadata dict.

        Returns:
            Blob URL when Azure succeeds, else "local:{path}".
        """
        path = (path or "").lstrip("/").strip()
        if not path:
            raise ValueError("path is required")

        if self._r2_available():
            try:
                from app.services import r2_storage

                _, location = await r2_storage.upload_bytes_async(
                    key=path,
                    content=data or b"",
                    bucket=self._r2_bucket,
                    content_type="application/octet-stream",
                    metadata=metadata,
                )
                logger.debug("cold_archive", path=path, size=len(data), storage="r2")
                return location
            except Exception as e:
                logger.warning("cold_archive_r2_failed", path=path, error=str(e))

        if self._azure_available():
            try:
                from azure.storage.blob import BlobServiceClient, ContentSettings  # type: ignore

                def _upload() -> str:
                    bsc = BlobServiceClient.from_connection_string(self._conn)
                    blob = bsc.get_blob_client(container=self._container, blob=path)
                    content_settings = ContentSettings(content_type="application/octet-stream")
                    blob.upload_blob(data or b"", overwrite=True, content_settings=content_settings)
                    if metadata:
                        blob.set_blob_metadata(metadata)
                    return blob.url

                url = await asyncio.to_thread(_upload)
                logger.debug("cold_archive", path=path, size=len(data), storage="azure")
                return url
            except Exception as e:
                logger.warning("cold_archive_azure_failed", path=path, error=str(e))

        self._local_archive[path] = data or b""
        logger.debug("cold_archive", path=path, size=len(data), storage="local")
        return f"local:{path}"

    async def retrieve(self, path: str) -> Optional[bytes]:
        """
        Retrieve archived data by path.

        Tries R2 first (zero egress), then Azure (existing-data fallback),
        then the local archive. Returns None if absent everywhere.
        """
        path = (path or "").lstrip("/").strip()
        if not path:
            return None

        if self._r2_available():
            try:
                from app.services import r2_storage

                data = await r2_storage.download_bytes_async(
                    key=path, bucket=self._r2_bucket
                )
                if data is not None:
                    return data
            except Exception as e:
                logger.debug("cold_retrieve_r2_failed", path=path, error=str(e))

        if self._azure_available():
            try:
                from azure.storage.blob import BlobServiceClient  # type: ignore

                def _download() -> bytes:
                    bsc = BlobServiceClient.from_connection_string(self._conn)
                    blob = bsc.get_blob_client(container=self._container, blob=path)
                    stream = blob.download_blob()
                    return stream.readall()

                return await asyncio.to_thread(_download)
            except Exception as e:
                logger.debug("cold_retrieve_azure_failed", path=path, error=str(e))

        return self._local_archive.get(path)

    async def archive_client_history(self, client_id: str, history: Dict[str, Any]) -> str:
        """
        Archive client history for long-term storage.

        Args:
            client_id: Client identifier.
            history: Client history dict.

        Returns:
            Blob URL or local key.
        """
        path = f"clients/{client_id}/history.json"
        data = json.dumps(history, default=str).encode("utf-8")
        return await self.archive(path, data, metadata={"client_id": client_id})

    async def archive_fibre_evolution_journal(
        self,
        fibre_id: str,
        journal: Dict[str, Any],
    ) -> str:
        """
        Archive fibre evolution journal. Patent Claim 22: Evolution journal preservation.

        Args:
            fibre_id: Fibre identifier.
            journal: Evolution journal dict.

        Returns:
            Blob URL or local key.
        """
        path = f"fibres/{fibre_id}/evolution_journal.json"
        data = json.dumps(journal, default=str).encode("utf-8")
        return await self.archive(path, data, metadata={"fibre_id": fibre_id})

    async def archive_family_legacy(self, family_id: str, legacy_data: Dict[str, Any]) -> str:
        """
        Archive family legacy data. Patent Claim 13: Legacy Vault cold storage.

        Args:
            family_id: Family identifier.
            legacy_data: Legacy data dict.

        Returns:
            Blob URL or local key.
        """
        path = f"families/{family_id}/legacy.json"
        data = json.dumps(legacy_data, default=str).encode("utf-8")
        return await self.archive(path, data, metadata={"family_id": family_id})

    async def list_archives(self, prefix: str) -> List[str]:
        """
        List archived blob paths matching a prefix.

        Args:
            prefix: Path prefix (e.g. "clients/", "families/").

        Returns:
            List of blob paths.
        """
        prefix = (prefix or "").strip().rstrip("/")
        keys: set[str] = set()

        if self._r2_available():
            try:
                from app.services import r2_storage

                r2_keys = await r2_storage.list_objects_async(
                    prefix=prefix, bucket=self._r2_bucket, max_keys=1000
                )
                keys.update(r2_keys)
            except Exception as e:
                logger.debug("cold_list_r2_failed", prefix=prefix, error=str(e))

        if self._azure_available():
            try:
                from azure.storage.blob import BlobServiceClient  # type: ignore

                def _list() -> List[str]:
                    bsc = BlobServiceClient.from_connection_string(self._conn)
                    container = bsc.get_container_client(self._container)
                    return [blob.name for blob in container.list_blobs(name_starts_with=prefix)]

                az_keys = await asyncio.to_thread(_list)
                keys.update(az_keys)
            except Exception as e:
                logger.warning("cold_list_azure_failed", prefix=prefix, error=str(e))

        keys.update(k for k in self._local_archive if k.startswith(prefix))
        return sorted(keys)
