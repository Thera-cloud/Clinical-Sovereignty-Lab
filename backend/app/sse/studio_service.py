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
_WORKERS_AI_MODEL = os.getenv("WORKERS_AI_MODEL", "@cf/meta/llama-3.3-70b-instruct-fp8-fast")

_AZURE_ENDPOINT = os.getenv("AZURE_OPENAI_ENDPOINT", "")
_AZURE_API_KEY = os.getenv("AZURE_API_KEY", "")
_AZURE_TTS_DEPLOYMENT = os.getenv("AZURE_OPENAI_MINI_TTS_DEPLOYMENT", "gpt-4o-mini-tts")

_COST_REDIS_KEY = "sse:studio:daily_cost"
_COST_CAP_CENTS = int(os.getenv("SSE_STUDIO_DAILY_CAP_CENTS", "15000"))

COST_PER_IMAGE_CENTS = 7
COST_PER_VIDEO_CENTS = 400
COST_PER_NARRATION_CENTS = 1

COST_PER_LORA_TRAIN_CENTS = 200

_replicate_available = bool(os.getenv("REPLICATE_API_TOKEN"))
if not _replicate_available:
    logger.warning("[STUDIO] REPLICATE_API_TOKEN not set — LoRA features disabled")


async def estimate_pipeline_cost(project_id: str, mode: str) -> dict:
    """Return a dynamic cost estimate based on project state."""
    from app.sse.trailer_generator import _load_manifest_from_r2, _load_trained_loras
    manifest = await _load_manifest_from_r2(project_id)
    if not manifest:
        return {"error": "Project not found"}

    scenes = [s for s in manifest.get("scenes", []) if s.get("status") == "success"]
    total_scenes = len(scenes)
    chain_state = manifest.get("chain_state", {})
    completed = len(chain_state.get("completed_clips", []))

    remaining = max(total_scenes - completed, 0) if chain_state else total_scenes

    trained_loras = await _load_trained_loras(project_id)
    has_lora = bool(trained_loras)

    if mode == "interpolated":
        video_clips = max(total_scenes - 1, 0) - completed
        lora_regen = total_scenes if has_lora else 0
        video_cost = max(video_clips, 0) * COST_PER_VIDEO_CENTS
        lora_image_cost = lora_regen * COST_PER_IMAGE_CENTS
        narration_cost = total_scenes * COST_PER_NARRATION_CENTS
        total = video_cost + lora_image_cost + narration_cost
    elif mode == "chain":
        video_cost = remaining * COST_PER_VIDEO_CENTS
        narration_cost = total_scenes * COST_PER_NARRATION_CENTS
        total = video_cost + narration_cost
    elif mode == "cel":
        video_cost = remaining * COST_PER_VIDEO_CENTS
        narration_cost = total_scenes * COST_PER_NARRATION_CENTS
        total = video_cost + narration_cost
    else:
        video_cost = remaining * COST_PER_VIDEO_CENTS
        narration_cost = 0
        total = video_cost

    return {
        "mode": mode,
        "total_scenes": total_scenes,
        "remaining_scenes": remaining,
        "completed_scenes": completed,
        "has_lora": has_lora,
        "estimated_cost_cents": total,
        "estimated_cost_usd": f"${total / 100:.2f}",
        "breakdown": {
            "video_generation": f"${video_cost / 100:.2f}",
            "narration": f"${narration_cost / 100:.2f}",
            "lora_regen": f"${(lora_regen * COST_PER_IMAGE_CENTS if mode == 'interpolated' else 0) / 100:.2f}" if mode == "interpolated" and has_lora else None,
        },
        "daily_cap_usd": f"${_COST_CAP_CENTS / 100:.2f}",
    }


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


