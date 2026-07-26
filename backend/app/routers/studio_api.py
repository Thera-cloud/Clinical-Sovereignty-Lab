"""SSE Studio — admin REST for subset generators, script/scene/library/project management.

Thera-World is one subset (thera_world_origin); other subsets are JSON presets under
studio_presets/ with their own casting_locksheet + visual_style_anchor + LoRAs.
"""
from __future__ import annotations

import json
import logging
import uuid
from datetime import date, datetime
from typing import Any, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, Request, UploadFile
from pydantic import BaseModel

from app.services.api_server import require_admin

logger = logging.getLogger(__name__)

studio_router = APIRouter(
    prefix="/api/sse/admin/studio",
    tags=["studio"],
    dependencies=[Depends(require_admin)],
)


def _coerce_json_list(val: Any) -> Any:
    if val is None:
        return None
    if isinstance(val, str):
        try:
            parsed = json.loads(val)
            return parsed if isinstance(parsed, list) else val
        except (json.JSONDecodeError, TypeError):
            return val
    return val


def _serialize_recap_job_row(row: dict[str, Any]) -> dict[str, Any]:
    d = dict(row)
    d["job_id"] = str(d["job_id"])
    for key in ("panel_alignments", "chat_captures", "segment_clips"):
        if key in d:
            d[key] = _coerce_json_list(d[key])
    for key, val in list(d.items()):
        if isinstance(val, (datetime, date)):
            d[key] = val.isoformat()
        elif isinstance(val, uuid.UUID):
            d[key] = str(val)
    return d


# ── Request models ────────────────────────────────────────────────────────

class GenerateScriptRequest(BaseModel):
    prompt: str
    content_sources: list[str] | None = None
    preset_id: str | None = None


class CreatePresetRequest(BaseModel):
    title: str
    id: str | None = None
    description: str | None = None
    subset_kind: str | None = "custom"
    visual_style_anchor: dict | str | None = None
    casting_locksheet: dict | None = None
    characters: dict | None = None
    scenes: list[dict] | None = None
    default_color_preset: str | None = None
    append_origin_suffix: bool = True

class BreakScenesRequest(BaseModel):
    script: str

class JourneyRecapTranscriptRequest(BaseModel):
    user_id: str
    transcript_text: str
    ingest_mode: str = "audio_driven"
    source_duration_seconds: float | None = None

class GenerateImageRequest(BaseModel):
    project_id: str
    scene_num: int
    description: str
    characters: list[str] | None = None
    source_image_url: str | None = None
    panel_visual_theme: str | None = None

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
    preset_id: str | None = None

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
    color_preset: str = "ghibli_warm"
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
    return await _gen(body.prompt, body.content_sources, preset_id=body.preset_id)


@studio_router.post("/break-scenes")
async def break_scenes(body: BreakScenesRequest):
    from app.sse.studio_service import break_into_scenes
    return await break_into_scenes(body.script)


@studio_router.post("/generate-image")
async def generate_image(body: GenerateImageRequest, request: Request):
    from app.sse.studio_service import generate_scene_image, _patch_project_manifest_image
    redis = _get_redis(request)
    try:
        url = await generate_scene_image(
            body.description,
            body.project_id,
            body.scene_num,
            redis=redis,
            characters=body.characters,
            source_image_url=body.source_image_url,
            panel_visual_theme=body.panel_visual_theme,
        )
    except RuntimeError as e:
        raise HTTPException(status_code=422, detail=str(e))
    db_pool = getattr(request.app.state, "db_pool", None)
    if db_pool:
        await _patch_project_manifest_image(body.project_id, body.scene_num, url, db_pool)
    return {"r2_url": url}


@studio_router.post("/generate-video")
async def generate_video(body: GenerateVideoRequest, request: Request, background_tasks: BackgroundTasks):
    from app.sse.studio_service import generate_scene_video, _patch_video_manifest
    redis = _get_redis(request)

    async def _run():
        try:
            print(f"[STUDIO] Background video gen starting: scene {body.scene_num}", flush=True)
            url = await generate_scene_video(body.image_url, body.motion_prompt, body.project_id, body.scene_num, redis=redis)
            print(f"[STUDIO] Background video gen complete: scene {body.scene_num} → {url}", flush=True)
            await _patch_video_manifest(body.project_id, body.scene_num, url)
        except Exception as e:
            import traceback
            print(f"[STUDIO] Background video gen FAILED scene {body.scene_num}: {e}", flush=True)
            traceback.print_exc()

    background_tasks.add_task(_run)
    return {"status": "started", "scene_num": body.scene_num,
            "message": "Video generation started — poll project manifest for completion"}


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


