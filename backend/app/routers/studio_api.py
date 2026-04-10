"""Thera-World Studio — admin-only REST endpoints for script/scene/library/project management."""
from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from pydantic import BaseModel

from app.services.api_server import require_admin

logger = logging.getLogger(__name__)

studio_router = APIRouter(
    prefix="/api/sse/admin/studio",
    tags=["studio"],
    dependencies=[Depends(require_admin)],
)


# ── Request models ────────────────────────────────────────────────────────

class GenerateScriptRequest(BaseModel):
    prompt: str
    content_sources: list[str] | None = None

class BreakScenesRequest(BaseModel):
    script: str

class GenerateImageRequest(BaseModel):
    project_id: str
    scene_num: int
    description: str

class GenerateVideoRequest(BaseModel):
    project_id: str
    scene_num: int
    image_url: str
    motion_prompt: str

class GenerateNarrationRequest(BaseModel):
    project_id: str
    scene_num: int
    text: str
    voice: str = "narrator"

class CreateProjectRequest(BaseModel):
    title: str
    scenes: list[dict]

class CleanProjectRequest(BaseModel):
    project_id: str

class DeleteLibraryRequest(BaseModel):
    r2_key: str

class GenerateCharRefsRequest(BaseModel):
    project_id: str

class GenerateVideoClipsRequest(BaseModel):
    project_id: str

class StitchTrailerRequest(BaseModel):
    project_id: str
    include_color_grade: bool = True
    include_narration: bool = True
    format: str = "16:9"


# ── Helpers ───────────────────────────────────────────────────────────────

def _get_db(request: Request):
    return getattr(request.app.state, "db_pool", None)


def _get_redis(request: Request):
    return getattr(request.app.state, "redis", None)


# ── Endpoints ─────────────────────────────────────────────────────────────

@studio_router.get("/content-sources")
async def content_sources():
    from app.sse.studio_service import get_content_sources
    return get_content_sources()


@studio_router.post("/generate-script")
async def generate_script(body: GenerateScriptRequest):
    from app.sse.studio_service import generate_script as _gen
    return await _gen(body.prompt, body.content_sources)


@studio_router.post("/break-scenes")
async def break_scenes(body: BreakScenesRequest):
    from app.sse.studio_service import break_into_scenes
    return await break_into_scenes(body.script)


@studio_router.post("/generate-image")
async def generate_image(body: GenerateImageRequest, request: Request):
    from app.sse.studio_service import generate_scene_image
    redis = _get_redis(request)
    url = await generate_scene_image(body.description, body.project_id, body.scene_num, redis=redis)
    return {"r2_url": url}


@studio_router.post("/generate-video")
async def generate_video(body: GenerateVideoRequest, request: Request):
    from app.sse.studio_service import generate_scene_video
    redis = _get_redis(request)
    url = await generate_scene_video(body.image_url, body.motion_prompt, body.project_id, body.scene_num, redis=redis)
    return {"video_url": url}


@studio_router.post("/generate-narration")
async def generate_narration(body: GenerateNarrationRequest, request: Request):
    from app.sse.studio_service import generate_narration as _gen
    redis = _get_redis(request)
    url = await _gen(body.text, body.voice, body.project_id, body.scene_num, redis=redis)
    return {"audio_url": url}


@studio_router.get("/library")
async def library(filter: str = "all"):
    from app.sse.studio_service import list_library
    items = await list_library(filter)
    return items


@studio_router.delete("/library/delete")
async def library_delete(body: DeleteLibraryRequest):
    from app.sse.studio_service import delete_library_object
    ok = await delete_library_object(body.r2_key)
    return {"deleted": ok}


@studio_router.get("/presets")
async def presets():
    from app.sse.studio_service import list_presets
    return list_presets()


@studio_router.get("/presets/{name}")
async def preset_detail(name: str):
    from app.sse.studio_service import get_preset
    try:
        return get_preset(name)
    except FileNotFoundError:
        raise HTTPException(404, f"Preset '{name}' not found")


@studio_router.post("/projects")
async def create_project(body: CreateProjectRequest, request: Request):
    from app.sse.studio_service import create_project as _create
    db = _get_db(request)
    if not db:
        raise HTTPException(503, "Database unavailable")
    return await _create(body.title, body.scenes, db)


@studio_router.get("/projects")
async def list_projects(request: Request):
    from app.sse.studio_service import list_projects as _list
    db = _get_db(request)
    if not db:
        raise HTTPException(503, "Database unavailable")
    return await _list(db)


@studio_router.get("/projects/{project_id}")
async def get_project(project_id: str, request: Request):
    from app.sse.studio_service import get_project as _get
    db = _get_db(request)
    if not db:
        raise HTTPException(503, "Database unavailable")
    proj = await _get(project_id, db)
    if not proj:
        raise HTTPException(404, "Project not found")
    return proj


@studio_router.post("/clean-project")
async def clean_project(body: CleanProjectRequest, request: Request):
    from app.sse.studio_service import clean_project as _clean
    db = _get_db(request)
    if not db:
        raise HTTPException(503, "Database unavailable")
    try:
        count = await _clean(body.project_id, db)
    except ValueError as e:
        raise HTTPException(404, str(e))
    return {"deleted_count": count}


@studio_router.get("/cost-status")
async def cost_status(request: Request):
    from app.sse.studio_service import get_daily_cost
    redis = _get_redis(request)
    return await get_daily_cost(redis)


# ── Phase 2 Endpoints ────────────────────────────────────────────────────

@studio_router.post("/generate-character-refs")
async def generate_char_refs(body: GenerateCharRefsRequest, request: Request, background_tasks: BackgroundTasks):
    from app.sse.studio_service import generate_character_refs
    redis = _get_redis(request)
    background_tasks.add_task(generate_character_refs, body.project_id, redis)
    return {"status": "started", "project_id": body.project_id,
            "message": "Generating 7 character reference images — ~40s"}


@studio_router.post("/generate-video-clips")
async def generate_video_clips(body: GenerateVideoClipsRequest, request: Request, background_tasks: BackgroundTasks):
    from app.sse.studio_service import generate_video_clips
    db = _get_db(request)
    redis = _get_redis(request)
    background_tasks.add_task(generate_video_clips, body.project_id, db, redis)
    return {"status": "started", "project_id": body.project_id,
            "message": "Generating motion video clips — this takes several minutes"}


@studio_router.post("/stitch-trailer")
async def stitch_trailer(body: StitchTrailerRequest, request: Request, background_tasks: BackgroundTasks):
    from app.sse.studio_service import stitch_project_trailer
    db = _get_db(request)
    redis = _get_redis(request)
    options = {"include_color_grade": body.include_color_grade,
               "include_narration": body.include_narration,
               "format": body.format}
    background_tasks.add_task(stitch_project_trailer, body.project_id, options, db, redis)
    return {"status": "started", "project_id": body.project_id,
            "message": "Stitching trailer — downloading clips, grading, narrating, exporting"}


@studio_router.get("/projects/{project_id}/video-status")
async def video_status(project_id: str):
    from app.sse.studio_service import get_video_status
    return await get_video_status(project_id)


@studio_router.get("/projects/{project_id}/trailer-status")
async def trailer_status(project_id: str):
    from app.sse.studio_service import get_trailer_status
    return await get_trailer_status(project_id)


@studio_router.get("/daily-budget")
async def daily_budget(request: Request):
    from app.sse.studio_service import get_daily_cost
    redis = _get_redis(request)
    return await get_daily_cost(redis)
