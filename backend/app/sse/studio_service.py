"""Thera-World Studio — service layer for script gen, scene gen, library, projects, cost tracking."""
from __future__ import annotations

import asyncio
import json
import logging
import os
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

import aiohttp

logger = logging.getLogger(__name__)
logger.info("Studio R2 bucket: %s", os.getenv("R2_BUCKET_NAME", "nate-vault"))

_PRESETS_DIR = Path(__file__).parent / "data" / "studio_presets"
_STORY_PLOTS_DIR = Path(__file__).parent / "data" / "story_plots"
_WORKBOOK_META = Path(__file__).parent.parent.parent / "resources" / "therapeutic_library" / "protocol_workbooks" / "metadata.json"
_CORE_CHAR_MD = Path(__file__).parent.parent.parent / "resources" / "therapeutic_library" / "core_character" / "core_character_foundation.md"

_WORKERS_AI_URL = os.getenv("WORKERS_AI_URL", "")
_WORKERS_AI_TOKEN = os.getenv("WORKERS_AI_TOKEN", "")
_WORKERS_AI_MODEL = os.getenv("WORKERS_AI_MODEL", "@cf/meta/llama-3.1-8b-instruct")

_AZURE_ENDPOINT = os.getenv("AZURE_OPENAI_ENDPOINT", "")
_AZURE_API_KEY = os.getenv("AZURE_API_KEY", "")
_AZURE_TTS_DEPLOYMENT = os.getenv("AZURE_OPENAI_MINI_TTS_DEPLOYMENT", "gpt-4o-mini-tts")

_COST_REDIS_KEY = "sse:studio:daily_cost"
_COST_CAP_CENTS = int(os.getenv("SSE_STUDIO_DAILY_CAP_CENTS", "2500"))

COST_PER_IMAGE_CENTS = 7
COST_PER_VIDEO_CENTS = 25
COST_PER_NARRATION_CENTS = 1


# ---------------------------------------------------------------------------
#  Content Sources
# ---------------------------------------------------------------------------

def get_content_sources() -> dict:
    """Aggregate all SSE content sources for the Studio script editor."""
    plots = []
    for p in sorted(_STORY_PLOTS_DIR.glob("*.json")):
        if p.name == "metadata.json":
            continue
        try:
            data = json.loads(p.read_text())
            plots.append({"id": p.stem, "title": data.get("title", p.stem),
                          "description": data.get("description", "")[:300]})
        except Exception:
            pass

    archetypes = ["warrior", "sage", "healer", "guardian", "explorer", "seraph"]

    biomes = []
    try:
        from app.sse.thera_world_engine import BIOME_THRESHOLDS
        biomes = [{"id": b["biome"], "description": b.get("description", "")} for b in BIOME_THRESHOLDS]
    except Exception:
        biomes = [
            {"id": "dark_forest", "description": "Dense fog, lantern light, shadows, isolation"},
            {"id": "fortress_plains", "description": "Open plains with towers and fortresses"},
            {"id": "river_valley", "description": "Gentle valley with a crystal river, healing trees"},
            {"id": "crystal_mountains", "description": "Mountains that glow from within, caves of crystals"},
            {"id": "open_sky", "description": "Boundless sky, integration and wholeness achieved"},
        ]

    workbooks = []
    if _WORKBOOK_META.exists():
        try:
            wm = json.loads(_WORKBOOK_META.read_text())
            for wb in wm.get("workbooks", []):
                workbooks.append({"id": wb["id"], "name": wb["protocol_name"], "theorist": wb.get("theorist", "")})
        except Exception:
            pass

    core_character = ""
    if _CORE_CHAR_MD.exists():
        try:
            core_character = _CORE_CHAR_MD.read_text()[:500]
        except Exception:
            pass

    npcs = []
    try:
        from app.sse.quest_mission_engine import TEMPLATE_NPCS
        npcs = [{"id": k, "name": v.get("name", k), "description": v.get("description", "")} for k, v in TEMPLATE_NPCS.items()]
    except Exception:
        pass

    return {"plots": plots, "archetypes": archetypes, "biomes": biomes,
            "workbooks": workbooks, "core_character": core_character, "npcs": npcs}


