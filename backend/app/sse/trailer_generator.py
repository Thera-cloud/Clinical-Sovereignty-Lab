"""Thera-World trailer generator — character-consistent hero images, motion video,
narration, and congruent stitching via FFmpeg.

Phase 2: CHARACTER_REFERENCES for visual consistency, STYLE_PREFIX for unified
color grade, motion prompts with transition context, Azure TTS narration per
character, and Ken Burns fallback when Grok Video is unavailable.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil
import subprocess
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Optional

import aiohttp

from app.sse.infrastructure.grok_imagine_client import (
    GROK_IMAGINE_LOCK,
    generate_image,
    generate_video,
    poll_video_status,
)
from app.sse.infrastructure.r2_storage import store_bytes, store_image

logger = logging.getLogger(__name__)

TRAILER_OUTPUT_DIR = "/tmp/trailer_scenes"
R2_TRAILER_PREFIX = "sse/trailer/scenes"
_PRESETS_DIR = Path(__file__).parent / "data" / "studio_presets"

# ---------------------------------------------------------------------------
#  Character Reference System
# ---------------------------------------------------------------------------

CHARACTER_REFERENCES = {
    "boy": {
        "ref_prompt": (
            "Character reference sheet, young boy age 6, messy brown hair, fair skin, "
            "simple white linen shirt, brown shorts, bare feet, holding a small carved "
            "wooden dragon toy in right hand, innocent face with large curious eyes, "
            "multiple angles showing front three-quarter and profile, consistent "
            "proportions, neutral studio lighting, white background, character design "
            "sheet style, 16:9"
        ),
        "inline_desc": (
            "young boy age 6 with messy brown hair, fair skin, simple white linen "
            "shirt, brown shorts, bare feet, clutching a small carved wooden dragon toy"
        ),
    },
    "serpent": {
        "ref_prompt": (
            "Character reference sheet, elegant dark serpent with ancient knowing amber "
            "eyes, iridescent dark green-black scales, coiled sinuous body, the serpent "
            "appears wise not evil, mystical aura, multiple angles showing head detail "
            "and full body coil, neutral lighting, character design sheet style, 16:9"
        ),
        "inline_desc": (
            "dark elegant serpent with iridescent green-black scales and ancient knowing "
            "amber eyes, wise and mystical not evil"
        ),
    },
    "dragon": {
        "ref_prompt": (
            "Character reference sheet, massive red dragon 50 feet tall, dark crimson "
            "scales with amber undertones, powerful wings spread wide, amber eyes "
            "matching the serpent, ancient intelligent face not mindless beast, fearsome "
            "but purposeful, multiple angles showing full body and head detail, "
            "character design sheet style, 16:9"
        ),
        "inline_desc": (
            "massive 50-foot red dragon with dark crimson scales, amber eyes matching "
            "the serpent, ancient intelligent face, fearsome but purposeful"
        ),
    },
    "girl": {
        "ref_prompt": (
            "Character reference sheet, young girl age 6, bright blonde hair in loose "
            "braids, light blue dress, bare feet, radiant smile, bright sparkling eyes "
            "full of joy, clean and dry appearance contrasting with the boy, multiple "
            "angles, character design sheet style, 16:9"
        ),
        "inline_desc": (
            "young girl age 6 with bright blonde hair in loose braids, light blue "
            "dress, bare feet, radiant joyful smile, bright sparkling eyes"
        ),
    },
    "watcher": {
        "ref_prompt": (
            "Character reference sheet, tall woman warrior in dark ornate armor, "
            "vigilant stern expression, pointing hand, short dark hair, battle-worn "
            "but noble, standing atop a stone tower, character design sheet style, 16:9"
        ),
        "inline_desc": (
            "tall armored woman watcher with dark ornate armor, vigilant stern "
            "expression, short dark hair, battle-worn noble bearing"
        ),
    },
    "glowing_woman": {
        "ref_prompt": (
            "Character reference sheet, ethereal woman radiating warm golden-white "
            "light, serene compassionate expression, flowing white and gold robes, "
            "her light illuminates everything around her, calm presence contrasting "
            "with chaos, character design sheet style, 16:9"
        ),
        "inline_desc": (
            "ethereal woman radiating warm golden-white light, flowing white and "
            "gold robes, serene compassionate expression"
        ),
    },
    "knight": {
        "ref_prompt": (
            "Character reference sheet, knight in brilliant polished silver armor, "
            "raised sword, noble defiant stance, red cape, standing at the base of "
            "a tower, heroic but ultimately ignored by the dragon, character design "
            "sheet style, 16:9"
        ),
        "inline_desc": (
            "knight in brilliant polished silver armor with raised sword, red cape, "
            "noble defiant heroic stance"
        ),
    },
}

STYLE_PREFIX = (
    "Maintaining exact visual consistency throughout: warm golden color grade, "
    "film grain texture, shallow depth of field, anamorphic lens characteristics, "
    "Terrence Malick meets Guillermo del Toro visual language, "
    "rich earth tones with mystical amber accents, "
    "cinematic 2.39:1 framing within 16:9 frame — "
)

CHARACTER_VOICES = {
    "serpent": {
        "voice": "onyx",
        "instructions": "Speak in a deep, ancient, knowing voice. Warm but unsettling. Slow cadence with deliberate pauses.",
    },
    "dragon": {
        "voice": "onyx",
        "instructions": "Speak in a deep, powerful, resonant voice. Ancient tone amplified and commanding. Echoes off stone walls.",
    },
    "boy": {
        "voice": "shimmer",
        "instructions": "Speak as a young 6-year-old boy. Innocent, curious, sometimes excited, sometimes scared.",
    },
    "girl": {
        "voice": "shimmer",
        "instructions": "Speak as a young 6-year-old girl. Bright, laughing, teasing, full of joy. Higher pitch.",
    },
}

SCENE_MOTION_PROMPTS = [
    {"scene": 1, "motion": "Camera slowly pushes forward toward the boy and tree, the boy runs in a circle, leaves flutter in warm wind, golden light shifts subtly", "transition_from": None, "transition_to": "camera descends toward puddle"},
    {"scene": 2, "motion": "Camera slowly descends toward the puddle, subtle ripple appears in the water, the serpent shadow shifts position on the reflected branch, tension builds", "transition_from": "meadow establishing shot", "transition_to": "close on puddle reflection"},
    {"scene": 3, "motion": "Subtle water ripples emanate from the serpent in the reflection, the boy's eyes widen slightly, light shifts on the water surface", "transition_from": "puddle discovery", "transition_to": "underwater perspective"},
    {"scene": 4, "motion": "Underwater camera slowly rises toward the surface, light rays shift through the water, the serpent shadow moves closer, bubbles rise", "transition_from": "surface reflection", "transition_to": "return to surface"},
    {"scene": 5, "motion": "The boy leans forward toward the puddle with growing excitement, the serpent's amber eyes pulse brighter, the dragon toy catches golden light", "transition_from": "underwater mystery", "transition_to": "boy running free"},
    {"scene": 6, "motion": "Fast joyful tracking shot following the running boy through golden grass, his shadow morphs dragon-like on the ground, wind blows", "transition_from": "intimate bargain", "transition_to": "return to stillness"},
    {"scene": 7, "motion": "Stillness and tension, the boy's shoulders tense and fists clench tighter, the puddle is perfectly still and empty, dusk light darkens", "transition_from": "joyful running stops", "transition_to": "explosive action"},
    {"scene": 8, "motion": "EXPLOSIVE upward motion, the dragon claw bursts violently from the water, water sprays in slow motion, the boy is jerked downward, debris hangs in air", "transition_from": "still tension snaps", "transition_to": "aerial chaos"},
    {"scene": 9, "motion": "Fast sweeping aerial flyover of the vast fantasy landscape, camera banks and rolls following the dragon, clouds part revealing biomes below", "transition_from": "pulled through portal", "transition_to": "approaching tower"},
    {"scene": 10, "motion": "Dragon swoops past the stone tower, camera tracks following, the watcher points urgently, the glowing woman's light pulses, the knight raises his sword", "transition_from": "aerial sweep", "transition_to": "descent to ground"},
    {"scene": 11, "motion": "Camera slowly tilts upward from the tiny boy's level to the massive dragon head above, emphasizing terrifying scale, the boy trembles, the well glows", "transition_from": "dropped from flight", "transition_to": "looking into well"},
    {"scene": 12, "motion": "Camera slowly descends into the well water, the reflection ripples as the dragon's voice reverberates, the boy's reflected face trembles", "transition_from": "looking up at dragon", "transition_to": "dragon descends"},
    {"scene": 13, "motion": "Dragon jaws descend rapidly toward camera filling the frame, fire builds in the throat, the boy falls backward, extreme dramatic zoom", "transition_from": "well reflection", "transition_to": "plunge underwater"},
    {"scene": 14, "motion": "Boy sinks through dark water in slow motion, dragon fire crashes on the surface above creating orange-red light, below a white vortex grows brighter", "transition_from": "escaping jaws", "transition_to": "emerging in meadow"},
    {"scene": 15, "motion": "Perfect stillness, water drips slowly from the motionless boy, the puddle slowly calms, a single ripple expands outward, impossibly still golden meadow", "transition_from": "shot through vortex", "transition_to": "girl appears"},
    {"scene": 16, "motion": "The bright girl steps forward into frame laughing, the wet dark boy stares motionless, the puddle between them smooths to a perfect mirror", "transition_from": "stillness and shock", "transition_to": "close on eyes"},
    {"scene": 17, "motion": "Extreme slow zoom into the boy's eyes, one pupil dilates and flashes amber dragon slit then returns, a knowing dangerous smile slowly creeps", "transition_from": "girl awakens him", "transition_to": "chase and fire"},
    {"scene": 18, "motion": "Children run away becoming small, camera descends to the still puddle, the serpent materializes, its amber eyes lock onto the viewer, mouth opens revealing flame", "transition_from": "boy transformed", "transition_to": "black and title"},
    {"scene": 19, "motion": "On pure black, golden text materializes letter by letter with subtle shimmer particle effects, THERA-WORLD appears then subtitle fades in below", "transition_from": "fire fills screen", "transition_to": None},
]


# ---------------------------------------------------------------------------
#  Helpers
# ---------------------------------------------------------------------------

def _load_preset(name: str) -> list[dict]:
    """Load scene list from a preset JSON file."""
    preset_path = _PRESETS_DIR / f"{name}.json"
    if not preset_path.exists():
        raise FileNotFoundError(f"Preset '{name}' not found at {preset_path}")
    with open(preset_path) as f:
        data = json.load(f)
    return data.get("scenes", [])


def _build_consistent_prompt(scene_prompt: str, characters: list[str]) -> str:
    """Prepend STYLE_PREFIX and inline character descriptions for visual consistency."""
    char_descs = []
    for char in characters:
        ref = CHARACTER_REFERENCES.get(char)
        if ref:
            char_descs.append(ref["inline_desc"])

    char_block = ""
    if char_descs:
        char_block = "Characters in scene (maintain exact appearance): " + "; ".join(char_descs) + ". "

    resolved = scene_prompt
    for char_name, ref in CHARACTER_REFERENCES.items():
        resolved = resolved.replace(f"{{{char_name}}}", ref["inline_desc"])

    return STYLE_PREFIX + char_block + resolved


def _write_manifest(results: list[dict], total: int) -> None:
    os.makedirs(TRAILER_OUTPUT_DIR, exist_ok=True)
    manifest = {
        "generated_at": datetime.utcnow().isoformat(),
        "scenes": results,
        "total": total,
        "success": sum(1 for r in results if r.get("status") == "success"),
    }
    with open(os.path.join(TRAILER_OUTPUT_DIR, "manifest.json"), "w") as f:
        json.dump(manifest, f, indent=2)


async def _save_manifest_to_r2(project_id: str, manifest: dict) -> str:
    data = json.dumps(manifest, indent=2).encode()
    key = f"sse/studio/projects/{project_id}/manifest.json"
    return await store_bytes(data, key, "application/json")


async def _load_manifest_from_r2(project_id: str) -> Optional[dict]:
    from app.sse.infrastructure import r2_storage as _r2
    client = _r2._get_client()
    if client is None:
        return None
    key = f"sse/studio/projects/{project_id}/manifest.json"
    try:
        def _get():
            return client.get_object(Bucket=_r2._R2_BUCKET, Key=key)
        resp = await asyncio.get_event_loop().run_in_executor(None, _get)
        return json.loads(resp["Body"].read().decode())
    except Exception:
        return None


# ---------------------------------------------------------------------------
#  Character Reference Generation
# ---------------------------------------------------------------------------

async def generate_character_references(project_id: str) -> dict[str, Optional[str]]:
    """Generate reference images for all characters. Returns {name: r2_url}."""
    refs: dict[str, Optional[str]] = {}

    async with GROK_IMAGINE_LOCK:
        for char_name, char_data in CHARACTER_REFERENCES.items():
            logger.info("[TRAILER-REF] Generating reference: %s", char_name)
            try:
                image_bytes = await generate_image(char_data["ref_prompt"])
                r2_key = f"sse/studio/projects/{project_id}/refs/{char_name}_ref.png"
                r2_url = await store_image(image_bytes, r2_key)
                refs[char_name] = r2_url
                logger.info("[TRAILER-REF] %s done", char_name)
            except Exception as e:
                logger.warning("[TRAILER-REF] %s failed: %s", char_name, e)
                refs[char_name] = None
            await asyncio.sleep(5)

    ref_manifest = json.dumps(refs).encode()
    await store_bytes(ref_manifest, f"sse/studio/projects/{project_id}/refs/manifest.json", "application/json")
    return refs


# ---------------------------------------------------------------------------
#  Hero Image Generation (Phase 2 — character-consistent)
# ---------------------------------------------------------------------------

async def generate_all_scenes(project_id: str, scenes: list[dict] | None = None) -> list[dict]:
    """Generate hero images with character consistency.

    If scenes is None, loads the thera_world_origin preset.
    """
    if scenes is None:
        scenes = _load_preset("thera_world_origin")

    os.makedirs(TRAILER_OUTPUT_DIR, exist_ok=True)

    logger.info("[TRAILER] Generating character references for project %s", project_id)
    refs = await generate_character_references(project_id)

    results: list[dict] = []
    total = len(scenes)

    async with GROK_IMAGINE_LOCK:
        for scene in scenes:
            num = scene.get("scene", 0)
            title = scene.get("title", f"scene_{num}")
            characters = scene.get("characters", [])

            consistent_prompt = _build_consistent_prompt(scene["prompt"], characters)

            logger.info("[TRAILER] Scene %d: %s", num, title)
            try:
                image_bytes = await generate_image(consistent_prompt)
                r2_key = f"sse/studio/projects/{project_id}/scenes/{title}.png"
                r2_url = await store_image(image_bytes, r2_key)
                results.append({"scene": num, "title": title, "r2_url": r2_url,
                                "status": "success", "cost": 0.07})
                logger.info("[TRAILER] Scene %d done", num)
            except Exception as e:
                results.append({"scene": num, "title": title, "r2_url": None,
                                "status": f"error: {str(e)[:120]}"})
                logger.warning("[TRAILER] Scene %d failed: %s", num, e)

            _write_manifest(results, total)
            await asyncio.sleep(5)

    manifest = {
        "project_id": project_id,
        "generated_at": datetime.utcnow().isoformat(),
        "character_refs": refs,
        "scenes": results,
        "total": total,
        "success": sum(1 for r in results if r.get("status") == "success"),
        "total_cost": sum(r.get("cost", 0) for r in results),
        "style_prefix": STYLE_PREFIX,
    }
    await _save_manifest_to_r2(project_id, manifest)

    logger.info("[TRAILER] Complete: %d/%d scenes, $%.2f",
                manifest["success"], total, manifest["total_cost"])
    return results


# ---------------------------------------------------------------------------
#  Ken Burns Fallback (static image → slow zoom video)
# ---------------------------------------------------------------------------

async def _ken_burns_fallback(image_url: str, output_path: str, duration: int = 5) -> bool:
    """Generate a slow-zoom Ken Burns clip from a static image using FFmpeg."""
    try:
        async with aiohttp.ClientSession() as sess:
            async with sess.get(image_url) as r:
                if r.status != 200:
                    return False
                img_bytes = await r.read()
    except Exception as e:
        logger.warning("[KEN-BURNS] Image download failed: %s", e)
        return False

    img_path = output_path.replace(".mp4", ".png")
    with open(img_path, "wb") as f:
        f.write(img_bytes)

    frames = duration * 24
    cmd = [
        "ffmpeg", "-y", "-loop", "1", "-t", str(duration), "-i", img_path,
        "-vf", f"zoompan=z='min(zoom+0.001,1.08)':d={frames}:s=1920x1080",
        "-c:v", "libx264", "-pix_fmt", "yuv420p", output_path,
    ]
    try:
        subprocess.run(cmd, capture_output=True, timeout=30)
    except Exception as e:
        logger.warning("[KEN-BURNS] FFmpeg failed: %s", e)
        return False

    return os.path.exists(output_path)


# ---------------------------------------------------------------------------
#  Motion Video Generation
# ---------------------------------------------------------------------------

async def generate_motion_clips(project_id: str) -> list[dict]:
    """Extend hero images into 5s motion video clips with transition context.

    Falls back to Ken Burns if Grok Video fails.
    """
    manifest = await _load_manifest_from_r2(project_id)
    if not manifest or not manifest.get("scenes"):
        logger.warning("[TRAILER-VIDEO] No manifest found — run generate_all_scenes first")
        return []

    successful_scenes = [s for s in manifest["scenes"] if s.get("status") == "success"]
    motion_map = {m["scene"]: m for m in SCENE_MOTION_PROMPTS}
    results: list[dict] = []

    async with GROK_IMAGINE_LOCK:
        for scene_data in successful_scenes:
            scene_num = scene_data["scene"]
            motion = motion_map.get(scene_num)
            if not motion:
                continue

            motion_prompt = STYLE_PREFIX + motion["motion"]
            if motion.get("transition_from"):
                motion_prompt += f". Transitioning from: {motion['transition_from']}"
            if motion.get("transition_to"):
                motion_prompt += f". Leading into: {motion['transition_to']}"

            logger.info("[TRAILER-VIDEO] Scene %d: %s", scene_num, scene_data["title"])

            try:
                video_id = await generate_video(motion_prompt, source_image_url=scene_data["r2_url"])

                video_url = None
                for attempt in range(36):
                    await asyncio.sleep(5)
                    status = await poll_video_status(video_id)
                    if status["status"] == "completed" and status.get("url"):
                        video_url = status["url"]
                        break
                    if status["status"] == "failed":
                        break
                    if attempt % 6 == 0:
                        logger.info("[TRAILER-VIDEO] Polling %s... %ds", video_id, attempt * 5)

                if video_url:
                    async with aiohttp.ClientSession() as sess:
                        async with sess.get(video_url) as vr:
                            if vr.status == 200:
                                video_bytes = await vr.read()
                                r2_key = f"sse/studio/projects/{project_id}/clips/scene_{scene_num:02d}.mp4"
                                stored_url = await store_bytes(video_bytes, r2_key, "video/mp4")
                                results.append({
                                    "scene": scene_num, "title": scene_data["title"],
                                    "hero_url": scene_data["r2_url"], "video_url": stored_url,
                                    "status": "success", "cost": 0.25,
                                })
                                logger.info("[TRAILER-VIDEO] Scene %d done (grok)", scene_num)
                                await asyncio.sleep(8)
                                continue

                raise RuntimeError("Grok Video returned no URL")

            except Exception as e:
                logger.warning("[TRAILER-VIDEO] Scene %d Grok Video failed: %s — trying Ken Burns", scene_num, e)

                work_dir = tempfile.mkdtemp(prefix="kb_")
                kb_path = os.path.join(work_dir, f"scene_{scene_num:02d}.mp4")
                success = await _ken_burns_fallback(scene_data["r2_url"], kb_path)

                if success and os.path.exists(kb_path):
                    with open(kb_path, "rb") as f:
                        kb_bytes = f.read()
                    r2_key = f"sse/studio/projects/{project_id}/clips/scene_{scene_num:02d}.mp4"
                    stored_url = await store_bytes(kb_bytes, r2_key, "video/mp4")
                    results.append({
                        "scene": scene_num, "title": scene_data["title"],
                        "hero_url": scene_data["r2_url"], "video_url": stored_url,
                        "status": "ken_burns", "cost": 0,
                    })
                    logger.info("[TRAILER-VIDEO] Scene %d done (ken burns)", scene_num)
                else:
                    results.append({
                        "scene": scene_num, "title": scene_data["title"],
                        "hero_url": scene_data["r2_url"], "video_url": None,
                        "status": f"failed: {str(e)[:100]}",
                    })
                    logger.warning("[TRAILER-VIDEO] Scene %d Ken Burns also failed", scene_num)

                shutil.rmtree(work_dir, ignore_errors=True)

            await asyncio.sleep(8)

    video_manifest = {
        "project_id": project_id,
        "generated_at": datetime.utcnow().isoformat(),
        "clips": results,
        "total": len(results),
        "success": sum(1 for r in results if r["status"] in ("success", "ken_burns")),
        "total_cost": sum(r.get("cost", 0) for r in results),
    }
    await store_bytes(
        json.dumps(video_manifest, indent=2).encode(),
        f"sse/studio/projects/{project_id}/video_manifest.json",
        "application/json",
    )

    logger.info("[TRAILER-VIDEO] Complete: %d/%d clips, $%.2f",
                video_manifest["success"], video_manifest["total"], video_manifest["total_cost"])
    return results


# ---------------------------------------------------------------------------
#  Narration Generation (Azure Mini TTS)
# ---------------------------------------------------------------------------

async def _azure_tts(text: str, voice: str = "onyx", instructions: str = "") -> Optional[bytes]:
    """Generate TTS audio via Azure gpt-4o-mini-tts."""
    api_key = os.getenv("AZURE_API_KEY", "").strip()
    endpoint = os.getenv("AZURE_OPENAI_ENDPOINT", "").strip()
    deployment = os.getenv("AZURE_OPENAI_MINI_TTS_DEPLOYMENT", "gpt-4o-mini-tts")

    if not api_key or not endpoint:
        return None

    url = f"https://{endpoint}/openai/deployments/{deployment}/audio/speech?api-version=2024-12-17"
    payload: dict = {"model": deployment, "input": text, "voice": voice}
    if instructions:
        payload["instructions"] = instructions

    async with aiohttp.ClientSession() as sess:
        async with sess.post(url, json=payload,
                             headers={"api-key": api_key, "Content-Type": "application/json"},
                             timeout=aiohttp.ClientTimeout(total=30)) as resp:
            if resp.status == 200:
                return await resp.read()
            body = await resp.text()
            logger.warning("[TTS] HTTP %d: %s", resp.status, body[:200])
            return None


def _concat_audio_files(file_paths: list[str], output_path: str) -> None:
    """Concatenate WAV/MP3 files using FFmpeg concat."""
    concat_list = os.path.join(os.path.dirname(output_path), "audio_concat.txt")
    with open(concat_list, "w") as f:
        for path in file_paths:
            f.write(f"file '{path}'\n")

    subprocess.run([
        "ffmpeg", "-y", "-f", "concat", "-safe", "0",
        "-i", concat_list, "-c:a", "pcm_s16le", output_path,
    ], capture_output=True, timeout=60)


async def _generate_all_narration(project_id: str, work_dir: str) -> dict[int, str]:
    """Generate TTS audio for all dialogue scenes. Returns {scene_num: r2_url}."""
    preset_scenes = _load_preset("thera_world_origin")
    dialogue_map = {s["scene"]: s.get("dialogue", []) for s in preset_scenes if s.get("dialogue")}

    narration_dir = os.path.join(work_dir, "narration")
    os.makedirs(narration_dir, exist_ok=True)

    results: dict[int, str] = {}

    for scene_num, lines in sorted(dialogue_map.items()):
        if not lines:
            continue

        scene_audio_parts: list[str] = []

        for i, line in enumerate(lines):
            voice_cfg = CHARACTER_VOICES.get(line["voice"], CHARACTER_VOICES["boy"])
            try:
                audio_bytes = await _azure_tts(
                    text=line["text"],
                    voice=voice_cfg["voice"],
                    instructions=voice_cfg["instructions"],
                )
                if audio_bytes:
                    part_path = os.path.join(narration_dir, f"scene_{scene_num:02d}_line_{i:02d}.wav")
                    with open(part_path, "wb") as f:
                        f.write(audio_bytes)
                    scene_audio_parts.append(part_path)
            except Exception as e:
                logger.warning("[NARRATION] Scene %d line %d failed: %s", scene_num, i, e)

        if scene_audio_parts:
            scene_audio = os.path.join(narration_dir, f"scene_{scene_num:02d}_narration.wav")
            _concat_audio_files(scene_audio_parts, scene_audio)

            if os.path.exists(scene_audio):
                with open(scene_audio, "rb") as f:
                    audio_data = f.read()
                r2_key = f"sse/studio/projects/{project_id}/narration/scene_{scene_num:02d}.wav"
                r2_url = await store_bytes(audio_data, r2_key, "audio/wav")
                results[scene_num] = r2_url

    return results


# ---------------------------------------------------------------------------
#  Congruent Stitching (FFmpeg)
# ---------------------------------------------------------------------------

async def stitch_trailer(project_id: str, options: dict | None = None) -> Optional[dict]:
    """Stitch clips into a congruent trailer with post-processing.

    Pipeline: download clips → color grade → concat → narration overlay → format convert.
    """
    options = options or {}
    include_color_grade = options.get("include_color_grade", True)
    include_narration = options.get("include_narration", True)
    output_format = options.get("format", "16:9")

    video_manifest_bytes = None
    from app.sse.infrastructure import r2_storage as _r2
    client = _r2._get_client()
    if client:
        try:
            def _get():
                return client.get_object(Bucket=_r2._R2_BUCKET,
                                         Key=f"sse/studio/projects/{project_id}/video_manifest.json")
            resp = await asyncio.get_event_loop().run_in_executor(None, _get)
            video_manifest_bytes = resp["Body"].read()
        except Exception:
            pass

    if not video_manifest_bytes:
        logger.warning("[STITCH] No video manifest found for project %s", project_id)
        return None

    video_manifest = json.loads(video_manifest_bytes.decode())
    successful = sorted(
        [c for c in video_manifest.get("clips", []) if c.get("status") in ("success", "ken_burns")],
        key=lambda c: c["scene"],
    )

    if len(successful) < 2:
        logger.warning("[STITCH] Only %d clips — need at least 2", len(successful))
        return None

    work_dir = tempfile.mkdtemp(prefix="stitch_")
    clip_dir = os.path.join(work_dir, "clips")
    graded_dir = os.path.join(work_dir, "graded")
    os.makedirs(clip_dir)
    os.makedirs(graded_dir)

    try:
        logger.info("[STITCH] Downloading %d clips...", len(successful))
        async with aiohttp.ClientSession() as sess:
            for clip in successful:
                local = os.path.join(clip_dir, f"scene_{clip['scene']:02d}.mp4")
                try:
                    async with sess.get(clip["video_url"]) as r:
                        if r.status == 200:
                            data = await r.read()
                            if len(data) > 1000:
                                with open(local, "wb") as f:
                                    f.write(data)
                except Exception as e:
                    logger.warning("[STITCH] Download failed scene %d: %s", clip["scene"], e)

        if include_color_grade:
            logger.info("[STITCH] Applying color grade...")
            for clip in successful:
                src = os.path.join(clip_dir, f"scene_{clip['scene']:02d}.mp4")
                dst = os.path.join(graded_dir, f"scene_{clip['scene']:02d}.mp4")
                if os.path.exists(src):
                    cmd = [
                        "ffmpeg", "-y", "-i", src,
                        "-vf", (
                            "colorbalance=rs=0.08:gs=0.03:bs=-0.08,"
                            "eq=gamma=1.05:saturation=1.15:contrast=1.05,"
                            "unsharp=5:5:0.5:5:5:0"
                        ),
                        "-c:v", "libx264", "-preset", "fast",
                        "-crf", "20", "-pix_fmt", "yuv420p", dst,
                    ]
                    subprocess.run(cmd, capture_output=True, timeout=30)
                    if not os.path.exists(dst):
                        shutil.copy(src, dst)
        else:
            for f in os.listdir(clip_dir):
                shutil.copy(os.path.join(clip_dir, f), os.path.join(graded_dir, f))

        narration_files: dict[int, str] = {}
        if include_narration:
            logger.info("[STITCH] Generating narration...")
            narration_files = await _generate_all_narration(project_id, work_dir)

        graded_clips = sorted([
            os.path.join(graded_dir, f) for f in os.listdir(graded_dir) if f.endswith(".mp4")
        ])

        if len(graded_clips) < 2:
            logger.warning("[STITCH] Not enough graded clips")
            return None

        concat_path = os.path.join(work_dir, "concat.txt")
        with open(concat_path, "w") as f:
            for clip_path in graded_clips:
                f.write(f"file '{clip_path}'\n")

        raw_output = os.path.join(work_dir, "trailer_raw.mp4")
        subprocess.run([
            "ffmpeg", "-y", "-f", "concat", "-safe", "0",
            "-i", concat_path, "-c:v", "libx264",
            "-pix_fmt", "yuv420p", "-preset", "fast",
            "-crf", "22", "-movflags", "+faststart", raw_output,
        ], capture_output=True, timeout=300)

        final_output = raw_output

        if output_format == "9:16":
            vert = os.path.join(work_dir, "trailer_vertical.mp4")
            subprocess.run([
                "ffmpeg", "-y", "-i", final_output,
                "-vf", "crop=ih*9/16:ih,scale=1080:1920",
                "-c:v", "libx264", "-preset", "fast", "-crf", "22", vert,
            ], capture_output=True, timeout=300)
            if os.path.exists(vert):
                final_output = vert
        elif output_format == "1:1":
            sq = os.path.join(work_dir, "trailer_square.mp4")
            subprocess.run([
                "ffmpeg", "-y", "-i", final_output,
                "-vf", "crop=min(iw\\,ih):min(iw\\,ih),scale=1080:1080",
                "-c:v", "libx264", "-preset", "fast", "-crf", "22", sq,
            ], capture_output=True, timeout=300)
            if os.path.exists(sq):
                final_output = sq

        results: dict = {}

        if os.path.exists(final_output):
            with open(final_output, "rb") as f:
                final_bytes = f.read()
            fmt_tag = output_format.replace(":", "x")
            r2_key = f"sse/studio/projects/{project_id}/trailer_{fmt_tag}.mp4"
            r2_url = await store_bytes(final_bytes, r2_key, "video/mp4")
            results["trailer_url"] = r2_url
            results["size_bytes"] = len(final_bytes)
            logger.info("[STITCH] Final trailer: %s (%d bytes)", r2_url, len(final_bytes))

        if os.path.exists(raw_output) and raw_output != final_output:
            with open(raw_output, "rb") as f:
                raw_bytes = f.read()
            raw_key = f"sse/studio/projects/{project_id}/trailer_raw.mp4"
            raw_url = await store_bytes(raw_bytes, raw_key, "video/mp4")
            results["raw_trailer_url"] = raw_url

        results["clips_used"] = len(graded_clips)
        results["format"] = output_format
        results["color_graded"] = include_color_grade
        results["has_narration"] = bool(narration_files)
        results["narration_scenes"] = list(narration_files.keys())

        trailer_manifest = await _load_manifest_from_r2(project_id)
        if trailer_manifest:
            trailer_manifest["trailer"] = results
            await _save_manifest_to_r2(project_id, trailer_manifest)

        return results

    except FileNotFoundError:
        logger.error("[STITCH] FFmpeg not installed")
        return None
    except subprocess.TimeoutExpired:
        logger.error("[STITCH] FFmpeg timeout")
        return None
    except Exception as e:
        logger.error("[STITCH] Error: %s", e)
        return None
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)
