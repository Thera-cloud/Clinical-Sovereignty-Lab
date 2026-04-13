"""Narrative State Object (NSO) — shared therapeutic story state.

Implements read/write with PostgreSQL advisory lock serialization (Phase 1).
Phase 4 upgrades to optimistic concurrency via generation_sequence_counter.
"""
from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

logger = logging.getLogger(__name__)

_NSO_HISTORY_LIMIT = 10

ACT_POSITIONS = ("act_1", "act_2", "act_3", "epilogue")


async def read_nso(user_id: str, db_pool) -> Optional[dict]:
    """Read the current NSO for a user. Returns None if no NSO exists."""
    if not db_pool:
        return None
    try:
        async with db_pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM narrative_state_objects WHERE user_id = $1",
                user_id,
            )
            if not row:
                return None
            return dict(row)
    except Exception as e:
        logger.warning("NSO read failed for %s: %s", user_id, e)
        return None


async def read_or_create_nso(user_id: str, db_pool) -> dict:
    """Read the NSO, creating a default if none exists."""
    existing = await read_nso(user_id, db_pool)
    if existing:
        return existing
    return await _create_default_nso(user_id, db_pool)


async def _create_default_nso(user_id: str, db_pool) -> dict:
    nso_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc)
    default = {
        "nso_id": nso_id,
        "user_id": user_id,
        "act_position": "act_1",
        "arc_label": None,
        "protagonist_state": {},
        "active_themes": [],
        "unresolved_threads": [],
        "resolved_threads": [],
        "last_generation_id": None,
        "generation_sequence": 0,
        "created_at": now,
        "updated_at": now,
    }
    if not db_pool:
        return default
    try:
        async with db_pool.acquire() as conn:
            await conn.execute(
                "INSERT INTO narrative_state_objects "
                "(nso_id, user_id, act_position, protagonist_state, "
                "active_themes, unresolved_threads, resolved_threads) "
                "VALUES ($1, $2, $3, $4, $5, $6, $7) "
                "ON CONFLICT (user_id) DO NOTHING",
                nso_id, user_id, "act_1",
                json.dumps({}), json.dumps([]),
                json.dumps([]), json.dumps([]),
            )
            row = await conn.fetchrow(
                "SELECT * FROM narrative_state_objects WHERE user_id = $1",
                user_id,
            )
            if row:
                return dict(row)
    except Exception as e:
        logger.warning("NSO create failed for %s: %s", user_id, e)
    return default


async def write_nso(
    user_id: str,
    updates: dict[str, Any],
    generation_id: Optional[str],
    db_pool,
    reason: str = "generation",
    expected_sequence: Optional[int] = None,
) -> Optional[dict]:
    """Write NSO updates using PostgreSQL advisory lock serialization.

    Snapshots the pre-mutation state to nso_history before applying changes.
    When *expected_sequence* is provided, the write is rejected if the
    current generation_sequence doesn't match (optimistic concurrency).
    """
    if not db_pool:
        return None
    try:
        async with db_pool.acquire() as conn:
            async with conn.transaction():
                lock_key = hash(user_id) & 0x7FFFFFFF
                await conn.execute(
                    "SELECT pg_advisory_xact_lock($1)", lock_key
                )

                current = await conn.fetchrow(
                    "SELECT * FROM narrative_state_objects WHERE user_id = $1",
                    user_id,
                )
                if not current:
                    await _create_default_nso(user_id, db_pool)
                    current = await conn.fetchrow(
                        "SELECT * FROM narrative_state_objects WHERE user_id = $1",
                        user_id,
                    )
                    if not current:
                        return None

                if expected_sequence is not None:
                    cur_seq = current.get("generation_sequence", 0) or 0
                    if cur_seq != expected_sequence:
                        logger.warning(
                            "NSO optimistic concurrency conflict for %s: "
                            "expected seq %d, current %d",
                            user_id, expected_sequence, cur_seq,
                        )
                        return None

                snapshot = _row_to_snapshot(current)
                await _save_history(conn, user_id, snapshot, generation_id, reason)

                set_clauses = []
                params = []
                idx = 1

                field_map = {
                    "act_position": "act_position",
                    "arc_label": "arc_label",
                    "protagonist_state": "protagonist_state",
                    "active_themes": "active_themes",
                    "unresolved_threads": "unresolved_threads",
                    "resolved_threads": "resolved_threads",
                }

                for key, col in field_map.items():
                    if key in updates:
                        val = updates[key]
                        if isinstance(val, (dict, list)):
                            val = json.dumps(val)
                        set_clauses.append(f"{col} = ${idx}")
                        params.append(val)
                        idx += 1

                if generation_id:
                    set_clauses.append(f"last_generation_id = ${idx}")
                    params.append(uuid.UUID(generation_id) if isinstance(generation_id, str) else generation_id)
                    idx += 1

                set_clauses.append(f"generation_sequence = generation_sequence + 1")
                set_clauses.append(f"updated_at = ${idx}")
                params.append(datetime.now(timezone.utc))
                idx += 1

                params.append(user_id)
                sql = (
                    f"UPDATE narrative_state_objects SET "
                    f"{', '.join(set_clauses)} "
                    f"WHERE user_id = ${idx}"
                )
                await conn.execute(sql, *params)

                updated = await conn.fetchrow(
                    "SELECT * FROM narrative_state_objects WHERE user_id = $1",
                    user_id,
                )
                return dict(updated) if updated else None

    except Exception as e:
        logger.error("NSO write failed for %s: %s", user_id, e)
        return None