# ---------------------------------------------------------------------------
#  Workers AI helpers
# ---------------------------------------------------------------------------

async def _call_workers_ai(system: str, user: str) -> str:
    """Call Cloudflare Workers AI. Returns raw text response."""
    if not _WORKERS_AI_URL:
        raise RuntimeError("WORKERS_AI_URL not configured")
    headers: dict[str, str] = {"Content-Type": "application/json"}
    if _WORKERS_AI_TOKEN:
        headers["Authorization"] = f"Bearer {_WORKERS_AI_TOKEN}"
    payload = {"model": _WORKERS_AI_MODEL,
               "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
               "max_tokens": 2048, "temperature": 0.7}
    async with aiohttp.ClientSession() as sess:
        async with sess.post(_WORKERS_AI_URL, json=payload, headers=headers, timeout=aiohttp.ClientTimeout(total=60)) as resp:
            if resp.status != 200:
                body = await resp.text()
                raise RuntimeError(f"Workers AI {resp.status}: {body[:300]}")
            data = await resp.json()
    result = data.get("result", data)
    if isinstance(result, dict):
        return result.get("response", "") or (result.get("choices", [{}])[0].get("message", {}).get("content", ""))
    return str(result)


async def generate_script(prompt: str, content_sources: list[str] | None = None) -> dict:
    """Use Workers AI to compose a script from a prompt + selected SSE content."""
    context_parts: list[str] = []
    if content_sources:
        sources = get_content_sources()
        if "plots" in content_sources and sources["plots"]:
            context_parts.append("STORY PLOTS:\n" + "\n".join(f"- {p['title']}: {p['description']}" for p in sources["plots"]))
        if "characters" in content_sources and sources["archetypes"]:
            context_parts.append("CHARACTER ARCHETYPES: " + ", ".join(sources["archetypes"]))
        if "biomes" in content_sources and sources["biomes"]:
            context_parts.append("BIOMES:\n" + "\n".join(f"- {b['id']}: {b['description']}" for b in sources["biomes"]))
        if "workbooks" in content_sources and sources["workbooks"]:
            context_parts.append("THERAPEUTIC PROTOCOLS:\n" + "\n".join(f"- {w['name']} ({w['theorist']})" for w in sources["workbooks"]))
        if "npcs" in content_sources and sources["npcs"]:
            context_parts.append("NPC TEMPLATES:\n" + "\n".join(f"- {n['name']}: {n['description']}" for n in sources["npcs"]))

    system = (
        "You are a cinematic script writer for Thera-World, a therapeutic fantasy universe.\n"
        "Write vivid, cinematic scene descriptions suitable for AI image/video generation.\n"
        "Return ONLY valid JSON: {\"scenes\": [{\"scene\": 1, \"title\": \"snake_case\", "
        "\"description\": \"visual description for image gen\", \"dialogue\": \"optional narration\", "
        "\"duration\": 5, \"mood\": \"one word\"}]}\n"
        "Keep descriptions visual and detailed — they will be used as image generation prompts.\n\n"
        + ("\n\n".join(context_parts) if context_parts else "")
    )
    raw = await _call_workers_ai(system, prompt)
    try:
        start = raw.find("{")
        end = raw.rfind("}") + 1
        if start >= 0 and end > start:
            return json.loads(raw[start:end])
    except json.JSONDecodeError:
        pass
    return {"scenes": [], "raw": raw}


async def break_into_scenes(script_text: str) -> dict:
    """Break freeform script text into structured scenes."""
    system = (
        "You are a cinematic editor. Break the following script into individual scenes.\n"
        "Return ONLY valid JSON: {\"scenes\": [{\"scene\": 1, \"title\": \"snake_case\", "
        "\"description\": \"visual description for image gen\", \"dialogue\": \"narration text\", "
        "\"duration\": 5, \"mood\": \"one word\"}]}\n"
        "Each scene should be 3-10 seconds. Descriptions must be vivid enough for AI image generation."
    )
    raw = await _call_workers_ai(system, script_text)
    try:
        start = raw.find("{")
        end = raw.rfind("}") + 1
        if start >= 0 and end > start:
            return json.loads(raw[start:end])
    except json.JSONDecodeError:
        pass
    return {"scenes": [], "raw": raw}


