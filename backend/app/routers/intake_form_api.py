"""Clinical intake REST API."""

from __future__ import annotations

import os
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from app.constants.intake_questions import ALL_QUESTION_FIELDS, SECTION2_FIELDS
from app.services.api_server import get_current_user, require_coach
from app.services.intake_form_service import (
    ensure_intake_row,
    get_client_intake,
    get_intake_summary,
    get_reminder_status,
    get_section1_for_nate,
    is_client_assigned_to_coach,
    mark_section2_complete,
    send_intake_reminder,
    update_client_answer,
    update_coach_section2_answer,
    update_coach_style_guidance,
)

router = APIRouter(prefix="/api", tags=["intake"])


def _intake_enabled() -> bool:
    return os.getenv("ENABLE_INTAKE_SYSTEM", "false").lower() in ("1", "true", "yes")


class IntakeAnswerPatch(BaseModel):
    value: Any


class IntakeReminderRequest(BaseModel):
    sections: List[str] = Field(default_factory=list)
    methods: List[str] = Field(default_factory=list)
    personal_note: Optional[str] = ""
    override_rate_limit: bool = False
    override_reason: Optional[str] = None


class NateStyleGuidancePatch(BaseModel):
    value: str


async def _get_pool(request: Request):
    pool = getattr(request.app.state, "db_pool", None)
    if not pool:
        raise HTTPException(status_code=503, detail="Database unavailable")
    return pool


async def _resolve_username_from_user(conn, user: Dict[str, Any]) -> Optional[str]:
    username = (user.get("username") or "").strip()
    if username:
        return username
    hardware_id = (user.get("hardware_id") or user.get("user_id") or "").strip()
    if not hardware_id:
        return None
    return await conn.fetchval(
        "SELECT username FROM users WHERE hardware_id = $1 LIMIT 1",
        hardware_id,
    )


@router.get("/client/intake")
async def get_client_intake_endpoint(request: Request, user: Dict = Depends(get_current_user)):
    if not _intake_enabled():
        raise HTTPException(status_code=404, detail="Intake system disabled")
    role = (user.get("role") or "").upper()
    if role not in ("CLIENT", "ADMIN"):
        raise HTTPException(status_code=403, detail="Client access required")
    pool = await _get_pool(request)
    async with pool.acquire() as conn:
        username = await _resolve_username_from_user(conn, user)
        if not username:
            raise HTTPException(status_code=400, detail="Unable to resolve username")
        return await get_client_intake(conn, username, user.get("hardware_id"))


@router.patch("/client/intake/{question_id}")
async def patch_client_intake_answer(
    question_id: str,
    body: IntakeAnswerPatch,
    request: Request,
    user: Dict = Depends(get_current_user),
):
    if not _intake_enabled():
        raise HTTPException(status_code=404, detail="Intake system disabled")
    role = (user.get("role") or "").upper()
    if role not in ("CLIENT", "ADMIN"):
        raise HTTPException(status_code=403, detail="Client access required")
    if question_id not in ALL_QUESTION_FIELDS:
        raise HTTPException(status_code=404, detail="Unknown question_id")

    pool = await _get_pool(request)
    async with pool.acquire() as conn:
        username = await _resolve_username_from_user(conn, user)
        if not username:
            raise HTTPException(status_code=400, detail="Unable to resolve username")
        try:
            return await update_client_answer(
                conn,
                username=username,
                hardware_id=user.get("hardware_id"),
                question_id=question_id,
                value=body.value,
                actor_id=username,
                method="self_service",
            )
        except ValueError as err:
            raise HTTPException(status_code=400, detail=str(err))


@router.get("/coach/intake/{client_username}")
async def get_coach_intake(client_username: str, request: Request, coach: Dict = Depends(require_coach)):
    if not _intake_enabled():
        raise HTTPException(status_code=404, detail="Intake system disabled")
    pool = await _get_pool(request)
    async with pool.acquire() as conn:
        allowed = await is_client_assigned_to_coach(conn, client_username=client_username, coach=coach)
        if not allowed:
            raise HTTPException(status_code=403, detail="Client is not assigned to this coach")

        await ensure_intake_row(conn, client_username, None)
        row = await conn.fetchrow("SELECT * FROM intake_form WHERE user_id = $1", client_username)
        payload = dict(row or {})
        payload["intake_summary"] = await get_intake_summary(conn, client_username)
        payload["nate_section_1_context"] = await get_section1_for_nate(conn, client_username)
        return payload


