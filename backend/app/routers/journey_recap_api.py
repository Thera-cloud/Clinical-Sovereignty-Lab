"""Admin API — 30s Journey Recap story video (transcript + panels + Ask Nate → stitched MP4)."""
from __future__ import annotations

import logging
import uuid
from typing import Any, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, Request, UploadFile
from pydantic import BaseModel, Field

from app.services.api_server import require_admin
from app.sse import journey_recap_video as recap

logger = logging.getLogger(__name__)

journey_recap_router = APIRouter(
    prefix="/api/sse/admin/journey-recap",
    tags=["journey-recap"],
    dependencies=[Depends(require_admin)],
)


class PanelAlignmentInput(BaseModel):
    segment_index: int
    panel_id: str
    transcript_excerpt: Optional[str] = None


class CreateRecapJobRequest(BaseModel):
    user_id: str
    transcript_text: str = Field(..., min_length=20)
    panel_alignments: list[PanelAlignmentInput] = Field(default_factory=list)
    target_duration_seconds: int = Field(default=30, ge=15, le=60)
    segment_count: int = Field(default=4, ge=2, le=6)


def _require_feature() -> None:
    if not recap.feature_enabled():
        raise HTTPException(
            503,
            detail=f"Journey recap disabled — set {recap.FEATURE_FLAG}=true",
        )


def _job_row_to_dict(row) -> dict[str, Any]:
    d = dict(row)
    for key in ("job_id",):
        if key in d and d[key] is not None:
            d[key] = str(d[key])
    for key in ("panel_alignments", "chat_captures", "segment_clips"):
        if key in d and isinstance(d[key], str):
            import json
            try:
                d[key] = json.loads(d[key])
            except Exception:
                pass
    return d


@journey_recap_router.get("/health")
async def journey_recap_health():
    return {
        "status": "ok",
        "enabled": recap.feature_enabled(),
        "target_duration_default": recap.DEFAULT_TARGET_DURATION,
        "segment_count_default": recap.DEFAULT_SEGMENT_COUNT,
    }


@journey_recap_router.post("/jobs")
async def create_journey_recap_job(request: Request, body: CreateRecapJobRequest):
    _require_feature()
    pool = request.app.state.db_pool
    if pool is None:
        raise HTTPException(503, detail="Database unavailable")

    alignments = [a.model_dump() for a in body.panel_alignments]
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO sse_journey_recap_jobs (
                user_id, transcript_text, panel_alignments,
                target_duration_seconds, segment_count, status
            ) VALUES ($1, $2, $3::jsonb, $4, $5, 'pending')
            RETURNING *
            """,
            body.user_id.strip(),
            body.transcript_text.strip(),
            alignments,
            body.target_duration_seconds,
            body.segment_count,
        )
    return {"job": _job_row_to_dict(row)}


@journey_recap_router.post("/jobs/{job_id}/audio")
async def upload_recap_audio(
    job_id: str,
    request: Request,
    file: UploadFile = File(...),
):
    _require_feature()
    pool = request.app.state.db_pool
    if pool is None:
        raise HTTPException(503, detail="Database unavailable")

    data = await file.read()
    if len(data) < 1000:
        raise HTTPException(400, detail="Audio file too small")

    async with pool.acquire() as conn:
        job = await conn.fetchrow(
            "SELECT user_id FROM sse_journey_recap_jobs WHERE job_id = $1::uuid",
            uuid.UUID(job_id),
        )
        if not job:
            raise HTTPException(404, detail="Job not found")

    content_type = file.content_type or "audio/mpeg"
    ext = ".m4a" if "m4a" in content_type or "mp4" in content_type else ".mp3"
    key = f"sse/journey-recap/{job['user_id']}/{job_id}/audio{ext}"
    from app.sse.infrastructure import r2_storage
    url = await r2_storage.store_bytes(data, key, content_type)

    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            UPDATE sse_journey_recap_jobs SET
                audio_r2_key = $2,
                audio_r2_url = $3,
                updated_at = NOW()
            WHERE job_id = $1::uuid
            RETURNING job_id::text, audio_r2_key, audio_r2_url
            """,
            uuid.UUID(job_id),
            key,
            url,
        )
    return {"job_id": str(row["job_id"]), "audio_r2_key": row["audio_r2_key"], "audio_r2_url": row["audio_r2_url"]}


@journey_recap_router.post("/jobs/{job_id}/generate")
async def generate_journey_recap(job_id: str, request: Request, background_tasks: BackgroundTasks):
    _require_feature()
    pool = request.app.state.db_pool
    if pool is None:
        raise HTTPException(503, detail="Database unavailable")

    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT status FROM sse_journey_recap_jobs WHERE job_id = $1::uuid",
            uuid.UUID(job_id),
        )
    if not row:
        raise HTTPException(404, detail="Job not found")
    if row["status"] not in ("pending", "failed"):
        raise HTTPException(409, detail=f"Job already {row['status']}")

    background_tasks.add_task(recap.run_journey_recap_job, pool, job_id)
    return {"job_id": job_id, "status": "queued"}


@journey_recap_router.get("/jobs/{job_id}")
async def get_journey_recap_job(job_id: str, request: Request):
    pool = request.app.state.db_pool
    if pool is None:
        raise HTTPException(503, detail="Database unavailable")
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM sse_journey_recap_jobs WHERE job_id = $1::uuid",
            uuid.UUID(job_id),
        )
    if not row:
        raise HTTPException(404, detail="Job not found")
    return {"job": _job_row_to_dict(row)}


@journey_recap_router.get("/jobs")
async def list_journey_recap_jobs(request: Request, user_id: Optional[str] = None, limit: int = 20):
    pool = request.app.state.db_pool
    if pool is None:
        raise HTTPException(503, detail="Database unavailable")
    limit = min(max(limit, 1), 50)
    async with pool.acquire() as conn:
        if user_id:
            rows = await conn.fetch(
                """
                SELECT job_id, user_id, status, target_duration_seconds, segment_count,
                       output_r2_url, created_at, completed_at, error_message
                FROM sse_journey_recap_jobs
                WHERE user_id = $1
                ORDER BY created_at DESC LIMIT $2
                """,
                user_id.strip(),
                limit,
            )
        else:
            rows = await conn.fetch(
                """
                SELECT job_id, user_id, status, target_duration_seconds, segment_count,
                       output_r2_url, created_at, completed_at, error_message
                FROM sse_journey_recap_jobs
                ORDER BY created_at DESC LIMIT $1
                """,
                limit,
            )
    jobs = []
    for r in rows:
        d = dict(r)
        d["job_id"] = str(d["job_id"])
        jobs.append(d)
    return {"jobs": jobs}
