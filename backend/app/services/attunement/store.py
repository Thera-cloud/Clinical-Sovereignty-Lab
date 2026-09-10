"""In-memory + optional Redis JSON blobs (PHI: short TTL).

QUANTUM-CRYSTAL-ARCH — clinical. SOVEREIGN-STANDARD.
CEO: Nathaniel James Nevedal. Risk: RED (never log values).
"""

from __future__ import annotations

import json
import os
import time
from typing import Any, Optional

_MEM: dict[str, tuple[float, str]] = {}
_redis = None
_redis_failed = False


def _env() -> str:
    return os.environ.get("ENVIRONMENT", "production")


def key(kind: str, uid: str, extra: str = "") -> str:
    prefix = os.environ.get("REDIS_KEY_PREFIX", "nate")
    tail = f":{extra}" if extra else ""
    return f"{prefix}:{_env()}:attune:{kind}:{uid}{tail}"


def _client():
    global _redis, _redis_failed
    if _redis is not None or _redis_failed:
        return _redis
    try:
        import redis as sync_redis

        _redis = sync_redis.Redis(
            host=os.environ.get("REDIS_HOST", "redis"),
            port=int(os.environ.get("REDIS_PORT", "6379")),
            password=os.environ.get("REDIS_PASSWORD") or None,
            decode_responses=True,
            socket_connect_timeout=0.4,
            socket_timeout=0.4,
        )
        _redis.ping()
        return _redis
    except Exception:
        _redis_failed = True
        _redis = None
        return None


def get_json(k: str) -> Any:
    now = time.time()
    hit = _MEM.get(k)
    if hit and hit[0] > now:
        try:
            return json.loads(hit[1])
        except Exception:
            return None
    if hit and hit[0] <= now:
        _MEM.pop(k, None)
    cli = _client()
    if cli is None:
        return None
    try:
        raw = cli.get(k)
        if not raw:
            return None
        return json.loads(raw)
    except Exception:
        return None


def set_json(k: str, value: Any, ttl_s: int) -> None:
    raw = json.dumps(value, default=str)
    _MEM[k] = (time.time() + ttl_s, raw)
    cli = _client()
    if cli is None:
        return
    try:
        cli.setex(k, ttl_s, raw)
    except Exception:
        return


def delete(k: str) -> None:
    _MEM.pop(k, None)
    cli = _client()
    if cli is None:
        return
    try:
        cli.delete(k)
    except Exception:
        return


def touch(k: str, ttl_s: int) -> None:
    hit = _MEM.get(k)
    if hit:
        _MEM[k] = (time.time() + ttl_s, hit[1])
    cli = _client()
    if cli is None:
        return
    try:
        cli.expire(k, ttl_s)
    except Exception:
        return