async def generate_script(
    prompt: str,
    content_sources: list[str] | None = None,
    preset_id: str | None = None,
) -> dict:
    """Use Workers AI to compose a script for the active subset (or open cinematic)."""
    context_parts: list[str] = []
    subset_label = "an open cinematic therapeutic universe"
    style_lock = ""
    cast_lock = ""
    if preset_id:
        try:
            pdata = get_preset(preset_id)
            subset_label = pdata.get("title") or preset_id
            anchor = pdata.get("visual_style_anchor") or {}
            if isinstance(anchor, dict) and anchor.get("look"):
                style_lock = f"\nVISUAL STYLE LOCK (must honor): {anchor.get('look')}\n"
            casting = pdata.get("casting_locksheet") or {}
            if isinstance(casting, dict) and casting:
                cast_lock = "\nCHARACTER CAST (use these keys in descriptions):\n" + "\n".join(
                    f"- {k}: {v if isinstance(v, str) else (v.get('inline_desc') or k)}"
                    for k, v in casting.items()
                ) + "\n"
        except Exception:
            subset_label = preset_id
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
        f"You are a cinematic script writer for the subset generator: {subset_label}.\n"
        "Thera-World is one possible subset — honor THIS subset's style and cast when provided.\n"
        "Write vivid, cinematic scene descriptions suitable for AI image/video generation.\n"
        "Return ONLY valid JSON: {\"scenes\": [{\"scene\": 1, \"title\": \"snake_case\", "
        "\"description\": \"visual description for image gen\", \"dialogue\": \"optional narration\", "
        "\"duration\": 5, \"mood\": \"one word\", \"characters\": [\"key\"]}]}\n"
        "Keep descriptions visual and detailed — they will be used as image generation prompts.\n"
        f"{style_lock}{cast_lock}\n"
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

async def generate_scene_image(
    description: str,
    project_id: str,
    scene_num: int,
    redis=None,
    characters: list[str] | None = None,
    preset_id: str | None = None,
    source_image_url: str | None = None,
    panel_visual_theme: str | None = None,
) -> str:
    """Generate image via LoRA (if trained) or Grok Imagine, upload to R2. Returns R2 URL."""
    await _check_cost_budget(COST_PER_IMAGE_CENTS, redis)

    from app.sse.infrastructure.grok_imagine_client import GROK_IMAGINE_LOCK, generate_image
    from app.sse.infrastructure.r2_storage import store_image
    from app.sse.trailer_generator import (
        _get_style_prefix,
        _generate_image_with_lora_or_grok,
        _load_trained_loras,
        _build_consistent_prompt,
        _load_manifest_from_r2,
        _manifest_preset_id,
    )

    theme = (panel_visual_theme or "").strip()
    source = (source_image_url or "").strip()

    if source:
        prompt_parts = []
        if theme:
            prompt_parts.append(
                f"Preserve exact palette, line weight, and composition of the source panel. {theme}"
            )
        if description:
            prompt_parts.append(description[:400])
        prompt_parts.append("No text overlays, no logos. Match the active subset visual style.")
        gen_prompt = " ".join(prompt_parts)
        async with GROK_IMAGINE_LOCK:
            image_bytes = await generate_image(gen_prompt, source_image_url=source)
    else:
        chars = characters or []
        proj = await _load_manifest_from_r2(project_id) or {}
        pid = preset_id or _manifest_preset_id(proj)
        trained_loras = await _load_trained_loras(project_id)
        prefix = _get_style_prefix(scene_num, pid)
        base_desc = description
        if theme:
            base_desc = f"{theme}. {description}"
        styled_description = (
            _build_consistent_prompt(base_desc, chars, scene_num=scene_num, preset_id=pid)
            if chars else prefix + base_desc
        )
        async with GROK_IMAGINE_LOCK:
            image_bytes = await _generate_image_with_lora_or_grok(
                styled_description, chars, trained_loras,
                scene_num=scene_num, preset_id=pid,
            )
    r2_key = f"sse/studio/projects/{project_id}/{scene_num}.png"
    r2_url = await store_image(image_bytes, r2_key)
    await _track_cost(COST_PER_IMAGE_CENTS, redis)
    return r2_url