async def revert_nso(user_id: str, snapshot_id: int, db_pool) -> Optional[dict]:
    """Revert NSO to a historical snapshot. Admin recovery tool."""
    if not db_pool:
        return None
    try:
        async with db_pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT nso_snapshot FROM nso_history "
                "WHERE id = $1 AND user_id = $2",
                snapshot_id, user_id,
            )
            if not row:
                return None
            snapshot = row["nso_snapshot"]
            if isinstance(snapshot, str):
                snapshot = json.loads(snapshot)

            return await write_nso(
                user_id,
                {
                    "act_position": snapshot.get("act_position", "act_1"),
                    "arc_label": snapshot.get("arc_label"),
                    "protagonist_state": snapshot.get("protagonist_state", {}),
                    "active_themes": snapshot.get("active_themes", []),
                    "unresolved_threads": snapshot.get("unresolved_threads", []),
                    "resolved_threads": snapshot.get("resolved_threads", []),
                },
                generation_id=None,
                db_pool=db_pool,
                reason=f"revert_to_snapshot_{snapshot_id}",
            )
    except Exception as e:
        logger.error("NSO revert failed for %s snapshot %d: %s", user_id, snapshot_id, e)
        return None


async def get_nso_history(user_id: str, db_pool, limit: int = 10) -> list[dict]:
    """Retrieve recent NSO snapshots for a user."""
    if not db_pool:
        return []
    try:
        async with db_pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT id, nso_snapshot, generation_id, reason, created_at "
                "FROM nso_history WHERE user_id = $1 "
                "ORDER BY created_at DESC LIMIT $2",
                user_id, limit,
            )
            return [dict(r) for r in rows]
    except Exception as e:
        logger.warning("NSO history fetch failed for %s: %s", user_id, e)
        return []


def nso_to_context(nso: dict) -> str:
    """Convert NSO to a text block for inclusion in generation prompts."""
    if not nso:
        return ""
    parts = [f"Act: {nso.get('act_position', 'act_1')}"]
    if nso.get("arc_label"):
        parts.append(f"Arc: {nso['arc_label']}")
    themes = nso.get("active_themes", [])
    if themes:
        t_list = themes if isinstance(themes, list) else json.loads(themes) if isinstance(themes, str) else []
        if t_list:
            parts.append(f"Active themes: {', '.join(str(t) for t in t_list)}")
    unresolved = nso.get("unresolved_threads", [])
    if unresolved:
        u_list = unresolved if isinstance(unresolved, list) else json.loads(unresolved) if isinstance(unresolved, str) else []
        if u_list:
            parts.append(f"Unresolved: {', '.join(str(t) for t in u_list[:5])}")
    return " | ".join(parts)


async def _save_history(conn, user_id: str, snapshot: dict, generation_id, reason: str):
    """Save pre-mutation snapshot and prune old entries."""
    gen_uuid = None
    if generation_id:
        gen_uuid = uuid.UUID(generation_id) if isinstance(generation_id, str) else generation_id
    try:
        await conn.execute(
            "INSERT INTO nso_history (user_id, nso_snapshot, generation_id, reason) "
            "VALUES ($1, $2, $3, $4)",
            user_id, json.dumps(snapshot, default=str), gen_uuid, reason,
        )
        await conn.execute(
            "DELETE FROM nso_history WHERE user_id = $1 AND id NOT IN "
            "(SELECT id FROM nso_history WHERE user_id = $1 "
            "ORDER BY created_at DESC LIMIT $2)",
            user_id, _NSO_HISTORY_LIMIT,
        )
    except Exception as e:
        logger.warning("NSO history save failed: %s", e)


def _row_to_snapshot(row) -> dict:
    """Convert a DB row to a JSON-serializable snapshot dict."""
    d = dict(row)
    result = {}
    for key in ("act_position", "arc_label", "protagonist_state",
                "active_themes", "unresolved_threads", "resolved_threads",
                "generation_sequence"):
        val = d.get(key)
        if isinstance(val, (datetime,)):
            val = val.isoformat()
        result[key] = val
    return result
