"""
SOVEREIGN SWARM — Warm Memory Tier

Storage priority: R2 (zero egress) → Azure Blob Hot → in-memory cache.
Graceful fallback when cloud providers are not configured.
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime
from typing import Any, Dict, List, Optional

import structlog

logger = structlog.get_logger(__name__)


class WarmMemoryTier:
    """
    Warm archive data stored in R2 (primary) or Azure Blob Hot (fallback).

    Stores session archives and fibre insights. Falls back to local in-memory
    cache when no cloud provider is configured.
    """

    def __init__(
        self,
        connection_string: Optional[str] = None,
        container_name: str = "warm-memory",
        r2_bucket: Optional[str] = None,
    ) -> None:
        import os

        self._conn = connection_string or os.getenv("AZURE_STORAGE_CONNECTION_STRING", "").strip()
        self._container = container_name
        self._r2_bucket = r2_bucket or os.getenv("R2_WARM_BUCKET", "nate-warm-memory")
        self._local_cache: Dict[str, bytes] = {}

    def _r2_available(self) -> bool:
        try:
            from app.services.r2_storage import is_r2_configured
            return is_r2_configured()
        except ImportError:
            return False

    def _azure_available(self) -> bool:
        """Check if Azure Blob Storage is configured."""
        return bool(self._conn and self._container)

    async def store(
        self,
        path: str,
        data: bytes,
        metadata: Optional[Dict[str, str]] = None,
    ) -> str:
        """
        Upload data: R2 first → Azure Hot → local cache.

        Returns:
            Storage URL/key on success, "local:{path}" on local fallback.
        """
        path = (path or "").lstrip("/").strip()
        if not path:
            raise ValueError("path is required")

        if self._r2_available():
            try:
                from app.services.r2_storage import upload_bytes_async
                _, url = await upload_bytes_async(
                    key=path, content=data or b"",
                    bucket=self._r2_bucket, metadata=metadata,
                )
                logger.debug("warm_store", path=path, size=len(data), storage="r2")
                return url
            except Exception as e:
                logger.warning("warm_store_r2_failed", path=path, error=str(e))

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
                logger.debug("warm_store", path=path, size=len(data), storage="azure")
                return url
            except Exception as e:
                logger.warning("warm_store_azure_failed", path=path, error=str(e))

        self._local_cache[path] = data or b""
        logger.debug("warm_store", path=path, size=len(data), storage="local")
        return f"local:{path}"

    async def retrieve(self, path: str) -> Optional[bytes]:
        """
        Retrieve data: R2 → Azure → local cache.
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
                logger.debug("warm_retrieve_r2_failed", path=path, error=str(e))

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
                logger.debug("warm_retrieve_azure_failed", path=path, error=str(e))

        return self._local_cache.get(path)

    async def delete(self, path: str) -> bool:
        """
        Delete from R2 → Azure → local cache.
        """
        path = (path or "").lstrip("/").strip()
        if not path:
            return False

        if self._r2_available():
            try:
                from app.services.r2_storage import delete_object_async
                ok = await delete_object_async(key=path, bucket=self._r2_bucket)
                if ok:
                    logger.debug("warm_delete", path=path, storage="r2")
                    return True
            except Exception as e:
                logger.warning("warm_delete_r2_failed", path=path, error=str(e))

        if self._azure_available():
            try:
                from azure.storage.blob import BlobServiceClient  # type: ignore

                def _delete() -> None:
                    bsc = BlobServiceClient.from_connection_string(self._conn)
                    blob = bsc.get_blob_client(container=self._container, blob=path)
                    blob.delete_blob()

                await asyncio.to_thread(_delete)
                logger.debug("warm_delete", path=path, storage="azure")
                return True
            except Exception as e:
                logger.warning("warm_delete_azure_failed", path=path, error=str(e))

        if path in self._local_cache:
            del self._local_cache[path]
            return True
        return False

    async def archive_session(self, session_id: str, session_data: Dict[str, Any]) -> str:
        """
        Serialize and store session data under sessions/{session_id}.json.

        Args:
            session_id: Session identifier.
            session_data: Session data dict (JSON-serializable).

        Returns:
            Blob URL or local key.
        """
        path = f"sessions/{session_id}.json"
        data = json.dumps(session_data, default=str).encode("utf-8")
        metadata = {"session_id": session_id, "archived_at": datetime.utcnow().isoformat()}
        return await self.store(path, data, metadata=metadata)

    async def archive_insights(
        self,
        fibre_id: str,
        insights: List[Dict[str, Any]],
    ) -> str:
        """
        Store fibre insights under insights/{fibre_id}/{date}.json.

        Args:
            fibre_id: Fibre identifier.
            insights: List of insight dicts.

        Returns:
            Blob URL or local key.
        """
        date_str = datetime.utcnow().strftime("%Y-%m-%d")
        path = f"insights/{fibre_id}/{date_str}.json"
        data = json.dumps(insights, default=str).encode("utf-8")
        metadata = {"fibre_id": fibre_id, "date": date_str}
        return await self.store(path, data, metadata=metadata)

    async def list_paths(self, prefix: str) -> List[str]:
        """
        List paths: R2 → Azure → local cache.
        """
        prefix = (prefix or "").strip().rstrip("/")

        if self._r2_available():
            try:
                from app.services.r2_storage import list_objects_async
                result = await list_objects_async(prefix=prefix, bucket=self._r2_bucket)
                if result:
                    return result
            except Exception as e:
                logger.warning("warm_list_r2_failed", prefix=prefix, error=str(e))

        if self._azure_available():
            try:
                from azure.storage.blob import BlobServiceClient  # type: ignore

                def _list() -> List[str]:
                    bsc = BlobServiceClient.from_connection_string(self._conn)
                    container = bsc.get_container_client(self._container)
                    return [blob.name for blob in container.list_blobs(name_starts_with=prefix)]

                return await asyncio.to_thread(_list)
            except Exception as e:
                logger.warning("warm_list_azure_failed", prefix=prefix, error=str(e))

        return [k for k in self._local_cache if k.startswith(prefix)]
