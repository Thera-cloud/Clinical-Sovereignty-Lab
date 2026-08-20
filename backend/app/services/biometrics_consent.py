"""Voice biometrics opt-out enforcement (IL BIPA §15(b) / BAA §6.3).

Every voice biometric extraction call site consults `is_biometrics_disabled`
before invoking the extractor. When a user has opted out via
`set_biometrics_opt_out`, the extractor returns empty metrics and the
downstream pipeline uses text-only affect signals.

Fail policy: fail-open (return False on DB error) so a transient outage
cannot silently disable biometrics for the entire user base. Compliance is
proven via the audit log (`biometrics_opt_out_log`), not via cache state.
"""

from __future__ import annotations

import logging
import time
from typing import Optional, Tuple

logger = logging.getLogger("biometrics_consent")

_CACHE_TTL_S = 300
_cache: dict[str, Tuple[bool, float]] = {}


def _now() -> float:
    return time.time()


def _cache_get(key: str) -> Optional[bool]:
    entry = _cache.get(key)
    if not entry:
        return None
    value, expires_at = entry
    if _now() >= expires_at:
        _cache.pop(key, None)
        return None
    return value


def _cache_put(key: str, value: bool) -> None:
    _cache[key] = (value, _now() + _CACHE_TTL_S)


def cache_clear(key: Optional[str] = None) -> None:
    if key is None:
        _cache.clear()
        return
    _cache.pop(str(key).strip().lower(), None)


def _normalize(user_id_or_username: Optional[str]) -> str:
    if not user_id_or_username:
        return ""
    return str(user_id_or_username).strip().lower()


async def is_biometrics_disabled(
    user_id_or_username: Optional[str],
    db_pool,
) -> bool:
    """Return True when the user has opted out. Fail-open on DB error."""
    key = _normalize(user_id_or_username)
    if not key or not db_pool:
        return False
    cached = _cache_get(key)
    if cached is not None:
        return cached
    try:
        async with db_pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT biometrics_disabled FROM users "
                "WHERE LOWER(username) = $1 OR LOWER(hardware_id) = $1 "
                "LIMIT 1",
                key,
            )
        disabled = bool(row and row["biometrics_disabled"])
    except Exception as exc:
        logger.warning("biometrics_consent lookup failed for %s: %s", key, exc)
        return False
    _cache_put(key, disabled)
    return disabled


async def set_biometrics_opt_out(
    username: str,
    disabled: bool,
    actor: str,
    reason: Optional[str],
    db_pool,
) -> bool:
    """Toggle the flag and write an audit row. Returns True on success."""
    if not username or not db_pool:
        return False
    actor = (actor or "self").strip() or "self"
    action = "opt_out" if disabled else "opt_in"
    try:
        async with db_pool.acquire() as conn:
            async with conn.transaction():
                result = await conn.execute(
                    "UPDATE users SET biometrics_disabled = $1 WHERE username = $2",
                    disabled,
                    username,
                )
                if not result or "UPDATE 1" not in result:
                    return False
                await conn.execute(
                    "INSERT INTO biometrics_opt_out_log "
                    "(username, action, actor, reason) VALUES ($1, $2, $3, $4)",
                    username,
                    action,
                    actor,
                    (reason or None),
                )
    except Exception as exc:
        logger.error("set_biometrics_opt_out failed for %s: %s", username, exc)
        return False
    cache_clear(username)
    return True


async def get_biometrics_status(username: str, db_pool) -> Optional[bool]:
    """Read current opt-out state, bypassing cache. None if user not found."""
    if not username or not db_pool:
        return None
    try:
        async with db_pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT biometrics_disabled FROM users WHERE username = $1",
                username,
            )
        if not row:
            return None
        return bool(row["biometrics_disabled"])
    except Exception as exc:
        logger.warning("get_biometrics_status failed for %s: %s", username, exc)
        return None
