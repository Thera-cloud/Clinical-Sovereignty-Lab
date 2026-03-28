"""
SOVEREIGN SWARM — Cold Memory Tier

Storage priority: R2 (hot reads) → B2 (cold archive, 60% cheaper) → Azure Blob Cool → in-memory archive.
Patent Claim 13: Legacy Vault cold storage.
Patent Claim 22: Evolution journal preservation.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any, Dict, List, Optional

import structlog

logger = structlog.get_logger(__name__)


class ColdMemoryTier:
    """
    Cold archive stored in R2 (primary) → B2 (secondary, 60% cheaper) →
    Azure Blob Cool (tertiary) → local in-memory (last resort).

    B2 is preferred for cold writes (cheaper storage at $0.006/GB vs R2 $0.015/GB).
    R2 is preferred for reads (Cloudflare edge integration).
    Both have zero egress through Cloudflare Bandwidth Alliance.
    """

    def __init__(
        self,
        connection_string: Optional[str] = None,
        container_name: str = "cold-archive",
        r2_bucket: Optional[str] = None,
        b2_bucket: Optional[str] = None,
    ) -> None:
        import os

        self._conn = connection_string or os.getenv("AZURE_STORAGE_CONNECTION_STRING", "").strip()
        self._container = container_name
        self._r2_bucket = r2_bucket or os.getenv("R2_COLD_BUCKET", "nate-cold-archive")
        self._b2_bucket = b2_bucket or os.getenv("B2_COLD_BUCKET", "nate-cold-archive")
        self._local_archive: Dict[str, bytes] = {}

    def _r2_available(self) -> bool:
        try:
            from app.services.r2_storage import is_r2_configured
            return is_r2_configured()
        except ImportError:
            return False

    def _b2_available(self) -> bool:
        try:
            from app.services.b2_storage import is_b2_configured
            return is_b2_configured()
        except ImportError:
            return False

    def _azure_available(self) -> bool:
        """Check if Azure Blob Storage is configured."""
        return bool(self._conn and self._container)

    async def archive(
        self,
        path: str,
        data: bytes,
        metadata: Optional[Dict[str, str]] = None,
    ) -> str:
        """
        Archive data: B2 first (cheapest cold) → R2 → Azure Cool → local.
        Writes prefer B2 for cost; reads prefer R2 for speed.

        Returns:
            Storage URL/key on success, "local:{path}" on local fallback.
        """
        path = (path or "").lstrip("/").strip()
        if not path:
            raise ValueError("path is required")

        if self._b2_available():
            try:
                from app.services.b2_storage import upload_bytes_async
                _, url = await upload_bytes_async(
                    key=path, content=data or b"",
                    bucket=self._b2_bucket, metadata=metadata,
                )
                logger.debug("cold_archive", path=path, size=len(data), storage="b2")
                return url
            except Exception as e:
                logger.warning("cold_archive_b2_failed", path=path, error=str(e))

        if self._r2_available():
            try:
                from app.services.r2_storage import upload_bytes_async
                _, url = await upload_bytes_async(
                    key=path, content=data or b"",
                    bucket=self._r2_bucket, metadata=metadata,
                )
                logger.debug("cold_archive", path=path, size=len(data), storage="r2")
                return url
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
        Retrieve: R2 → B2 → Azure → local.
        Reads prefer R2 (Cloudflare edge), fall back to B2 (Bandwidth Alliance).
        """
        path = (path or "").lstrip("/").strip()
        if not path:
            return None

        if self._r2_available():
            try:
                from app.services.r2_storage import download_bytes_async
                data = await download_bytes_async(key=path, bucket=self._r2_bucket)
                if data is not None:
                    return data
            except Exception as e:
                logger.debug("cold_retrieve_r2_failed", path=path, error=str(e))

        if self._b2_available():
            try:
                from app.services.b2_storage import download_bytes_async
                data = await download_bytes_async(key=path, bucket=self._b2_bucket)
                if data is not None:
                    return data
            except Exception as e:
                logger.debug("cold_retrieve_b2_failed", path=path, error=str(e))

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

    def get_download_url(self, path: str) -> Optional[str]:
        """
        Get a Cloudflare-cached download URL for a cold archive object.
        Zero egress via Bandwidth Alliance CNAME. Returns None if unavailable.
        """
        path = (path or "").lstrip("/").strip()
        if not path:
            return None
        if self._b2_available():
            try:
                from app.services.b2_storage import get_cached_url
                return get_cached_url(key=path, bucket=self._b2_bucket)
            except ImportError:
                pass
        return None

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
        List archives: B2 → R2 → Azure → local.
        """
        prefix = (prefix or "").strip().rstrip("/")

        if self._b2_available():
            try:
                from app.services.b2_storage import list_objects_async
                result = await list_objects_async(prefix=prefix, bucket=self._b2_bucket)
                if result:
                    return result
            except Exception as e:
                logger.warning("cold_list_b2_failed", prefix=prefix, error=str(e))

        if self._r2_available():
            try:
                from app.services.r2_storage import list_objects_async
                result = await list_objects_async(prefix=prefix, bucket=self._r2_bucket)
                if result:
                    return result
            except Exception as e:
                logger.warning("cold_list_r2_failed", prefix=prefix, error=str(e))

        if self._azure_available():
            try:
                from azure.storage.blob import BlobServiceClient  # type: ignore

                def _list() -> List[str]:
                    bsc = BlobServiceClient.from_connection_string(self._conn)
                    container = bsc.get_container_client(self._container)
                    return [blob.name for blob in container.list_blobs(name_starts_with=prefix)]

                return await asyncio.to_thread(_list)
            except Exception as e:
                logger.warning("cold_list_azure_failed", prefix=prefix, error=str(e))

        return [k for k in self._local_archive if k.startswith(prefix)]
