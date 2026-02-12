"""
Azure Blob storage helper (optional).

Design:
- If `azure-storage-blob` is installed and env vars are configured, upload to Azure.
- Otherwise, fall back to writing to local disk (DATA_DIR/archives).

This keeps the system functional in dev/test without forcing dependencies.

Enhanced for Classroom feature:
- Download blobs for transcript analysis
- Delete blobs after processing
- List blobs for batch operations
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional, Tuple, List


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
    Upload bytes to Azure blob if configured; otherwise writes locally.

    Returns:
      (storage_kind, location)
        - storage_kind: "azure" | "local"
        - location: blob url (azure) or local file path
    """
    rel = (rel_path or "").lstrip("/").strip()
    if not rel:
        raise ValueError("Missing rel_path")

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
            print(f"[BlobStorage] Azure upload failed, falling back to local: {e}")
            pass

    path = save_bytes_local(rel_path=rel, content=content)
    return "local", path


def download_bytes(
    *,
    location: str,
    storage_kind: str = "auto",
    container: Optional[str] = None,
) -> Optional[bytes]:
    """
    Download bytes from Azure blob or local storage.
    
    Args:
        location: blob URL, blob path, or local file path
        storage_kind: "azure", "local", or "auto" to detect
        container: Optional container name (for Azure)
    
    Returns:
        bytes content or None if not found
    """
    if not location:
        return None
    
    # Auto-detect storage kind
    if storage_kind == "auto":
        if location.startswith("http") or location.startswith("https"):
            storage_kind = "azure"
        elif location.startswith("/") or Path(location).exists():
            storage_kind = "local"
        else:
            storage_kind = "azure"  # Assume relative path is Azure blob
    
    if storage_kind == "local":
        try:
            path = Path(location)
            if path.exists():
                return path.read_bytes()
        except Exception as e:
            print(f"[BlobStorage] Local read failed: {e}")
        return None
    
    # Azure storage
    conn, cont = _get_azure_config()
    cont = container or cont
    
    if not conn or not cont:
        # Try local fallback with archives path
        try:
            local_path = _local_archive_root() / location.lstrip("/")
            if local_path.exists():
                return local_path.read_bytes()
        except Exception:
            pass
        return None
    
    try:
        from azure.storage.blob import BlobServiceClient  # type: ignore
        
        bsc = BlobServiceClient.from_connection_string(conn)
        
        # Extract blob name from URL if needed
        blob_name = location
        if location.startswith("http"):
            # Parse blob name from URL
            # Format: https://<account>.blob.core.windows.net/<container>/<blob_path>
            parts = location.split(f"/{cont}/", 1)
            if len(parts) > 1:
                blob_name = parts[1]
            else:
                # Try to extract from path
                blob_name = location.split("/")[-1]
        
        blob = bsc.get_blob_client(container=cont, blob=blob_name)
        return blob.download_blob().readall()
        
    except Exception as e:
        print(f"[BlobStorage] Azure download failed: {e}")
        
        # Try local fallback
        try:
            local_path = _local_archive_root() / location.lstrip("/")
            if local_path.exists():
                return local_path.read_bytes()
        except Exception:
            pass
        
        return None


def delete_blob(
    *,
    location: str,
    storage_kind: str = "auto",
    container: Optional[str] = None,
) -> bool:
    """
    Delete a blob from Azure or local storage.
    
    Args:
        location: blob URL, blob path, or local file path
        storage_kind: "azure", "local", or "auto" to detect
        container: Optional container name (for Azure)
    
    Returns:
        True if deleted, False otherwise
    """
    if not location:
        return False
    
    # Auto-detect storage kind
    if storage_kind == "auto":
        if location.startswith("http") or location.startswith("https"):
            storage_kind = "azure"
        elif location.startswith("/") or Path(location).exists():
            storage_kind = "local"
        else:
            storage_kind = "azure"
    
    if storage_kind == "local":
        try:
            path = Path(location)
            if path.exists():
                path.unlink()
                print(f"[BlobStorage] Deleted local file: {location}")
                return True
        except Exception as e:
            print(f"[BlobStorage] Local delete failed: {e}")
        return False
    
    # Azure storage
    conn, cont = _get_azure_config()
    cont = container or cont
    
    if not conn or not cont:
        return False
    
    try:
        from azure.storage.blob import BlobServiceClient  # type: ignore
        
        bsc = BlobServiceClient.from_connection_string(conn)
        
        # Extract blob name from URL if needed
        blob_name = location
        if location.startswith("http"):
            parts = location.split(f"/{cont}/", 1)
            if len(parts) > 1:
                blob_name = parts[1]
        
        blob = bsc.get_blob_client(container=cont, blob=blob_name)
        blob.delete_blob()
        print(f"[BlobStorage] Deleted Azure blob: {blob_name}")
        return True
        
    except Exception as e:
        print(f"[BlobStorage] Azure delete failed: {e}")
        return False


def list_blobs(
    *,
    prefix: str = "",
    container: Optional[str] = None,
) -> List[str]:
    """
    List blobs with a given prefix.
    
    Args:
        prefix: Blob name prefix to filter by
        container: Optional container name
    
    Returns:
        List of blob names
    """
    conn, cont = _get_azure_config()
    cont = container or cont
    
    if not conn or not cont:
        # List local files
        try:
            root = _local_archive_root()
            if prefix:
                search_path = root / prefix
            else:
                search_path = root
            
            if search_path.is_dir():
                return [str(p.relative_to(root)) for p in search_path.rglob("*") if p.is_file()]
            elif search_path.parent.exists():
                return [str(p.relative_to(root)) for p in search_path.parent.glob(f"{search_path.name}*") if p.is_file()]
        except Exception as e:
            print(f"[BlobStorage] Local list failed: {e}")
        return []
    
    try:
        from azure.storage.blob import BlobServiceClient  # type: ignore
        
        bsc = BlobServiceClient.from_connection_string(conn)
        container_client = bsc.get_container_client(cont)
        
        blobs = []
        for blob in container_client.list_blobs(name_starts_with=prefix):
            blobs.append(blob.name)
        
        return blobs
        
    except Exception as e:
        print(f"[BlobStorage] Azure list failed: {e}")
        return []


def get_blob_url(*, rel_path: str, container: Optional[str] = None) -> Optional[str]:
    """
    Get the URL for a blob without downloading it.
    
    Args:
        rel_path: Relative path to the blob
        container: Optional container name
    
    Returns:
        Blob URL if Azure is configured, local path otherwise
    """
    conn, cont = _get_azure_config()
    cont = container or cont
    
    if not conn or not cont:
        path = _local_archive_root() / rel_path.lstrip("/")
        return str(path) if path.exists() else None
    
    try:
        from azure.storage.blob import BlobServiceClient  # type: ignore
        
        bsc = BlobServiceClient.from_connection_string(conn)
        blob = bsc.get_blob_client(container=cont, blob=rel_path)
        return blob.url
        
    except Exception as e:
        print(f"[BlobStorage] Get URL failed: {e}")
        return None

