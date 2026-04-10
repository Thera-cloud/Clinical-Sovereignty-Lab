"""SSE Infrastructure — Cloudflare R2 storage for generated assets."""
from __future__ import annotations

import asyncio
import logging
import os
from typing import Optional

import aiohttp

logger = logging.getLogger(__name__)

_R2_ACCOUNT_ID = os.getenv("R2_ACCOUNT_ID", "").strip()
_R2_ACCESS_KEY = os.getenv("R2_ACCESS_KEY_ID", "").strip()
_R2_SECRET_KEY = os.getenv("R2_SECRET_ACCESS_KEY", "").strip()
_R2_BUCKET = os.getenv("R2_BUCKET_NAME", "nate-vault").strip()
_R2_PUBLIC_BASE = os.getenv("R2_CDN_BASE_URL", "https://vault.sovereign-sanctuary.com").strip()

_client = None


def _is_configured() -> bool:
    return bool(_R2_ACCOUNT_ID and _R2_ACCESS_KEY and _R2_SECRET_KEY)


def _get_client():
    global _client
    if _client is not None:
        return _client
    if not _is_configured():
        return None
    try:
        import boto3
        _client = boto3.client(
            "s3",
            endpoint_url=f"https://{_R2_ACCOUNT_ID}.r2.cloudflarestorage.com",
            aws_access_key_id=_R2_ACCESS_KEY,
            aws_secret_access_key=_R2_SECRET_KEY,
            region_name="auto",
        )
    except Exception as e:
        logger.warning("r2_storage: boto3 client init failed: %s", e)
        return None
    return _client


def _mock_url(key: str) -> str:
    return f"mock://r2-not-configured/{key}"


async def store_image(image_bytes: bytes, key: str) -> str:
    """Upload image bytes to R2. Returns a presigned URL (24h)."""
    client = _get_client()
    if client is None:
        logger.warning("r2_storage: R2 credentials missing — returning mock URL for %s", key)
        return _mock_url(key)

    def _upload():
        client.put_object(
            Bucket=_R2_BUCKET,
            Key=key,
            Body=image_bytes,
            ContentType="image/png",
        )

    await asyncio.get_event_loop().run_in_executor(None, _upload)
    return presigned_url(key) or f"{_R2_PUBLIC_BASE}/{key}"


async def store_bytes(data: bytes, key: str, content_type: str = "application/octet-stream") -> str:
    """Upload arbitrary bytes to R2 with a specific content type. Returns presigned URL (24h)."""
    client = _get_client()
    if client is None:
        logger.warning("r2_storage: R2 credentials missing — returning mock URL for %s", key)
        return _mock_url(key)

    def _upload():
        client.put_object(Bucket=_R2_BUCKET, Key=key, Body=data, ContentType=content_type)

    await asyncio.get_event_loop().run_in_executor(None, _upload)
    return presigned_url(key) or f"{_R2_PUBLIC_BASE}/{key}"


async def store_video(video_url: str, key: str) -> str:
    """Download video from temporary URL and upload to R2. Returns presigned URL (24h)."""
    client = _get_client()
    if client is None:
        logger.warning("r2_storage: R2 credentials missing — returning mock URL for %s", key)
        return _mock_url(key)

    async with aiohttp.ClientSession() as session:
        async with session.get(video_url) as resp:
            if resp.status != 200:
                raise RuntimeError(f"Video download failed: {resp.status}")
            video_bytes = await resp.read()

    def _upload():
        client.put_object(
            Bucket=_R2_BUCKET,
            Key=key,
            Body=video_bytes,
            ContentType="video/mp4",
        )

    await asyncio.get_event_loop().run_in_executor(None, _upload)
    return presigned_url(key) or f"{_R2_PUBLIC_BASE}/{key}"


async def list_objects(prefix: str, max_keys: int = 500) -> list[dict]:
    """List R2 objects under *prefix*. Returns [{Key, Size, LastModified}, ...]."""
    client = _get_client()
    if client is None:
        return []

    def _list():
        resp = client.list_objects_v2(Bucket=_R2_BUCKET, Prefix=prefix, MaxKeys=max_keys)
        return resp.get("Contents", [])

    return await asyncio.get_event_loop().run_in_executor(None, _list)


async def download_bytes(key: str) -> Optional[bytes]:
    """Download object bytes directly from R2 via S3 API (no public URL needed)."""
    client = _get_client()
    if client is None:
        return None

    def _get():
        resp = client.get_object(Bucket=_R2_BUCKET, Key=key)
        return resp["Body"].read()

    try:
        return await asyncio.get_event_loop().run_in_executor(None, _get)
    except Exception as e:
        logger.warning("r2_storage: download_bytes(%s) failed: %s", key, e)
        return None


def presigned_url(key: str, expires_in: int = 86400) -> Optional[str]:
    """Generate a presigned GET URL for an R2 object (default 24h expiry)."""
    client = _get_client()
    if client is None:
        return None
    return client.generate_presigned_url(
        "get_object", Params={"Bucket": _R2_BUCKET, "Key": key}, ExpiresIn=expires_in,
    )