async def generate_scene_video(
    image_url: str,
    motion_prompt: str,
    project_id: str,
    scene_num: int,
    redis=None,
    preset_id: str | None = None,
) -> str:
    """Generate video via Grok Video and upload to R2. Returns R2 URL."""
    await _check_cost_budget(COST_PER_VIDEO_CENTS, redis)

    from app.sse.infrastructure.grok_imagine_client import generate_video, poll_video_status, GROK_IMAGINE_LOCK
    from app.sse.infrastructure.r2_storage import store_video
    from app.sse.trailer_generator import (
        _build_video_prompt,
        _load_manifest_from_r2,
        _manifest_preset_id,
    )

    proj = await _load_manifest_from_r2(project_id) or {}
    pid = preset_id or _manifest_preset_id(proj)
    styled_motion = _build_video_prompt(scene_num, motion_prompt, preset_id=pid)
    async with GROK_IMAGINE_LOCK:
        video_id = await generate_video(styled_motion, source_image_url=image_url)

    for _ in range(60):
        await asyncio.sleep(5)
        status = await poll_video_status(video_id)
        if status["status"] == "completed" and status.get("url"):
            r2_key = f"sse/studio/projects/{project_id}/{scene_num}.mp4"
            r2_url = await store_video(status["url"], r2_key)
            await _track_cost(COST_PER_VIDEO_CENTS, redis)
            return r2_url
        if status["status"] == "failed":
            raise RuntimeError("Grok Video generation failed")
    raise RuntimeError("Grok Video timed out after 300s")


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

    url = f"https://{_AZURE_ENDPOINT}/openai/deployments/{_AZURE_TTS_DEPLOYMENT}/audio/speech?api-version=2025-01-01-preview"
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
    return _r2.presigned_url(r2_key) or f"{_r2._R2_PUBLIC_BASE}/{r2_key}"


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
                        "url": _r2.presigned_url(key) or f"{_r2._R2_PUBLIC_BASE}/{key}",
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
    """List imagery/story subsets (JSON presets). Thera-World is one subset among many."""
    from app.sse.trailer_generator import preset_character_keys

    presets: list[dict] = []
    if not _PRESETS_DIR.exists():
        return presets
    for p in sorted(_PRESETS_DIR.glob("*.json")):
        try:
            data = json.loads(p.read_text())
            pid = data.get("id", p.stem)
            casting = data.get("casting_locksheet") or {}
            presets.append({
                "id": pid,
                "title": data.get("title", p.stem),
                "description": (data.get("description") or "")[:280],
                "subset_kind": data.get("subset_kind") or (
                    "thera_world" if "thera_world" in pid else "custom"
                ),
                "scene_count": len(data.get("scenes", [])),
                "character_keys": preset_character_keys(pid),
                "character_count": len(casting) if isinstance(casting, dict) else 0,
                "has_style_anchor": bool(data.get("visual_style_anchor")),
                "color_preset": (data.get("color_grade") or {}).get("preset")
                or data.get("default_color_preset"),
            })
        except Exception:
            pass
    return presets


def get_preset(name: str) -> dict:
    """Load a subset preset by name."""
    from app.sse.trailer_generator import preset_character_keys

    path = _PRESETS_DIR / f"{name}.json"
    if not path.exists():
        raise FileNotFoundError(f"Preset '{name}' not found")
    data = json.loads(path.read_text())
    data["character_keys"] = preset_character_keys(data.get("id") or name)
    return data


def _slug_preset_id(raw: str) -> str:
    import re
    s = (raw or "").strip().lower().replace(" ", "_").replace("-", "_")
    s = re.sub(r"[^a-z0-9_]", "", s)
    s = re.sub(r"_+", "_", s).strip("_")
    return s or "custom_subset"


