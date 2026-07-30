"""Redis burst serve endpoint discovery (W4 / W5 intent queue).

Keys:
  nate:{env}:ln7:serve:endpoint
  nate:{env}:ln7:serve:engine
  nate:{env}:ln7:adapter_intent  (list)

# QUANTUM-CRYSTAL-ARCH
"""
from __future__ import annotations

import json
import logging
import os
import time
from typing import Any, Dict, List, Optional

logger = logging.getLogger("ln7_serve_endpoint")


def _prefix() -> str:
    env = os.getenv("ENVIRONMENT", "production")
    pref = os.getenv("REDIS_KEY_PREFIX", "nate")
    return f"{pref}:{env}"


def endpoint_key() -> str:
    return f"{_prefix()}:ln7:serve:endpoint"


def engine_key() -> str:
    return f"{_prefix()}:ln7:serve:engine"


def intent_key() -> str:
    return f"{_prefix()}:ln7:adapter_intent"


def _redis():
    try:
        from app.websocket.cli_task_bus import _redis as _r

        return _r()
    except Exception:
        return None


def publish_serve_endpoint(
    url: str,
    *,
    engine: str = "vllm_burst",
    ttl_s: int = 3600,
) -> bool:
    r = _redis()
    if r is None:
        return False
    try:
        r.set(endpoint_key(), url, ex=max(60, ttl_s))
        r.set(engine_key(), engine, ex=max(60, ttl_s))
        return True
    except Exception as e:
        logger.warning("publish_serve_endpoint failed: %s", e)
        return False


def clear_serve_endpoint() -> bool:
    r = _redis()
    if r is None:
        return False
    try:
        r.delete(endpoint_key(), engine_key())
        return True
    except Exception as e:
        logger.warning("clear_serve_endpoint failed: %s", e)
        return False


def get_serve_endpoint() -> Optional[str]:
    r = _redis()
    if r is None:
        return None
    try:
        v = r.get(endpoint_key())
        if v is None:
            return None
        return v.decode() if isinstance(v, bytes) else str(v)
    except Exception:
        return None


def get_serve_engine() -> str:
    r = _redis()
    if r is None:
        return "ollama"
    try:
        v = r.get(engine_key())
        if v is None:
            return "ollama"
        return v.decode() if isinstance(v, bytes) else str(v)
    except Exception:
        return "ollama"


def push_adapter_intent(
    adapter_id: str,
    task_hash: str = "",
) -> bool:
    r = _redis()
    if r is None:
        return False
    try:
        payload = json.dumps({
            "adapter_id": adapter_id,
            "task_hash": task_hash,
            "ts": time.time(),
        })
        r.lpush(intent_key(), payload)
        r.ltrim(intent_key(), 0, 499)
        r.expire(intent_key(), 86400)
        return True
    except Exception as e:
        logger.warning("push_adapter_intent failed: %s", e)
        return False


def drain_adapter_intents(limit: int = 32) -> List[Dict[str, Any]]:
    r = _redis()
    if r is None:
        return []
    out: List[Dict[str, Any]] = []
    try:
        for _ in range(max(1, limit)):
            raw = r.rpop(intent_key())
            if raw is None:
                break
            if isinstance(raw, bytes):
                raw = raw.decode()
            try:
                out.append(json.loads(raw))
            except Exception:
                continue
    except Exception as e:
        logger.warning("drain_adapter_intents failed: %s", e)
    return out
