"""Coach Nate check-in REST + Twilio TwiML/status webhooks.

# SOVEREIGN-VOICE
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, Form, HTTPException, Query, Request
from fastapi.responses import Response
from pydantic import BaseModel, Field

from app.services.api_server import require_coach
from app.services.coach_nate_checkin_service import (
    CoachNateCheckinService,
    feature_enabled,
    twiml_connect_stream,
)

logger = logging.getLogger("nate.coach_nate_checkin_api")

router = APIRouter(tags=["coach-nate-checkin"])


def _svc(request: Request) -> CoachNateCheckinService:
    pool = getattr(request.app.state, "db_pool", None)
    return CoachNateCheckinService(pool, app_state=request.app.state)


class CreateCheckinBody(BaseModel):
    client_username: str = Field(..., min_length=1, max_length=120)
    intent: str = Field(default="coach_checkin", max_length=64)
    note: str = Field(default="", max_length=500)


class OtpConfirmBody(BaseModel):
    code: str = Field(..., min_length=4, max_length=12)


@router.post("/api/coach/nate-checkin")
async def create_checkin(
    body: CreateCheckinBody,
    request: Request,
    coach: Dict[str, Any] = Depends(require_coach),
):
    if not feature_enabled():
        raise HTTPException(503, "Coach Nate check-in is disabled")
    coach_username = (
        coach.get("username")
        or coach.get("user_id")
        or coach.get("sub")
        or ""
    )
    if not coach_username:
        raise HTTPException(401, "Coach identity missing")
    svc = _svc(request)
    result = await svc.create_and_dial(
        coach_username=str(coach_username),
        client_username=body.client_username.strip(),
        intent=body.intent,
        note=body.note,
    )
    if result.get("status") != "ok":
        raise HTTPException(400, result.get("error") or "checkin_failed")
    return result


@router.get("/api/coach/nate-checkin/{task_id}")
async def get_checkin(
    task_id: int,
    request: Request,
    coach: Dict[str, Any] = Depends(require_coach),
):
    svc = _svc(request)
    task = await svc.get_task(task_id)
    if not task:
        raise HTTPException(404, "Task not found")
    cu = (coach.get("username") or "").lower()
    if task["coach_username"].lower() != cu and cu != "drnevedal1":
        raise HTTPException(403, "Not your task")
    return {"status": "ok", "task": task}


@router.get("/api/coach/nate-checkin")
async def list_checkins(
    request: Request,
    coach: Dict[str, Any] = Depends(require_coach),
    limit: int = Query(40, ge=1, le=100),
):
    svc = _svc(request)
    coach_username = coach.get("username") or ""
    rows = await svc.list_for_coach(str(coach_username), limit=limit)
    return {"status": "ok", "tasks": rows, "count": len(rows)}


@router.post("/api/coach/nate-checkin/{task_id}/send-otp")
async def send_otp(
    task_id: int,
    request: Request,
    coach: Dict[str, Any] = Depends(require_coach),
):
    svc = _svc(request)
    task = await svc.get_task(task_id)
    if not task:
        raise HTTPException(404, "Task not found")
    return await svc.send_otp(task_id)


@router.post("/api/coach/nate-checkin/{task_id}/confirm-otp")
async def confirm_otp(
    task_id: int,
    body: OtpConfirmBody,
    request: Request,
    coach: Dict[str, Any] = Depends(require_coach),
):
    svc = _svc(request)
    return await svc.confirm_otp(task_id, body.code.strip())


# ── Twilio public webhooks (also used by callback_processor) ───────────


@router.api_route("/api/calls/nate-checkin-twiml", methods=["GET", "POST"])
async def nate_checkin_twiml(
    request: Request,
    call_id: str = "",
    task_id: int = 0,
    AnsweredBy: str = "",
):
    """Outbound check-in TwiML — AMD machine → Say; else media stream."""
    form = {}
    try:
        if request.method == "POST":
            form = dict(await request.form())
    except Exception:
        form = {}
    answered_by = AnsweredBy or form.get("AnsweredBy") or ""
    cid = call_id or form.get("call_id") or request.query_params.get("call_id") or ""
    tid = task_id or int(form.get("task_id") or request.query_params.get("task_id") or 0)
    # Also accept Twilio CallSid mapping via Redis call_id
    if not cid:
        cid = request.query_params.get("call_id") or ""
    uname, phone = "", ""
    if tid:
        try:
            svc = _svc(request)
            task = await svc.get_task(int(tid))
            if task:
                uname = str(task.get("client_username") or "")
                phone = str(task.get("client_phone_e164") or "")
        except Exception as e:
            logger.warning("twiml task lookup: %s", e)
    xml = twiml_connect_stream(
        cid, tid, answered_by=str(answered_by), username=uname, phone=phone
    )
    # If machine, mark voicemail
    if str(answered_by).lower().startswith("machine") and tid:
        try:
            svc = _svc(request)
            await svc.handle_status(
                task_id=tid,
                call_sid=str(form.get("CallSid") or ""),
                call_status="completed",
                answered_by=str(answered_by),
            )
        except Exception as e:
            logger.warning("machine VM mark failed: %s", e)
    return Response(content=xml, media_type="application/xml")


@router.post("/api/calls/nate-checkin-status")
async def nate_checkin_status(
    request: Request,
    task_id: int = Query(0),
    CallSid: str = Form(""),
    CallStatus: str = Form(""),
    CallDuration: str = Form("0"),
    AnsweredBy: str = Form(""),
):
    if not task_id:
        try:
            task_id = int(request.query_params.get("task_id") or 0)
        except Exception:
            task_id = 0
    if not task_id:
        return {"status": "skipped", "reason": "no_task_id"}
    svc = _svc(request)
    return await svc.handle_status(
        task_id=task_id,
        call_sid=CallSid,
        call_status=CallStatus,
        call_duration=CallDuration,
        answered_by=AnsweredBy,
    )
