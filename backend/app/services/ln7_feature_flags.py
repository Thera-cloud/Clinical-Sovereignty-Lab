"""PG-backed LN7 / flywheel feature flags (W6).

Readers consult PG first; env remains emergency kill-switch
(env false/empty does not override PG true except for force-off:
ENABLE_LN7_AUTO_PROMOTE=false kills auto-promote even if PG true).

# QUANTUM-CRYSTAL-ARCH
"""
from __future__ import annotations

import logging
import os
from typing import Optional

logger = logging.getLogger("ln7_feature_flags")

_CACHE: dict[str, tuple[bool, float]] = {}
_CACHE_TTL_S = 30.0


def _env_force_off(key: str) -> bool:
    """True when env explicitly disables the flag (kill-switch)."""
    raw = os.getenv(key, "").strip().lower()
    return raw in ("0", "false", "no", "off")


def _env_force_on(key: str) -> bool:
    raw = os.getenv(key, "").strip().lower()
    return raw in ("1", "true", "yes", "on")


async def flag_enabled(db_pool, key: str, *, default: bool = False) -> bool:
    """Return whether flag is enabled. Kill-switch: env false wins."""
    if _env_force_off(key):
        return False
    if db_pool is None:
        return _env_force_on(key) if not default else default
    import time

    now = time.monotonic()
    cached = _CACHE.get(key)
    if cached and (now - cached[1]) < _CACHE_TTL_S:
        return cached[0]
    try:
        async with db_pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT enabled FROM ln7_feature_flags WHERE key = $1",
                key,
            )
        enabled = bool(row["enabled"]) if row else default
    except Exception as e:
        logger.warning("ln7_feature_flags: read %s failed: %s", key, e)
        enabled = _env_force_on(key) or default
    _CACHE[key] = (enabled, now)
    return enabled


async def set_flag(
    db_pool,
    key: str,
    enabled: bool,
    *,
    notes: Optional[str] = None,
) -> bool:
    if not db_pool:
        return False
    try:
        async with db_pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO ln7_feature_flags (key, enabled, updated_at, notes)
                VALUES ($1, $2, NOW(), $3)
                ON CONFLICT (key) DO UPDATE SET
                    enabled = EXCLUDED.enabled,
                    updated_at = NOW(),
                    notes = COALESCE(EXCLUDED.notes, ln7_feature_flags.notes)
                """,
                key,
                enabled,
                notes,
            )
        _CACHE.pop(key, None)
        return True
    except Exception as e:
        logger.warning("ln7_feature_flags: set %s failed: %s", key, e)
        return False


async def auto_promote_enabled(db_pool=None) -> bool:
    if _env_force_off("ENABLE_LN7_AUTO_PROMOTE"):
        return False
    if db_pool is not None:
        return await flag_enabled(db_pool, "ENABLE_LN7_AUTO_PROMOTE", default=False)
    return _env_force_on("ENABLE_LN7_AUTO_PROMOTE")


async def dual_coo_mechanical_promote(db_pool=None) -> bool:
    if _env_force_off("DUAL_COO_MECHANICAL_PROMOTE"):
        return False
    if db_pool is not None:
        return await flag_enabled(
            db_pool, "DUAL_COO_MECHANICAL_PROMOTE", default=False
        )
    return _env_force_on("DUAL_COO_MECHANICAL_PROMOTE")


async def flip_g2_governance(db_pool, *, reason: str = "step0_green") -> bool:
    """Step 0 green → G0→G2 product-rule change."""
    ok1 = await set_flag(
        db_pool, "ENABLE_LN7_AUTO_PROMOTE", True, notes=reason
    )
    ok2 = await set_flag(
        db_pool, "DUAL_COO_MECHANICAL_PROMOTE", True, notes=reason
    )
    return ok1 and ok2