@router.patch("/coach/intake/{client_username}/{question_id}")
async def patch_coach_section2(
    client_username: str,
    question_id: str,
    body: IntakeAnswerPatch,
    request: Request,
    coach: Dict = Depends(require_coach),
):
    if not _intake_enabled():
        raise HTTPException(status_code=404, detail="Intake system disabled")
    pool = await _get_pool(request)
    async with pool.acquire() as conn:
        allowed = await is_client_assigned_to_coach(conn, client_username=client_username, coach=coach)
        if not allowed:
            raise HTTPException(status_code=403, detail="Client is not assigned to this coach")
        try:
            coach_username = await _resolve_username_from_user(conn, coach) or "unknown_coach"
            return await update_coach_section2_answer(
                conn,
                username=client_username,
                question_id=question_id,
                value=body.value,
                coach_username=coach_username,
            )
        except PermissionError as err:
            raise HTTPException(status_code=403, detail=str(err))
        except ValueError as err:
            raise HTTPException(status_code=400, detail=str(err))


@router.post("/coach/intake/{client_username}/complete-section-2")
async def complete_section2(client_username: str, request: Request, coach: Dict = Depends(require_coach)):
    if not _intake_enabled():
        raise HTTPException(status_code=404, detail="Intake system disabled")
    pool = await _get_pool(request)
    async with pool.acquire() as conn:
        allowed = await is_client_assigned_to_coach(conn, client_username=client_username, coach=coach)
        if not allowed:
            raise HTTPException(status_code=403, detail="Client is not assigned to this coach")
        return await mark_section2_complete(conn, username=client_username, completed_by="coach")


@router.patch("/coach/intake/{client_username}/nate-style-guidance")
async def patch_nate_style_guidance(
    client_username: str,
    body: NateStyleGuidancePatch,
    request: Request,
    coach: Dict = Depends(require_coach),
):
    if not _intake_enabled():
        raise HTTPException(status_code=404, detail="Intake system disabled")
    pool = await _get_pool(request)
    async with pool.acquire() as conn:
        allowed = await is_client_assigned_to_coach(conn, client_username=client_username, coach=coach)
        if not allowed:
            raise HTTPException(status_code=403, detail="Client is not assigned to this coach")
        coach_username = await _resolve_username_from_user(conn, coach) or "unknown_coach"
        try:
            return await update_coach_style_guidance(
                conn,
                username=client_username,
                guidance=body.value,
                coach_username=coach_username,
            )
        except ValueError as err:
            raise HTTPException(status_code=400, detail=str(err))


@router.get("/coach/intake/{client_username}/reminder-status")
async def reminder_status(client_username: str, request: Request, coach: Dict = Depends(require_coach)):
    if not _intake_enabled():
        raise HTTPException(status_code=404, detail="Intake system disabled")
    pool = await _get_pool(request)
    async with pool.acquire() as conn:
        allowed = await is_client_assigned_to_coach(conn, client_username=client_username, coach=coach)
        if not allowed:
            raise HTTPException(status_code=403, detail="Client is not assigned to this coach")
        return await get_reminder_status(conn, client_username)


@router.post("/coach/intake/{client_username}/remind")
async def remind_client(
    client_username: str,
    body: IntakeReminderRequest,
    request: Request,
    coach: Dict = Depends(require_coach),
):
    if not _intake_enabled():
        raise HTTPException(status_code=404, detail="Intake system disabled")
    for section in body.sections:
        if section not in ("section_1", "section_2"):
            raise HTTPException(status_code=400, detail="Invalid section in reminder")
    for method in body.methods:
        if method not in ("in_app", "email", "sms"):
            raise HTTPException(status_code=400, detail="Invalid method in reminder")

    pool = await _get_pool(request)
    notification_system = getattr(request.app.state, "notification_system", None)
    async with pool.acquire() as conn:
        allowed = await is_client_assigned_to_coach(conn, client_username=client_username, coach=coach)
        if not allowed:
            raise HTTPException(status_code=403, detail="Client is not assigned to this coach")
        coach_username = await _resolve_username_from_user(conn, coach) or "unknown_coach"
        try:
            return await send_intake_reminder(
                conn,
                username=client_username,
                coach_username=coach_username,
                sections=body.sections or ["section_1", "section_2"],
                methods=body.methods or ["in_app"],
                personal_note=body.personal_note or "",
                override_rate_limit=body.override_rate_limit,
                override_reason=body.override_reason,
                notification_system=notification_system,
            )
        except PermissionError as err:
            raise HTTPException(status_code=429, detail=str(err))
        except ValueError as err:
            raise HTTPException(status_code=400, detail=str(err))
