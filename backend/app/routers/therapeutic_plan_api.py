"""
QUANTUM-CRYSTAL-ARCH: Coach therapeutic plan REST API (Agentic Phase 3).
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from app.services.api_server import require_coach
from app.services.nate_therapeutic_plan_service import therapeutic_plans_enabled

logger = logging.getLogger("nate.therapeutic_plan_api")

router = APIRouter(
    prefix="/api/coach/therapeutic-plans",
    tags=["therapeutic-plans"],
    dependencies=[Depends(require_coach)],
)


class AssignPlanRequest(BaseModel):
    user_id: str = Field(..., description="Client hardware_id or username")
    template_id: Optional[str] = None
    title: Optional[str] = None
    total_steps: Optional[int] = None
    step_definitions: Optional[List[Dict[str, Any]]] = None


class AdvancePlanRequest(BaseModel):
    note: Optional[str] = None


def _get_db(request: Request):
    pool = getattr(request.app.state, "db_pool", None)
    if not pool:
        raise HTTPException(503, "Database unavailable")
    return pool


def _coach_id(coach: Dict[str, Any]) -> str:
    return (
        coach.get("hardware_id")
        or coach.get("username")
        or coach.get("user_id")
        or ""
    )


@router.get("/templates")
async def list_templates(
    request: Request,
    coach: Dict[str, Any] = Depends(require_coach),
):
    if not therapeutic_plans_enabled():
        raise HTTPException(404, "Therapeutic plans feature disabled")
    pool = _get_db(request)
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT id, title, total_steps, step_definitions, created_by, created_at
            FROM plan_templates
            ORDER BY created_at DESC
            LIMIT 100
            """
        )
    return [
        {
            "id": str(r["id"]),
            "title": r["title"],
            "total_steps": r["total_steps"],
            "step_definitions": r["step_definitions"],
            "created_by": r["created_by"],
            "created_at": r["created_at"].isoformat() if r["created_at"] else None,
        }
        for r in rows
    ]