# ---------------------------------------------------------------------------
#  Image / Video / Narration generation
# ---------------------------------------------------------------------------

async def generate_scene_image(description: str, project_id: str, scene_num: int, redis=None) -> str:
    """Generate image via Grok Imagine and upload to R2. Returns R2 URL."""
    await _check_cost_budget(COST_PER_IMAGE_CENTS, redis)

    from app.sse.infrastructure.grok_imagine_client import generate_image, GROK_IMAGINE_LOCK
    from app.sse.infrastructure.r2_storage import store_image

    async with GROK_IMAGINE_LOCK:
        image_bytes = await generate_image(description)
    r2_key = f"sse/studio/projects/{project_id}/{scene_num}.png"
    r2_url = await store_image(image_bytes, r2_key)
    await _track_cost(COST_PER_IMAGE_CENTS, redis)
    return r2_url


async def generate_scene_video(image_url: str, motion_prompt: str, project_id: str, scene_num: int, redis=None) -> str:
    """Generate video via Grok Video and upload to R2. Returns R2 URL."""
    await _check_cost_budget(COST_PER_VIDEO_CENTS, redis)

    from app.sse.infrastructure.grok_imagine_client import generate_video, poll_video_status, GROK_IMAGINE_LOCK
    from app.sse.infrastructure.r2_storage import store_video

    async with GROK_IMAGINE_LOCK:
        video_id = await generate_video(motion_prompt, source_image_url=image_url)

    for _ in range(24):
        await asyncio.sleep(5)
        status = await poll_video_status(video_id)
        if status["status"] == "completed" and status.get("url"):
            r2_key = f"sse/studio/projects/{project_id}/{scene_num}.mp4"
            r2_url = await store_video(status["url"], r2_key)
            await _track_cost(COST_PER_VIDEO_CENTS, redis)
            return r2_url
        if status["status"] == "failed":
            raise RuntimeError("Grok Video generation failed")
    raise RuntimeError("Grok Video timed out after 120s")


async def generate_narration(text: str, voice: str, project_id: str, scene_num: int, redis=None) -> str:
    """Generate narration audio via Azure Mini TTS and upload to R2."""
    await _check_cost_budget(COST_PER_NARRATION_CENTS, redis)

    if not _AZURE_ENDPOINT or not _AZURE_API_KEY:
        raise RuntimeError("Azure TTS not configured")

    voice_map = {
        "serpent": {"voice": "onyx", "instructions": "Speak in a deep, slow, reverberant tone. Ancient and knowing."},
        "boy": {"voice": "echo", "instructions": "Speak as a young child, curious and bright."},
        "girl": {"voice": "shimmer", "instructions": "Speak as a bright, cheerful young girl."},
        "narrator": {"voice": "onyx", "instructions": "Speak as a calm cinematic narrator."},
    }
    cfg = voice_map.get(voice, voice_map["narrator"])

    url = f"https://{_AZURE_ENDPOINT}/openai/deployments/{_AZURE_TTS_DEPLOYMENT}/audio/speech?api-version=2024-12-17"
    payload = {"model": _AZURE_TTS_DEPLOYMENT, "input": text, "voice": cfg["voice"],
               "instructions": cfg["instructions"], "response_format": "mp3"}
    headers = {"api-key": _AZURE_API_KEY, "Content-Type": "application/json"}

    async with aiohttp.ClientSession() as sess:
        async with sess.post(url, json=payload, headers=headers, timeout=aiohttp.ClientTimeout(total=30)) as resp:
            if resp.status != 200:
                body = await resp.text()
                raise RuntimeError(f"Azure TTS {resp.status}: {body[:200]}")
            audio_bytes = await resp.read()

    from app.sse.infrastructure.r2_storage import store_image as _store_bytes
    r2_key = f"sse/studio/projects/{project_id}/{scene_num}.mp3"

    from app.sse.infrastructure import r2_storage as _r2
    client = _r2._get_client()
    if client is None:
        logger.warning("R2 not configured — skipping narration upload")
        await _track_cost(COST_PER_NARRATION_CENTS, redis)
        return f"mock://r2-not-configured/{r2_key}"

    def _upload():
        client.put_object(Bucket=_r2._R2_BUCKET, Key=r2_key, Body=audio_bytes, ContentType="audio/mpeg")

    await asyncio.get_event_loop().run_in_executor(None, _upload)
    await _track_cost(COST_PER_NARRATION_CENTS, redis)
    return f"{_r2._R2_PUBLIC_BASE}/{r2_key}"


