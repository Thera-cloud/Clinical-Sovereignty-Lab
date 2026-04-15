"""Participation Tracker — active vs background members for group videos.

Queries session logs for a given month to classify group members:
- active: participated in a group-context session (mesh, family, BLE, community)
- background: still in the group but no group session activity this month

A background member is always visible in the video (not absent).
Only is_active=False members are excluded entirely.
"""
from __future__ import annotations

import logging
from datetime import date
from typing import Any

logger = logging.getLogger(__name__)


async def get_group_participation(
    group_entity_id: str,
    month: int,
    year: int,
    db_pool,
) -> dict[str, list[str]]:
    """Return active_members and background_members client_id lists.

    Checks coaching_mesh_participants, family_sanctuary_sessions,
    and community_attendance_records for group-context activity.
    """
    month_start = date(year, month, 1)
    if month == 12:
        month_end = date(year + 1, 1, 1)
    else:
        month_end = date(year, month + 1, 1)

    try:
        async with db_pool.acquire() as conn:
            members = await conn.fetch(
                "SELECT client_id FROM group_entity_members "
                "WHERE group_entity_id = $1 AND is_active = TRUE",
                group_entity_id)

            all_ids = [str(m["client_id"]) for m in members]
            if not all_ids:
                return {"active_members": [], "background_members": []}

            active_set: set[str] = set()

            mesh_active = await conn.fetch(
                "SELECT DISTINCT p.user_id FROM coaching_mesh_participants p "
                "JOIN coaching_mesh_sessions s ON s.id = p.session_id "
                "WHERE p.joined_at >= $1 AND p.joined_at < $2",
                month_start, month_end)
            for r in mesh_active:
                uid = str(r["user_id"])
                if uid in all_ids:
                    active_set.add(uid)

            family_sessions = await conn.fetch(
                "SELECT family_id FROM family_sanctuary_sessions "
                "WHERE started_at >= $1 AND started_at < $2",
                month_start, month_end)
            if family_sessions:
                family_ids = [r["family_id"] for r in family_sessions]
                ge_row = await conn.fetchrow(
                    "SELECT group_entity_id FROM families "
                    "WHERE group_entity_id = $1 LIMIT 1",
                    group_entity_id)
                if ge_row:
                    for cid in all_ids:
                        active_set.add(cid)

            comm_active = await conn.fetch(
                "SELECT DISTINCT user_id FROM community_attendance_records "
                "WHERE session_date >= $1 AND session_date < $2",
                month_start, month_end)
            for r in comm_active:
                uid = str(r["user_id"])
                if uid in all_ids:
                    active_set.add(uid)

            active_members = [cid for cid in all_ids if cid in active_set]
            background_members = [cid for cid in all_ids if cid not in active_set]

        return {
            "active_members": active_members,
            "background_members": background_members,
        }

    except Exception as e:
        logger.error(
            "[PARTICIPATION] Failed for group %s %d/%d: %s",
            group_entity_id, month, year, e)
        return {"active_members": all_ids, "background_members": []}
