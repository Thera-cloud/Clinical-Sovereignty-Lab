"""Coach-client tasks. assignee_id = hardware_id. ENABLE_COACH_TASKS."""

from __future__ import annotations

import os
from typing import Any, Dict, List, Optional

from app.services.effective_scope import client_in_scope, effective_scope
from app.services.google_workspace_service import FlagOff


def _flag_on(name: str) -> bool:
    return os.getenv(name, "false").strip().lower() in ("1", "true", "yes")


def _require_tasks() -> None:
    if not _flag_on("ENABLE_COACH_TASKS"):
        raise FlagOff("ENABLE_COACH_TASKS")


async def list_open_tasks(db_pool, coach_hardware_id: str) -> List[Dict[str, Any]]:
    _require_tasks()
    scope = await effective_scope(db_pool, coach_hardware_id)
    ids = scope["client_hardware_ids"]
    if not ids or db_pool is None:
        return []
    async with db_pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT id, coach_id, client_id, assignee_id, title, status, created_at
            FROM coach_client_tasks
            WHERE client_id = ANY($1::text[])
              AND status = 'open'
            ORDER BY created_at DESC
            LIMIT 50
            """,
            ids,
        )
    return [dict(r) for r in rows]


async def create_task(
    db_pool,
    coach_hardware_id: str,
    *,
    client_id: str,
    title: str,
    assignee_id: Optional[str] = None,
) -> Dict[str, Any]:
    _require_tasks()
    if not await client_in_scope(db_pool, coach_hardware_id, client_id):
        raise PermissionError("client out of scope")
    assignee = (assignee_id or coach_hardware_id).strip()
    async with db_pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO coach_client_tasks (coach_id, client_id, assignee_id, title)
            VALUES ($1, $2, $3, $4)
            RETURNING id, coach_id, client_id, assignee_id, title, status
            """,
            coach_hardware_id,
            client_id,
            assignee,
            (title or "").strip()[:300],
        )
    return dict(row)
