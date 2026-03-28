"""
Cloudflare R2 object storage client (S3-compatible).

Priority in the storage hierarchy:
  R2 (zero egress) → Azure Blob (fallback) → Local disk (last resort)

R2 is S3-compatible, so we use boto3 with a custom endpoint URL.
Free tier: 10 GB storage, 1M Class A (writes), 10M Class B (reads)/month.
Zero egress fees at any scale.
"""

from __future__ import annotations

import asyncio
import io
import logging
import os
from typing import Dict, List, Optional, Tuple

_logger = logging.getLogger("r2_storage")

_R2_ACCOUNT_ID = os.getenv("R2_ACCOUNT_ID", "").strip()
_R2_ACCESS_KEY_ID = os.getenv("R2_ACCESS_KEY_ID", "").strip()
_R2_SECRET_ACCESS_KEY = os.getenv("R2_SECRET_ACCESS_KEY", "").strip()
_R2_DEFAULT_BUCKET = os.getenv("R2_DEFAULT_BUCKET", "nate-vault").strip()
_R2_PUBLIC_URL = os.getenv("R2_PUBLIC_URL", "").strip()


def _endpoint_url() -> str:
    return f"https://{_R2_ACCOUNT_ID}.r2.cloudflarestorage.com"


def is_r2_configured() -> bool:
    return bool(_R2_ACCOUNT_ID and _R2_ACCESS_KEY_ID and _R2_SECRET_ACCESS_KEY)


def _get_s3_client():
    """Create a boto3 S3 client pointed at Cloudflare R2."""
    try:
        import boto3
        from botocore.config import Config
    except ImportError:
        _logger.warning("boto3 not installed — R2 storage unavailable")
        return None

    return boto3.client(
        "s3",
        endpoint_url=_endpoint_url(),
        aws_access_key_id=_R2_ACCESS_KEY_ID,
        aws_secret_access_key=_R2_SECRET_ACCESS_KEY,
        config=Config(
            signature_version="s3v4",
            retries={"max_attempts": 3, "mode": "adaptive"},
        ),
        region_name="auto",
    )


def upload_bytes(
    *,
    key: str,
    content: bytes,
    bucket: Optional[str] = None,
    content_type: str = "application/octet-stream",
    metadata: Optional[Dict[str, str]] = None,
) -> Tuple[str, str]:
    """
    Upload bytes to R2.

    Returns:
        (storage_kind, location) — ("r2", public_url_or_key)

    Raises:
        RuntimeError if R2 is not configured or upload fails.
    """
    if not is_r2_configured():
        raise RuntimeError("R2 not configured")

    bucket = bucket or _R2_DEFAULT_BUCKET
    key = (key or "").lstrip("/").strip()
    if not key:
        raise ValueError("key is required")

    client = _get_s3_client()
    if client is None:
        raise RuntimeError("boto3 not available")

    extra_args: Dict = {"ContentType": content_type}
    if metadata:
        extra_args["Metadata"] = metadata

    client.put_object(
        Bucket=bucket,
        Key=key,
        Body=content or b"",
        **extra_args,
    )

    location = f"{_R2_PUBLIC_URL}/{key}" if _R2_PUBLIC_URL else key
    return "r2", location


async def upload_bytes_async(
    *,
    key: str,
    content: bytes,
    bucket: Optional[str] = None,
    content_type: str = "application/octet-stream",
    metadata: Optional[Dict[str, str]] = None,
) -> Tuple[str, str]:
    """Async wrapper for upload_bytes (runs in thread pool)."""
    return await asyncio.to_thread(
        upload_bytes,
        key=key,
        content=content,
        bucket=bucket,
        content_type=content_type,
        metadata=metadata,
    )


