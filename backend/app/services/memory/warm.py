"""
SOVEREIGN SWARM — Warm Memory Tier

Storage priority (per r2-cloudflare-storage.mdc):
  1. Cloudflare R2  — primary, zero egress fees
  2. Azure Blob     — secondary fallback (existing data stays readable)
  3. Local in-memory cache — last-resort when both clouds are unreachable

Reads try R2 first (cheapest), fall through to Azure on miss/error,
then to the local cache. Writes go to R2 first; if R2 fails the write
falls through to Azure so durability is never reduced by the change.
"""

from __future__ import annotations

import asyncio
import json
import os
from datetime import datetime
from typing import Any, Dict, List, Optional

import structlog

logger = structlog.get_logger(__name__)


class WarmMemoryTier:
    """
    Two-cloud warm archive tier (R2 primary, Azure fallback).

    Stores session archives and fibre insights. Falls back to a local
    in-memory cache when both clouds are unreachable.
    """

    def __init__(
        self,
        connection_string: Optional[str] = None,
        container_name: str = "warm-memory",
        r2_bucket: Optional[str] = None,
    ) -> None:
        """
        Args:
            connection_string: Azure Storage connection string. If None, uses env var.
            container_name: Azure blob container name (default "warm-memory").
            r2_bucket: R2 bucket name (default from env R2_WARM_BUCKET → "nate-warm-memory").
        """
        self._conn = connection_string or os.getenv("AZURE_STORAGE_CONNECTION_STRING", "").strip()
        self._container = container_name
        self._r2_bucket = (r2_bucket or os.getenv("R2_WARM_BUCKET", "nate-warm-memory")).strip()
        self._local_cache: Dict[str, bytes] = {}

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

    async def store(
        self,
        path: str,
        data: bytes,
        metadata: Optional[Dict[str, str]] = None,
    ) -> str:
        """
        Upload data to Azure Blob Storage hot tier.

        Args:
            path: Blob path (e.g. "sessions/abc123.json").
            data: Raw bytes to store.
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
                logger.debug("warm_store", path=path, size=len(data), storage="r2")
                return location
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
        Retrieve data by path.

        Tries R2 first (zero egress), then Azure (existing-data fallback),
        then the local cache. Returns None if absent everywhere.
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
        Delete a blob by path.

        Returns:
            True if deleted, False if not found.
        """
        path = (path or "").lstrip("/").strip()
        if not path:
            return False

        any_deleted = False

        # Delete from R2 if present (best-effort).
        if self._r2_available():
            try:
                from app.services import r2_storage

                ok = await r2_storage.delete_object_async(
                    key=path, bucket=self._r2_bucket
                )
                if ok:
                    any_deleted = True
                    logger.debug("warm_delete", path=path, storage="r2")
            except Exception as e:
                logger.debug("warm_delete_r2_failed", path=path, error=str(e))

        # ALSO delete from Azure — historical data may live there from
        # before the R2 cutover. We don't want a "deleted" key resurrecting.
        if self._azure_available():
            try:
                from azure.storage.blob import BlobServiceClient  # type: ignore

                def _delete() -> None:
                    bsc = BlobServiceClient.from_connection_string(self._conn)
                    blob = bsc.get_blob_client(container=self._container, blob=path)
                    blob.delete_blob()

                await asyncio.to_thread(_delete)
                any_deleted = True
                logger.debug("warm_delete", path=path, storage="azure")
            except Exception as e:
                # Missing-blob is the common case; only warn on real errors.
                logger.debug("warm_delete_azure_failed", path=path, error=str(e))

        if path in self._local_cache:
            del self._local_cache[path]
            any_deleted = True
        return any_deleted

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
        List blob paths matching a prefix.

        Args:
            prefix: Path prefix (e.g. "sessions/", "insights/fibre_1/").

        Returns:
            List of blob paths.
        """
        prefix = (prefix or "").strip().rstrip("/")
        # Union of R2 + Azure + local so callers see one consistent view
        # during the migration window. De-dup is via set().
        keys: set[str] = set()

        if self._r2_available():
            try:
                from app.services import r2_storage

                r2_keys = await r2_storage.list_objects_async(
                    prefix=prefix, bucket=self._r2_bucket, max_keys=1000
                )
                keys.update(r2_keys)
            except Exception as e:
                logger.debug("warm_list_r2_failed", prefix=prefix, error=str(e))

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
                logger.warning("warm_list_azure_failed", prefix=prefix, error=str(e))

        keys.update(k for k in self._local_cache if k.startswith(prefix))
        return sorted(keys)