def create_or_update_preset(body: dict) -> dict:
    """Create/update a subset generator JSON under studio_presets/.

    Required: title. Optional: id, description, subset_kind, visual_style_anchor,
    casting_locksheet (dict key→description), scenes, default_color_preset.
    """
    title = (body.get("title") or "").strip()
    if not title:
        raise ValueError("title required")
    pid = _slug_preset_id(body.get("id") or title)
    if body.get("append_origin_suffix", True) and not pid.endswith("_origin"):
        pid = f"{pid}_origin"

    path = _PRESETS_DIR / f"{pid}.json"
    existing: dict = {}
    if path.exists():
        try:
            existing = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            existing = {}

    casting = body.get("casting_locksheet") or body.get("characters") or existing.get("casting_locksheet") or {}
    if isinstance(casting, list):
        casting = {str(c): str(c) for c in casting if c}

    style = body.get("visual_style_anchor") or existing.get("visual_style_anchor") or {}
    if isinstance(style, str) and style.strip():
        style = {"look": style.strip()}

    scenes = body.get("scenes")
    if scenes is None:
        scenes = existing.get("scenes") or []

    doc = {
        **existing,
        "id": pid,
        "preset_id": pid,
        "title": title,
        "description": (body.get("description") or existing.get("description") or title).strip(),
        "subset_kind": body.get("subset_kind") or existing.get("subset_kind") or "custom",
        "visual_style_anchor": style if isinstance(style, dict) else {"look": str(style)},
        "casting_locksheet": casting if isinstance(casting, dict) else {},
        "default_color_preset": body.get("default_color_preset")
        or existing.get("default_color_preset")
        or "counseling_neon",
        "branch_points": body.get("branch_points") or existing.get("branch_points") or [1],
        "scenes": scenes,
        "output": existing.get("output") or {
            "filename": f"{pid}.mp4",
            "duration_target_seconds": 24,
            "aspect": "16:9",
            "resolution": "1920x1080",
            "r2_character_prefix": f"sse/trailer/{pid}/characters/",
        },
    }
    if body.get("music_brief"):
        doc["music_brief"] = body["music_brief"]
    if body.get("narration_voice"):
        doc["narration_voice"] = body["narration_voice"]

    _PRESETS_DIR.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return get_preset(pid)


async def get_trained_loras_for_project(project_id: str) -> dict:
    """Return trained_loras map from R2 project manifest."""
    from app.sse.trailer_generator import _load_trained_loras

    return await _load_trained_loras(project_id)


# ---------------------------------------------------------------------------
#  Project CRUD (PostgreSQL)
# ---------------------------------------------------------------------------

async def create_project(
    title: str,
    scenes: list[dict],
    db_pool,
    preset_id: str | None = None,
) -> dict:
    """Create a new studio project."""
    project_id = str(uuid.uuid4())
    estimated_cost = len(scenes) * (COST_PER_IMAGE_CENTS + COST_PER_VIDEO_CENTS + COST_PER_NARRATION_CENTS)
    manifest: dict = {"scenes": scenes}
    if preset_id:
        manifest["preset_id"] = preset_id
        manifest["id"] = preset_id
    async with db_pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO sse_studio_projects (project_id, title, scene_count, status, manifest, estimated_cost_cents) "
            "VALUES ($1, $2, $3, 'draft', $4::jsonb, $5)",
            project_id, title, len(scenes), json.dumps(manifest), estimated_cost)
    try:
        from app.sse.trailer_generator import _save_manifest_to_r2
        await _save_manifest_to_r2(project_id, manifest)
    except Exception as e:
        logger.warning("[STUDIO] R2 manifest seed failed for %s: %s", project_id, e)
    return {"project_id": project_id, "title": title, "scene_count": len(scenes),
            "estimated_cost_cents": estimated_cost, "preset_id": preset_id}


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