# ---------------------------------------------------------------------------
#  Library (R2 content browser)
# ---------------------------------------------------------------------------

async def list_library(filter_type: str = "all") -> list[dict]:
    """List all media stored under sse/trailer/ and sse/studio/ prefixes."""
    from app.sse.infrastructure import r2_storage as _r2
    client = _r2._get_client()
    if client is None:
        return []

    items: list[dict] = []
    for prefix in ("sse/trailer/", "sse/studio/"):
        try:
            paginator = client.get_paginator("list_objects_v2")
            for page in paginator.paginate(Bucket=_r2._R2_BUCKET, Prefix=prefix):
                for obj in page.get("Contents", []):
                    key = obj["Key"]
                    ext = key.rsplit(".", 1)[-1].lower() if "." in key else ""
                    media_type = {"png": "image", "jpg": "image", "jpeg": "image", "webp": "image",
                                  "mp4": "video", "webm": "video", "mov": "video",
                                  "mp3": "audio", "wav": "audio", "json": "data"}.get(ext, "other")
                    if filter_type != "all" and media_type != filter_type:
                        continue
                    items.append({
                        "key": key,
                        "url": f"{_r2._R2_PUBLIC_BASE}/{key}",
                        "size_bytes": obj.get("Size", 0),
                        "last_modified": obj["LastModified"].isoformat() if obj.get("LastModified") else None,
                        "type": media_type,
                    })
        except Exception as e:
            logger.warning("list_library prefix=%s failed: %s", prefix, e)

    items.sort(key=lambda x: x.get("last_modified") or "", reverse=True)
    return items


async def delete_library_object(r2_key: str) -> bool:
    """Delete a single object from R2."""
    if not r2_key.startswith("sse/"):
        raise ValueError("Can only delete objects under sse/ prefix")
    from app.sse.infrastructure import r2_storage as _r2
    client = _r2._get_client()
    if client is None:
        return False

    def _delete():
        client.delete_object(Bucket=_r2._R2_BUCKET, Key=r2_key)

    await asyncio.get_event_loop().run_in_executor(None, _delete)
    return True


# ---------------------------------------------------------------------------
#  Presets
# ---------------------------------------------------------------------------

def list_presets() -> list[dict]:
    """List available scene presets."""
    presets: list[dict] = []
    if not _PRESETS_DIR.exists():
        return presets
    for p in sorted(_PRESETS_DIR.glob("*.json")):
        try:
            data = json.loads(p.read_text())
            presets.append({"id": data.get("id", p.stem), "title": data.get("title", p.stem),
                            "scene_count": len(data.get("scenes", []))})
        except Exception:
            pass
    return presets


def get_preset(name: str) -> dict:
    """Load a preset by name."""
    path = _PRESETS_DIR / f"{name}.json"
    if not path.exists():
        raise FileNotFoundError(f"Preset '{name}' not found")
    return json.loads(path.read_text())


# ---------------------------------------------------------------------------
#  Project CRUD (PostgreSQL)
# ---------------------------------------------------------------------------

