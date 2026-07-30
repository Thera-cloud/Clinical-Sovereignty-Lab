"""30-day reverse suppress patterns (W18).

# QUANTUM-CRYSTAL-ARCH
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

logger = logging.getLogger("ln7_suppress")

DEFAULT_DAYS = 30


async def suppress_pattern(
    db_pool,
    pattern_key: str,
    *,
    reason: str = "reverse",
    days: int = DEFAULT_DAYS,
) -> bool:
    if not db_pool or not pattern_key:
        return False
    until = datetime.now(timezone.utc) + timedelta(days=days)
    try:
        async with db_pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO ln7_suppress_patterns (pattern_key, until_ts, reason)
                VALUES ($1, $2, $3)
                ON CONFLICT (pattern_key) DO UPDATE SET
                    until_ts = EXCLUDED.until_ts,
                    reason = EXCLUDED.reason
                """,
                pattern_key,
                until,
                reason,
            )
        return True
    except Exception as e:
        logger.warning("suppress_pattern failed: %s", e)
        return False


async def is_suppressed(db_pool, pattern_key: str) -> bool:
    if not db_pool or not pattern_key:
        return False
    try:
        async with db_pool.acquire() as conn:
            val = await conn.fetchval(
                """
                SELECT 1 FROM ln7_suppress_patterns
                WHERE pattern_key = $1 AND until_ts > NOW()
                """,
                pattern_key,
            )
        return val is not None
    except Exception as e:
        logger.warning("is_suppressed failed: %s", e)
        return False
