"""Coach visibility keyed only on hardware_id. Master = active coach_hierarchy."""

from __future__ import annotations

import os
from typing import Any, Dict, List

from app.services.google_workspace_service import FlagOff


def _flag_on(name: str) -> bool:
    return os.getenv(name, "false").strip().lower() in ("1", "true", "yes")


async def effective_scope(db_pool, hardware_id: str) -> Dict[str, Any]:
    hw = (hardware_id or "").strip()
    if not hw:
        raise ValueError("hardware_id required")
    coach_ids: List[str] = [hw]
    assistants: List[str] = []
    is_master = False
    if db_pool is None:
        return {
            "hardware_id": hw,
            "coach_ids": coach_ids,
            "assistants": assistants,
            "is_master": False,
            "client_hardware_ids": [],
            "supervision_visible": False,
        }
    async with db_pool.acquire() as conn:
        if _flag_on("ENABLE_SUPERVISION_VIEW"):
            rows = await conn.fetch(
                """
                SELECT assistant_id
                FROM coach_hierarchy
                WHERE master_coach_id = $1 AND status = 'active'
                """,
                hw,
            )
            assistants = [r["assistant_id"] for r in rows if r["assistant_id"]]
            is_master = bool(assistants)
            coach_ids.extend(assistants)
            if is_master:
                await conn.execute(
                    """
                    INSERT INTO supervision_access_audit (actor_id, target_id, action)
                    VALUES ($1, $2, 'effective_scope')
                    """,
                    hw,
                    ",".join(assistants)[:200],
                )
        clients = await conn.fetch(
            """
            SELECT hardware_id
            FROM users
            WHERE role = 'CLIENT'
              AND hardware_id IS NOT NULL AND hardware_id <> ''
              AND (
                profile_data->>'coach_id' = ANY($1::text[])
                OR profile_data->>'assigned_coach_id' = ANY($1::text[])
              )
            """,
            coach_ids,
        )
    return {
        "hardware_id": hw,
        "coach_ids": coach_ids,
        "assistants": assistants,
        "is_master": is_master,
        "client_hardware_ids": [r["hardware_id"] for r in clients],
        "supervision_visible": _flag_on("ENABLE_SUPERVISION_VIEW") and is_master,
    }


async def client_in_scope(db_pool, coach_hardware_id: str, client_hardware_id: str) -> bool:
    cid = (client_hardware_id or "").strip()
    if not cid:
        return False
    scope = await effective_scope(db_pool, coach_hardware_id)
    return cid in scope["client_hardware_ids"]


def require_supervision() -> None:
    if not _flag_on("ENABLE_SUPERVISION_VIEW"):
        raise FlagOff("ENABLE_SUPERVISION_VIEW")