async def create_project(title: str, scenes: list[dict], db_pool) -> dict:
    """Create a new studio project."""
    project_id = str(uuid.uuid4())
    estimated_cost = len(scenes) * (COST_PER_IMAGE_CENTS + COST_PER_VIDEO_CENTS + COST_PER_NARRATION_CENTS)
    async with db_pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO sse_studio_projects (project_id, title, scene_count, status, manifest, estimated_cost_cents) "
            "VALUES ($1, $2, $3, 'draft', $4::jsonb, $5)",
            project_id, title, len(scenes), json.dumps({"scenes": scenes}), estimated_cost)
    return {"project_id": project_id, "title": title, "scene_count": len(scenes),
            "estimated_cost_cents": estimated_cost}


async def update_project(project_id: str, manifest: dict, status: str | None, actual_cost_cents: int | None, db_pool) -> None:
    """Update project manifest and/or status."""
    parts = ["updated_at = now()"]
    args: list[Any] = []
    idx = 1
    if manifest is not None:
        parts.append(f"manifest = ${idx}::jsonb")
        args.append(json.dumps(manifest))
        idx += 1
    if status is not None:
        parts.append(f"status = ${idx}")
        args.append(status)
        idx += 1
    if actual_cost_cents is not None:
        parts.append(f"actual_cost_cents = ${idx}")
        args.append(actual_cost_cents)
        idx += 1
    parts_sql = ", ".join(parts)
    args.append(project_id)
    async with db_pool.acquire() as conn:
        await conn.execute(f"UPDATE sse_studio_projects SET {parts_sql} WHERE project_id = ${idx}", *args)


async def get_project(project_id: str, db_pool) -> dict | None:
    """Get a single project by ID."""
    async with db_pool.acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM sse_studio_projects WHERE project_id = $1", project_id)
    if not row:
        return None
    return _row_to_dict(row)


async def list_projects(db_pool) -> list[dict]:
    """List all studio projects."""
    async with db_pool.acquire() as conn:
        rows = await conn.fetch("SELECT * FROM sse_studio_projects ORDER BY created_at DESC LIMIT 50")
    return [_row_to_dict(r) for r in rows]


def _row_to_dict(row) -> dict:
    d = dict(row)
    for k in ("created_at", "updated_at"):
        if d.get(k):
            d[k] = d[k].isoformat()
    if isinstance(d.get("manifest"), str):
        try:
            d["manifest"] = json.loads(d["manifest"])
        except Exception:
            pass
    if isinstance(d.get("project_id"), uuid.UUID):
        d["project_id"] = str(d["project_id"])
    return d


# ---------------------------------------------------------------------------
#  Clean Project (R2 orphan cleanup — Option E)
# ---------------------------------------------------------------------------

async def clean_project(project_id: str, db_pool) -> int:
    """Delete R2 objects for a project and mark it as cleaned."""
    proj = await get_project(project_id, db_pool)
    if not proj:
        raise ValueError("Project not found")

    manifest = proj.get("manifest", {})
    if isinstance(manifest, str):
        manifest = json.loads(manifest)
    scenes = manifest.get("scenes", [])

    deleted = 0
    for scene in scenes:
        for field in ("r2_url", "image_url", "video_url", "audio_url"):
            url = scene.get(field)
            if not url or "mock://" in url:
                continue
            key = url.split("/", 3)[-1] if url.startswith("http") else url
            if key.startswith("sse/"):
                try:
                    await delete_library_object(key)
                    deleted += 1
                except Exception as e:
                    logger.warning("clean_project: failed to delete %s: %s", key, e)

    await update_project(project_id, None, "cleaned", None, db_pool)
    return deleted


# ---------------------------------------------------------------------------
#  Redis Cost Tracking (Option D)
# ---------------------------------------------------------------------------

async def _check_cost_budget(cost_cents: int, redis=None) -> None:
    """Check if daily cost cap would be exceeded. Raises 429 if so."""
    if redis is None:
        return
    try:
        current = await redis.get(_COST_REDIS_KEY)
        current_cents = int(current) if current else 0
        if current_cents + cost_cents > _COST_CAP_CENTS:
            from fastapi import HTTPException
            raise HTTPException(
                status_code=429,
                detail=f"Daily studio generation limit reached (${_COST_CAP_CENTS / 100:.2f}). Spent: ${current_cents / 100:.2f}",
            )
    except ImportError:
        raise
    except Exception as e:
        if "429" in str(type(e).__name__) or "HTTPException" in str(type(e).__name__):
            raise
        logger.warning("Cost budget check failed (allowing): %s", e)


