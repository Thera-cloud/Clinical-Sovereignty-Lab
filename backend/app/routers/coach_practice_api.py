"""Coach practice snapshot + print report. QUANTUM-CRYSTAL-ARCH."""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from app.services.api_server import require_coach
from app.services.assistant_consult_archive import (
    backfill_completed_consults,
    ensure_assistant_folder,
    list_consult_actions,
)
from app.services.coach_practice_report import (
    anonymize_snapshot,
    compose_guidance,
    render_html,
)
from app.services.coach_practice_snapshot import build_snapshot, resolve_coach_ids

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/coach/practice", tags=["coach-practice"])


class ReportRequest(BaseModel):
    days: int = 90
    coach_username: Optional[str] = None


def _pool(request: Request):
    pool = getattr(request.app.state, "db_pool", None)
    if pool is None:
        raise HTTPException(503, "database unavailable")
    return pool


def _caller_ident(user: Dict[str, Any]) -> str:
    return str(user.get("username") or user.get("hardware_id") or user.get("user_id") or "")


async def _authorize_target(conn, caller: Dict[str, Any], target_ident: str) -> str:
    target = await resolve_coach_ids(conn, target_ident)
    if not target:
        raise HTTPException(404, "Coach not found")
    caller_user = str(caller.get("username") or "")
    caller_hw = str(caller.get("hardware_id") or "")
    role = str(caller.get("role") or "").upper()
    if role == "ADMIN" or target["username"] == caller_user or target["hardware_id"] == caller_hw:
        return target["username"]
    ok = await conn.fetchval(
        """SELECT 1 FROM coach_hierarchy
           WHERE master_coach_id = $1 AND assistant_id = $2
             AND status IN ('active', 'accepted')
           LIMIT 1""",
        caller_hw,
        target["hardware_id"],
    )
    if not ok:
        raise HTTPException(403, "Not authorized for this coach snapshot")
    return target["username"]


@router.get("/snapshot")
async def get_snapshot(
    request: Request,
    days: int = 90,
    coach: Optional[str] = None,
    user: Dict = Depends(require_coach),
):
    pool = _pool(request)
    ident = coach or _caller_ident(user)
    async with pool.acquire() as conn:
        target_username = await _authorize_target(conn, user, ident)
        coach_row = await resolve_coach_ids(conn, target_username)
    if coach_row:
        await backfill_completed_consults(pool, coach_row["hardware_id"])
        master = None
        async with pool.acquire() as conn:
            from app.services.coach_practice_snapshot import resolve_master_for
            master = await resolve_master_for(conn, coach_row["hardware_id"])
        if master:
            await backfill_completed_consults(pool, master["hardware_id"])
    snap = await build_snapshot(pool, coach_ident=target_username, days=days, include_names=True)
    return {"status": "ok", "snapshot": snap}


@router.get("/reports")
async def list_reports(
    request: Request,
    coach: Optional[str] = None,
    user: Dict = Depends(require_coach),
):
    pool = _pool(request)
    ident = coach or _caller_ident(user)
    async with pool.acquire() as conn:
        target = await _authorize_target(conn, user, ident)
        rows = await conn.fetch(
            """SELECT id::text, window_days, created_at, master_username
               FROM coach_practice_reports
               WHERE coach_username = $1
               ORDER BY created_at DESC LIMIT 20""",
            target,
        )
    return {
        "status": "ok",
        "reports": [
            {
                "id": r["id"],
                "window_days": r["window_days"],
                "created_at": r["created_at"].isoformat() if r["created_at"] else None,
                "master_username": r["master_username"],
            }
            for r in rows
        ],
    }


