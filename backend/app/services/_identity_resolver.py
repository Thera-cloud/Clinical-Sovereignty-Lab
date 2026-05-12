"""Resolve bridge/session identifiers to canonical ``users.username``.

Chat paths often pass ``hardware_id``; Sensitive Clinical Bridge tables and
``users.profile_data`` lookups are keyed by username. Single lookup, no cache.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)


async def resolve_username(db_pool: Any, identifier: str) -> Optional[str]:
    """Resolve username, hardware_id, or user UUID string to ``users.username``.

    Returns None if no match. Mirrors the OR clause used in
    ``therapeutic_controller._recent_floor_age_hours`` narrative resolution.
    """
    if not db_pool or not identifier:
        return None
    try:
        async with db_pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT username FROM users WHERE username = $1 "
                "OR hardware_id = $1 OR id::text = $1 LIMIT 1",
                identifier,
            )
            return str(row["username"]) if row and row.get("username") else None
    except Exception as e:
        logger.warning("_identity_resolver: lookup failed for %r: %s", identifier, e)
        return None
