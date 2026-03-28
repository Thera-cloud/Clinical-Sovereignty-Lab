"""
Backblaze B2 object storage client (S3-compatible).

Priority in the storage hierarchy:
  R2 (hot/warm, zero egress) → B2 (cold/archive, 60% cheaper) → Azure (fallback)

B2 is S3-compatible via its S3 endpoint. Zero egress through Cloudflare
Bandwidth Alliance when reads go through the custom domain CNAME
(b2.sovereignsanctuary.net → s3.{region}.backblazeb2.com).

Storage: $0.006/GB/month (vs R2 $0.015/GB/month).

Object Lock support for WORM compliance (heritage vault, audit logs,
therapy recordings, GKM donation records).
"""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Dict, List, Optional, Tuple

_logger = logging.getLogger("b2_storage")

_B2_KEY_ID = os.getenv("B2_APPLICATION_KEY_ID", "").strip()
_B2_APP_KEY = os.getenv("B2_APPLICATION_KEY", "").strip()
_B2_ENDPOINT = os.getenv("B2_S3_ENDPOINT", "").strip()
_B2_REGION = os.getenv("B2_REGION", "us-west-004").strip()
_B2_DEFAULT_BUCKET = os.getenv("B2_DEFAULT_BUCKET", "nate-cold-archive").strip()
_B2_PUBLIC_URL = os.getenv("B2_PUBLIC_URL", "").strip()


def _endpoint_url() -> str:
    if _B2_ENDPOINT:
        return _B2_ENDPOINT
    return f"https://s3.{_B2_REGION}.backblazeb2.com"


def is_b2_configured() -> bool:
    return bool(_B2_KEY_ID and _B2_APP_KEY)


def _get_s3_client():
    """Create a boto3 S3 client pointed at Backblaze B2 S3-compatible endpoint."""
    try:
        import boto3
        from botocore.config import Config
    except ImportError:
        _logger.warning("boto3 not installed — B2 storage unavailable")
        return None

    return boto3.client(
        "s3",
        endpoint_url=_endpoint_url(),
        aws_access_key_id=_B2_KEY_ID,
        aws_secret_access_key=_B2_APP_KEY,
        config=Config(
            signature_version="s3v4",
            retries={"max_attempts": 3, "mode": "adaptive"},
        ),
        region_name=_B2_REGION,
    )


def upload_bytes(
    *,
    key: str,
    content: bytes,
    bucket: Optional[str] = None,
    content_type: str = "application/octet-stream",
    metadata: Optional[Dict[str, str]] = None,
    object_lock_mode: Optional[str] = None,
    object_lock_retain_until: Optional[str] = None,
) -> Tuple[str, str]:
    """
    Upload bytes to B2.

    Args:
        object_lock_mode: "GOVERNANCE" or "COMPLIANCE" (requires bucket lock enabled).
        object_lock_retain_until: ISO 8601 datetime for retention (e.g., "2033-01-01T00:00:00Z").

    Returns:
        (storage_kind, location) — ("b2", public_url_or_key)
    """
    if not is_b2_configured():
        raise RuntimeError("B2 not configured")

    bucket = bucket or _B2_DEFAULT_BUCKET
    key = (key or "").lstrip("/").strip()
    if not key:
        raise ValueError("key is required")

    client = _get_s3_client()
    if client is None:
        raise RuntimeError("boto3 not available")

    extra_args: Dict = {"ContentType": content_type}
    if metadata:
        extra_args["Metadata"] = metadata
    if object_lock_mode:
        extra_args["ObjectLockMode"] = object_lock_mode
    if object_lock_retain_until:
        extra_args["ObjectLockRetainUntilDate"] = object_lock_retain_until

    client.put_object(
        Bucket=bucket,
        Key=key,
        Body=content or b"",
        **extra_args,
    )

    location = f"{_B2_PUBLIC_URL}/{key}" if _B2_PUBLIC_URL else key
    return "b2", location


async def upload_bytes_async(
    *,
    key: str,
    content: bytes,
    bucket: Optional[str] = None,
    content_type: str = "application/octet-stream",
    metadata: Optional[Dict[str, str]] = None,
    object_lock_mode: Optional[str] = None,
    object_lock_retain_until: Optional[str] = None,
) -> Tuple[str, str]:
    """Async wrapper for upload_bytes (runs in thread pool)."""
    return await asyncio.to_thread(
        upload_bytes,
        key=key,
        content=content,
        bucket=bucket,
        content_type=content_type,
        metadata=metadata,
        object_lock_mode=object_lock_mode,
        object_lock_retain_until=object_lock_retain_until,
    )


