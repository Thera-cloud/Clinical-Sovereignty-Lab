"""
SOVEREIGN SWARM — Hot Memory Tier

Redis-backed active context for session state, fibre state, and ephemeral data.
Graceful fallback to in-memory dict when Redis is not available.
Tapped through Pipeline Drum Clot Sensor for Redis flow monitoring (Hive v4.3).
"""

from __future__ import annotations

import json
import time as _time
from typing import Any, Callable, Dict, Optional

import structlog

logger = structlog.get_logger(__name__)

# Key prefixes for namespacing — every key MUST use one of these
PREFIX_SESSION = "hot:session:"
PREFIX_FIBRE = "hot:fibre:"
PREFIX_USER = "hot:user:"

ALLOWED_PREFIXES = (PREFIX_SESSION, PREFIX_FIBRE, PREFIX_USER)


class HotMemoryTier:
    """
    Redis-backed hot memory for active context.

    Stores JSON-serializable dicts with configurable TTL.
    Falls back to in-memory dict when Redis is unavailable.
    """

    def __init__(
        self,
        redis_client: Optional[Any] = None,
        drum_tap: Optional[Callable] = None,
    ) -> None:
        """
        Initialize HotMemoryTier.

        Args:
            redis_client: Optional Redis client (async). If None, uses in-memory fallback.
            drum_tap: Optional Pipeline Drum tap_redis callback for flow monitoring.
        """
        self._redis = redis_client
        self._drum_tap = drum_tap
        self._fallback: Dict[str, tuple[Dict[str, Any], Optional[int]]] = {}

    def _tap(self, op: str, key: str, latency_ms: float, success: bool = True) -> None:
        """Non-blocking tap for Pipeline Drum Clot Sensor."""
        if self._drum_tap:
            try:
                prefix = key.split(":")[0] + ":" + key.split(":")[1] if ":" in key else key[:20]
                self._drum_tap(op, prefix, latency_ms, success)
            except Exception:
                pass

    async def store(
        self,
        key: str,
        value: dict,
        ttl_seconds: int = 3600,
    ) -> None:
        """
        Store a key-value pair in Redis with optional TTL.

        Args:
            key: Storage key.
            value: Dict to store (must be JSON-serializable).
            ttl_seconds: Time-to-live in seconds. Default 1 hour.
        """
        if not any(key.startswith(p) for p in ALLOWED_PREFIXES):
            logger.warning(
                "hot_store_rejected_unscoped_key",
                key=key,
                hint="All keys must be prefixed with a recognized namespace (hot:session:, hot:fibre:, hot:user:)",
            )
            raise ValueError(
                f"HotMemoryTier key must start with an allowed prefix {ALLOWED_PREFIXES}. Got: {key[:40]}"
            )
        payload = json.dumps(value)
        if self._redis:
            _t0 = _time.monotonic()
            try:
                await self._redis.set(key, payload, ex=ttl_seconds)
                _lat = (_time.monotonic() - _t0) * 1000
                self._tap("SET", key, _lat, success=True)
                logger.debug("hot_store", key=key, ttl=ttl_seconds, redis=True)
            except Exception as e:
                _lat = (_time.monotonic() - _t0) * 1000
                self._tap("SET", key, _lat, success=False)
                logger.warning("hot_store_redis_failed", key=key, error=str(e))
                self._fallback[key] = (value, ttl_seconds)
        else:
            self._fallback[key] = (value, ttl_seconds)
            logger.debug("hot_store", key=key, ttl=ttl_seconds, redis=False)

    async def retrieve(self, key: str) -> Optional[Dict[str, Any]]:
        """
        Retrieve a value by key.

        Returns:
            Deserialized dict, or None if not found.
        """
        if self._redis:
            _t0 = _time.monotonic()
            try:
                raw = await self._redis.get(key)
                _lat = (_time.monotonic() - _t0) * 1000
                self._tap("GET", key, _lat, success=True)
                if raw is None:
                    return None
                return json.loads(raw)
            except json.JSONDecodeError as e:
                logger.warning("hot_retrieve_decode_error", key=key, error=str(e))
                return None
            except Exception as e:
                _lat = (_time.monotonic() - _t0) * 1000
                self._tap("GET", key, _lat, success=False)
                logger.warning("hot_retrieve_redis_failed", key=key, error=str(e))
                data = self._fallback.get(key)
                return data[0] if data else None
        data = self._fallback.get(key)
        return data[0] if data else None

    async def delete(self, key: str) -> bool:
        """
        Delete a key from storage.

        Returns:
            True if key was present and removed, False otherwise.
        """
        if self._redis:
            _t0 = _time.monotonic()
            try:
                n = await self._redis.delete(key)
                _lat = (_time.monotonic() - _t0) * 1000
                self._tap("DEL", key, _lat, success=True)
                return n > 0
            except Exception as e:
                _lat = (_time.monotonic() - _t0) * 1000
                self._tap("DEL", key, _lat, success=False)
                logger.warning("hot_delete_redis_failed", key=key, error=str(e))
        if key in self._fallback:
            del self._fallback[key]
            return True
        return False

    async def store_session_context(
        self,
        session_id: str,
        context: dict,
        ttl: int = 7200,
    ) -> None:
        """
        Store session context under the session namespace.

        Args:
            session_id: Session identifier.
            context: Session context dict.
            ttl: TTL in seconds. Default 2 hours.
        """
        key = f"{PREFIX_SESSION}{session_id}"
        await self.store(key, context, ttl_seconds=ttl)

    async def get_session_context(self, session_id: str) -> Optional[Dict[str, Any]]:
        """
        Retrieve session context by session_id.

        Returns:
            Session context dict, or None if not found.
        """
        key = f"{PREFIX_SESSION}{session_id}"
        return await self.retrieve(key)

    async def store_fibre_state(self, fibre_id: str, state: dict) -> None:
        """
        Store fibre state under the fibre namespace.

        Args:
            fibre_id: Fibre identifier.
            state: Fibre state dict.
        """
        key = f"{PREFIX_FIBRE}{fibre_id}"
        await self.store(key, state, ttl_seconds=3600)

    async def get_fibre_state(self, fibre_id: str) -> Optional[Dict[str, Any]]:
        """
        Retrieve fibre state by fibre_id.

        Returns:
            Fibre state dict, or None if not found.
        """
        key = f"{PREFIX_FIBRE}{fibre_id}"
        return await self.retrieve(key)

    @property
    def keys_count(self) -> int:
        """
        Approximate count of keys.

        When using in-memory fallback, returns exact len of stored keys.
        When Redis is primary, returns 0 (Redis DBSIZE requires async context).
        """
        return len(self._fallback)
