"""
LITTLE NATE — Community Mesh REST API
Endpoints for community group sessions, attendance tracking, and wisdom queries.
"""

import io
import csv
import logging
from datetime import datetime, date
from typing import Optional, List

from fastapi import APIRouter, Request, HTTPException, Depends, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from app.services.api_server import get_current_user

logger = logging.getLogger("nate.community_api")

router = APIRouter(prefix="/api/community", tags=["community"], dependencies=[Depends(get_current_user)])


class SessionCreateRequest(BaseModel):
    session_id: str
    group_name: Optional[str] = None
    peer_count: int = 0
    topic_tags: List[str] = []
    location_lat: Optional[float] = None
    location_lng: Optional[float] = None
    location_name: Optional[str] = None
    manager_user_id: Optional[str] = None


class CheckInRequest(BaseModel):
    session_id: str
    user_id: str
    mood_valence: Optional[float] = None
    location_lat: Optional[float] = None
    location_lng: Optional[float] = None
    location_name: Optional[str] = None


class AttendanceRecordRequest(BaseModel):
    session_id: str
    user_id: str
    display_name: Optional[str] = None
    check_in_time: str
    check_out_time: Optional[str] = None
    location_name: Optional[str] = None
    group_name: Optional[str] = None
    session_date: str
    duration_minutes: Optional[int] = None
    verified_by_manager: bool = False
    signature_b64: Optional[str] = None


class WisdomSubmitRequest(BaseModel):
    session_id: str
    topic_tags: List[str] = []
    anonymized_wisdom: List[str] = []
    peer_count: int = 0
    location_name: Optional[str] = None


class AttendanceEmailRequest(BaseModel):
    user_id: str
    recipient_email: str
    from_date: Optional[str] = None
    to_date: Optional[str] = None
    format: str = "pdf"


@router.post("/sessions")
async def create_session(body: SessionCreateRequest, request: Request):
    """Create or update a community mesh session."""
    engine = getattr(request.app.state, "community_mesh_engine", None)
    if not engine:
        raise HTTPException(status_code=503, detail="Community mesh engine not available")

    await engine.record_session(
        session_id=body.session_id,
        group_name=body.group_name,
        peer_count=body.peer_count,
        topic_tags=body.topic_tags,
        location_lat=body.location_lat,
        location_lng=body.location_lng,
        location_name=body.location_name,
        manager_user_id=body.manager_user_id,
    )
    return {"status": "recorded", "session_id": body.session_id}


@router.post("/check-in")
async def check_in(body: CheckInRequest, request: Request):
    """Record a user check-in to a community session."""
    engine = getattr(request.app.state, "community_mesh_engine", None)
    if not engine:
        raise HTTPException(status_code=503, detail="Community mesh engine not available")

    await engine.record_check_in(
        session_id=body.session_id,
        user_id=body.user_id,
        mood_valence=body.mood_valence,
        location_lat=body.location_lat,
        location_lng=body.location_lng,
        location_name=body.location_name,
    )
    return {"status": "checked_in"}


@router.post("/check-out")
async def check_out(body: dict, request: Request):
    """Record a user check-out from a community session."""
    engine = getattr(request.app.state, "community_mesh_engine", None)
    if not engine:
        raise HTTPException(status_code=503, detail="Community mesh engine not available")

    await engine.record_check_out(
        session_id=body.get("session_id", ""),
        user_id=body.get("user_id", ""),
    )
    return {"status": "checked_out"}


@router.post("/attendance")
async def record_attendance(body: AttendanceRecordRequest, request: Request):
    """Record an attendance entry (usually by group manager)."""
    engine = getattr(request.app.state, "community_mesh_engine", None)
    if not engine:
        raise HTTPException(status_code=503, detail="Community mesh engine not available")

    await engine.record_attendance(
        session_id=body.session_id,
        user_id=body.user_id,
        display_name=body.display_name,
        check_in_time=body.check_in_time,
        check_out_time=body.check_out_time,
        location_name=body.location_name,
        group_name=body.group_name,
        session_date=body.session_date,
        duration_minutes=body.duration_minutes,
        verified_by_manager=body.verified_by_manager,
        signature_b64=body.signature_b64,
    )
    return {"status": "recorded"}


