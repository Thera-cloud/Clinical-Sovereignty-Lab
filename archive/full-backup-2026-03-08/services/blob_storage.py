"""
Object storage helper — R2 primary, Azure fallback, local last resort.

Priority chain:
  1. Cloudflare R2 (zero egress, S3-compatible)  — if R2 env vars are set
  2. Azure Blob Storage                          — if Azure connection string is set
  3. Local disk (DATA_DIR/archives)              — always available

This keeps the system functional in dev/test without forcing cloud dependencies.

Enhanced for Classroom feature:
- Download blobs for transcript analysis
- Delete blobs after processing
- List blobs for batch operations
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Optional, Tuple, List

_logger = logging.getLogger("blob_storage")

_R2_CDN_BASE = (os.getenv("R2_CDN_BASE_URL") or "").rstrip("/")


def get_cdn_url(r2_key: str) -> Optional[str]:
    """Return a CDN URL for an R2 object, or None if CDN is not configured."""
    if not _R2_CDN_BASE or not r2_key:
        return None
    return f"{_R2_CDN_BASE}/vault/{r2_key}"


def _local_archive_root() -> Path:
    data_dir = Path(os.getenv("DATA_DIR", "/app/data"))
    return data_dir / "archives"


def _get_azure_config() -> Tuple[str, str]:
    """Get Azure configuration from environment."""
    conn = (os.getenv("AZURE_STORAGE_CONNECTION_STRING") or "").strip()
    cont = (os.getenv("AZURE_BLOB_CONTAINER") or os.getenv("AZURE_STORAGE_CONTAINER_NAME") or "").strip()
    return conn, cont


def is_azure_configured() -> bool:
    """Check if Azure Blob Storage is properly configured."""
    conn, cont = _get_azure_config()
    return bool(conn and cont)


def _try_r2_upload(rel_path: str, content: bytes, content_type: str) -> Optional[Tuple[str, str]]:
    """Attempt R2 upload. Returns (storage_kind, location) or None."""
    try:
        from app.services.r2_storage import is_r2_configured, upload_bytes as r2_upload
        if not is_r2_configured():
            return None
        return r2_upload(key=rel_path, content=content, content_type=content_type)
    except Exception as e:
        _logger.warning("[BlobStorage] R2 upload failed, trying Azure: %s", e)
        return None


def _try_r2_download(rel_path: str) -> Optional[bytes]:
    """Attempt R2 download. Returns bytes or None."""
    try:
        from app.services.r2_storage import is_r2_configured, download_bytes as r2_download
        if not is_r2_configured():
            return None
        return r2_download(key=rel_path)
    except Exception as e:
        _logger.debug("[BlobStorage] R2 download miss: %s", e)
        return None


def _try_r2_delete(rel_path: str) -> Optional[bool]:
    """Attempt R2 delete. Returns True/False or None if R2 not configured."""
    try:
        from app.services.r2_storage import is_r2_configured, delete_object as r2_delete
        if not is_r2_configured():
            return None
        return r2_delete(key=rel_path)
    except Exception as e:
        _logger.debug("[BlobStorage] R2 delete failed: %s", e)
        return None


def _try_r2_list(prefix: str) -> Optional[List[str]]:
    """Attempt R2 list. Returns list or None if R2 not configured."""
    try:
        from app.services.r2_storage import is_r2_configured, list_objects as r2_list
        if not is_r2_configured():
            return None
        result = r2_list(prefix=prefix)
        return result if result else None
    except Exception as e:
        _logger.debug("[BlobStorage] R2 list failed: %s", e)
        return None


def save_bytes_local(*, rel_path: str, content: bytes) -> str:
    root = _local_archive_root()
    p = root / rel_path
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(content or b"")
    return str(p)


def upload_bytes(
    *,
    rel_path: str,
    content: bytes,
    container: Optional[str] = None,
    content_type: str = "application/octet-stream",
) -> Tuple[str, str]:
    """
    Upload bytes: R2 first → Azure fallback → local last resort.

    Returns:
      (storage_kind, location)
        - storage_kind: "r2" | "azure" | "local"
        - location: public URL, blob URL, or local file path
    """
    rel = (rel_path or "").lstrip("/").strip()
    if not rel:
        raise ValueError("Missing rel_path")

    r2_result = _try_r2_upload(rel, content, content_type)
    if r2_result:
        return r2_result

    conn, cont = _get_azure_config()
    cont = container or cont

    if conn and cont:
        try:
            from azure.storage.blob import BlobServiceClient, ContentSettings  # type: ignore

            bsc = BlobServiceClient.from_connection_string(conn)
            blob = bsc.get_blob_client(container=cont, blob=rel)
            blob.upload_blob(
                content or b"",
                overwrite=True,
                content_settings=ContentSettings(content_type=content_type),
            )
            return "azure", blob.url
        except Exception as e:
            _logger.warning("[BlobStorage] Azure upload failed, falling back to local: %s", e)

    path = save_bytes_local(rel_path=rel, content=content)
    return "local", path


def download_bytes(
    *,
    location: str,
    storage_kind: str = "auto",
    container: Optional[str] = None,
) -> Optional[bytes]:
    """
    Download bytes: tries R2 first → Azure → local.

    Args:
        location: blob URL, blob path, or local file path
        storage_kind: "r2", "azure", "local", or "auto" to detect
        container: Optional container name (for Azure)

    Returns:
        bytes content or None if not found
    """
    if not location:
        return None

    if storage_kind == "auto":
        if location.startswith("/") or Path(location).exists():
            storage_kind = "local"
        elif location.startswith("http"):
            storage_kind = "azure"
        else:
            storage_kind = "r2"

    if storage_kind == "local":
        try:
            path = Path(location)
            if path.exists():
                return path.read_bytes()
        except Exception as e:
            _logger.warning("[BlobStorage] Local read failed: %s", e)
        return None

    rel_key = _extract_key(location, container)

    if storage_kind == "r2":
        data = _try_r2_download(rel_key)
        if data is not None:
            return data

    conn, cont = _get_azure_config()
    cont = container or cont

    if conn and cont:
        try:
            from azure.storage.blob import BlobServiceClient  # type: ignore

            bsc = BlobServiceClient.from_connection_string(conn)
            blob = bsc.get_blob_client(container=cont, blob=rel_key)
            return blob.download_blob().readall()
        except Exception as e:
            _logger.debug("[BlobStorage] Azure download failed: %s", e)

    try:
        local_path = _local_archive_root() / location.lstrip("/")
        if local_path.exists():
            return local_path.read_bytes()
    except Exception:
        pass

    return None


def _extract_key(location: str, container: Optional[str] = None) -> str:
    """Extract the object key from a URL or return the raw path."""
    if not location.startswith("http"):
        return location.lstrip("/").strip()
    _, cont = _get_azure_config()
    cont = container or cont
    if cont and f"/{cont}/" in location:
        parts = location.split(f"/{cont}/", 1)
        if len(parts) > 1:
            return parts[1]
    return location.split("/")[-1]


def delete_blob(
    *,
    location: str,
    storage_kind: str = "auto",
    container: Optional[str] = None,
) -> bool:
    """
    Delete a blob: tries R2 → Azure → local.

    Args:
        location: blob URL, blob path, or local file path
        storage_kind: "r2", "azure", "local", or "auto" to detect
        container: Optional container name (for Azure)

    Returns:
        True if deleted from any backend, False otherwise
    """
    if not location:
        return False

    if storage_kind == "auto":
        if location.startswith("/") or Path(location).exists():
            storage_kind = "local"
        elif location.startswith("http"):
            storage_kind = "azure"
        else:
            storage_kind = "r2"

    if storage_kind == "local":
        try:
            path = Path(location)
            if path.exists():
                path.unlink()
                _logger.info("[BlobStorage] Deleted local file: %s", location)
                return True
        except Exception as e:
            _logger.warning("[BlobStorage] Local delete failed: %s", e)
        return False

    rel_key = _extract_key(location, container)

    r2_ok = _try_r2_delete(rel_key)
    if r2_ok:
        return True

    conn, cont = _get_azure_config()
    cont = container or cont

    if not conn or not cont:
        return False

    try:
        from azure.storage.blob import BlobServiceClient  # type: ignore

        bsc = BlobServiceClient.from_connection_string(conn)
        blob = bsc.get_blob_client(container=cont, blob=rel_key)
        blob.delete_blob()
        _logger.info("[BlobStorage] Deleted Azure blob: %s", rel_key)
        return True
    except Exception as e:
        _logger.warning("[BlobStorage] Azure delete failed: %s", e)
        return False


def list_blobs(
    *,
    prefix: str = "",
    container: Optional[str] = None,
) -> List[str]:
    """
    List blobs: tries R2 → Azure → local.

    Args:
        prefix: Blob name prefix to filter by
        container: Optional container name

    Returns:
        List of blob names
    """
    r2_result = _try_r2_list(prefix)
    if r2_result is not None:
        return r2_result

    conn, cont = _get_azure_config()
    cont = container or cont

    if conn and cont:
        try:
            from azure.storage.blob import BlobServiceClient  # type: ignore

            bsc = BlobServiceClient.from_connection_string(conn)
            container_client = bsc.get_container_client(cont)
            return [blob.name for blob in container_client.list_blobs(name_starts_with=prefix)]
        except Exception as e:
            _logger.warning("[BlobStorage] Azure list failed: %s", e)

    try:
        root = _local_archive_root()
        search_path = root / prefix if prefix else root
        if search_path.is_dir():
            return [str(p.relative_to(root)) for p in search_path.rglob("*") if p.is_file()]
        elif search_path.parent.exists():
            return [str(p.relative_to(root)) for p in search_path.parent.glob(f"{search_path.name}*") if p.is_file()]
    except Exception as e:
        _logger.warning("[BlobStorage] Local list failed: %s", e)
    return []


def get_blob_url(*, rel_path: str, container: Optional[str] = None) -> Optional[str]:
    """
    Get URL for a blob: R2 presigned URL → Azure blob URL → local path.

    Args:
        rel_path: Relative path to the blob
        container: Optional container name

    Returns:
        URL string or local path
    """
    try:
        from app.services.r2_storage import is_r2_configured, generate_presigned_url
        if is_r2_configured():
            url = generate_presigned_url(key=rel_path)
            if url:
                return url
    except Exception:
        pass

    conn, cont = _get_azure_config()
    cont = container or cont

    if conn and cont:
        try:
            from azure.storage.blob import BlobServiceClient  # type: ignore

            bsc = BlobServiceClient.from_connection_string(conn)
            blob = bsc.get_blob_client(container=cont, blob=rel_path)
            return blob.url
        except Exception as e:
            _logger.warning("[BlobStorage] Get URL failed: %s", e)

    path = _local_archive_root() / rel_path.lstrip("/")
    return str(path) if path.exists() else None