async def _track_cost(cost_cents: int, redis=None) -> None:
    """Increment the daily cost counter in Redis."""
    if redis is None:
        return
    try:
        pipe = redis.pipeline()
        pipe.incrby(_COST_REDIS_KEY, cost_cents)
        pipe.expire(_COST_REDIS_KEY, 86400)
        await pipe.execute()
    except Exception as e:
        logger.warning("Cost tracking failed: %s", e)


async def get_daily_cost(redis=None) -> dict:
    """Return current daily spending status."""
    spent = 0
    if redis:
        try:
            val = await redis.get(_COST_REDIS_KEY)
            spent = int(val) if val else 0
        except Exception:
            pass
    return {"spent_cents": spent, "cap_cents": _COST_CAP_CENTS,
            "remaining_cents": max(0, _COST_CAP_CENTS - spent)}


# ---------------------------------------------------------------------------
#  Phase 2: Batch Orchestrators (wiring trailer_generator into Studio)
# ---------------------------------------------------------------------------

async def generate_character_refs(project_id: str, redis=None) -> dict:
    """Generate character reference images for a project. Returns ref map."""
    from app.sse.trailer_generator import generate_character_references, CHARACTER_REFERENCES
    num_chars = len(CHARACTER_REFERENCES)
    await _check_cost_budget(COST_PER_IMAGE_CENTS * num_chars, redis)

    refs = await generate_character_references(project_id)
    await _track_cost(COST_PER_IMAGE_CENTS * sum(1 for v in refs.values() if v), redis)
    return refs


async def generate_video_clips(project_id: str, db_pool, redis=None) -> dict:
    """Generate motion video clips for all scenes in a project."""
    from app.sse.trailer_generator import generate_motion_clips
    results = await generate_motion_clips(project_id)
    cost = sum(r.get("cost", 0) for r in results)
    total_cost_cents = int(cost * 100)
    await _track_cost(total_cost_cents, redis)
    if db_pool:
        await update_project(project_id, None, "videos_generated", total_cost_cents, db_pool)
    return {
        "project_id": project_id,
        "clips": results,
        "total": len(results),
        "success": sum(1 for r in results if r.get("status") in ("success", "ken_burns")),
        "total_cost_cents": total_cost_cents,
    }


async def stitch_project_trailer(project_id: str, options: dict, db_pool, redis=None) -> dict:
    """Stitch a congruent trailer for a project."""
    from app.sse.trailer_generator import stitch_trailer
    result = await stitch_trailer(project_id, options)
    if result and db_pool:
        await update_project(project_id, None, "stitched", None, db_pool)
    return result or {"error": "Stitching failed — check logs"}


async def get_video_status(project_id: str) -> dict:
    """Check video generation status from R2 manifest."""
    from app.sse.trailer_generator import _load_manifest_from_r2
    from app.sse.infrastructure import r2_storage as _r2
    client = _r2._get_client()
    if not client:
        return {"status": "r2_unavailable"}

    try:
        def _get():
            return client.get_object(Bucket=_r2._R2_BUCKET,
                                     Key=f"sse/studio/projects/{project_id}/video_manifest.json")
        resp = await asyncio.get_event_loop().run_in_executor(None, _get)
        data = json.loads(resp["Body"].read().decode())
        return data
    except Exception:
        return {"status": "not_started"}


async def get_trailer_status(project_id: str) -> dict:
    """Check overall project status including trailer stitching."""
    manifest = None
    from app.sse.infrastructure import r2_storage as _r2
    client = _r2._get_client()
    if client:
        try:
            def _get():
                return client.get_object(Bucket=_r2._R2_BUCKET,
                                         Key=f"sse/studio/projects/{project_id}/manifest.json")
            resp = await asyncio.get_event_loop().run_in_executor(None, _get)
            manifest = json.loads(resp["Body"].read().decode())
        except Exception:
            pass
    if not manifest:
        return {"status": "not_started"}
    return manifest