def download_bytes(
    *,
    key: str,
    bucket: Optional[str] = None,
) -> Optional[bytes]:
    """
    Download bytes from R2 by key.

    Returns:
        Raw bytes or None if not found / not configured.
    """
    if not is_r2_configured():
        return None

    bucket = bucket or _R2_DEFAULT_BUCKET
    key = (key or "").lstrip("/").strip()
    if not key:
        return None

    client = _get_s3_client()
    if client is None:
        return None

    try:
        resp = client.get_object(Bucket=bucket, Key=key)
        return resp["Body"].read()
    except client.exceptions.NoSuchKey:
        return None
    except Exception as e:
        _logger.warning("R2 download failed for %s: %s", key, e)
        return None


async def download_bytes_async(
    *,
    key: str,
    bucket: Optional[str] = None,
) -> Optional[bytes]:
    """Async wrapper for download_bytes."""
    return await asyncio.to_thread(download_bytes, key=key, bucket=bucket)


def delete_object(
    *,
    key: str,
    bucket: Optional[str] = None,
) -> bool:
    """
    Delete an object from R2.

    Returns:
        True if delete call succeeded, False otherwise.
    """
    if not is_r2_configured():
        return False

    bucket = bucket or _R2_DEFAULT_BUCKET
    key = (key or "").lstrip("/").strip()
    if not key:
        return False

    client = _get_s3_client()
    if client is None:
        return False

    try:
        client.delete_object(Bucket=bucket, Key=key)
        return True
    except Exception as e:
        _logger.warning("R2 delete failed for %s: %s", key, e)
        return False


async def delete_object_async(
    *,
    key: str,
    bucket: Optional[str] = None,
) -> bool:
    """Async wrapper for delete_object."""
    return await asyncio.to_thread(delete_object, key=key, bucket=bucket)


def list_objects(
    *,
    prefix: str = "",
    bucket: Optional[str] = None,
    max_keys: int = 1000,
) -> List[str]:
    """
    List object keys matching a prefix.

    Returns:
        List of object keys.
    """
    if not is_r2_configured():
        return []

    bucket = bucket or _R2_DEFAULT_BUCKET
    client = _get_s3_client()
    if client is None:
        return []

    try:
        resp = client.list_objects_v2(
            Bucket=bucket,
            Prefix=prefix,
            MaxKeys=max_keys,
        )
        return [obj["Key"] for obj in resp.get("Contents", [])]
    except Exception as e:
        _logger.warning("R2 list failed for prefix=%s: %s", prefix, e)
        return []


async def list_objects_async(
    *,
    prefix: str = "",
    bucket: Optional[str] = None,
    max_keys: int = 1000,
) -> List[str]:
    """Async wrapper for list_objects."""
    return await asyncio.to_thread(
        list_objects, prefix=prefix, bucket=bucket, max_keys=max_keys
    )


def generate_presigned_url(
    *,
    key: str,
    bucket: Optional[str] = None,
    expires_in: int = 3600,
) -> Optional[str]:
    """
    Generate a presigned URL for direct client download (bypasses origin).

    Args:
        key: Object key in R2.
        bucket: Bucket name (default: R2_DEFAULT_BUCKET).
        expires_in: URL validity in seconds (default: 1 hour).

    Returns:
        Presigned URL string, or None if R2 not configured.
    """
    if not is_r2_configured():
        return None

    bucket = bucket or _R2_DEFAULT_BUCKET
    client = _get_s3_client()
    if client is None:
        return None

    try:
        return client.generate_presigned_url(
            "get_object",
            Params={"Bucket": bucket, "Key": key},
            ExpiresIn=expires_in,
        )
    except Exception as e:
        _logger.warning("R2 presigned URL failed for %s: %s", key, e)
        return None


def head_object(
    *,
    key: str,
    bucket: Optional[str] = None,
) -> Optional[Dict]:
    """
    Get object metadata without downloading the body.

    Returns:
        Dict with ContentLength, ContentType, Metadata, etc. or None.
    """
    if not is_r2_configured():
        return None

    bucket = bucket or _R2_DEFAULT_BUCKET
    client = _get_s3_client()
    if client is None:
        return None

    try:
        return client.head_object(Bucket=bucket, Key=key)
    except Exception as e:
        _logger.debug("R2 head_object failed for %s: %s", key, e)
        return None