@router.post("/report")
async def create_report(
    req: ReportRequest,
    request: Request,
    user: Dict = Depends(require_coach),
):
    pool = _pool(request)
    ident = req.coach_username or _caller_ident(user)
    async with pool.acquire() as conn:
        target = await _authorize_target(conn, user, ident)
        coach_row = await resolve_coach_ids(conn, target)
        prior = await conn.fetchrow(
            """SELECT metrics, guidance FROM coach_practice_reports
               WHERE coach_username = $1 ORDER BY created_at DESC LIMIT 1""",
            target,
        )
    snap = await build_snapshot(pool, coach_ident=target, days=req.days, include_names=False)
    banned = []
    consult = {"open": [], "completed": []}
    master = snap.get("master")
    if master and coach_row:
        async with pool.acquire() as conn:
            await backfill_completed_consults(pool, master["hardware_id"])
            open_i, done_i = await list_consult_actions(
                conn, master["username"], target
            )
            consult = {"open": open_i, "completed": done_i}
            folder_id = await ensure_assistant_folder(
                conn,
                master["hardware_id"],
                target,
                (snap.get("coach") or {}).get("display_name") or target,
            )
        # also keep a copy on the coach's personal tree
        _ = folder_id
    prior_dict = None
    if prior:
        prior_dict = {"metrics": prior["metrics"] or {}, "guidance": prior["guidance"] or {}}
    guidance = await compose_guidance(request, snap, prior_dict, consult, banned)
    print_snap = anonymize_snapshot(snap)
    html_doc = render_html(print_snap, guidance, req.days)
    file_id = None
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """INSERT INTO coach_practice_reports
               (coach_username, master_username, window_days, metrics, guidance, html)
               VALUES ($1, $2, $3, $4::jsonb, $5::jsonb, $6)
               RETURNING id""",
            target,
            (master or {}).get("username") if master else None,
            req.days,
            json.dumps(print_snap),
            json.dumps(guidance),
            html_doc,
        )
        report_id = str(row["id"])
        try:
            from app.services.blob_storage import upload_bytes

            owner_hw = (master or {}).get("hardware_id") or (coach_row or {}).get("hardware_id")
            if owner_hw:
                filename = f"Practice_Review_{target}_{req.days}d.html"
                rel = f"coach_uploads/{owner_hw}/practice_reports/{report_id}/{filename}"
                _kind, location = upload_bytes(
                    rel_path=rel,
                    content=html_doc.encode("utf-8"),
                    content_type="text/html",
                )
                folder_id = None
                if master:
                    folder_id = await ensure_assistant_folder(
                        conn,
                        master["hardware_id"],
                        target,
                        (snap.get("coach") or {}).get("display_name") or target,
                    )
                else:
                    folder_id = await conn.fetchval(
                        """SELECT id FROM coach_folders
                           WHERE coach_id = $1 AND folder_type = 'personal'
                           LIMIT 1""",
                        (coach_row or {}).get("hardware_id"),
                    )
                    if not folder_id:
                        folder_id = await conn.fetchval(
                            """INSERT INTO coach_folders (coach_id, folder_type, entity_id, entity_name)
                               VALUES ($1, 'personal', $1, 'My Files') RETURNING id""",
                            (coach_row or {}).get("hardware_id"),
                        )
                if folder_id:
                    frow = await conn.fetchrow(
                        """INSERT INTO coach_folder_files
                           (folder_id, filename, file_type, azure_blob_url, storage_url, uploaded_by, metadata)
                           VALUES ($1, $2, 'practice_report', $3, $3, $4, $5::jsonb)
                           RETURNING id""",
                        folder_id,
                        filename,
                        location,
                        owner_hw,
                        json.dumps({"source": "coach_practice_report", "report_id": report_id}),
                    )
                    file_id = str(frow["id"]) if frow else None
                    await conn.execute(
                        "UPDATE coach_practice_reports SET folder_file_id = $1::uuid WHERE id = $2::uuid",
                        file_id,
                        report_id,
                    )
        except Exception as e:
            logger.warning("practice report folder write: %s", e)
    return {
        "status": "ok",
        "report_id": report_id,
        "print_url": f"/api/coach/practice/report/{report_id}/print",
        "folder_file_id": file_id,
        "guidance": guidance,
        "totals": snap.get("totals") or {},
    }


@router.get("/report/{report_id}/print")
async def print_report(
    report_id: str,
    request: Request,
    user: Dict = Depends(require_coach),
):
    pool = _pool(request)
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """SELECT coach_username, master_username, html
               FROM coach_practice_reports WHERE id = $1::uuid""",
            report_id,
        )
        if not row:
            raise HTTPException(404, "Report not found")
        await _authorize_target(conn, user, row["coach_username"])
    return HTMLResponse(content=row["html"] or "<html><body>Empty</body></html>")


@router.get("/health")
async def practice_health():
    return {"status": "ok", "service": "coach_practice"}
