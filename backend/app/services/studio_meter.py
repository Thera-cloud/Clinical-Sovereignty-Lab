"""Studio billing rollup — studio_meter only. QUANTUM-CRYSTAL-ARCH"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Optional


def session_minutes(started_at: Optional[datetime], ended_at: Optional[datetime]) -> float:
    if not started_at or not ended_at:
        return 0.0
    if started_at.tzinfo is None:
        started_at = started_at.replace(tzinfo=timezone.utc)
    if ended_at.tzinfo is None:
        ended_at = ended_at.replace(tzinfo=timezone.utc)
    secs = max(0.0, (ended_at - started_at).total_seconds())
    return round(secs / 60.0, 2)


async def add_session_minutes(db_pool, show_id: str, minutes: float) -> Dict[str, Any]:
    mins = max(0.0, float(minutes))
    if not db_pool or mins <= 0:
        return {"ok": True, "dry": True, "minutes": mins}
    async with db_pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO studio_meter (show_id, day, session_minutes)
            VALUES ($1::uuid, CURRENT_DATE, $2)
            ON CONFLICT (show_id, day) DO UPDATE
            SET session_minutes = studio_meter.session_minutes + EXCLUDED.session_minutes
            """,
            show_id,
            mins,
        )
    return {"ok": True, "minutes": mins}


async def post_session_billing(
    db_pool, show_id: str, coach_id: str, minutes: float
) -> Dict[str, Any]:
    """Roll studio_meter into token_transactions (usage, no deduct). QUANTUM-CRYSTAL-ARCH"""
    mins = max(0.0, float(minutes))
    if not db_pool or mins <= 0:
        return {"ok": True, "dry": True, "minutes": mins}
    units = max(1, int(round(mins * 10)))
    async with db_pool.acquire() as conn:
        user = await conn.fetchrow(
            """
            SELECT username, company_id
            FROM users
            WHERE hardware_id = $1 AND (deleted_at IS NULL)
            """,
            coach_id,
        )
        if not user:
            return {"ok": True, "skipped": "no_user", "minutes": mins}
        bal = await conn.fetchval(
            "SELECT COALESCE(token_balance, 0) FROM users WHERE username = $1",
            user["username"],
        )
        scope = "corporate" if user.get("company_id") else "coach"
        await conn.execute(
            """
            INSERT INTO token_transactions
              (username, action, amount, balance_before, balance_after,
               reason, source, initiated_by, target_scope, target_ref)
            VALUES ($1, 'usage', $2, $3, $3, $4, 'studio_session', 'studio', $5, $6)
            """,
            user["username"],
            units,
            int(bal or 0),
            f"Studio session {mins} min",
            scope,
            str(show_id),
        )
    return {"ok": True, "minutes": mins, "units": units, "source": "studio_session"}


async def add_youtube_push(db_pool, show_id: str) -> None:
    if not db_pool:
        return
    async with db_pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO studio_meter (show_id, day, youtube_pushes)
            VALUES ($1::uuid, CURRENT_DATE, 1)
            ON CONFLICT (show_id, day) DO UPDATE
            SET youtube_pushes = studio_meter.youtube_pushes + 1
            """,
            show_id,
        )


async def add_egress_bytes(db_pool, show_id: str, nbytes: int) -> None:
    if not db_pool or nbytes <= 0:
        return
    async with db_pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO studio_meter (show_id, day, egress_bytes)
            VALUES ($1::uuid, CURRENT_DATE, $2)
            ON CONFLICT (show_id, day) DO UPDATE
            SET egress_bytes = studio_meter.egress_bytes + EXCLUDED.egress_bytes
            """,
            show_id,
            int(nbytes),
        )


async def show_meter(db_pool, show_id: str, coach_id: str) -> Dict[str, Any]:
    if not db_pool:
        return {"ok": True, "days": []}
    async with db_pool.acquire() as conn:
        owned = await conn.fetchrow(
            "SELECT id FROM studio_shows WHERE id = $1::uuid AND coach_id = $2",
            show_id,
            coach_id,
        )
        if not owned:
            return {"ok": False, "reason": "not_found", "code": 404}
        rows = await conn.fetch(
            """
            SELECT day, session_minutes, caller_minutes, egress_bytes, youtube_pushes
            FROM studio_meter
            WHERE show_id = $1::uuid
            ORDER BY day DESC
            LIMIT 30
            """,
            show_id,
        )
    return {
        "ok": True,
        "days": [
            {
                "day": str(r["day"]),
                "session_minutes": float(r["session_minutes"] or 0),
                "caller_minutes": float(r["caller_minutes"] or 0),
                "egress_bytes": int(r["egress_bytes"] or 0),
                "youtube_pushes": int(r["youtube_pushes"] or 0),
            }
            for r in rows
        ],
    }
