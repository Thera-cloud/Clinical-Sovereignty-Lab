"""Coach credentials + legal holds. No erasure UI. hardware_id only."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional


async def add_credential(
    db_pool,
    coach_id: str,
    *,
    credential_type: str,
    document_ref: str = "",
    expires_at: Optional[datetime] = None,
) -> Dict[str, Any]:
    hw = (coach_id or "").strip()
    if not hw:
        raise ValueError("coach_id (hardware_id) required")
    async with db_pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO coach_credentials (coach_id, credential_type, document_ref, expires_at)
            VALUES ($1, $2, $3, $4)
            RETURNING id, coach_id, credential_type, document_ref, expires_at
            """,
            hw,
            (credential_type or "license").strip()[:80],
            (document_ref or "")[:500],
            expires_at,
        )
    return dict(row)


async def list_credentials(db_pool, coach_id: str) -> List[Dict[str, Any]]:
    async with db_pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT id, coach_id, credential_type, document_ref, expires_at, created_at
            FROM coach_credentials
            WHERE coach_id = $1
            ORDER BY created_at DESC
            LIMIT 50
            """,
            coach_id,
        )
    return [dict(r) for r in rows]


async def has_active_legal_hold(db_pool, client_id: str) -> bool:
    if db_pool is None:
        return False
    async with db_pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT 1 AS ok
            FROM legal_holds
            WHERE client_id = $1 AND released_at IS NULL
            LIMIT 1
            """,
            client_id,
        )
    return bool(row)


async def place_legal_hold(db_pool, client_id: str, reason: str = "") -> Dict[str, Any]:
    async with db_pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO legal_holds (client_id, reason)
            VALUES ($1, $2)
            RETURNING id, client_id, reason, placed_at
            """,
            client_id,
            (reason or "hold")[:300],
        )
    return dict(row)
