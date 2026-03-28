"""
Voice capacity: Redis-backed active session counter, XTTS concurrency, firehose throttle.
"""

from __future__ import annotations

import logging
import os
from typing import Optional

logger = logging.getLogger("nate.voice_capacity")

XTTS_CONCURRENCY_LIMIT = int(os.getenv("XTTS_CONCURRENCY_LIMIT", "8"))
REDIS_ACTIVE_KEY = "nate:voice:active_sessions"
SLOT_KEY_PREFIX = "nate:voice:slot:"
FIREHOSE_KEY = "nate:voice:firehose_throttle"
SLOT_TTL_SEC = int(os.getenv("VOICE_SLOT_TTL_SEC", "7200"))


async def _redis():
    try:
        from app.services.api_server import _get_auth_redis
        return await _get_auth_redis()
    except Exception:
        return None


async def get_active_voice_count() -> int:
    r = await _redis()
    if not r:
        return 0
    try:
        v = await r.get(REDIS_ACTIVE_KEY)
        return int(v) if v is not None else 0
    except Exception as e:
        logger.warning("get_active_voice_count: %s", e)
        return 0


async def acquire_voice_slot(call_sid: str, *, crisis: bool = False) -> bool:
    """
    Reserve a voice rendering slot. Crisis callers bypass the concurrency cap.
    """
    if not call_sid:
        return False
    r = await _redis()
    if not r:
        # No Redis — allow (degraded) so voice still works on tiny dev setups
        return True
    slot_key = f"{SLOT_KEY_PREFIX}{call_sid}"
    try:
        exists = await r.get(slot_key)
        if exists:
            return True
        if crisis:
            pipe = r.pipeline()
            pipe.incr(REDIS_ACTIVE_KEY)
            pipe.setex(slot_key, SLOT_TTL_SEC, "1")
            await pipe.execute()
            logger.info("voice slot acquired (crisis bypass) call_sid=%s", call_sid[:12])
            return True
        cur = int(await r.get(REDIS_ACTIVE_KEY) or 0)
        if cur >= XTTS_CONCURRENCY_LIMIT:
            logger.info("voice slot denied (at capacity) active=%s limit=%s", cur, XTTS_CONCURRENCY_LIMIT)
            return False
        pipe = r.pipeline()
        pipe.incr(REDIS_ACTIVE_KEY)
        pipe.setex(slot_key, SLOT_TTL_SEC, "1")
        await pipe.execute()
        return True
    except Exception as e:
        logger.warning("acquire_voice_slot error: %s", e)
        return True


async def release_voice_slot(call_sid: str) -> None:
    if not call_sid:
        return
    r = await _redis()
    if not r:
        return
    slot_key = f"{SLOT_KEY_PREFIX}{call_sid}"
    try:
        existed = await r.get(slot_key)
        if existed:
            await r.delete(slot_key)
            n = await r.decr(REDIS_ACTIVE_KEY)
            if n < 0:
                await r.set(REDIS_ACTIVE_KEY, 0)
    except Exception as e:
        logger.warning("release_voice_slot error: %s", e)


async def set_firehose_throttle(level: str) -> None:
    """level: none | light | moderate | paused"""
    r = await _redis()
    if not r:
        return
    try:
        await r.set(FIREHOSE_KEY, level, ex=3600)
    except Exception as e:
        logger.warning("set_firehose_throttle: %s", e)


async def get_firehose_throttle() -> str:
    r = await _redis()
    if not r:
        return "none"
    try:
        v = await r.get(FIREHOSE_KEY)
        if isinstance(v, bytes):
            v = v.decode()
        return v or "none"
    except Exception:
        return "none"


def recompute_firehose_from_active(active: int) -> str:
    """Derive throttle label from active session count (addendum §4.3)."""
    if active <= 0:
        return "none"
    if active <= 3:
        return "light"
    if active <= 6:
        return "moderate"
    return "paused"
