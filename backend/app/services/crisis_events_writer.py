"""Write-through helper for crisis_events (migration 052). v1.4+ Sensitive Bridge."""

from __future__ import annotations

import logging
from typing import Any, List, Optional, Sequence

logger = logging.getLogger(__name__)


async def write_crisis_event(
    pool: Any,
    *,
    client_username: str,
    user_display_name: str,
    risk_level: str,
    reason: str,
    keywords: Optional[Sequence[str]] = None,
    session_id: Optional[str] = None,
    family_id: Optional[str] = None,
    bridge_row_notes: Optional[str] = None,
) -> int:
    """Insert one crisis_events row; return id.

    ``client_username`` must be ``users.username``. Resolves UUID for FK column ``user_id``.
    Optional ``bridge_row_notes`` populates ``resolution_notes`` until resolved (parity hook).
    """
    kw_list: List[str] = list(keywords) if keywords else []
    async with pool.acquire() as conn:
        uid = await conn.fetchval(
            "SELECT id FROM users WHERE username = $1",
            client_username,
        )
        if uid is None:
            raise ValueError(f"crisis_events_writer: unknown user {client_username!r}")

        row = await conn.fetchrow(
            """
            INSERT INTO crisis_events (
                user_id, user_name, risk_level, reason, keywords, session_id, family_id,
                resolution_notes
            )
            VALUES ($1::uuid, $2, $3, $4, $5::text[], $6, $7, $8)
            RETURNING id
            """,
            uid,
            user_display_name or client_username,
            risk_level or "medium",
            reason or "",
            kw_list,
            session_id,
            family_id,
            bridge_row_notes,
        )
        cid = int(row["id"]) if row else 0
        if cid <= 0:
            raise RuntimeError("crisis_events_writer: INSERT returned no id")
        return cid