async def get_project_hydrated(project_id: str, db_pool) -> dict | None:
    """Get project with scenes hydrated from R2 asset URLs."""
    proj = await get_project(project_id, db_pool)
    if not proj:
        return None

    from app.sse.infrastructure.r2_storage import list_objects, presigned_url, _R2_PUBLIC_BASE

    prefix = f"sse/studio/projects/{project_id}/"
    objects = await list_objects(prefix)

    asset_map: dict[int, dict] = {}
    for obj in objects:
        key = obj["Key"]
        filename = key.split("/")[-1]
        if "/" in filename or filename.startswith("refs"):
            continue
        name, _, ext = filename.rpartition(".")
        if not name.isdigit():
            continue
        scene_num = int(name)
        url = presigned_url(key) or f"{_R2_PUBLIC_BASE}/{key}"
        entry = asset_map.setdefault(scene_num, {})
        if ext == "png":
            entry["image_url"] = url
        elif ext == "mp4":
            entry["video_url"] = url
        elif ext in ("mp3", "wav", "ogg"):
            entry["audio_url"] = url

    manifest = proj.get("manifest", {})
    if isinstance(manifest, str):
        manifest = json.loads(manifest)
    scenes = manifest.get("scenes", [])

    for s in scenes:
        sn = s.get("scene", 0)
        if sn in asset_map:
            s.update(asset_map[sn])

    proj["manifest"] = manifest
    return proj


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

async def generate_character_refs(
    project_id: str,
    redis=None,
    preset_id: str | None = None,
) -> dict:
    """Generate character reference images for a project. Returns ref map."""
    from app.sse.trailer_generator import (
        generate_character_references,
        _load_manifest_from_r2,
        _manifest_preset_id,
        preset_character_keys,
    )

    proj = await _load_manifest_from_r2(project_id) or {}
    pid = preset_id or _manifest_preset_id(proj)
    num_chars = len(preset_character_keys(pid))
    await _check_cost_budget(COST_PER_IMAGE_CENTS * num_chars, redis)

    refs = await generate_character_references(project_id, preset_id=pid)
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


def _refresh_presigned_urls(clips: list[dict], project_id: str) -> None:
    """Replace stale presigned video_url/r2_url with fresh ones (24h TTL)."""
    from app.sse.infrastructure import r2_storage as _r2
    for clip in clips:
        fs = clip.get("from_scene", clip.get("scene"))
        ts = clip.get("to_scene")
        if ts is not None:
            key = f"sse/studio/projects/{project_id}/clips/transition_{fs:02d}_to_{ts:02d}.mp4"
        elif clip.get("status") == "ken_burns" or "endcard" in clip.get("title", ""):
            key = f"sse/studio/projects/{project_id}/clips/endcard_{fs:02d}.mp4"
        else:
            key = f"sse/studio/projects/{project_id}/clips/scene_{fs:02d}.mp4"
        fresh = _r2.presigned_url(key)
        if fresh:
            clip["video_url"] = fresh
        if clip.get("r2_url"):
            img_key = clip.get("r2_key", "")
            if img_key:
                img_fresh = _r2.presigned_url(img_key)
                if img_fresh:
                    clip["r2_url"] = img_fresh


async def get_video_status(project_id: str) -> dict:
    """Check video generation status from R2 manifest + chain state."""
    from app.sse.trailer_generator import _load_manifest_from_r2
    from app.sse.infrastructure import r2_storage as _r2
    client = _r2._get_client()
    if not client:
        return {"status": "r2_unavailable"}

    data: dict = {}
    try:
        def _get():
            return client.get_object(Bucket=_r2._R2_BUCKET,
                                     Key=f"sse/studio/projects/{project_id}/video_manifest.json")
        resp = await asyncio.get_event_loop().run_in_executor(None, _get)
        data = json.loads(resp["Body"].read().decode())
    except Exception:
        data = {"status": "not_started"}

    if data.get("clips"):
        _refresh_presigned_urls(data["clips"], project_id)

    try:
        proj_manifest = await _load_manifest_from_r2(project_id)
        if proj_manifest and proj_manifest.get("chain_state"):
            data["chain_state"] = proj_manifest["chain_state"]
    except Exception:
        pass

    return data


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
    if manifest.get("trailer", {}).get("trailer_url"):
        key = f"sse/studio/projects/{project_id}/trailer_{manifest['trailer'].get('format', '16:9').replace(':', 'x')}.mp4"
        fresh = _r2.presigned_url(key)
        if fresh:
            manifest["trailer"]["trailer_url"] = fresh
    return manifest


