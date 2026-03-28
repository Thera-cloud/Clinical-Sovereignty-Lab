"""
SDH Pre-computation Cache — Redis-backed cache for pre-computed SDH context blocks.

Key pattern: sdh:{user_id}:{state_hash}
TTL: 60 seconds default
Uses redis.asyncio for async operations.
Gracefully handles missing Redis (returns None on get, no-op on put).
"""

import hashlib
import json
import logging
import os
from typing import Dict, Optional

logger = logging.getLogger(__name__)

_SDH_PREFIX = "sdh"
_DEFAULT_TTL = 60


class SDHPrecomputeCache:
    """Redis-backed cache for pre-computed SDH context blocks."""

    def __init__(self, redis_url: str = None):
        self._redis_url = redis_url or os.getenv("REDIS_URL", "redis://localhost:6379")
        self._redis = None
        self._available = False
        self._init_client()

    def _init_client(self):
        """Create async Redis client (lazy connect on first use)."""
        try:
            import redis.asyncio as aioredis
            self._redis = aioredis.from_url(
                self._redis_url,
                decode_responses=True,
                socket_connect_timeout=3,
            )
            self._available = True
        except Exception as e:
            logger.warning("SDHPrecomputeCache: Redis init failed: %s", e)
            self._available = False

    def _key(self, user_id: str, state_hash: str, face_path: str = "") -> str:
        if face_path:
            return f"{_SDH_PREFIX}:{user_id}:{face_path}:{state_hash}"
        return f"{_SDH_PREFIX}:{user_id}:{state_hash}"

    async def get(self, user_id: str, state_hash: str, face_path: str = "") -> Optional[Dict]:
        """Retrieve a cached SDH block. Returns dict or None if miss/unavailable."""
        if not self._available or not self._redis:
            return None
        try:
            key = self._key(user_id, state_hash, face_path)
            raw = await self._redis.get(key)
            if raw is None:
                return None
            data = json.loads(raw)
            logger.debug("SDH cache HIT for %s:%s", user_id, state_hash[:8] if state_hash else "")
            return data
        except Exception as e:
            logger.warning("SDH cache get failed: %s", e)
            self._available = False
            return None

    async def put(
        self, user_id: str, state_hash: str, block_dict: Dict,
        ttl: int = 60, face_path: str = "",
    ) -> None:
        """Store a pre-computed SDH block. L1-keyed entries get longer TTL (300s)."""
        if not self._available or not self._redis:
            return
        effective_ttl = ttl
        if face_path and ":" in face_path:
            effective_ttl = max(ttl, 300)
        try:
            key = self._key(user_id, state_hash, face_path)
            payload = json.dumps(block_dict)
            await self._redis.setex(key, effective_ttl, payload)
            logger.debug("SDH cache PUT for %s:%s (TTL=%ds, face=%s)", user_id, state_hash[:8] if state_hash else "", effective_ttl, face_path[:40] if face_path else "")
        except Exception as e:
            logger.warning("SDH cache put failed: %s", e)
            self._available = False

    async def invalidate(self, user_id: str) -> None:
        """Remove all cached blocks for a user."""
        if not self._available or not self._redis:
            return
        try:
            pattern = f"{_SDH_PREFIX}:{user_id}:*"
            cursor = 0
            deleted = 0
            while True:
                cursor, keys = await self._redis.scan(cursor, match=pattern, count=100)
                if keys:
                    await self._redis.delete(*keys)
                    deleted += len(keys)
                if cursor == 0:
                    break
            if deleted:
                logger.debug("SDH cache invalidated %d entries for %s", deleted, user_id)
        except Exception as e:
            logger.warning("SDH cache invalidate failed: %s", e)
            self._available = False

    def compute_state_hash(
        self, user_id: str, last_message: str, session_id: str = "",
        face_path: str = "",
    ) -> str:
        """SHA256 hash of the conversation state for cache keying."""
        raw = f"{user_id}:{last_message}:{session_id}:{face_path}"
        return hashlib.sha256(raw.encode()).hexdigest()

    async def has_any_entry(self, user_id: str) -> bool:
        """Check if user has any valid cache entry (for skip logic)."""
        if not self._available or not self._redis:
            return False
        try:
            cursor, keys = await self._redis.scan(0, match=f"{_SDH_PREFIX}:{user_id}:*", count=10)
            return len(keys) > 0
        except Exception:
            return False

    @property
    def is_available(self) -> bool:
        return self._available