@router.get("/attendance/{user_id}")
async def get_attendance(
    user_id: str,
    request: Request,
    from_date: Optional[str] = Query(None, alias="from"),
    to_date: Optional[str] = Query(None, alias="to"),
    format: str = Query("json"),
):
    """Get attendance records for a user. Supports json and csv formats."""
    engine = getattr(request.app.state, "community_mesh_engine", None)
    if not engine:
        raise HTTPException(status_code=503, detail="Community mesh engine not available")

    fd = None
    td = None
    if from_date:
        fd = date.fromisoformat(from_date)
    if to_date:
        td = date.fromisoformat(to_date)

    records = await engine.get_attendance_records(user_id, from_date=fd, to_date=td)

    if format == "csv":
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow([
            "Date", "Group", "Location", "Check-In", "Check-Out",
            "Duration (min)", "Verified", "Signature",
        ])
        for r in records:
            writer.writerow([
                str(r.get("session_date", "")),
                r.get("group_name", ""),
                r.get("location_name", ""),
                str(r.get("check_in_time", "")),
                str(r.get("check_out_time", "")),
                r.get("duration_minutes", ""),
                "Yes" if r.get("verified_by_manager") else "No",
                "Signed" if r.get("signature_b64") else "—",
            ])
        output.seek(0)
        return StreamingResponse(
            io.BytesIO(output.getvalue().encode()),
            media_type="text/csv",
            headers={"Content-Disposition": f'attachment; filename="attendance_{user_id}.csv"'},
        )

    return {"records": records, "total": len(records)}


@router.post("/attendance/email")
async def email_attendance(body: AttendanceEmailRequest, request: Request):
    """Email attendance records to a specified address (e.g., probation officer)."""
    engine = getattr(request.app.state, "community_mesh_engine", None)
    if not engine:
        raise HTTPException(status_code=503, detail="Community mesh engine not available")

    fd = date.fromisoformat(body.from_date) if body.from_date else None
    td = date.fromisoformat(body.to_date) if body.to_date else None

    records = await engine.get_attendance_records(body.user_id, from_date=fd, to_date=td)

    if not records:
        raise HTTPException(status_code=404, detail="No attendance records found")

    notification_system = getattr(request.app.state, "notification_system", None)
    if not notification_system:
        raise HTTPException(status_code=503, detail="Email service not available")

    csv_buf = io.StringIO()
    writer = csv.writer(csv_buf)
    writer.writerow(["Date", "Group", "Location", "Check-In", "Check-Out", "Duration (min)", "Verified"])
    for r in records:
        writer.writerow([
            str(r.get("session_date", "")),
            r.get("group_name", ""),
            r.get("location_name", ""),
            str(r.get("check_in_time", "")),
            str(r.get("check_out_time", "")),
            r.get("duration_minutes", ""),
            "Yes" if r.get("verified_by_manager") else "No",
        ])

    body_html = f"""
    <h2>Attendance Records — Sovereign Sanctuary</h2>
    <p>Attached are the community session attendance records for the requested date range.</p>
    <p>Total sessions: {len(records)}</p>
    <p><em>Generated by Sovereign Sanctuary (sovereignsanctuary.net)</em></p>
    """

    try:
        import base64
        from sendgrid import SendGridAPIClient
        from sendgrid.helpers.mail import Mail, Attachment, FileContent, FileName, FileType, Disposition
        import os

        sg = SendGridAPIClient(os.getenv("SENDGRID_API_KEY", ""))
        message = Mail(
            from_email="records@sovereignsanctuary.net",
            to_emails=body.recipient_email,
            subject="Attendance Records — Sovereign Sanctuary",
            html_content=body_html,
        )

        csv_b64 = base64.b64encode(csv_buf.getvalue().encode()).decode()
        attachment = Attachment(
            FileContent(csv_b64),
            FileName(f"attendance_{body.user_id}.csv"),
            FileType("text/csv"),
            Disposition("attachment"),
        )
        message.attachment = attachment

        sg.send(message)
        return {"status": "sent", "recipient": body.recipient_email, "records": len(records)}
    except Exception as e:
        logger.error("Failed to send attendance email: %s", e)
        raise HTTPException(status_code=500, detail="Failed to send email")


@router.post("/wisdom")
async def submit_wisdom(body: WisdomSubmitRequest, request: Request):
    """Submit anonymized community wisdom from a group session."""
    engine = getattr(request.app.state, "community_mesh_engine", None)
    if not engine:
        raise HTTPException(status_code=503, detail="Community mesh engine not available")

    await engine.process_community_data(
        session_id=body.session_id,
        anonymized_wisdom=body.anonymized_wisdom,
        topic_tags=body.topic_tags,
        peer_count=body.peer_count,
        location=body.location_name,
    )
    return {"status": "received", "wisdom_count": len(body.anonymized_wisdom)}


@router.get("/wisdom")
async def get_wisdom(
    request: Request,
    topic: Optional[str] = None,
    limit: int = Query(20, le=100),
):
    """Get community wisdom insights, optionally filtered by topic."""
    engine = getattr(request.app.state, "community_mesh_engine", None)
    if not engine:
        raise HTTPException(status_code=503, detail="Community mesh engine not available")

    insights = await engine.get_community_insights(topic=topic, limit=limit)
    return {"insights": insights, "total": len(insights)}