@studio_router.post("/presets")
async def create_preset(body: CreatePresetRequest):
    """Create or update an imagery/story subset generator (JSON preset)."""
    from app.sse.studio_service import create_or_update_preset
    try:
        return create_or_update_preset(body.model_dump(exclude_none=True))
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        logger.exception("create_preset failed")
        raise HTTPException(status_code=500, detail=str(e)[:300])


@studio_router.get("/projects/{project_id}/trained-loras")
async def project_trained_loras(project_id: str):
    from app.sse.studio_service import get_trained_loras_for_project
    loras = await get_trained_loras_for_project(project_id)
    return {"project_id": project_id, "trained_loras": loras, "characters": list(loras.keys())}


@studio_router.post("/projects")
async def create_project(body: CreateProjectRequest, request: Request):
    from app.sse.studio_service import create_project as _create
    db = _get_db(request)
    if not db:
        raise HTTPException(503, "Database unavailable")
    return await _create(body.title, body.scenes, db, preset_id=body.preset_id)


@studio_router.get("/projects")
async def list_projects(request: Request):
    from app.sse.studio_service import list_projects as _list
    db = _get_db(request)
    if not db:
        raise HTTPException(503, "Database unavailable")
    return await _list(db)


@studio_router.get("/projects/{project_id}")
async def get_project(project_id: str, request: Request, hydrate: bool = False):
    db = _get_db(request)
    if not db:
        raise HTTPException(503, "Database unavailable")
    if hydrate:
        from app.sse.studio_service import get_project_hydrated as _get
    else:
        from app.sse.studio_service import get_project as _get
    proj = await _get(project_id, db)
    if not proj:
        raise HTTPException(404, "Project not found")
    return proj


@studio_router.put("/projects/{project_id}")
async def update_project_endpoint(project_id: str, request: Request):
    from app.sse.studio_service import update_project as _update, get_project as _get
    db = _get_db(request)
    if not db:
        raise HTTPException(503, "Database unavailable")
    proj = await _get(project_id, db)
    if not proj:
        raise HTTPException(404, "Project not found")
    body = await request.json()
    manifest = body.get("manifest")
    status = body.get("status")
    cost = body.get("actual_cost_cents")
    await _update(project_id, manifest, status, cost, db)
    return {"status": "updated", "project_id": project_id}


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
               "color_preset": body.color_preset,
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


@studio_router.delete("/projects/{project_id}/clips/{clip_index}")
async def delete_clip(project_id: str, clip_index: int):
    from app.sse.trailer_generator import delete_video_clip
    return await delete_video_clip(project_id, clip_index)


@studio_router.post("/projects/{project_id}/deduplicate-clips")
async def deduplicate_clips(project_id: str):
    from app.sse.trailer_generator import deduplicate_video_manifest
    return await deduplicate_video_manifest(project_id)


# ── Phase 2: LoRA Character Lock ──────────────────────────────────────────

class LoraTrainRequest(BaseModel):
    character_key: str
    training_images_zip_url: str

class LoraGenerateRequest(BaseModel):
    prompt: str
    lora_urls: list[str]
    width: int = 1024
    height: int = 576

class LoraTrainingImagesRequest(BaseModel):
    character_key: str
    project_id: str
    preset_id: str | None = None

class VoiceOverrideRequest(BaseModel):
    project_id: str
    character: str
    voice: str
    instructions: str | None = None

class CongruentClipsRequest(BaseModel):
    project_id: str
    mode: str = "interpolated"
    resume_from: int | None = None

class InterpolatedTrailerRequest(BaseModel):
    project_id: str
    resume_from: int | None = None


@studio_router.post("/lora/train")
async def lora_train(body: LoraTrainRequest):
    from app.sse.studio_service import start_lora_training
    try:
        return await start_lora_training(body.character_key, body.training_images_zip_url)
    except RuntimeError as e:
        raise HTTPException(status_code=422, detail=str(e))


