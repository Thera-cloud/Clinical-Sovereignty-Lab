"""Training Ground coach REST — safety queue (LB-4)."""

from __future__ import annotations

from typing import Any, Dict, List

from fastapi import APIRouter, Depends, HTTPException, Request

from app.services.api_server import require_coach

router = APIRouter(
    prefix="/api/coach/training-ground",
    tags=["training-ground-coach"],
    dependencies=[Depends(require_coach)],
)


def _coach_client_filter(coach: Dict[str, Any]) -> tuple[str, List[Any]]:
    coach_username = coach.get("username") or coach.get("user_id") or ""
    coach_hw = coach.get("hardware_id") or ""
    keys = [k for k in (coach_username, coach_hw) if k]
    return coach_username, keys or [coach_username]


@router.get("/safety-queue")
async def safety_queue(
    request: Request,
    coach: Dict = Depends(require_coach),
    limit: int = 50,
):
    """Open Training Ground safety tickets for this coach's assigned clients."""
    db_pool = request.app.state.db_pool
    if db_pool is None:
        raise HTTPException(503, detail={"reason": "database_unavailable"})

    coach_username, coach_keys = _coach_client_filter(coach)
    lim = max(1, min(int(limit), 200))

    async with db_pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT t.id, t.user_id, t.ticket_tier, t.priority, t.status,
                   t.trigger_class, t.user_turn_text, t.auto_generated,
                   t.created_at, t.session_id,
                   u.profile_data->>'name' AS client_name
              FROM training_ground_progression_tickets t
              JOIN users u ON u.username = t.user_id
             WHERE t.status = 'open'
               AND t.origin = 'training_ground'
               AND t.ticket_tier IN ('CRISIS', 'HYPO', 'DEPTH')
               AND (
                    u.profile_data->>'coach_id' = ANY($1::text[])
                 OR u.profile_data->>'assigned_coach_id' = ANY($1::text[])
                 OR LOWER(u.profile_data->>'assigned_coach') = LOWER($2)
               )
             ORDER BY t.priority ASC, t.created_at DESC
             LIMIT $3
            """,
            coach_keys,
            coach_username,
            lim,
        )

    tickets = []
    for r in rows:
        item = dict(r)
        item["id"] = str(item["id"])
        if item.get("session_id"):
            item["session_id"] = str(item["session_id"])
        item["label"] = "Training Ground — coaching boundary"
        tickets.append(item)

    return {"ok": True, "count": len(tickets), "tickets": tickets}


@router.get("/safety-queue/count")
async def safety_queue_count(request: Request, coach: Dict = Depends(require_coach)):
    db_pool = request.app.state.db_pool
    if db_pool is None:
        raise HTTPException(503, detail={"reason": "database_unavailable"})

    coach_username, coach_keys = _coach_client_filter(coach)

    async with db_pool.acquire() as conn:
        count = await conn.fetchval(
            """
            SELECT COUNT(*)
              FROM training_ground_progression_tickets t
              JOIN users u ON u.username = t.user_id
             WHERE t.status = 'open'
               AND t.origin = 'training_ground'
               AND t.ticket_tier IN ('CRISIS', 'HYPO', 'DEPTH')
               AND (
                    u.profile_data->>'coach_id' = ANY($1::text[])
                 OR u.profile_data->>'assigned_coach_id' = ANY($1::text[])
                 OR LOWER(u.profile_data->>'assigned_coach') = LOWER($2)
               )
            """,
            coach_keys,
            coach_username,
        )

    return {"ok": True, "count": int(count or 0)}