# ---------------------------------------------------------------------------
#  Phase 2: LoRA Character Lock Pipeline
# ---------------------------------------------------------------------------

def _require_replicate() -> None:
    if not _replicate_available:
        from fastapi import HTTPException
        raise HTTPException(status_code=501, detail="LoRA features require REPLICATE_API_TOKEN")


async def start_lora_training(character_key: str, training_images_zip_url: str) -> dict:
    """Kick off LoRA training on Replicate for a character."""
    _require_replicate()
    from app.sse.infrastructure.replicate_client import train_lora
    return await train_lora(
        training_images_url=training_images_zip_url,
        trigger_word=f"THERA_{character_key.upper()}",
        character_key=character_key,
    )


async def poll_lora_training(
    training_id: str,
    project_id: str | None = None,
    character_key: str | None = None,
    db_pool=None,
) -> dict:
    """Check LoRA training status. On completion, saves LoRA URL to project manifest and DB registry."""
    _require_replicate()
    from app.sse.infrastructure.replicate_client import poll_training
    result = await poll_training(training_id)
    if result.get("status") == "succeeded" and result.get("output") and project_id and character_key:
        lora_url = result["output"] if isinstance(result["output"], str) else result["output"].get("weights", "")
        if lora_url:
            from app.sse.trailer_generator import save_trained_lora
            await save_trained_lora(project_id, character_key, lora_url)
            logger.info("[STUDIO] LoRA for %s saved to manifest: %s", character_key, lora_url[:80])
            if db_pool:
                try:
                    from app.sse.adapters.lora_registry import register_lora
                    await register_lora(
                        db_pool, character_key, lora_url,
                        project_id=project_id,
                        trigger_word=f"THERA_{character_key.upper()}",
                        metadata={"training_id": training_id},
                    )
                except Exception as _lr_err:
                    logger.warning("[STUDIO] LoRA registry mirror failed: %s", _lr_err)
                try:
                    lora_record = await db_pool.fetchrow(
                        "SELECT user_id FROM character_lora_models "
                        "WHERE project_id = $1 AND status = 'active' "
                        "ORDER BY created_at DESC LIMIT 1",
                        project_id)
                    if lora_record:
                        from app.sse.adapters.group_lora_manager import on_member_lora_updated
                        asyncio.create_task(
                            on_member_lora_updated(lora_record["user_id"], db_pool))
                except Exception as _gl_err:
                    logger.warning("[STUDIO] Group LoRA sync failed: %s", _gl_err)
    return result


async def generate_with_lora(prompt: str, lora_urls: list[str], width: int = 1024, height: int = 576) -> list[str]:
    """Generate images using trained LoRA weights."""
    _require_replicate()
    from app.sse.infrastructure.replicate_client import generate_with_loras
    return await generate_with_loras(prompt, lora_urls, width=width, height=height)


async def generate_lora_training_images(
    character_key: str,
    project_id: str,
    redis=None,
    db_pool=None,
    preset_id: str | None = None,
) -> dict:
    """Generate a diverse set of training images for LoRA fine-tuning."""
    from app.sse.trailer_generator import generate_lora_training_set
    pid = preset_id
    if not pid and db_pool:
        try:
            proj = await get_project(project_id, db_pool)
            man = (proj or {}).get("manifest") or {}
            if isinstance(man, str):
                man = json.loads(man)
            pid = man.get("preset_id") or man.get("id")
        except Exception as e:
            logger.warning("[STUDIO] preset resolve from DB failed: %s", e)
    num_images = 20
    await _check_cost_budget(COST_PER_IMAGE_CENTS * num_images, redis)
    # project_id first — matches trailer_generator.generate_lora_training_set signature
    results = await generate_lora_training_set(project_id, character_key, preset_id=pid)
    await _track_cost(COST_PER_IMAGE_CENTS * len(results), redis)
    return {"character": character_key, "images": results, "count": len(results)}