@studio_router.get("/lora/status/{training_id}")
async def lora_status(request: Request, training_id: str, project_id: str | None = None, character_key: str | None = None):
    from app.sse.studio_service import poll_lora_training
    _db = getattr(request.app.state, "db_pool", None)
    try:
        return await poll_lora_training(training_id, project_id=project_id, character_key=character_key, db_pool=_db)
    except RuntimeError as e:
        raise HTTPException(status_code=422, detail=str(e))


@studio_router.post("/lora/generate")
async def lora_generate(body: LoraGenerateRequest):
    from app.sse.studio_service import generate_with_lora
    try:
        urls = await generate_with_lora(body.prompt, body.lora_urls, body.width, body.height)
        return {"images": urls}
    except RuntimeError as e:
        raise HTTPException(status_code=422, detail=str(e))


@studio_router.post("/lora/training-images")
async def lora_training_images(body: LoraTrainingImagesRequest, request: Request, background_tasks: BackgroundTasks):
    from app.sse.studio_service import generate_lora_training_images
    redis = _get_redis(request)
    db = _get_db(request)
    background_tasks.add_task(
        generate_lora_training_images,
        body.character_key,
        body.project_id,
        redis,
        db,
        body.preset_id,
    )
    return {"status": "started", "character": body.character_key,
            "message": "Generating 20 training images — ~2 minutes"}


@studio_router.post("/lora/zip-training-images")
async def lora_zip_images(body: LoraTrainingImagesRequest):
    from app.sse.trailer_generator import zip_lora_training_images
    url = await zip_lora_training_images(body.project_id, body.character_key)
    if not url:
        raise HTTPException(404, "No training images found for this character")
    return {"zip_url": url, "character": body.character_key}


@studio_router.post("/lora/test")
async def lora_test(body: LoraGenerateRequest):
    from app.sse.studio_service import generate_with_lora
    try:
        urls = await generate_with_lora(body.prompt, body.lora_urls, body.width, body.height)
        return {"test_images": urls, "count": len(urls)}
    except RuntimeError as e:
        raise HTTPException(status_code=422, detail=str(e))


# ── Phase 2: Voice Mapping ────────────────────────────────────────────────

@studio_router.get("/voice-config/{project_id}")
async def voice_config(project_id: str):
    from app.sse.trailer_generator import get_voice_config, AVAILABLE_TTS_VOICES
    cfg = await get_voice_config(project_id)
    return {"voices": cfg, "available_voices": AVAILABLE_TTS_VOICES}


@studio_router.post("/voice-config")
async def set_voice(body: VoiceOverrideRequest):
    from app.sse.trailer_generator import set_voice_override, AVAILABLE_TTS_VOICES
    if body.voice not in AVAILABLE_TTS_VOICES:
        raise HTTPException(422, f"Invalid voice. Choose from: {AVAILABLE_TTS_VOICES}")
    result = await set_voice_override(body.project_id, body.character, body.voice, body.instructions)
    return {"character": body.character, "override": result}


@studio_router.get("/color-presets")
async def list_color_presets():
    from app.sse.trailer_generator import COLOR_GRADE_PRESETS
    return {"presets": list(COLOR_GRADE_PRESETS.keys()), "default": "ghibli_warm"}


@studio_router.get("/cost-estimate/{project_id}")
async def cost_estimate(project_id: str, mode: str = "interpolated"):
    from app.sse.studio_service import estimate_pipeline_cost
    return await estimate_pipeline_cost(project_id, mode)


# ── Phase 2: Congruent Generation ─────────────────────────────────────────

@studio_router.post("/generate-congruent-clips")
async def generate_congruent_clips(body: CongruentClipsRequest, request: Request, background_tasks: BackgroundTasks):
    from app.sse.studio_service import generate_congruent_clips as _gen
    db = _get_db(request)
    redis = _get_redis(request)
    if not db:
        raise HTTPException(503, "Database unavailable")

    async def _run():
        try:
            print(f"[STUDIO] Congruent {body.mode} starting: {body.project_id}", flush=True)
            result = await _gen(body.project_id, body.mode, db, redis, body.resume_from)
            ok = result.get("success", 0) if isinstance(result, dict) else 0
            print(f"[STUDIO] Congruent {body.mode} complete: {ok} clips", flush=True)
        except Exception as e:
            import traceback
            print(f"[STUDIO] Congruent {body.mode} FAILED: {e}", flush=True)
            traceback.print_exc()

    background_tasks.add_task(_run)
    cost_estimate = "$72.00" if body.mode == "interpolated" else "$76.00"
    return {"status": "started", "project_id": body.project_id, "mode": body.mode,
            "estimated_cost": cost_estimate,
            "message": f"Generating {body.mode} trailer — this takes several minutes"}