def download_bytes(
    *,
    key: str,
    bucket: Optional[str] = None,
) -> Optional[bytes]:
    """
    Download bytes from B2 by key.

    Returns:
        Raw bytes or None if not found / not configured.
    """
    if not is_b2_configured():
        return None

    bucket = bucket or _B2_DEFAULT_BUCKET
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
        _logger.warning("B2 download failed for %s: %s", key, e)
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
    Delete an object from B2.

    Returns:
        True if delete call succeeded, False otherwise.
    Note: Object Lock objects cannot be deleted until retention expires.
    """
    if not is_b2_configured():
        return False

    bucket = bucket or _B2_DEFAULT_BUCKET
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
        _logger.warning("B2 delete failed for %s: %s", key, e)
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
    if not is_b2_configured():
        return []

    bucket = bucket or _B2_DEFAULT_BUCKET
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
        _logger.warning("B2 list failed for prefix=%s: %s", prefix, e)
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
    Generate a presigned URL for direct client download.
    When served through a Cloudflare custom domain, egress is $0.

    Args:
        key: Object key in B2.
        bucket: Bucket name (default: B2_DEFAULT_BUCKET).
        expires_in: URL validity in seconds (default: 1 hour).

    Returns:
        Presigned URL string, or None if B2 not configured.
    """
    if not is_b2_configured():
        return None

    bucket = bucket or _B2_DEFAULT_BUCKET
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
        _logger.warning("B2 presigned URL failed for %s: %s", key, e)
        return None


def get_public_url(
    *,
    key: str,
    bucket: Optional[str] = None,
) -> Optional[str]:
    """
    Build a Cloudflare-proxied public URL for a B2 object.

    The CNAME b2.sovereignsanctuary.net → s3.{region}.backblazeb2.com routes
    through Cloudflare's network, activating the Bandwidth Alliance (zero
    egress) and edge caching. The URL format follows B2's S3-compatible path:
      https://b2.sovereignsanctuary.net/file/{bucket}/{key}

    Returns None if B2_PUBLIC_URL is not configured.
    """
    if not _B2_PUBLIC_URL:
        return None
    bucket = bucket or _B2_DEFAULT_BUCKET
    key = (key or "").lstrip("/").strip()
    if not key:
        return None
    return f"{_B2_PUBLIC_URL}/file/{bucket}/{key}"


def get_cached_url(
    *,
    key: str,
    bucket: Optional[str] = None,
    expires_in: int = 3600,
) -> Optional[str]:
    """
    Get a URL for reading a B2 object through Cloudflare (zero egress + caching).

    Prefers the public CNAME URL (cached at edge, zero cost). Falls back to a
    presigned S3 URL if the CNAME is not configured.
    """
    public = get_public_url(key=key, bucket=bucket)
    if public:
        return public
    return generate_presigned_url(key=key, bucket=bucket, expires_in=expires_in)


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
    if not is_b2_configured():
        return None

    bucket = bucket or _B2_DEFAULT_BUCKET
    client = _get_s3_client()
    if client is None:
        return None

    try:
        return client.head_object(Bucket=bucket, Key=key)
    except Exception as e:
        _logger.debug("B2 head_object failed for %s: %s", key, e)
        return None


def copy_from_r2(
    *,
    r2_key: str,
    b2_key: Optional[str] = None,
    r2_bucket: Optional[str] = None,
    b2_bucket: Optional[str] = None,
    object_lock_mode: Optional[str] = None,
    object_lock_retain_until: Optional[str] = None,
) -> bool:
    """
    Copy an object from R2 to B2 (cold tiering migration).

    Downloads from R2 then uploads to B2. Both use S3 API via boto3
    but different endpoints, so cross-copy requires a local relay.

    Returns:
        True on success, False on failure.
    """
    try:
        from app.services.r2_storage import download_bytes as r2_download

        data = r2_download(key=r2_key, bucket=r2_bucket)
        if data is None:
            _logger.warning("B2 copy_from_r2: R2 object not found: %s", r2_key)
            return False

        target_key = b2_key or r2_key
        upload_bytes(
            key=target_key,
            content=data,
            bucket=b2_bucket,
            object_lock_mode=object_lock_mode,
            object_lock_retain_until=object_lock_retain_until,
        )
        _logger.info("Copied R2→B2: %s (%d bytes)", target_key, len(data))
        return True
    except Exception as e:
        _logger.warning("B2 copy_from_r2 failed for %s: %s", r2_key, e)
        return False


async def copy_from_r2_async(
    *,
    r2_key: str,
    b2_key: Optional[str] = None,
    r2_bucket: Optional[str] = None,
    b2_bucket: Optional[str] = None,
    object_lock_mode: Optional[str] = None,
    object_lock_retain_until: Optional[str] = None,
) -> bool:
    """Async wrapper for copy_from_r2."""
    return await asyncio.to_thread(
        copy_from_r2,
        r2_key=r2_key,
        b2_key=b2_key,
        r2_bucket=r2_bucket,
        b2_bucket=b2_bucket,
        object_lock_mode=object_lock_mode,
        object_lock_retain_until=object_lock_retain_until,
    )