# ---------------------------------------------------------------------------
#  Phase 2: Congruent Generation Pipelines
# ---------------------------------------------------------------------------

async def generate_congruent_clips(project_id: str, mode: str, db_pool, redis=None, resume_from: int | None = None) -> dict:
    """Run a congruent generation pipeline (interpolated/chain/cel/independent)."""
    from app.sse.trailer_generator import generate_congruent_trailer
    results = await generate_congruent_trailer(project_id, mode=mode, resume_from=resume_from)
    cost = sum(r.get("cost", 0) for r in results)
    total_cost_cents = int(cost * 100)
    await _track_cost(total_cost_cents, redis)
    if db_pool:
        await update_project(project_id, None, f"{mode}_generated", total_cost_cents, db_pool)
    return {
        "project_id": project_id,
        "mode": mode,
        "clips": results,
        "total": len(results),
        "success": sum(1 for r in results if r.get("status") == "success"),
        "total_cost_cents": total_cost_cents,
    }


async def generate_interpolated(project_id: str, db_pool, redis=None, resume_from: int | None = None) -> dict:
    """Shortcut for interpolated trailer generation (recommended default)."""
    return await generate_congruent_clips(project_id, "interpolated", db_pool, redis, resume_from)


# ---------------------------------------------------------------------------
#  Manifest Patching — keep stitcher in sync after single-scene regen
# ---------------------------------------------------------------------------

async def _patch_video_manifest(project_id: str, scene_num: int, new_url: str):
    """Update a single clip entry in video_manifest.json after scene regen."""
    from app.sse.infrastructure.r2_storage import store_bytes
    from app.sse.infrastructure import r2_storage as _r2

    client = _r2._get_client()
    if not client:
        logger.warning("[MANIFEST PATCH] No R2 client")
        return

    key = f"sse/studio/projects/{project_id}/video_manifest.json"
    try:
        def _get():
            return client.get_object(Bucket=_r2._R2_BUCKET, Key=key)
        resp = await asyncio.get_event_loop().run_in_executor(None, _get)
        manifest = json.loads(resp["Body"].read().decode())
    except Exception as e:
        logger.warning("[MANIFEST PATCH] Could not read video manifest: %s", e)
        return

    patched = False
    for clip in manifest.get("clips", []):
        clip_scene = clip.get("from_scene", clip.get("scene"))
        if clip_scene == scene_num:
            clip["video_url"] = new_url
            clip["status"] = "success"
            clip["regenerated_at"] = datetime.utcnow().isoformat()
            patched = True
            logger.info("[MANIFEST PATCH] Updated scene %d in video_manifest.json", scene_num)
            break

    if not patched:
        logger.warning("[MANIFEST PATCH] No clip found for scene %d", scene_num)
        return

    await store_bytes(json.dumps(manifest, indent=2).encode(), key, "application/json")
    logger.info("[MANIFEST PATCH] Saved video manifest for project %s", project_id)


async def _patch_project_manifest_image(project_id: str, scene_num: int, new_image_url: str, db_pool):
    """Update a scene image URL in the project manifest (DB) after image regen."""
    try:
        async with db_pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT manifest FROM sse_studio_projects WHERE project_id = $1", project_id)
            if not row:
                return
            manifest = json.loads(row["manifest"]) if isinstance(row["manifest"], str) else row["manifest"]
            for scene in manifest.get("scenes", []):
                if scene.get("scene") == scene_num:
                    scene["r2_url"] = new_image_url
                    scene["image_url"] = new_image_url
                    scene["regenerated_at"] = datetime.utcnow().isoformat()
                    break
            await conn.execute(
                "UPDATE sse_studio_projects SET manifest = $1::jsonb WHERE project_id = $2",
                json.dumps(manifest), project_id)
            logger.info("[MANIFEST PATCH] Updated image for scene %d in project manifest", scene_num)
    except Exception as e:
        logger.error("[MANIFEST PATCH] Failed to patch project manifest: %s", e)