@studio_router.post("/generate-interpolated-trailer")
async def generate_interpolated_trailer(body: InterpolatedTrailerRequest, request: Request, background_tasks: BackgroundTasks):
    from app.sse.studio_service import generate_interpolated
    db = _get_db(request)
    redis = _get_redis(request)
    if not db:
        raise HTTPException(503, "Database unavailable")

    async def _run():
        try:
            print(f"[STUDIO] Interpolated trailer starting: {body.project_id}", flush=True)
            result = await generate_interpolated(body.project_id, db, redis, body.resume_from)
            ok = result.get("success", 0) if isinstance(result, dict) else len(result)
            print(f"[STUDIO] Interpolated trailer complete: {ok} clips", flush=True)
        except Exception as e:
            import traceback
            print(f"[STUDIO] Interpolated trailer FAILED: {e}", flush=True)
            traceback.print_exc()

    background_tasks.add_task(_run)
    return {"status": "started", "project_id": body.project_id, "mode": "interpolated",
            "estimated_cost": "$72.00", "clips": 18,
            "message": "Generating interpolated trailer (start→end frame) — best quality mode"}


@studio_router.post("/resume-generation")
async def resume_generation(body: CongruentClipsRequest, request: Request, background_tasks: BackgroundTasks):
    from app.sse.studio_service import generate_congruent_clips as _gen
    db = _get_db(request)
    redis = _get_redis(request)
    if not db:
        raise HTTPException(503, "Database unavailable")
    if body.resume_from is None:
        raise HTTPException(400, "resume_from is required for resume")
    background_tasks.add_task(_gen, body.project_id, body.mode, db, redis, body.resume_from)
    return {"status": "resuming", "project_id": body.project_id, "mode": body.mode,
            "resume_from": body.resume_from}


class BranchApprovalRequest(BaseModel):
    project_id: str
    action: str = "approve"


@studio_router.post("/approve-branch")
async def approve_branch(body: BranchApprovalRequest, request: Request, background_tasks: BackgroundTasks):
    from app.sse.trailer_generator import approve_branch_point
    from app.sse.studio_service import generate_congruent_clips as _gen
    result = await approve_branch_point(body.project_id, body.action)
    if result.get("status") == "approved":
        db = _get_db(request)
        redis = _get_redis(request)
        background_tasks.add_task(_gen, body.project_id, "chain", db, redis, result["resuming_from"])
        result["message"] = f"Approved — resuming chain from scene {result['resuming_from']}"
    return result


@studio_router.get("/chain-state/{project_id}")
async def get_chain_state(project_id: str):
    from app.sse.trailer_generator import _load_manifest_from_r2
    manifest = await _load_manifest_from_r2(project_id)
    if not manifest:
        raise HTTPException(404, "Project not found")
    return manifest.get("chain_state", {})


# ── Journey Recap (client video → 30s Thera-World stitch) ─────────────────

@studio_router.post("/journey-recap/ingest")
async def studio_journey_recap_ingest(
    request: Request,
    background_tasks: BackgroundTasks,
    user_id: str = Form(...),
    file: UploadFile = File(...),
    ingest_mode: str = Form("audio_driven"),
):
    from app.sse import journey_recap_video as recap

    if not recap.feature_enabled():
        raise HTTPException(
            503,
            detail=f"Journey recap disabled — set {recap.FEATURE_FLAG}=true",
        )
    db = _get_db(request)
    if not db:
        raise HTTPException(503, "Database unavailable")
    if not user_id.strip():
        raise HTTPException(400, "user_id required")

    data = await file.read()
    if len(data) < 5000:
        raise HTTPException(400, "Video file too small")

    mode = recap.normalize_ingest_mode(ingest_mode)
    try:
        result = await recap.enqueue_studio_video_ingest(
            db,
            user_id=user_id.strip(),
            video_bytes=data,
            filename=file.filename or "upload.mp4",
            ingest_mode=mode,
        )
    except RuntimeError as e:
        raise HTTPException(400, detail=str(e)) from e
    except ValueError as e:
        raise HTTPException(404, detail=str(e)) from e

    job_id = result["job_id"]
    background_tasks.add_task(
        recap.run_studio_video_ingest_task,
        db,
        job_id=job_id,
        ingest_mode=mode,
        filename=file.filename or "upload.mp4",
    )
    return result


