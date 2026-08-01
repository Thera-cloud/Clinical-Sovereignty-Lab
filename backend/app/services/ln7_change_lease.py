"""Redis change-lease with TTL (E5).

Key: ln7:change_lease:{loop}
Overlap → serialize (deny second acquirer).

# QUANTUM-CRYSTAL-ARCH
"""
from __future__ import annotations

import logging
import os
import time
import uuid
from typing import Optional

logger = logging.getLogger("ln7_change_lease")

DEFAULT_TTL_S = int(os.getenv("LN7_CHANGE_LEASE_TTL_S", "900"))


def _prefix() -> str:
    env = os.getenv("ENVIRONMENT", "production")
    pref = os.getenv("REDIS_KEY_PREFIX", "nate")
    return f"{pref}:{env}"


def lease_key(loop: str) -> str:
    return f"{_prefix()}:ln7:change_lease:{loop}"


def _redis():
    try:
        from app.websocket.cli_task_bus import _redis as _r

        return _r()
    except Exception:
        return None


def acquire_lease(
    loop: str,
    *,
    holder: Optional[str] = None,
    ttl_s: int = DEFAULT_TTL_S,
) -> Optional[str]:
    """SETNX lease. Returns lease_id or None if held."""
    r = _redis()
    if r is None:
        return holder or str(uuid.uuid4())
    lease_id = holder or str(uuid.uuid4())
    key = lease_key(loop)
    try:
        ok = r.set(key, lease_id, nx=True, ex=max(30, ttl_s))
        if ok:
            return lease_id
        return None
    except Exception as e:
        logger.warning("acquire_lease failed: %s", e)
        return None


def release_lease(loop: str, lease_id: str) -> bool:
    r = _redis()
    if r is None:
        return True
    key = lease_key(loop)
    try:
        cur = r.get(key)
        if cur is None:
            return True
        if isinstance(cur, bytes):
            cur = cur.decode()
        if cur != lease_id:
            return False
        r.delete(key)
        return True
    except Exception as e:
        logger.warning("release_lease failed: %s", e)
        return False


def lease_holder(loop: str) -> Optional[str]:
    r = _redis()
    if r is None:
        return None
    try:
        cur = r.get(lease_key(loop))
        if cur is None:
            return None
        return cur.decode() if isinstance(cur, bytes) else str(cur)
    except Exception:
        return None


def is_any_loop_active(loops) -> bool:
    """E5: cross-loop overlap detection — True if any named loop currently
    holds a change-lease. Used to flag confounded evidence windows (e.g. a
    canary evaluation running while hive_burst is mutating shared state).
    """
    for loop in loops or []:
        try:
            if lease_holder(loop) is not None:
                return True
        except Exception:
            continue
    return False
