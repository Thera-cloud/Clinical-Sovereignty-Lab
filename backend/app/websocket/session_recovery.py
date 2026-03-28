# SOVEREIGN-VOICE — WebSocket session recovery via Redis
#
# Provides recovery tokens so clients can resume sessions after
# brief disconnects without re-authenticating.  Also buffers recent
# outbound messages so the client can catch up after reconnecting.

import json
import os
import secrets
import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger("session_recovery")

_REDIS_CONFIG = {
    "host": os.environ.get("REDIS_HOST", "redis"),
    "port": int(os.environ.get("REDIS_PORT", "6379")),
    "password": os.environ.get("REDIS_PASSWORD"),
    "prefix": os.environ.get("REDIS_KEY_PREFIX", "nate"),
    "env": os.environ.get("ENVIRONMENT", "prod"),
}

RECOVERY_TTL_SECONDS = 300  # 5 minutes
MESSAGE_BUFFER_MAX = 50

_redis_client = None


def _get_redis():
    """Lazy-init a synchronous Redis client (reuses bridge's pattern)."""
    global _redis_client
    if _redis_client is not None:
        return _redis_client
    try:
        import redis as sync_redis
        _redis_client = sync_redis.Redis(
            host=_REDIS_CONFIG["host"],
            port=_REDIS_CONFIG["port"],
            password=_REDIS_CONFIG["password"],
            decode_responses=True,
            socket_connect_timeout=3,
        )
        _redis_client.ping()
        return _redis_client
    except Exception as e:
        logger.warning("Session recovery Redis init failed: %s", e)
        _redis_client = None
        return None


def _session_key(token: str) -> str:
    return f"{_REDIS_CONFIG['prefix']}:{_REDIS_CONFIG['env']}:session:{token}"


def _buffer_key(hardware_id: str) -> str:
    return f"{_REDIS_CONFIG['prefix']}:{_REDIS_CONFIG['env']}:msgbuf:{hardware_id}"


def generate_recovery_token(
    hardware_id: str,
    username: str,
    role: str,
) -> Optional[str]:
    """Create a short-lived recovery token stored in Redis.

    Returns the token string, or None if Redis is unavailable.
    """
    r = _get_redis()
    if not r:
        return None
    try:
        token = secrets.token_urlsafe(32)
        session_data = json.dumps({
            "hardware_id": hardware_id,
            "username": username,
            "role": role,
        })
        r.setex(_session_key(token), RECOVERY_TTL_SECONDS, session_data)
        return token
    except Exception as e:
        logger.warning("Failed to generate recovery token: %s", e)
        return None


def recover_session(recovery_token: str) -> Optional[Dict[str, Any]]:
    """Look up a recovery token and return the session data.

    Returns None if token is expired/missing or Redis is unavailable.
    The token is consumed (deleted) on successful recovery.
    """
    r = _get_redis()
    if not r:
        return None
    try:
        key = _session_key(recovery_token)
        raw = r.get(key)
        if not raw:
            return None
        r.delete(key)
        return json.loads(raw)
    except Exception as e:
        logger.warning("Session recovery lookup failed: %s", e)
        return None


def buffer_message(hardware_id: str, message: Dict[str, Any]) -> None:
    """Append an outbound message to the per-user Redis buffer.

    Keeps at most MESSAGE_BUFFER_MAX entries (FIFO). TTL matches recovery.
    """
    r = _get_redis()
    if not r:
        return
    try:
        key = _buffer_key(hardware_id)
        r.rpush(key, json.dumps(message, default=str))
        r.ltrim(key, -MESSAGE_BUFFER_MAX, -1)
        r.expire(key, RECOVERY_TTL_SECONDS)
    except Exception as e:
        logger.warning("Message buffer write failed: %s", e)


def get_buffered_messages(hardware_id: str) -> List[Dict[str, Any]]:
    """Retrieve and clear the message buffer for a hardware_id."""
    r = _get_redis()
    if not r:
        return []
    try:
        key = _buffer_key(hardware_id)
        raw_list = r.lrange(key, 0, -1)
        r.delete(key)
        messages = []
        for raw in raw_list:
            try:
                messages.append(json.loads(raw))
            except (json.JSONDecodeError, TypeError):
                continue
        return messages
    except Exception as e:
        logger.warning("Message buffer read failed: %s", e)
        return []
