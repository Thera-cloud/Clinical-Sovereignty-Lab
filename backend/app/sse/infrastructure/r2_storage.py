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
_R2_PUBLIC_BASE = "https://vault.sovereign-sanctuary.com"

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
    """Upload image bytes to R2. Returns the public URL."""
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
    return f"{_R2_PUBLIC_BASE}/{key}"


async def store_video(video_url: str, key: str) -> str:
    """Download video from temporary URL and upload to R2. Returns permanent URL."""
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
    return f"{_R2_PUBLIC_BASE}/{key}"
