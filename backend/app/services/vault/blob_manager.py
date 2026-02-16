"""
Sovereign Vault — Blob storage manager (B2).

VaultBlobManager: Quarantine → clean → permanent storage with tiered containers.
Wraps backend/app/services/blob_storage.
"""

from __future__ import annotations

import logging
import os
import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

from app.services import blob_storage


def _parse_account_key(conn_str: str) -> Optional[str]:
    """Extract AccountKey from Azure connection string."""
    for part in conn_str.split(";"):
        if part.strip().lower().startswith("accountkey="):
            return part.split("=", 1)[1].strip()
    return None


def _sanitize_path_component(s: str) -> str:
    """Remove any characters that could enable path traversal."""
    return re.sub(r'[^a-zA-Z0-9_\-]', '', str(s))


def _local_archive_root() -> Path:
    data_dir = Path(os.getenv("DATA_DIR", "/app/data"))
    return data_dir / "archives"


# Container / path prefixes for vault tiers
VAULT_QUARANTINE = "vault-quarantine"
VAULT_CLEAN = "vault-clean"
VAULT_PERMANENT = "vault-permanent"


class VaultBlobManager:
    """
    Manages vault blob storage: quarantine for new uploads, clean after scan,
    permanent for promoted items.
    """

    def __init__(
        self,
        quarantine_container: Optional[str] = None,
        clean_container: Optional[str] = None,
        permanent_container: Optional[str] = None,
    ):
        self.quarantine_container = quarantine_container or VAULT_QUARANTINE
        self.clean_container = clean_container or VAULT_CLEAN
        self.permanent_container = permanent_container or VAULT_PERMANENT

    def store_quarantine(
        self, upload_id: str, file_bytes: bytes, mime_type: str
    ) -> str:
        """
        Store file in quarantine container. Returns storage location (blob URL or path).
        """
        safe_upload_id = _sanitize_path_component(upload_id)
        rel_path = f"quarantine/{safe_upload_id}"
        _, location = blob_storage.upload_bytes(
            rel_path=rel_path,
            content=file_bytes,
            container=self.quarantine_container,
            content_type=mime_type or "application/octet-stream",
        )
        return location

    def promote_to_clean(self, upload_id: str) -> str:
        """
        Move blob from quarantine to clean container. Returns new location.
        """
        safe_upload_id = _sanitize_path_component(upload_id)
        rel_quarantine = f"quarantine/{safe_upload_id}"
        # Download from quarantine
        content = blob_storage.download_bytes(
            location=rel_quarantine,
            storage_kind="auto",
            container=self.quarantine_container,
        )
        if not content:
            # Try with full path for local (container not used in local path)
            if blob_storage.is_azure_configured():
                raise ValueError(f"Quarantine blob not found: {upload_id}")
            local_path = _local_archive_root() / rel_quarantine
            if local_path.exists():
                content = local_path.read_bytes()
            else:
                raise ValueError(f"Quarantine blob not found: {upload_id}")
        # Upload to clean
        rel_clean = f"clean/{safe_upload_id}"
        _, location = blob_storage.upload_bytes(
            rel_path=rel_clean,
            content=content,
            container=self.clean_container,
            content_type="application/octet-stream",
        )
        # Delete from quarantine
        delete_location = (
            str(_local_archive_root() / rel_quarantine)
            if not blob_storage.is_azure_configured()
            else rel_quarantine
        )
        blob_storage.delete_blob(
            location=delete_location,
            storage_kind="local" if not blob_storage.is_azure_configured() else "azure",
            container=self.quarantine_container,
        )
        return location

    def store_permanent(
        self,
        member_id: str,
        item_id: str,
        file_bytes: bytes,
        mime_type: str,
    ) -> str:
        """
        Store file in permanent vault under member/item.
        Returns storage location.
        """
        safe_member = _sanitize_path_component(member_id)
        safe_item = _sanitize_path_component(item_id)
        rel_path = f"members/{safe_member}/{safe_item}"
        _, location = blob_storage.upload_bytes(
            rel_path=rel_path,
            content=file_bytes,
            container=self.permanent_container,
            content_type=mime_type or "application/octet-stream",
        )
        return location

    def store_thumbnail(
        self, member_id: str, item_id: str, thumbnail_bytes: bytes
    ) -> str:
        """Store thumbnail in permanent vault."""
        safe_member = _sanitize_path_component(member_id)
        safe_item = _sanitize_path_component(item_id)
        rel_path = f"members/{safe_member}/{safe_item}_thumb.jpg"
        _, location = blob_storage.upload_bytes(
            rel_path=rel_path,
            content=thumbnail_bytes,
            container=self.permanent_container,
            content_type="image/jpeg",
        )
        return location

    def read_blob(self, blob_path: str) -> bytes:
        """
        Read blob content by path. Tries permanent, clean, then quarantine containers.
        Returns bytes or empty bytes if not found.
        """
        if not blob_path or ".." in blob_path:
            return b""
        if blob_storage.is_azure_configured():
            for container_name in [
                self.permanent_container,
                self.clean_container,
                self.quarantine_container,
            ]:
                content = blob_storage.download_bytes(
                    location=blob_path,
                    storage_kind="azure",
                    container=container_name,
                )
                if content:
                    return content
            return b""
        # Local: blob_path may be full path or relative
        path = Path(blob_path) if blob_path.startswith("/") else _local_archive_root() / blob_path.lstrip("/")
        if path.exists() and path.is_file():
            return path.read_bytes()
        return b""

    def get_signed_url(self, blob_path: str, ttl_minutes: int = 15) -> str:
        """
        Return a signed URL (Azure SAS) or direct path (local) for the blob.
        """
        if ".." in blob_path or not blob_path:
            raise ValueError("Invalid blob path")
        if blob_storage.is_azure_configured():
            return self._get_azure_sas_url(blob_path, ttl_minutes)
        # Local: blob_path may be full path from upload_bytes or relative
        path = Path(blob_path) if blob_path.startswith("/") else _local_archive_root() / blob_path.lstrip("/")
        return str(path) if path.exists() else ""

    def _get_azure_sas_url(self, blob_path: str, ttl_minutes: int) -> str:
        """Generate Azure Blob SAS URL."""
        conn = (os.getenv("AZURE_STORAGE_CONNECTION_STRING") or "").strip()
        account_key = _parse_account_key(conn)
        if not conn or not account_key:
            return ""
        try:
            from azure.storage.blob import (
                BlobServiceClient,
                BlobSasPermissions,
                generate_blob_sas,
            )

            bsc = BlobServiceClient.from_connection_string(conn)
            account_name = bsc.account_name
            for container_name in [
                self.permanent_container,
                self.clean_container,
                self.quarantine_container,
            ]:
                blob = bsc.get_blob_client(container=container_name, blob=blob_path)
                try:
                    if blob.exists():
                        sas_token = generate_blob_sas(
                            account_name=account_name,
                            container_name=container_name,
                            blob_name=blob_path,
                            account_key=account_key,
                            permission=BlobSasPermissions(read=True),
                            expiry=datetime.utcnow() + timedelta(minutes=ttl_minutes),
                        )
                        return f"{blob.url}?{sas_token}"
                except Exception as e:
                    logging.getLogger(__name__).debug(
                        "SAS skip container %s: %s", container_name, e
                    )
                    continue
            return ""
        except Exception as e:
            logging.getLogger(__name__).warning(
                "VaultBlobManager SAS generation failed: %s", e
            )
            url = blob_storage.get_blob_url(
                rel_path=blob_path,
                container=self.permanent_container,
            )
            return url or ""

    def delete_blob(self, blob_path: str) -> bool:
        """Delete a blob from storage."""
        if ".." in blob_path:
            raise ValueError("Invalid blob path")
        return blob_storage.delete_blob(
            location=blob_path,
            storage_kind="auto",
            container=None,
        )

    def get_member_storage_bytes(self, member_id: str) -> int:
        """Calculate total storage used by a member (sum of blob sizes)."""
        safe_member = _sanitize_path_component(member_id)
        prefix = f"members/{safe_member}/"
        total = 0
        if blob_storage.is_azure_configured():
            total = self._sum_azure_blob_sizes(prefix)
        else:
            total = self._sum_local_sizes(prefix)
        return total

    def _sum_local_sizes(self, prefix: str) -> int:
        """Sum file sizes for local storage (container not used in path)."""
        root = _local_archive_root()
        base = root / prefix
        if not base.exists():
            return 0
        total = 0
        for p in base.rglob("*"):
            if p.is_file():
                total += p.stat().st_size
        return total

    def _sum_azure_blob_sizes(self, prefix: str) -> int:
        """Sum blob sizes for Azure storage."""
        conn = (os.getenv("AZURE_STORAGE_CONNECTION_STRING") or "").strip()
        if not conn:
            return 0
        try:
            from azure.storage.blob import BlobServiceClient

            bsc = BlobServiceClient.from_connection_string(conn)
            container = bsc.get_container_client(self.permanent_container)
            total = 0
            for blob in container.list_blobs(name_starts_with=prefix):
                total += blob.size or 0
            return total
        except Exception as e:
            logging.getLogger(__name__).warning(
                "VaultBlobManager Azure list sizes failed: %s", e
            )
            return 0
