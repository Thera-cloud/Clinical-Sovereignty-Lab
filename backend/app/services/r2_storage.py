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


# ---------------------------------------------------------------------------
# Multipart upload — direct browser → R2 path for large files (videos up to 5TB).
#
# The flow:
#   1. backend create_multipart_upload(key) → {upload_id}
#   2. backend generate_presigned_part_url(...) for each part_number → URL
#   3. browser PUTs each chunk to its URL, captures ETag from response header
#   4. backend complete_multipart_upload(key, upload_id, parts=[{ETag, PartNumber}])
#   5. on any failure / cancel: backend abort_multipart_upload(key, upload_id)
#
# R2 implements the S3 multipart API with these constraints:
#   - min part size = 5 MiB (except final part)
#   - max parts    = 10000
#   - max object   = 5 TiB
#
# We use 8 MiB parts by default → supports up to 80 GiB per object.
# ---------------------------------------------------------------------------

DEFAULT_MULTIPART_PART_SIZE = 8 * 1024 * 1024  # 8 MiB
MAX_MULTIPART_OBJECT_BYTES = 5 * 1024 * 1024 * 1024 * 1024  # 5 TiB R2 hard limit
MAX_MULTIPART_PARTS = 10000


def create_multipart_upload(
    *,
    key: str,
    bucket: Optional[str] = None,
    content_type: str = "application/octet-stream",
    metadata: Optional[Dict[str, str]] = None,
) -> Optional[Dict]:
    """
    Initiate an S3 multipart upload on R2.

    Returns a dict {bucket, key, upload_id} or None on failure.
    """
    if not is_r2_configured():
        return None

    bucket = bucket or _R2_DEFAULT_BUCKET
    key = (key or "").lstrip("/").strip()
    if not key:
        raise ValueError("key is required")

    client = _get_s3_client()
    if client is None:
        return None

    try:
        params: Dict = {"Bucket": bucket, "Key": key, "ContentType": content_type}
        if metadata:
            params["Metadata"] = metadata
        resp = client.create_multipart_upload(**params)
        return {
            "bucket": bucket,
            "key": key,
            "upload_id": resp["UploadId"],
        }
    except Exception as e:
        _logger.error("R2 create_multipart_upload failed for %s: %s", key, e)
        return None


def generate_presigned_part_url(
    *,
    key: str,
    upload_id: str,
    part_number: int,
    bucket: Optional[str] = None,
    expires_in: int = 6 * 3600,
) -> Optional[str]:
    """
    Generate a presigned URL the browser can use to PUT a single multipart part.

    The browser will PUT the chunk bytes to this URL and read the `ETag`
    response header to send back to /complete. No auth header is needed
    on the PUT itself — the URL contains the signature.

    Default TTL is 6 hours so a slow 3 GB upload over a flaky connection
    has plenty of headroom.
    """
    if not is_r2_configured():
        return None
    if part_number < 1 or part_number > MAX_MULTIPART_PARTS:
        raise ValueError(f"part_number must be 1..{MAX_MULTIPART_PARTS}")

    bucket = bucket or _R2_DEFAULT_BUCKET
    client = _get_s3_client()
    if client is None:
        return None

    try:
        return client.generate_presigned_url(
            "upload_part",
            Params={
                "Bucket": bucket,
                "Key": key,
                "UploadId": upload_id,
                "PartNumber": part_number,
            },
            ExpiresIn=expires_in,
        )
    except Exception as e:
        _logger.warning(
            "R2 presigned upload_part failed for %s part %d: %s",
            key,
            part_number,
            e,
        )
        return None


def complete_multipart_upload(
    *,
    key: str,
    upload_id: str,
    parts: List[Dict],
    bucket: Optional[str] = None,
) -> Optional[Dict]:
    """
    Finalize a multipart upload.

    `parts` must be a list of dicts shaped {"PartNumber": int, "ETag": str},
    sorted ascending by PartNumber. Returns the boto3 response dict on
    success or None on failure.
    """
    if not is_r2_configured():
        return None
    if not parts:
        raise ValueError("parts is required and non-empty")

    bucket = bucket or _R2_DEFAULT_BUCKET
    client = _get_s3_client()
    if client is None:
        return None

    normalized: List[Dict] = []
    for p in parts:
        pn = int(p.get("PartNumber") or p.get("part_number") or 0)
        etag = p.get("ETag") or p.get("etag") or ""
        if pn < 1 or not etag:
            raise ValueError(f"invalid part entry: {p!r}")
        # ETag from S3 PUT comes wrapped in quotes; preserve as-is
        normalized.append({"PartNumber": pn, "ETag": etag})
    normalized.sort(key=lambda x: x["PartNumber"])

    try:
        return client.complete_multipart_upload(
            Bucket=bucket,
            Key=key,
            UploadId=upload_id,
            MultipartUpload={"Parts": normalized},
        )
    except Exception as e:
        _logger.error(
            "R2 complete_multipart_upload failed for %s upload_id=%s: %s",
            key,
            upload_id,
            e,
        )
        return None


def abort_multipart_upload(
    *,
    key: str,
    upload_id: str,
    bucket: Optional[str] = None,
) -> bool:
    """Abort an in-flight multipart upload (releases R2 staged-part storage)."""
    if not is_r2_configured():
        return False

    bucket = bucket or _R2_DEFAULT_BUCKET
    client = _get_s3_client()
    if client is None:
        return False

    try:
        client.abort_multipart_upload(Bucket=bucket, Key=key, UploadId=upload_id)
        return True
    except Exception as e:
        _logger.warning(
            "R2 abort_multipart_upload failed for %s upload_id=%s: %s",
            key,
            upload_id,
            e,
        )
        return False


def download_to_file(
    *,
    key: str,
    dest_path: str,
    bucket: Optional[str] = None,
) -> bool:
    """
    Stream an R2 object to a local file using boto3's chunked download.

    Used by the transcription pipeline to pull large videos out of R2
    without ever loading the bytes into Python memory.
    """
    if not is_r2_configured():
        return False

    bucket = bucket or _R2_DEFAULT_BUCKET
    client = _get_s3_client()
    if client is None:
        return False

    try:
        client.download_file(Bucket=bucket, Key=key, Filename=dest_path)
        return True
    except Exception as e:
        _logger.error("R2 download_file failed for %s → %s: %s", key, dest_path, e)
        return False


async def download_to_file_async(
    *,
    key: str,
    dest_path: str,
    bucket: Optional[str] = None,
) -> bool:
    """Async wrapper for download_to_file."""
    return await asyncio.to_thread(
        download_to_file, key=key, dest_path=dest_path, bucket=bucket
    )