@router.get("")
@router.get("/")
async def list_coach_plans(
    request: Request,
    status: Optional[str] = None,
    user_id: Optional[str] = None,
    coach: Dict[str, Any] = Depends(require_coach),
):
    """List treatment + cycle-skill plans for this coach's clients."""
    if not therapeutic_plans_enabled() and not os.getenv(
        "ENABLE_CYCLE_SKILL_PLANS", ""
    ).strip().lower() in ("1", "true", "yes", "on"):
        raise HTTPException(404, "Therapeutic plans feature disabled")
    pool = _get_db(request)
    coach_hw = _coach_id(coach)
    coach_uname = (coach.get("username") or "").strip()
    statuses = (
        [s.strip() for s in (status or "active,suggested").split(",") if s.strip()]
        or ["active", "suggested"]
    )
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT p.id, p.user_id, p.title, p.total_steps, p.current_step,
                   p.status, p.source, p.modality, p.cycle_domain,
                   p.started_at, p.updated_at, p.completed_at,
                   p.step_definitions,
                   COALESCE(u.profile_data->>'name', p.user_id) AS client_name
            FROM nate_therapeutic_plans p
            LEFT JOIN users u
              ON u.username = p.user_id OR u.hardware_id = p.user_id
            WHERE (
                p.coach_id = $1
                OR p.coach_id = $2
                OR (
                    COALESCE(p.source, 'coach') = 'cycle_skill'
                    AND (
                        u.profile_data->>'coach_id' = $1
                        OR u.profile_data->>'assigned_coach_id' = $1
                        OR LOWER(COALESCE(u.profile_data->>'assigned_coach', ''))
                            = LOWER($2)
                    )
                )
            )
            AND ($3::text IS NULL OR p.user_id = $3 OR u.username = $3
                 OR u.hardware_id = $3)
            AND p.status = ANY($4::text[])
            ORDER BY COALESCE(p.updated_at, p.started_at) DESC NULLS LAST
            LIMIT 100
            """,
            coach_hw,
            coach_uname,
            user_id,
            statuses,
        )
    out = []
    for r in rows:
        steps = r["step_definitions"]
        if isinstance(steps, str):
            try:
                steps = json.loads(steps)
            except Exception:
                steps = []
        theme = ""
        cur = int(r["current_step"] or 1)
        if isinstance(steps, list):
            for s in steps:
                if isinstance(s, dict) and int(s.get("step_number") or 0) == cur:
                    theme = str(s.get("theme") or s.get("practice") or "")
                    break
        out.append(
            {
                "plan_id": str(r["id"]),
                "user_id": r["user_id"],
                "client_name": r["client_name"],
                "title": r["title"],
                "total_steps": r["total_steps"],
                "current_step": r["current_step"],
                "status": r["status"],
                "source": r["source"],
                "modality": r["modality"],
                "cycle_domain": r["cycle_domain"],
                "theme": theme,
                "started_at": r["started_at"].isoformat() if r["started_at"] else None,
                "updated_at": r["updated_at"].isoformat() if r["updated_at"] else None,
                "completed_at": r["completed_at"].isoformat()
                if r["completed_at"]
                else None,
            }
        )
    return {"plans": out, "count": len(out)}


@router.post("/assign")
async def assign_plan(
    body: AssignPlanRequest,
    request: Request,
    coach: Dict[str, Any] = Depends(require_coach),
):
    if not therapeutic_plans_enabled():
        raise HTTPException(404, "Therapeutic plans feature disabled")
    pool = _get_db(request)
    coach_hw = _coach_id(coach)

    title = body.title
    total_steps = body.total_steps
    steps = body.step_definitions

    async with pool.acquire() as conn:
        if body.template_id:
            tpl = await conn.fetchrow(
                "SELECT title, total_steps, step_definitions FROM plan_templates WHERE id = $1::uuid",
                body.template_id,
            )
            if not tpl:
                raise HTTPException(404, "Template not found")
            title = title or tpl["title"]
            total_steps = total_steps or tpl["total_steps"]
            steps = steps if steps is not None else tpl["step_definitions"]

        if not title or not total_steps or not steps:
            raise HTTPException(422, "title, total_steps, and step_definitions required")

        row = await conn.fetchrow(
            """
            INSERT INTO nate_therapeutic_plans
                (user_id, coach_id, template_id, title, total_steps,
                 current_step, step_definitions, status, source)
            VALUES ($1, $2, $3::uuid, $4, $5, 1, $6::jsonb, 'active', 'coach')
            RETURNING id, title, total_steps, current_step, status, started_at,
                      step_definitions
            """,
            body.user_id,
            coach_hw,
            body.template_id,
            title,
            int(total_steps),
            json.dumps(steps),
        )

    # QUANTUM-CRYSTAL-ARCH: email client when coach assigns a treatment plan
    try:
        from app.services.cycle_skill_plan_service import (
            schedule_client_skill_plan_email,
            schedule_coach_skill_plan_notify,
        )

        plan_payload = {
            "id": str(row["id"]),
            "title": row["title"],
            "total_steps": row["total_steps"],
            "current_step": row["current_step"],
            "step_definitions": row["step_definitions"],
            "modality": "treatment",
            "status": "active",
            "source": "coach",
        }
        schedule_client_skill_plan_email(
            pool, user_id=body.user_id, plan=plan_payload, event="activated"
        )
        schedule_coach_skill_plan_notify(
            pool, user_id=body.user_id, plan=plan_payload, event="activated"
        )
    except Exception as e:
        logger.warning("therapeutic_plan: assign notify failed: %s", e)

    return {
        "plan_id": str(row["id"]),
        "title": row["title"],
        "total_steps": row["total_steps"],
        "current_step": row["current_step"],
        "status": row["status"],
        "started_at": row["started_at"].isoformat() if row["started_at"] else None,
    }


@router.post("/{plan_id}/advance")
async def advance_plan(
    plan_id: str,
    body: AdvancePlanRequest,
    request: Request,
    coach: Dict[str, Any] = Depends(require_coach),
):
    if not therapeutic_plans_enabled():
        raise HTTPException(404, "Therapeutic plans feature disabled")
    pool = _get_db(request)
    coach_hw = _coach_id(coach)

    async with pool.acquire() as conn:
        plan = await conn.fetchrow(
            """
            SELECT id, coach_id, current_step, total_steps, adaptation_log
            FROM nate_therapeutic_plans
            WHERE id = $1::uuid AND status = 'active'
            """,
            plan_id,
        )
        if not plan:
            raise HTTPException(404, "Active plan not found")
        if plan["coach_id"] and plan["coach_id"] != coach_hw:
            role = (coach.get("role") or "").upper()
            if role != "ADMIN":
                raise HTTPException(403, "Not plan owner")

        new_step = min(int(plan["current_step"]) + 1, int(plan["total_steps"]))
        log_entry = {
            "event": "step_advanced",
            "from_step": int(plan["current_step"]),
            "to_step": new_step,
            "coach_id": coach_hw,
            "note": (body.note or "")[:500],
        }
        status = "completed" if new_step >= int(plan["total_steps"]) else "active"
        row = await conn.fetchrow(
            """
            UPDATE nate_therapeutic_plans
            SET current_step = $2,
                status = $3,
                adaptation_log = adaptation_log || $4::jsonb,
                updated_at = NOW(),
                completed_at = CASE WHEN $3 = 'completed' THEN NOW() ELSE completed_at END
            WHERE id = $1::uuid
            RETURNING id, current_step, total_steps, status
            """,
            plan_id,
            new_step,
            status,
            json.dumps([log_entry]),
        )

    return {
        "plan_id": str(row["id"]),
        "current_step": row["current_step"],
        "total_steps": row["total_steps"],
        "status": row["status"],
    }