@studio_router.post("/journey-recap/ingest-transcript")
async def studio_journey_recap_ingest_transcript(
    body: JourneyRecapTranscriptRequest,
    request: Request,
    background_tasks: BackgroundTasks,
):
    from app.sse import journey_recap_video as recap

    if not recap.feature_enabled():
        raise HTTPException(
            503,
            detail=f"Journey recap disabled — set {recap.FEATURE_FLAG}=true",
        )
    db = _get_db(request)
    if not db:
        raise HTTPException(503, "Database unavailable")
    if not body.user_id.strip():
        raise HTTPException(400, "user_id required")
    text = (body.transcript_text or "").strip()
    if len(text) < 20:
        raise HTTPException(400, "transcript_text must be at least 20 characters")

    mode = recap.normalize_ingest_mode(body.ingest_mode)
    try:
        result = await recap.ingest_studio_transcript(
            db,
            user_id=body.user_id.strip(),
            transcript=text,
            ingest_mode=mode,
            source_duration_seconds=body.source_duration_seconds,
        )
    except RuntimeError as e:
        raise HTTPException(400, detail=str(e)) from e
    except ValueError as e:
        raise HTTPException(404, detail=str(e)) from e

    if mode == recap.INGEST_MODE_AUDIO and result.get("job_id") and result.get("async_pipeline"):
        background_tasks.add_task(recap.run_trailer_auto_pipeline, db, str(result["job_id"]))
    return result


@studio_router.post("/journey-recap/{job_id}/render-segment/{segment_index}")
async def studio_journey_recap_render_segment(
    job_id: str, segment_index: int, request: Request,
):
    from app.sse import journey_recap_video as recap

    if not recap.feature_enabled():
        raise HTTPException(503, detail="Journey recap disabled")
    db = _get_db(request)
    if not db:
        raise HTTPException(503, "Database unavailable")
    try:
        meta = await recap.render_recap_segment(db, job_id, segment_index)
    except ValueError as e:
        raise HTTPException(404, detail=str(e)) from e
    except RuntimeError as e:
        raise HTTPException(400, detail=str(e)) from e
    return {"segment": meta}


@studio_router.post("/journey-recap/{job_id}/render-all")
async def studio_journey_recap_render_all(
    job_id: str, request: Request, background_tasks: BackgroundTasks,
):
    from app.sse import journey_recap_video as recap

    if not recap.feature_enabled():
        raise HTTPException(503, detail="Journey recap disabled")
    db = _get_db(request)
    if not db:
        raise HTTPException(503, "Database unavailable")

    async def _run():
        try:
            await recap.render_all_recap_segments(db, job_id)
        except Exception as e:
            logger.warning("[STUDIO-RECAP] render-all failed job=%s: %s", job_id, e)

    background_tasks.add_task(_run)
    return {"job_id": job_id, "status": "rendering"}


@studio_router.post("/journey-recap/{job_id}/stitch")
async def studio_journey_recap_stitch(job_id: str, request: Request):
    from app.sse import journey_recap_video as recap

    if not recap.feature_enabled():
        raise HTTPException(503, detail="Journey recap disabled")
    db = _get_db(request)
    if not db:
        raise HTTPException(503, "Database unavailable")
    try:
        result = await recap.stitch_recap_job_only(db, job_id)
    except ValueError as e:
        raise HTTPException(404, detail=str(e)) from e
    except RuntimeError as e:
        raise HTTPException(400, detail=str(e)) from e
    return result


@studio_router.get("/journey-recap/{job_id}")
async def studio_journey_recap_status(job_id: str, request: Request):
    from app.sse import journey_recap_video as recap

    db = _get_db(request)
    if not db:
        raise HTTPException(503, "Database unavailable")
    async with db.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM sse_journey_recap_jobs WHERE job_id = $1::uuid",
            uuid.UUID(job_id),
        )
    if not row:
        raise HTTPException(404, "Job not found")
    job = _serialize_recap_job_row(dict(row))
    payload: dict[str, Any] = {"job": job, "enabled": recap.feature_enabled()}
    studio = recap.build_studio_result_from_job(dict(row))
    if studio:
        payload["studio"] = studio
    return payload
