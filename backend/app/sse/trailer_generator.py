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


async def _apply_faststart(vid_bytes: bytes) -> bytes:
    """Re-mux MP4 with -movflags +faststart so browsers can stream progressively."""
    tmp = tempfile.mkdtemp(prefix="faststart_")
    src = os.path.join(tmp, "in.mp4")
    dst = os.path.join(tmp, "out.mp4")
    try:
        with open(src, "wb") as f:
            f.write(vid_bytes)
        proc = subprocess.run(
            ["ffmpeg", "-y", "-i", src, "-c", "copy",
             "-movflags", "+faststart", dst],
            capture_output=True, timeout=30,
        )
        if proc.returncode == 0 and os.path.exists(dst):
            with open(dst, "rb") as f:
                return f.read()
        logger.warning("[FASTSTART] ffmpeg failed (rc=%d), using original", proc.returncode)
        return vid_bytes
    except Exception as e:
        logger.warning("[FASTSTART] Error: %s, using original", e)
        return vid_bytes
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
R2_TRAILER_PREFIX = "sse/trailer/scenes"
_PRESETS_DIR = Path(__file__).parent / "data" / "studio_presets"

# ---------------------------------------------------------------------------
#  Character Reference System
# ---------------------------------------------------------------------------

_GHIBLI_PREFIX = (
    "Studio Ghibli anime art style, soft cel shading, "
    "expressive large emotive eyes, hand-drawn animation aesthetic, "
)

CHARACTER_REFERENCES = {
    "boy": {
        "ref_prompt": (
            f"{_GHIBLI_PREFIX}"
            "character reference sheet, young boy age 6, messy brown hair, fair skin, "
            "simple white linen shirt, brown shorts, bare feet, holding a small carved "
            "wooden dragon toy in right hand, innocent face with large curious eyes, "
            "multiple angles showing front three-quarter and profile, consistent "
            "proportions, neutral studio lighting, white background, Ghibli character "
            "model sheet style, 16:9"
        ),
        "inline_desc": (
            "young boy age 6 with messy brown hair, fair skin, simple white linen "
            "shirt, brown shorts, bare feet, clutching a small carved wooden dragon toy"
        ),
    },
    "serpent": {
        "ref_prompt": (
            f"{_GHIBLI_PREFIX}"
            "Studio Ghibli magical creature design, "
            "character reference sheet, elegant dark serpent with ancient knowing amber "
            "eyes, iridescent dark green-black scales, coiled sinuous body, the serpent "
            "appears wise not evil, mystical aura, multiple angles showing head detail "
            "and full body coil, neutral lighting, Ghibli character model sheet style, 16:9"
        ),
        "inline_desc": (
            "dark elegant serpent with iridescent green-black scales and ancient knowing "
            "amber eyes, wise and mystical not evil"
        ),
    },
    "dragon": {
        "ref_prompt": (
            f"{_GHIBLI_PREFIX}"
            "Ghibli-scale fantasy creature reminiscent of Haku from Spirited Away but red, "
            "character reference sheet, massive red dragon 50 feet tall, dark crimson "
            "scales with amber undertones, powerful wings spread wide, amber eyes "
            "matching the serpent, ancient intelligent face not mindless beast, fearsome "
            "but purposeful, multiple angles showing full body and head detail, "
            "Ghibli character model sheet style, 16:9"
        ),
        "inline_desc": (
            "massive 50-foot red dragon with dark crimson scales, amber eyes matching "
            "the serpent, ancient intelligent face, fearsome but purposeful"
        ),
    },
    "girl": {
        "ref_prompt": (
            f"{_GHIBLI_PREFIX}"
            "character reference sheet, young girl age 6, bright blonde hair in loose "
            "braids, light blue dress, bare feet, radiant smile, bright sparkling eyes "
            "full of joy, clean and dry appearance contrasting with the boy, multiple "
            "angles, Ghibli character model sheet style, 16:9"
        ),
        "inline_desc": (
            "young girl age 6 with bright blonde hair in loose braids, light blue "
            "dress, bare feet, radiant joyful smile, bright sparkling eyes"
        ),
    },
    "watcher": {
        "ref_prompt": (
            f"{_GHIBLI_PREFIX}"
            "Ghibli warrior character design, "
            "character reference sheet, tall woman warrior in dark ornate armor, "
            "vigilant stern expression, pointing hand, short dark hair, battle-worn "
            "but noble, standing atop a stone tower, Ghibli character model sheet style, 16:9"
        ),
        "inline_desc": (
            "tall armored woman watcher with dark ornate armor, vigilant stern "
            "expression, short dark hair, battle-worn noble bearing"
        ),
    },
    "glowing_woman": {
        "ref_prompt": (
            f"{_GHIBLI_PREFIX}"
            "ethereal Ghibli spirit character, "
            "character reference sheet, ethereal woman radiating warm golden-white "
            "light, serene compassionate expression, flowing white and gold robes, "
            "her light illuminates everything around her, calm presence contrasting "
            "with chaos, Ghibli character model sheet style, 16:9"
        ),
        "inline_desc": (
            "ethereal woman radiating warm golden-white light, flowing white and "
            "gold robes, serene compassionate expression"
        ),
    },
    "knight": {
        "ref_prompt": (
            f"{_GHIBLI_PREFIX}"
            "Ghibli noble warrior character, "
            "character reference sheet, knight in brilliant polished silver armor, "
            "raised sword, noble defiant stance, red cape, standing at the base of "
            "a tower, heroic but ultimately ignored by the dragon, "
            "Ghibli character model sheet style, 16:9"
        ),
        "inline_desc": (
            "knight in brilliant polished silver armor with raised sword, red cape, "
            "noble defiant heroic stance"
        ),
    },
}

STYLE_PREFIX_WARM = (
    "Studio Ghibli anime art style, Makoto Shinkai inspired, "
    "warm watercolor sky backgrounds with soft golden atmospheric light, "
    "soft cel shading with hand-drawn animation aesthetic, "
    "expressive characters with large emotive eyes, "
    "lush hand-painted nature environments with dreamy depth, "
    "cinematic 16:9 framing — "
)

STYLE_PREFIX_DARK = (
    "Studio Ghibli anime art style with dark dramatic tension, "
    "Makoto Shinkai inspired, ominous and foreboding atmosphere, "
    "dramatic shadows and deep reds against golden skies, "
    "characters maintain Ghibli proportions with imposing serious presence, "
    "Princess Mononoke intensity meets Spirited Away grandeur, "
    "cinematic 16:9 framing — "
)

STYLE_PREFIX = STYLE_PREFIX_WARM

SCENE_TONE: dict[int, str] = {
    1: "warm", 2: "warm", 3: "dark",
    4: "dark", 5: "dark", 6: "warm",
    7: "dark", 8: "dark", 9: "dark",
    10: "dark", 11: "dark", 12: "dark",
    13: "dark", 14: "dark", 15: "warm",
    16: "warm", 17: "dark", 18: "dark",
    19: "warm",
}

NEGATIVE_PROMPT_DARK = (
    "The dragon must be massive, ancient, dark crimson, imposing and serious. "
    "The serpent must be sleek, dark-scaled, mysterious and formidable. "
    "Neither creature should appear small, friendly, cute, or bright green."
)


def _get_style_prefix(scene_num: int) -> str:
    return STYLE_PREFIX_DARK if SCENE_TONE.get(scene_num, "warm") == "dark" else STYLE_PREFIX_WARM

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
    {"scene": 1, "motion": "Camera slowly pushes forward toward a young boy age 6 with messy brown hair, white linen shirt, brown shorts, bare feet clutching a small carved wooden dragon toy, he runs around a massive ancient oak tree in a golden meadow, leaves flutter in warm wind, golden light shifts subtly"},
    {"scene": 2, "motion": "Camera slowly descends toward a still puddle, a subtle ripple appears in the water, within the reflection a DARK ELEGANT SERPENT with iridescent green-black scales and ancient knowing amber eyes coils along a reflected branch, the young boy with messy brown hair crouches beside the puddle, tension builds"},
    {"scene": 3, "motion": "Subtle water ripples emanate from the DARK ELEGANT SERPENT with iridescent green-black scales and ancient knowing amber eyes coiled in the puddle reflection, the serpent looks wise but unsettling and deceptive not cute or friendly, the young boy with messy brown hair and wide curious eyes leans closer, light shifts on the water surface"},
    {"scene": 4, "motion": "Underwater camera slowly rises toward the surface, light rays shift through the water, in the foreground the shadow of the DARK ELEGANT SERPENT with iridescent green-black scales moves closer with deliberate ancient menace, above the silhouette of the young boy with messy brown hair kneels at the surface, bubbles rise"},
    {"scene": 5, "motion": "The young boy age 6 with messy brown hair and white linen shirt leans forward toward the puddle holding his wooden dragon toy with growing excitement, in the reflection the DARK ELEGANT SERPENT with iridescent green-black scales and glowing amber eyes pulses brighter, the serpent appears wise but deceptive"},
    {"scene": 6, "motion": "Fast joyful tracking shot following the young boy age 6 with messy brown hair and white linen shirt running through golden grass swooping his wooden dragon toy, his shadow on the ground subtly morphs into a dragon-like shape with wings, wind blows his hair"},
    {"scene": 7, "motion": "Stillness and tension, the young boy age 6 with messy brown hair and clenched fists stands at the edge of the puddle, his shoulders tense with anger and hurt, the puddle is perfectly still and empty showing no serpent, dusk light darkens ominously"},
    {"scene": 8, "motion": "EXPLOSIVE upward motion, a MASSIVE RED DRAGON with dark crimson scales and glowing amber eyes erupts its claw from the small puddle, the dragon is imposing and ancient, it reaches for the young boy with messy brown hair pulling him downward, water explodes in slow motion, debris hangs in air"},
    {"scene": 9, "motion": "Fast sweeping aerial flyover, the MASSIVE RED DRAGON with dark crimson scales and glowing amber eyes beats its powerful wings carrying the small young boy in its great talons, the dragon is ancient and imposing, fire trails from its jaws, vast fantasy landscape below with dark forests and stone fortresses, clouds part revealing biomes"},
    {"scene": 10, "motion": "The MASSIVE RED DRAGON with dark crimson scales swoops dramatically past a tall stone tower, on top stands a tall armored woman watcher with dark ornate armor pointing urgently, beside her an ethereal woman radiating warm golden-white light in flowing white and gold robes watches calmly, at the tower base a knight in brilliant polished silver armor with red cape raises his sword defiantly, the dragon roars with jaws wide"},
    {"scene": 11, "motion": "Camera slowly tilts upward from the tiny young boy with messy brown hair standing at ground level to the MASSIVE RED DRAGON with dark crimson scales and glowing amber eyes towering above, the dragon is ancient and overwhelming in scale, beside the boy an ancient spiraling stone well glows with runes"},
    {"scene": 12, "motion": "Camera slowly descends into well water, in the dark reflection the MASSIVE RED DRAGON with dark crimson scales and amber eyes towers above menacingly, the young boy with messy brown hair and frightened face looks down trembling, the dragon's deep voice reverberates through the water, the reflection ripples"},
    {"scene": 13, "motion": "The MASSIVE RED DRAGON with dark crimson scales and glowing amber eyes descends its huge jaws rapidly toward camera filling the entire frame, fire builds in the dragon's throat glowing orange-red, the young boy with messy brown hair stumbles backward in awe, extreme dramatic zoom, the dragon is ancient and formidable"},
    {"scene": 14, "motion": "The young boy with messy brown hair sinks through dark well water in slow motion clutching his wooden dragon toy to his chest, above him dragon fire from the MASSIVE RED DRAGON crashes against the water surface creating orange-red rippling light, below a bright white vortex of light pulls him downward, air bubbles trail"},
    {"scene": 15, "motion": "Perfect stillness, the young boy with messy brown hair stands soaking wet and motionless in a shallow puddle beneath the ancient oak tree, water drips slowly from him, his face shows shock and confusion, the puddle slowly calms, a single ripple expands outward, impossibly still golden meadow"},
    {"scene": 16, "motion": "A bright young girl age 6 with blonde hair in loose braids and light blue dress steps forward into frame laughing joyfully, the wet dark young boy with messy brown hair stares motionless and stunned, the puddle between them smooths to a perfect mirror, warm golden light"},
    {"scene": 17, "motion": "Extreme slow zoom into the young boy's eyes with messy brown hair and mud on his face, one pupil dilates and flashes amber dragon slit like the serpent's ancient knowing amber eyes then returns to normal, a knowing dangerous smile slowly creeps across his face, half golden light half dark shadow"},
    {"scene": 18, "motion": "The young boy with messy brown hair and the bright girl with blonde braids run away becoming small, camera descends to the still puddle, the DARK ELEGANT SERPENT with iridescent green-black scales materializes in the reflection, its ancient knowing amber eyes lock onto the viewer with deceptive menace, its mouth opens revealing flame within"},
    {"scene": 19, "motion": "On pure black, golden text materializes letter by letter with subtle shimmer particle effects, THERA-WORLD appears then subtitle fades in below"},
]


def _build_video_prompt(scene_num: int, motion_text: str) -> str:
    """Assemble the full video prompt with tone-appropriate style, character enforcement, and negative constraints."""
    prefix = _get_style_prefix(scene_num)

    preset_scenes = _load_preset("thera_world_origin") if (_PRESETS_DIR / "thera_world_origin.json").exists() else []
    scene_def = next((s for s in preset_scenes if s.get("scene") == scene_num), {})
    scene_chars = scene_def.get("characters", [])

    char_enforcement = ""
    if scene_chars:
        parts = []
        for char in scene_chars:
            ref = CHARACTER_REFERENCES.get(char)
            if ref:
                parts.append(ref["inline_desc"])
        if parts:
            char_enforcement = "CRITICAL — maintain exact character appearance: " + ". ".join(parts) + ". "

    prompt = prefix + char_enforcement + motion_text

    if SCENE_TONE.get(scene_num, "warm") == "dark":
        prompt += " " + NEGATIVE_PROMPT_DARK

    return prompt


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


def _build_consistent_prompt(scene_prompt: str, characters: list[str], scene_num: int = 0) -> str:
    """Prepend tone-aware style prefix and inline character descriptions for visual consistency."""
    prefix = _get_style_prefix(scene_num) if scene_num else STYLE_PREFIX
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

    prompt = prefix + char_block + resolved
    if scene_num and SCENE_TONE.get(scene_num, "warm") == "dark":
        prompt += " " + NEGATIVE_PROMPT_DARK
    return prompt


def _build_lora_prompt(scene_prompt: str, characters: list[str], trained_loras: dict[str, dict], scene_num: int = 0) -> str:
    """Build prompt for LoRA generation with trigger words replacing character descriptions."""
    prefix = _get_style_prefix(scene_num) if scene_num else STYLE_PREFIX
    trigger_parts = []
    for char in characters:
        lora_info = trained_loras.get(char)
        if lora_info:
            trigger_parts.append(lora_info["trigger_word"])
        else:
            ref = CHARACTER_REFERENCES.get(char)
            if ref:
                trigger_parts.append(ref["inline_desc"])

    resolved = scene_prompt
    for char_name, ref in CHARACTER_REFERENCES.items():
        lora_info = trained_loras.get(char_name)
        if lora_info:
            resolved = resolved.replace(f"{{{char_name}}}", lora_info["trigger_word"])
        else:
            resolved = resolved.replace(f"{{{char_name}}}", ref["inline_desc"])

    char_block = ""
    if trigger_parts:
        char_block = "Characters: " + ", ".join(trigger_parts) + ". "

    prompt = prefix + char_block + resolved
    if scene_num and SCENE_TONE.get(scene_num, "warm") == "dark":
        prompt += " " + NEGATIVE_PROMPT_DARK
    return prompt


async def _generate_image_with_lora_or_grok(
    prompt: str,
    characters: list[str],
    trained_loras: dict[str, dict],
) -> bytes:
    """Generate an image using trained LoRAs if available, else fall back to Grok Imagine.

    trained_loras: {character_key: {"lora_url": "https://...", "trigger_word": "THERA_BOY"}}
    """
    relevant_loras = {
        c: trained_loras[c] for c in characters if c in trained_loras and trained_loras[c].get("lora_url")
    }

    if relevant_loras:
        try:
            from app.sse.infrastructure.replicate_client import generate_with_loras
            lora_urls = [info["lora_url"] for info in relevant_loras.values()]
            lora_prompt = _build_lora_prompt(prompt, characters, trained_loras)
            logger.info("[LORA-GEN] Using %d LoRA(s) for characters: %s", len(lora_urls), list(relevant_loras.keys()))
            image_urls = await generate_with_loras(lora_prompt, lora_urls, width=1024, height=576)
            if image_urls:
                async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=30)) as sess:
                    async with sess.get(image_urls[0]) as resp:
                        if resp.status == 200:
                            return await resp.read()
                logger.warning("[LORA-GEN] Failed to download LoRA image, falling back to Grok")
        except Exception as e:
            logger.warning("[LORA-GEN] LoRA generation failed (%s), falling back to Grok", e)

    return await generate_image(prompt)


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


async def _load_trained_loras(project_id: str) -> dict[str, dict]:
    """Load trained LoRA weights from the project manifest.

    Returns {character_key: {"lora_url": "https://...", "trigger_word": "THERA_BOY"}}
    or empty dict if none trained.
    """
    manifest = await _load_manifest_from_r2(project_id)
    if not manifest:
        return {}
    return manifest.get("trained_loras", {})


async def save_trained_lora(project_id: str, character_key: str, lora_url: str) -> None:
    """Record a completed LoRA training result in the project manifest."""
    manifest = await _load_manifest_from_r2(project_id) or {}
    loras = manifest.get("trained_loras", {})
    loras[character_key] = {
        "lora_url": lora_url,
        "trigger_word": f"THERA_{character_key.upper()}",
        "trained_at": datetime.utcnow().isoformat(),
    }
    manifest["trained_loras"] = loras
    await _save_manifest_to_r2(project_id, manifest)


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

    If trained LoRA weights exist in the project manifest, uses Replicate Flux
    with those LoRAs for character-locked images. Falls back to Grok Imagine.
    If scenes is None, loads the thera_world_origin preset.
    """
    if scenes is None:
        scenes = _load_preset("thera_world_origin")

    os.makedirs(TRAILER_OUTPUT_DIR, exist_ok=True)

    logger.info("[TRAILER] Generating character references for project %s", project_id)
    refs = await generate_character_references(project_id)

    trained_loras = await _load_trained_loras(project_id)
    if trained_loras:
        logger.info("[TRAILER] Found trained LoRAs for: %s", list(trained_loras.keys()))

    results: list[dict] = []
    total = len(scenes)

    async with GROK_IMAGINE_LOCK:
        for scene in scenes:
            num = scene.get("scene", 0)
            title = scene.get("title", f"scene_{num}")
            characters = scene.get("characters", [])

            consistent_prompt = _build_consistent_prompt(scene["prompt"], characters, scene_num=num)

            logger.info("[TRAILER] Scene %d: %s", num, title)
            try:
                image_bytes = await _generate_image_with_lora_or_grok(
                    consistent_prompt, characters, trained_loras,
                )
                r2_key = f"sse/studio/projects/{project_id}/{num}.png"
                r2_url = await store_image(image_bytes, r2_key)
                used_lora = any(c in trained_loras for c in characters)
                results.append({"scene": num, "title": title, "r2_url": r2_url,
                                "r2_key": r2_key,
                                "status": "success", "cost": 0.07,
                                "used_lora": used_lora})
                logger.info("[TRAILER] Scene %d done (lora=%s)", num, used_lora)
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

async def _ken_burns_fallback(image_source: str, output_path: str, duration: int = 8) -> bool:
    """Generate a slow-zoom Ken Burns clip from a static image using FFmpeg.

    image_source can be an R2 key (no protocol) or a URL. R2 keys are
    downloaded via the S3 API directly, avoiding the broken public URL.
    """
    from app.sse.infrastructure.r2_storage import download_bytes as _r2_download

    img_bytes = None
    if image_source.startswith("http://") or image_source.startswith("https://"):
        try:
            async with aiohttp.ClientSession() as sess:
                async with sess.get(image_source) as r:
                    if r.status == 200:
                        img_bytes = await r.read()
        except Exception as e:
            logger.warning("[KEN-BURNS] HTTP download failed: %s", e)

    if img_bytes is None:
        r2_key = image_source
        if "://" in r2_key:
            parts = r2_key.split("/", 3)
            r2_key = parts[-1] if len(parts) > 3 else r2_key
        img_bytes = await _r2_download(r2_key)

    if not img_bytes:
        logger.warning("[KEN-BURNS] Could not obtain image bytes for %s", image_source)
        return False

    img_path = output_path.replace(".mp4", ".png")
    with open(img_path, "wb") as f:
        f.write(img_bytes)

    # Pre-scale to 2112x1188 (10% overshoot), then linear inward crop for
    # a smooth zoom-in effect. Much faster than zoompan on large images.
    vf = (
        "scale=2112:1188:force_original_aspect_ratio=decrease,"
        "pad=2112:1188:(ow-iw)/2:(oh-ih)/2,"
        f"crop=1920:1080:'96*(1-t/{duration})':'54*(1-t/{duration})'"
    )
    cmd = [
        "ffmpeg", "-y", "-loop", "1", "-t", str(duration), "-i", img_path,
        "-vf", vf, "-c:v", "libx264", "-pix_fmt", "yuv420p", "-r", "24",
        output_path,
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, timeout=30)
        if result.returncode != 0:
            logger.warning("[KEN-BURNS] FFmpeg exit %d: %s", result.returncode,
                           result.stderr.decode(errors="replace")[:500])
            return False
    except Exception as e:
        logger.warning("[KEN-BURNS] FFmpeg failed: %s", e)
        return False

    return os.path.exists(output_path)


# ---------------------------------------------------------------------------
#  Motion Video Generation
# ---------------------------------------------------------------------------

async def _build_manifest_from_individual_images(project_id: str) -> Optional[dict]:
    """Build a manifest from individually-generated scene images in R2."""
    from app.sse.infrastructure import r2_storage as _r2
    client = _r2._get_client()
    if client is None:
        return None

    prefix = f"sse/studio/projects/{project_id}/"
    try:
        def _list():
            return client.list_objects_v2(Bucket=_r2._R2_BUCKET, Prefix=prefix, MaxKeys=100)
        resp = await asyncio.get_event_loop().run_in_executor(None, _list)
    except Exception as e:
        logger.warning("[TRAILER-VIDEO] R2 list failed: %s", e)
        return None

    scenes = []
    for obj in resp.get("Contents", []):
        key = obj["Key"]
        filename = key.split("/")[-1]
        if not filename.endswith(".png") or filename.endswith("_ref.png"):
            continue
        try:
            scene_num = int(filename.replace(".png", ""))
        except ValueError:
            continue
        r2_url = _r2.presigned_url(key) or f"{_r2._R2_PUBLIC_BASE}/{key}"
        scenes.append({"scene": scene_num, "title": f"scene_{scene_num}", "r2_url": r2_url, "r2_key": key, "status": "success"})

    if not scenes:
        return None

    scenes.sort(key=lambda s: s["scene"])
    manifest = {"project_id": project_id, "scenes": scenes, "total": len(scenes),
                "success": len(scenes), "source": "individual_images"}
    logger.info("[TRAILER-VIDEO] Built manifest from %d individual images", len(scenes))
    return manifest


async def generate_motion_clips(project_id: str) -> list[dict]:
    """Extend hero images into 8s motion video clips with transition context.

    Falls back to Ken Burns if Grok Video fails.
    Grok Video cost: ~$4.00 per clip (4B ticks).
    """
    manifest = await _load_manifest_from_r2(project_id)
    if not manifest or not manifest.get("scenes"):
        manifest = await _build_manifest_from_individual_images(project_id)
    if not manifest or not manifest.get("scenes"):
        logger.warning("[TRAILER-VIDEO] No manifest or images found for project %s", project_id)
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

            motion_prompt = _build_video_prompt(scene_num, motion["motion"])

            logger.info("[TRAILER-VIDEO] Scene %d: %s", scene_num, scene_data["title"])

            try:
                video_id = await generate_video(motion_prompt, source_image_url=scene_data["r2_url"])

                video_url = None
                for attempt in range(60):
                    await asyncio.sleep(5)
                    poll = await poll_video_status(video_id)
                    if poll["status"] == "completed" and poll.get("url"):
                        video_url = poll["url"]
                        break
                    if poll["status"] == "failed":
                        break
                    if attempt % 6 == 0:
                        logger.info("[TRAILER-VIDEO] Polling %s — progress %s%% (%ds)",
                                    video_id, poll.get("progress", "?"), attempt * 5)

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
                                    "status": "success", "cost": 4.00,
                                })
                                logger.info("[TRAILER-VIDEO] Scene %d done (grok)", scene_num)
                                await asyncio.sleep(8)
                                continue

                raise RuntimeError("Grok Video returned no URL")

            except Exception as e:
                logger.warning("[TRAILER-VIDEO] Scene %d Grok Video failed: %s — trying Ken Burns", scene_num, e)

                work_dir = tempfile.mkdtemp(prefix="kb_")
                try:
                    kb_path = os.path.join(work_dir, f"scene_{scene_num:02d}.mp4")
                    img_src = scene_data.get("r2_key") or scene_data["r2_url"]
                    success = await _ken_burns_fallback(img_src, kb_path)

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
                finally:
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
#  Reusable Video-from-Image helper (supports end_frame interpolation)
# ---------------------------------------------------------------------------

async def _generate_video_from_image(
    image_url: str,
    motion_prompt: str,
    end_frame_url: str | None = None,
    duration_seconds: int = 8,
) -> dict | None:
    """Generate an 8s motion clip from a hero image, optionally interpolating toward end_frame.

    Returns dict with video_url, cost, etc. on success or None on failure.
    """
    payload: dict = {
        "model": "grok-imagine-video",
        "prompt": motion_prompt,
        "image_url": image_url,
    }
    if end_frame_url:
        payload["end_frame"] = end_frame_url

    from app.sse.infrastructure.grok_imagine_client import (
        _get_api_key, _get_fallback_key, _get_session, _headers_for,
        _VIDEO_URL,
    )

    key = _get_api_key()
    fallback = _get_fallback_key()
    session = _get_session()
    video_id: str | None = None

    for api_key in (key, fallback):
        if not api_key:
            continue
        try:
            async with session.post(_VIDEO_URL, json=payload, headers=_headers_for(api_key)) as resp:
                if resp.status == 429 and api_key == key:
                    continue
                if resp.status != 200:
                    body = await resp.text()
                    logger.warning("[VIDEO-GEN] HTTP %d: %s", resp.status, body[:300])
                    continue
                data = await resp.json()
                video_id = data.get("request_id") or data.get("id")
                break
        except Exception as e:
            logger.warning("[VIDEO-GEN] Request error: %s", e)

    if not video_id:
        return None

    for attempt in range(60):
        await asyncio.sleep(5)
        try:
            poll = await poll_video_status(video_id)
        except Exception as e:
            logger.warning("[VIDEO-GEN] Poll error attempt %d: %s", attempt, e)
            continue

        if poll["status"] == "completed" and poll.get("url"):
            return {
                "video_url": poll["url"],
                "video": {"url": poll["url"], "duration": poll.get("duration", 8)},
                "cost": 4.00,
                "progress": 100,
            }
        if poll["status"] == "failed":
            logger.warning("[VIDEO-GEN] Generation failed for %s", video_id)
            return None
        if attempt % 6 == 0:
            logger.info("[VIDEO-GEN] Polling %s — progress %s%%", video_id, poll.get("progress", "?"))

    logger.warning("[VIDEO-GEN] Timeout polling %s", video_id)
    return None


# ---------------------------------------------------------------------------
#  Last-Frame Extraction (FFmpeg)
# ---------------------------------------------------------------------------

BRANCH_POINTS = [1, 8, 15]


def _extract_last_frame(video_bytes: bytes, scene_num: int) -> bytes | None:
    """Extract the last frame of a video as PNG bytes. Returns None on failure."""
    work_dir = tempfile.mkdtemp(prefix=f"lastframe_{scene_num}_")
    try:
        vid_path = os.path.join(work_dir, f"scene_{scene_num:02d}.mp4")
        frame_path = os.path.join(work_dir, f"scene_{scene_num:02d}_last.png")
        with open(vid_path, "wb") as f:
            f.write(video_bytes)
        result = subprocess.run(
            ["ffmpeg", "-y", "-sseof", "-0.1", "-i", vid_path, "-frames:v", "1", frame_path],
            capture_output=True, timeout=30,
        )
        if result.returncode != 0 or not os.path.exists(frame_path):
            return None
        with open(frame_path, "rb") as f:
            return f.read()
    except Exception as e:
        logger.warning("[LAST-FRAME] Scene %d extraction failed: %s", scene_num, e)
        return None
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)


# ---------------------------------------------------------------------------
#  Interpolated Pipeline (start_frame + end_frame — DEFAULT mode)
# ---------------------------------------------------------------------------

async def generate_interpolated_trailer(
    project_id: str, resume_from: int | None = None,
    regenerate_with_lora: bool = True,
) -> list[dict]:
    """Generate trailer using start+end frame interpolation.

    If *regenerate_with_lora* is True and trained LoRAs exist, hero images
    are regenerated via LoRA before interpolation to lock character identity.

    Requires all 19 hero images pre-generated (status=success in manifest).
    Produces 18 transition clips (N→N+1) + 1 end card = 19 videos.
    Checkpoint saved after each successful clip.
    """
    manifest = await _load_manifest_from_r2(project_id)
    if not manifest or not manifest.get("scenes"):
        manifest = await _build_manifest_from_individual_images(project_id)
    if not manifest or not manifest.get("scenes"):
        logger.warning("[INTERPOLATE] No manifest or images for project %s", project_id)
        return []

    if regenerate_with_lora and resume_from is None:
        trained_loras = await _load_trained_loras(project_id)
        if trained_loras:
            preset_scenes = _load_preset("thera_world_origin") if _PRESETS_DIR.exists() else []
            preset_map = {s["scene"]: s for s in preset_scenes}
            for scene_data in manifest["scenes"]:
                if scene_data.get("status") != "success":
                    continue
                snum = scene_data["scene"]
                pdef = preset_map.get(snum, {})
                chars = pdef.get("characters", [])
                relevant = {c: trained_loras[c] for c in chars if c in trained_loras}
                if not relevant:
                    continue
                try:
                    prompt = _build_consistent_prompt(pdef.get("prompt", scene_data.get("title", "")), chars, scene_num=snum)
                    img = await _generate_image_with_lora_or_grok(prompt, chars, trained_loras)
                    key = f"sse/studio/projects/{project_id}/{snum}.png"
                    new_url = await store_image(img, key)
                    scene_data["r2_url"] = new_url
                    scene_data["used_lora"] = True
                    logger.info("[INTERPOLATE] LoRA-regenerated scene %d hero image", snum)
                except Exception as e:
                    logger.warning("[INTERPOLATE] LoRA regen failed scene %d: %s", snum, e)
            await _save_manifest_to_r2(project_id, manifest)

    scenes = sorted(
        [s for s in manifest["scenes"] if s.get("status") == "success"],
        key=lambda s: s["scene"],
    )
    if len(scenes) < 2:
        logger.warning("[INTERPOLATE] Need at least 2 scenes, got %d", len(scenes))
        return []

    from app.sse.infrastructure import r2_storage as _r2
    for sc in scenes:
        r2k = sc.get("r2_key", "")
        if not r2k:
            snum = sc["scene"]
            r2k = f"sse/studio/projects/{project_id}/{snum}.png"
            if not r2k:
                continue
        fresh = _r2.presigned_url(r2k, expires_in=7200)
        if fresh:
            sc["r2_url"] = fresh
            logger.debug("[INTERPOLATE] Refreshed presigned URL for scene %d", sc["scene"])

    motion_map = {m["scene"]: m for m in SCENE_MOTION_PROMPTS}

    results: list[dict] = []
    start_idx = 0

    if resume_from is not None:
        chain_state = manifest.get("chain_state", {})
        results = [c for c in chain_state.get("completed_clips", [])
                   if c.get("from_scene", 999) < resume_from]
        for idx, s in enumerate(scenes[:-1]):
            if s["scene"] >= resume_from:
                start_idx = idx
                break

    async with GROK_IMAGINE_LOCK:
        for i in range(start_idx, len(scenes) - 1):
            start_scene = scenes[i]
            end_scene = scenes[i + 1]
            motion = motion_map.get(start_scene["scene"], {"motion": "Smooth cinematic transition"})

            logger.info("[INTERPOLATE] Transition %d→%d...", start_scene["scene"], end_scene["scene"])

            video_result = await _generate_video_from_image(
                image_url=start_scene["r2_url"],
                motion_prompt=_build_video_prompt(start_scene["scene"], motion["motion"]),
                end_frame_url=end_scene["r2_url"],
            )

            if video_result and video_result.get("video_url"):
                video_url = video_result["video_url"]
                try:
                    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=60)) as dl:
                        async with dl.get(video_url) as vr:
                            if vr.status == 200:
                                vid_bytes = await vr.read()
                                vid_bytes = await _apply_faststart(vid_bytes)
                                r2_key = (
                                    f"sse/studio/projects/{project_id}/clips/"
                                    f"transition_{start_scene['scene']:02d}_to_{end_scene['scene']:02d}.mp4"
                                )
                                stored = await store_bytes(vid_bytes, r2_key, "video/mp4")
                                video_url = stored
                except Exception as e:
                    logger.warning("[INTERPOLATE] R2 upload failed: %s", e)

                results.append({
                    "from_scene": start_scene["scene"],
                    "to_scene": end_scene["scene"],
                    "video_url": video_url,
                    "status": "success",
                    "cost": 4.00,
                })

                chain_state = {
                    "mode": "interpolated",
                    "last_completed_transition": i,
                    "completed_clips": results,
                    "total_cost_so_far": sum(r.get("cost", 0) for r in results),
                }
                manifest["chain_state"] = chain_state
                await _save_manifest_to_r2(project_id, manifest)
            else:
                results.append({
                    "from_scene": start_scene["scene"],
                    "to_scene": end_scene["scene"],
                    "video_url": None,
                    "status": "failed",
                    "cost": 0,
                })

            await asyncio.sleep(8)

        # End card — use Ken Burns on the title image ($0, no Grok Video)
        # AI video models cannot reliably render specific text; the hero
        # image already contains the correct THERA-WORLD title.
        last_scene = scenes[-1]
        logger.info("[INTERPOLATE] End card scene %d (Ken Burns)...", last_scene["scene"])
        work_dir = tempfile.mkdtemp(prefix="endcard_")
        try:
            kb_path = os.path.join(work_dir, f"endcard_{last_scene['scene']:02d}.mp4")
            img_src = last_scene.get("r2_key") or last_scene["r2_url"]
            kb_ok = await _ken_burns_fallback(img_src, kb_path, duration=8)
            if kb_ok and os.path.exists(kb_path):
                with open(kb_path, "rb") as f:
                    kb_bytes = f.read()
                r2_key = f"sse/studio/projects/{project_id}/clips/endcard_{last_scene['scene']:02d}.mp4"
                stored = await store_bytes(kb_bytes, r2_key, "video/mp4")
                results.append({
                    "from_scene": last_scene["scene"],
                    "to_scene": None,
                    "video_url": stored,
                    "status": "success",
                    "cost": 0,
                })
            else:
                logger.warning("[INTERPOLATE] End card Ken Burns failed")
        finally:
            shutil.rmtree(work_dir, ignore_errors=True)

    video_manifest = {
        "project_id": project_id,
        "mode": "interpolated",
        "generated_at": datetime.utcnow().isoformat(),
        "clips": results,
        "total": len(results),
        "success": sum(1 for r in results if r["status"] == "success"),
        "total_cost": sum(r.get("cost", 0) for r in results),
    }
    await store_bytes(
        json.dumps(video_manifest, indent=2).encode(),
        f"sse/studio/projects/{project_id}/video_manifest.json",
        "application/json",
    )
    manifest["chain_state"] = {"mode": "interpolated", "completed": True, "completed_clips": results}
    await _save_manifest_to_r2(project_id, manifest)

    logger.info("[INTERPOLATE] Complete: %d/%d clips, $%.2f",
                video_manifest["success"], video_manifest["total"], video_manifest["total_cost"])
    return results


# ---------------------------------------------------------------------------
#  Video Manifest Clip Management
# ---------------------------------------------------------------------------

async def delete_video_clip(project_id: str, clip_index: int) -> dict:
    """Delete a single clip from the video manifest by index."""
    from app.sse.infrastructure.r2_storage import _get_client, _R2_BUCKET

    client = _get_client()
    if not client:
        return {"error": "R2 unavailable"}

    key = f"sse/studio/projects/{project_id}/video_manifest.json"
    try:
        resp = client.get_object(Bucket=_R2_BUCKET, Key=key)
        data = json.loads(resp["Body"].read().decode())
    except Exception:
        return {"error": "No video manifest found"}

    clips = data.get("clips", [])
    if clip_index < 0 or clip_index >= len(clips):
        return {"error": f"Invalid clip index {clip_index}, manifest has {len(clips)} clips"}

    removed = clips.pop(clip_index)
    data["clips"] = clips
    data["total"] = len(clips)
    data["success"] = sum(1 for c in clips if c.get("status") == "success")
    data["total_cost"] = sum(c.get("cost", 0) for c in clips)

    await store_bytes(json.dumps(data, indent=2).encode(), key, "application/json")
    return {"deleted": removed, "remaining": len(clips)}


async def deduplicate_video_manifest(project_id: str) -> dict:
    """Keep only the LAST clip for each unique transition, removing earlier duplicates."""
    from app.sse.infrastructure.r2_storage import _get_client, _R2_BUCKET

    client = _get_client()
    if not client:
        return {"error": "R2 unavailable"}

    key = f"sse/studio/projects/{project_id}/video_manifest.json"
    try:
        resp = client.get_object(Bucket=_R2_BUCKET, Key=key)
        data = json.loads(resp["Body"].read().decode())
    except Exception:
        return {"error": "No video manifest found"}

    clips = data.get("clips", [])
    before = len(clips)

    # Walk in reverse so the LAST occurrence (most recent) wins
    seen: dict[str, int] = {}
    unique: list[dict] = []
    for clip in reversed(clips):
        transition_key = f"{clip.get('from_scene')}->{clip.get('to_scene')}"
        if transition_key not in seen:
            seen[transition_key] = 1
            unique.append(clip)

    unique.reverse()
    data["clips"] = unique
    data["total"] = len(unique)
    data["success"] = sum(1 for c in unique if c.get("status") == "success")
    data["total_cost"] = sum(c.get("cost", 0) for c in unique)

    await store_bytes(json.dumps(data, indent=2).encode(), key, "application/json")
    return {"before": before, "after": len(unique), "removed": before - len(unique)}


# ---------------------------------------------------------------------------
#  Chain Pipeline (each scene from previous last frame)
# ---------------------------------------------------------------------------

async def generate_chain_trailer(
    project_id: str, resume_from: int | None = None,
) -> list[dict]:
    """Generate trailer using progressive chain method.

    Each scene extends from the previous scene's last frame.
    Branch points get fresh hero images with character references.
    """
    manifest = await _load_manifest_from_r2(project_id)
    if not manifest or not manifest.get("scenes"):
        manifest = await _build_manifest_from_individual_images(project_id)
    if not manifest or not manifest.get("scenes"):
        return []

    scenes = sorted(
        [s for s in manifest["scenes"] if s.get("status") == "success"],
        key=lambda s: s["scene"],
    )
    motion_map = {m["scene"]: m for m in SCENE_MOTION_PROMPTS}
    trained_loras = await _load_trained_loras(project_id)

    preset_scenes = _load_preset("thera_world_origin") if (_PRESETS_DIR / "thera_world_origin.json").exists() else []
    preset_map = {s["scene"]: s for s in preset_scenes}

    chain_state = manifest.get("chain_state", {})
    results: list[dict] = chain_state.get("completed_clips", [])
    previous_last_frame_url: str | None = chain_state.get("previous_last_frame_url")

    start_idx = 0
    if resume_from is not None:
        for idx, s in enumerate(scenes):
            if s["scene"] >= resume_from:
                start_idx = idx
                break

    async with GROK_IMAGINE_LOCK:
        for i in range(start_idx, len(scenes)):
            scene_data = scenes[i]
            scene_num = scene_data["scene"]
            motion = motion_map.get(scene_num, {"motion": "Smooth cinematic motion"})

            if scene_num in BRANCH_POINTS or previous_last_frame_url is None:
                if trained_loras and scene_num in preset_map:
                    chars = preset_map[scene_num].get("characters", [])
                    relevant = {c: trained_loras[c] for c in chars if c in trained_loras}
                    if relevant:
                        prompt = _build_consistent_prompt(preset_map[scene_num]["prompt"], chars, scene_num=scene_num)
                        try:
                            img = await _generate_image_with_lora_or_grok(prompt, chars, trained_loras)
                            branch_key = f"sse/studio/projects/{project_id}/chain/branch_{scene_num:02d}.png"
                            hero_url = await store_image(img, branch_key)
                            logger.info("[CHAIN] Branch %d: LoRA-generated hero image", scene_num)
                        except Exception as e:
                            logger.warning("[CHAIN] LoRA branch %d failed (%s), using existing image", scene_num, e)
                            hero_url = scene_data["r2_url"]
                    else:
                        hero_url = scene_data["r2_url"]
                else:
                    hero_url = scene_data["r2_url"]
            else:
                hero_url = previous_last_frame_url

            logger.info("[CHAIN] Scene %d: %s...", scene_num, scene_data.get("title", ""))

            video_result = await _generate_video_from_image(
                image_url=hero_url,
                motion_prompt=_build_video_prompt(scene_num, motion["motion"]),
            )

            if video_result and video_result.get("video_url"):
                video_url = video_result["video_url"]
                vid_bytes: bytes | None = None
                try:
                    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=60)) as dl:
                        async with dl.get(video_url) as vr:
                            if vr.status == 200:
                                vid_bytes = await vr.read()
                                r2_key = f"sse/studio/projects/{project_id}/clips/scene_{scene_num:02d}.mp4"
                                stored = await store_bytes(vid_bytes, r2_key, "video/mp4")
                                video_url = stored
                except Exception as e:
                    logger.warning("[CHAIN] R2 upload failed scene %d: %s", scene_num, e)

                if vid_bytes:
                    frame_bytes = _extract_last_frame(vid_bytes, scene_num)
                    if frame_bytes:
                        frame_r2_key = f"sse/studio/projects/{project_id}/chain/scene_{scene_num:02d}_lastframe.png"
                        previous_last_frame_url = await store_image(frame_bytes, frame_r2_key)
                    else:
                        previous_last_frame_url = None

                results.append({
                    "scene": scene_num, "title": scene_data.get("title", ""),
                    "video_url": video_url, "status": "success", "cost": 4.00,
                })
            else:
                results.append({
                    "scene": scene_num, "title": scene_data.get("title", ""),
                    "video_url": None, "status": "failed", "cost": 0,
                })

            chain_state = {
                "mode": "chain",
                "last_completed_scene": scene_num,
                "previous_last_frame_url": previous_last_frame_url,
                "completed_clips": results,
                "total_cost_so_far": sum(r.get("cost", 0) for r in results),
            }
            manifest["chain_state"] = chain_state

            next_scene = scenes[i + 1]["scene"] if i + 1 < len(scenes) else None
            if next_scene and next_scene in BRANCH_POINTS:
                chain_state["awaiting_approval"] = True
                chain_state["branch_scene"] = next_scene
                chain_state["branch_preview_url"] = hero_url
                manifest["chain_state"] = chain_state
                await _save_manifest_to_r2(project_id, manifest)
                logger.info("[CHAIN] Paused at branch point before scene %d — awaiting admin approval", next_scene)
                return results

            await _save_manifest_to_r2(project_id, manifest)
            await asyncio.sleep(8)

    video_manifest = {
        "project_id": project_id,
        "mode": "chain",
        "generated_at": datetime.utcnow().isoformat(),
        "clips": results,
        "total": len(results),
        "success": sum(1 for r in results if r["status"] == "success"),
        "total_cost": sum(r.get("cost", 0) for r in results),
    }
    await store_bytes(
        json.dumps(video_manifest, indent=2).encode(),
        f"sse/studio/projects/{project_id}/video_manifest.json",
        "application/json",
    )
    return results


async def approve_branch_point(project_id: str, action: str = "approve") -> dict:
    """Approve or reject a branch point pause, then resume chain generation.

    action: "approve" to continue, "regenerate" to re-gen the branch hero image.
    Returns the chain state or an error.
    """
    manifest = await _load_manifest_from_r2(project_id)
    if not manifest:
        return {"error": "Project not found"}

    chain_state = manifest.get("chain_state", {})
    if not chain_state.get("awaiting_approval"):
        return {"error": "No pending approval", "chain_state": chain_state}

    if action == "reject":
        chain_state["awaiting_approval"] = False
        chain_state["rejected"] = True
        manifest["chain_state"] = chain_state
        await _save_manifest_to_r2(project_id, manifest)
        return {"status": "rejected", "message": "Branch point rejected. Chain paused."}

    chain_state.pop("awaiting_approval", None)
    chain_state.pop("branch_scene", None)
    chain_state.pop("branch_preview_url", None)
    manifest["chain_state"] = chain_state
    await _save_manifest_to_r2(project_id, manifest)

    resume_scene = chain_state.get("last_completed_scene", 0) + 1
    return {"status": "approved", "resuming_from": resume_scene}


# ---------------------------------------------------------------------------
#  Cel Animation Compositing
# ---------------------------------------------------------------------------

def _build_composite_plate(
    character_ref_images: list[bytes],
    storyboard_bytes: bytes,
    previous_frame_bytes: bytes | None,
) -> bytes:
    """Build a composite reference plate: [char refs | storyboard | prev frame]."""
    import io
    from PIL import Image

    storyboard_img = Image.open(io.BytesIO(storyboard_bytes)).convert("RGB")
    sw, sh = storyboard_img.size

    ref_strip_width = sw // 3
    has_prev = previous_frame_bytes is not None
    canvas_width = ref_strip_width + sw + (ref_strip_width if has_prev else 0)
    canvas = Image.new("RGB", (canvas_width, sh), (0, 0, 0))

    if character_ref_images:
        ref_height = sh // max(len(character_ref_images), 1)
        y_offset = 0
        for ref_bytes in character_ref_images:
            ref_img = Image.open(io.BytesIO(ref_bytes)).convert("RGB")
            ref_img = ref_img.resize((ref_strip_width, ref_height))
            canvas.paste(ref_img, (0, y_offset))
            y_offset += ref_height

    canvas.paste(storyboard_img, (ref_strip_width, 0))

    if previous_frame_bytes:
        prev_img = Image.open(io.BytesIO(previous_frame_bytes)).convert("RGB")
        prev_img = prev_img.resize((ref_strip_width, sh))
        canvas.paste(prev_img, (ref_strip_width + sw, 0))

    buf = io.BytesIO()
    canvas.save(buf, format="JPEG", quality=90)
    return buf.getvalue()


async def generate_cel_animation_clip(
    project_id: str,
    scene_num: int,
    character_refs: dict[str, str | None],
    storyboard_url: str,
    previous_last_frame_url: str | None,
    motion_prompt: str,
) -> dict:
    """Generate a single scene using cel animation composite method.

    If trained LoRAs exist, generates fresh character reference images via LoRA
    instead of using the Grok-generated reference PNGs.
    """
    scene_def = next(
        (s for s in (_load_preset("thera_world_origin") if _PRESETS_DIR.exists() else [])
         if s.get("scene") == scene_num),
        {},
    )
    scene_characters = scene_def.get("characters", [])

    trained_loras = await _load_trained_loras(project_id)

    ref_images: list[bytes] = []
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=30)) as sess:
        for char in scene_characters[:3]:
            if char in trained_loras and trained_loras[char].get("lora_url"):
                try:
                    ref = CHARACTER_REFERENCES.get(char, {})
                    prompt = f"{STYLE_PREFIX}{ref.get('ref_prompt', char)}, full body reference sheet"
                    img = await _generate_image_with_lora_or_grok(prompt, [char], trained_loras)
                    ref_images.append(img)
                    continue
                except Exception as e:
                    logger.warning("[CEL] LoRA ref failed for %s: %s, falling back", char, e)
            url = character_refs.get(char)
            if not url:
                continue
            try:
                async with sess.get(url) as r:
                    if r.status == 200:
                        ref_images.append(await r.read())
            except Exception:
                pass

        try:
            async with sess.get(storyboard_url) as r:
                storyboard_bytes = await r.read() if r.status == 200 else b""
        except Exception:
            storyboard_bytes = b""

        prev_bytes: bytes | None = None
        if previous_last_frame_url:
            try:
                async with sess.get(previous_last_frame_url) as r:
                    if r.status == 200:
                        prev_bytes = await r.read()
            except Exception:
                pass

    if not storyboard_bytes:
        return {"scene": scene_num, "status": "failed_no_storyboard"}

    composite_bytes = _build_composite_plate(ref_images, storyboard_bytes, prev_bytes)
    composite_r2_key = f"sse/studio/projects/{project_id}/composites/scene_{scene_num:02d}_composite.jpg"
    composite_url = await store_image(composite_bytes, composite_r2_key)

    char_names = [
        CHARACTER_REFERENCES[c]["inline_desc"] for c in scene_characters if c in CHARACTER_REFERENCES
    ]
    _cel_prefix = _get_style_prefix(scene_num)
    animation_prompt = (
        f"{_cel_prefix}"
        f"ANIMATE the center panel of this reference plate. "
        f"The left panel shows the exact character design to use — "
        f"maintain these exact proportions, clothing, and features. "
        f"{'The right panel shows what just happened — continue smoothly from that motion. ' if prev_bytes else ''}"
        f"Characters in scene: {'; '.join(char_names)}. "
        f"Action: {motion_prompt}"
    )
    if SCENE_TONE.get(scene_num, "warm") == "dark":
        animation_prompt += " " + NEGATIVE_PROMPT_DARK

    video_result = await _generate_video_from_image(
        image_url=composite_url,
        motion_prompt=animation_prompt,
    )

    if not video_result or not video_result.get("video_url"):
        return {"scene": scene_num, "status": "failed"}

    work_dir = tempfile.mkdtemp(prefix=f"cel_{scene_num}_")
    try:
        video_url = video_result["video_url"]
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=60)) as sess:
            async with sess.get(video_url) as vr:
                if vr.status != 200:
                    return {"scene": scene_num, "status": "failed_download"}
                vid_bytes = await vr.read()

        raw_path = os.path.join(work_dir, f"scene_{scene_num:02d}_raw.mp4")
        cropped_path = os.path.join(work_dir, f"scene_{scene_num:02d}_cropped.mp4")
        with open(raw_path, "wb") as f:
            f.write(vid_bytes)

        import io
        from PIL import Image
        sb_img = Image.open(io.BytesIO(storyboard_bytes)).convert("RGB")
        sw, sh = sb_img.size
        crop_x = sw // 3

        subprocess.run([
            "ffmpeg", "-y", "-i", raw_path,
            "-vf", f"crop={sw}:{sh}:{crop_x}:0",
            "-c:v", "libx264", "-preset", "fast", "-crf", "20", "-pix_fmt", "yuv420p",
            cropped_path,
        ], capture_output=True, timeout=60)

        if not os.path.exists(cropped_path):
            cropped_path = raw_path

        with open(cropped_path, "rb") as f:
            cropped_bytes = f.read()

        clip_r2_key = f"sse/studio/projects/{project_id}/clips/scene_{scene_num:02d}.mp4"
        clip_url = await store_bytes(cropped_bytes, clip_r2_key, "video/mp4")

        frame_bytes = _extract_last_frame(cropped_bytes, scene_num)
        last_frame_url = None
        if frame_bytes:
            frame_key = f"sse/studio/projects/{project_id}/chain/scene_{scene_num:02d}_lastframe.png"
            last_frame_url = await store_image(frame_bytes, frame_key)

        return {
            "scene": scene_num,
            "clip_url": clip_url,
            "last_frame_url": last_frame_url,
            "status": "success",
            "cost": 4.00,
        }
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)


# ---------------------------------------------------------------------------
#  LoRA Training Variations
# ---------------------------------------------------------------------------

LORA_TRAINING_VARIATIONS = [
    "standing facing camera, neutral pose",
    "looking to the left, three-quarter view",
    "looking to the right, three-quarter view",
    "sitting on the ground, relaxed",
    "running to the right, dynamic action pose",
    "arms raised above head, joyful expression",
    "looking down, thoughtful expression",
    "looking up at the sky, wonder on face",
    "crouching down, examining something on the ground",
    "side profile, walking left",
    "back view, looking over shoulder",
    "close-up portrait, head and shoulders only",
    "full body, standing in meadow with wind blowing",
    "full body, dramatic lighting from below",
    "full body, soft golden sunset lighting",
    "medium shot, hands together, contemplative",
    "dynamic pose, leaping forward",
    "sitting on a rock, legs dangling",
    "standing in rain, looking up with determination",
    "gentle smile, holding out hand toward camera",
]


async def generate_lora_training_set(
    project_id: str, character: str, count: int = 20,
) -> list[dict]:
    """Generate training images for LoRA fine-tuning of a specific character."""
    ref = CHARACTER_REFERENCES.get(character)
    if not ref:
        raise ValueError(f"Unknown character: {character}")

    results: list[dict] = []
    async with GROK_IMAGINE_LOCK:
        for i in range(min(count, len(LORA_TRAINING_VARIATIONS))):
            variation = LORA_TRAINING_VARIATIONS[i]
            prompt = f"{STYLE_PREFIX}{ref['ref_prompt']}, {variation}"
            try:
                img_bytes = await generate_image(prompt)
                r2_key = f"sse/studio/projects/{project_id}/lora/{character}/train_{i:02d}.png"
                r2_url = await store_image(img_bytes, r2_key)
                results.append({"index": i, "r2_url": r2_url, "status": "success"})
            except Exception as e:
                results.append({"index": i, "r2_url": None, "status": f"error: {str(e)[:100]}"})
            await asyncio.sleep(3)

    return results


async def zip_lora_training_images(project_id: str, character: str) -> str | None:
    """Collect generated training images from R2, zip them, upload zip, return URL."""
    from app.sse.infrastructure import r2_storage as _r2
    client = _r2._get_client()
    if not client:
        return None

    prefix = f"sse/studio/projects/{project_id}/lora/{character}/"
    work_dir = tempfile.mkdtemp(prefix="lora_zip_")
    try:
        def _list():
            return client.list_objects_v2(Bucket=_r2._R2_BUCKET, Prefix=prefix)
        resp = await asyncio.get_event_loop().run_in_executor(None, _list)
        contents = resp.get("Contents", [])
        png_keys = [c["Key"] for c in contents if c["Key"].endswith(".png")]
        if not png_keys:
            return None

        img_dir = os.path.join(work_dir, "images")
        os.makedirs(img_dir, exist_ok=True)

        for key in png_keys:
            fname = key.rsplit("/", 1)[-1]
            def _dl(k=key):
                return client.get_object(Bucket=_r2._R2_BUCKET, Key=k)
            obj = await asyncio.get_event_loop().run_in_executor(None, _dl)
            with open(os.path.join(img_dir, fname), "wb") as f:
                f.write(obj["Body"].read())

        zip_path = os.path.join(work_dir, f"{character}_training.zip")
        import zipfile
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for fname in os.listdir(img_dir):
                zf.write(os.path.join(img_dir, fname), fname)

        zip_key = f"sse/studio/projects/{project_id}/lora/{character}_training.zip"
        with open(zip_path, "rb") as f:
            url = await store_bytes(f.read(), zip_key, "application/zip")
        return url
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)


# ---------------------------------------------------------------------------
#  Narration Audio Merge (into stitched trailer)
# ---------------------------------------------------------------------------

async def _merge_narration_audio(
    video_path: str,
    narration_files: dict[int, str],
    scene_offsets: dict[int, float],
    output_path: str,
) -> bool:
    """Overlay positioned narration audio onto a video.

    For each scene with narration, pads with silence to match its offset,
    then mixes all tracks and overlays onto the video.
    """
    if not narration_files:
        return False

    work_dir = tempfile.mkdtemp(prefix="narr_merge_")
    try:
        positioned_tracks: list[str] = []
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=30)) as sess:
            for scene_num, narr_url in sorted(narration_files.items()):
                offset = scene_offsets.get(scene_num, 0.0)
                local_narr = os.path.join(work_dir, f"narr_{scene_num:02d}.wav")
                try:
                    async with sess.get(narr_url) as r:
                        if r.status == 200:
                            with open(local_narr, "wb") as f:
                                f.write(await r.read())
                        else:
                            continue
                except Exception:
                    continue

                positioned = os.path.join(work_dir, f"positioned_{scene_num:02d}.wav")
                if offset > 0.1:
                    subprocess.run([
                        "ffmpeg", "-y",
                        "-f", "lavfi", "-t", f"{offset:.2f}", "-i", "anullsrc=r=44100:cl=mono",
                        "-i", local_narr,
                        "-filter_complex", "[0][1]concat=n=2:v=0:a=1",
                        positioned,
                    ], capture_output=True, timeout=30)
                else:
                    shutil.copy(local_narr, positioned)

                if os.path.exists(positioned):
                    positioned_tracks.append(positioned)

        if not positioned_tracks:
            return False

        combined = os.path.join(work_dir, "combined_narration.wav")
        if len(positioned_tracks) == 1:
            shutil.copy(positioned_tracks[0], combined)
        else:
            inputs: list[str] = []
            filter_parts: list[str] = []
            for idx, t in enumerate(positioned_tracks):
                inputs.extend(["-i", t])
                filter_parts.append(f"[{idx}]")
            amix_filter = "".join(filter_parts) + f"amix=inputs={len(positioned_tracks)}:duration=longest"
            cmd = ["ffmpeg", "-y"] + inputs + ["-filter_complex", amix_filter, combined]
            subprocess.run(cmd, capture_output=True, timeout=60)

        if not os.path.exists(combined):
            return False

        subprocess.run([
            "ffmpeg", "-y", "-i", video_path, "-i", combined,
            "-c:v", "copy", "-c:a", "aac", "-map", "0:v", "-map", "1:a",
            "-shortest", output_path,
        ], capture_output=True, timeout=300)
        return os.path.exists(output_path)
    except Exception as e:
        logger.warning("[NARR-MERGE] Error: %s", e)
        return False
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)


# ---------------------------------------------------------------------------
#  Unified Pipeline Orchestrator
# ---------------------------------------------------------------------------

async def generate_congruent_trailer(
    project_id: str,
    mode: str = "interpolated",
    resume_from: int | None = None,
) -> list[dict]:
    """Master orchestrator for all congruent generation modes.

    LoRA is auto-detected from the project manifest — no flag needed.
    Modes: interpolated (default), chain, cel, independent.
    """
    if mode == "interpolated":
        return await generate_interpolated_trailer(project_id, resume_from=resume_from)
    elif mode == "chain":
        return await generate_chain_trailer(project_id, resume_from=resume_from)
    elif mode == "cel":
        manifest = await _load_manifest_from_r2(project_id)
        if not manifest or not manifest.get("scenes"):
            return []
        scenes = sorted(
            [s for s in manifest["scenes"] if s.get("status") == "success"],
            key=lambda s: s["scene"],
        )
        refs = manifest.get("character_refs", {})
        motion_map = {m["scene"]: m for m in SCENE_MOTION_PROMPTS}
        results: list[dict] = []
        previous_last_frame: str | None = None

        for scene_data in scenes:
            scene_num = scene_data["scene"]
            if scene_num in BRANCH_POINTS:
                previous_last_frame = None
            motion = motion_map.get(scene_num, {"motion": "Smooth cinematic motion"})
            result = await generate_cel_animation_clip(
                project_id=project_id,
                scene_num=scene_num,
                character_refs=refs,
                storyboard_url=scene_data["r2_url"],
                previous_last_frame_url=previous_last_frame,
                motion_prompt=motion["motion"],
            )
            results.append(result)
            if result.get("status") == "success" and result.get("last_frame_url"):
                previous_last_frame = result["last_frame_url"]
            await asyncio.sleep(8)

        video_manifest = {
            "project_id": project_id,
            "mode": "cel",
            "generated_at": datetime.utcnow().isoformat(),
            "clips": results,
            "total": len(results),
            "success": sum(1 for r in results if r.get("status") == "success"),
            "total_cost": sum(r.get("cost", 0) for r in results),
        }
        await store_bytes(
            json.dumps(video_manifest, indent=2).encode(),
            f"sse/studio/projects/{project_id}/video_manifest.json",
            "application/json",
        )
        return results
    else:
        return await generate_motion_clips(project_id)


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


AVAILABLE_TTS_VOICES = ["alloy", "ash", "ballad", "coral", "echo", "fable", "onyx", "nova", "sage", "shimmer"]


async def get_voice_config(project_id: str) -> dict[str, dict]:
    """Return project voice overrides merged with defaults."""
    manifest = await _load_manifest_from_r2(project_id)
    overrides = (manifest or {}).get("voice_overrides", {})
    merged = {}
    for char, cfg in CHARACTER_VOICES.items():
        merged[char] = {**cfg, **(overrides.get(char, {}))}
    return merged


async def set_voice_override(project_id: str, character: str, voice: str, instructions: str | None = None) -> dict:
    """Persist a per-project voice override for a character."""
    manifest = await _load_manifest_from_r2(project_id) or {}
    overrides = manifest.get("voice_overrides", {})
    overrides[character] = {"voice": voice}
    if instructions is not None:
        overrides[character]["instructions"] = instructions
    manifest["voice_overrides"] = overrides
    await _save_manifest_to_r2(project_id, manifest)
    return overrides[character]


async def _generate_all_narration(project_id: str, work_dir: str) -> dict[int, str]:
    """Generate TTS audio for all dialogue scenes. Returns {scene_num: r2_url}."""
    preset_scenes = _load_preset("thera_world_origin")
    dialogue_map = {s["scene"]: s.get("dialogue", []) for s in preset_scenes if s.get("dialogue")}
    voice_map = await get_voice_config(project_id)

    narration_dir = os.path.join(work_dir, "narration")
    os.makedirs(narration_dir, exist_ok=True)

    results: dict[int, str] = {}

    for scene_num, lines in sorted(dialogue_map.items()):
        if not lines:
            continue

        scene_audio_parts: list[str] = []

        for i, line in enumerate(lines):
            voice_cfg = voice_map.get(line["voice"], CHARACTER_VOICES.get("boy", {"voice": "shimmer", "instructions": ""}))
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

COLOR_GRADE_PRESETS = {
    "ghibli_warm": (
        "colorbalance=rs=0.08:gs=0.03:bs=-0.08,"
        "eq=gamma=1.05:saturation=1.15:contrast=1.05,"
        "unsharp=5:5:0.5:5:5:0"
    ),
    "cool_night": (
        "colorbalance=rs=-0.06:gs=0.0:bs=0.10,"
        "eq=gamma=0.95:saturation=0.90:contrast=1.10,"
        "unsharp=5:5:0.4:5:5:0"
    ),
    "neutral": (
        "eq=gamma=1.0:saturation=1.0:contrast=1.0,"
        "unsharp=5:5:0.3:5:5:0"
    ),
    "sunset_drama": (
        "colorbalance=rs=0.12:gs=0.05:bs=-0.10,"
        "eq=gamma=1.10:saturation=1.25:contrast=1.08,"
        "unsharp=5:5:0.6:5:5:0"
    ),
}


async def stitch_trailer(project_id: str, options: dict | None = None) -> Optional[dict]:
    """Stitch clips into a congruent trailer with post-processing.

    Pipeline: download clips → color grade → concat → narration overlay → format convert.
    """
    options = options or {}
    include_color_grade = options.get("include_color_grade", True)
    color_preset = options.get("color_preset", "ghibli_warm")
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
    raw_clips = [c for c in video_manifest.get("clips", []) if c.get("status") in ("success", "ken_burns")]
    for c in raw_clips:
        if "scene" not in c and "from_scene" in c:
            c["scene"] = c["from_scene"]
    successful = sorted(raw_clips, key=lambda c: c.get("scene", 0))

    if len(successful) < 2:
        logger.warning("[STITCH] Only %d clips — need at least 2", len(successful))
        return None

    work_dir = tempfile.mkdtemp(prefix="stitch_")
    clip_dir = os.path.join(work_dir, "clips")
    graded_dir = os.path.join(work_dir, "graded")
    os.makedirs(clip_dir)
    os.makedirs(graded_dir)

    try:
        logger.info("[STITCH] Downloading %d clips from R2...", len(successful))
        for clip in successful:
            local = os.path.join(clip_dir, f"scene_{clip['scene']:02d}.mp4")
            try:
                # Build R2 key from clip metadata — bypasses stale presigned URLs
                fs = clip.get("from_scene", clip.get("scene", 0))
                ts = clip.get("to_scene")
                if ts is not None:
                    r2_key = f"sse/studio/projects/{project_id}/clips/transition_{fs:02d}_to_{ts:02d}.mp4"
                else:
                    r2_key = f"sse/studio/projects/{project_id}/clips/endcard_{fs:02d}.mp4"

                def _dl(k=r2_key):
                    return client.get_object(Bucket=_r2._R2_BUCKET, Key=k)["Body"].read()

                vid_data = await asyncio.get_event_loop().run_in_executor(None, _dl)
                if len(vid_data) > 1000:
                    with open(local, "wb") as f:
                        f.write(vid_data)
                    logger.info("[STITCH] Downloaded %s (%dKB)", r2_key.split("/")[-1], len(vid_data) // 1024)
            except Exception as e:
                logger.warning("[STITCH] Download failed scene %d: %s", clip["scene"], e)

        if include_color_grade:
            grade_filter = COLOR_GRADE_PRESETS.get(color_preset, COLOR_GRADE_PRESETS["ghibli_warm"])
            logger.info("[STITCH] Applying color grade preset '%s'...", color_preset)
            for clip in successful:
                src = os.path.join(clip_dir, f"scene_{clip['scene']:02d}.mp4")
                dst = os.path.join(graded_dir, f"scene_{clip['scene']:02d}.mp4")
                if os.path.exists(src):
                    cmd = [
                        "ffmpeg", "-y", "-i", src,
                        "-vf", grade_filter,
                        "-c:v", "libx264", "-preset", "fast",
                        "-crf", "20", "-pix_fmt", "yuv420p", dst,
                    ]
                    subprocess.run(cmd, capture_output=True, timeout=120)
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
        ], capture_output=True, timeout=900)

        final_output = raw_output

        if include_narration and narration_files:
            scene_offsets: dict[int, float] = {}
            cumulative = 0.0
            for clip in successful:
                scene_offsets[clip["scene"]] = cumulative
                cumulative += 8.0
            narrated = os.path.join(work_dir, "trailer_narrated.mp4")
            if await _merge_narration_audio(raw_output, narration_files, scene_offsets, narrated):
                final_output = narrated

        if output_format == "9:16":
            vert = os.path.join(work_dir, "trailer_vertical.mp4")
            subprocess.run([
                "ffmpeg", "-y", "-i", final_output,
                "-vf", "crop=ih*9/16:ih,scale=1080:1920",
                "-c:v", "libx264", "-preset", "fast", "-crf", "22", vert,
            ], capture_output=True, timeout=600)
            if os.path.exists(vert):
                final_output = vert
        elif output_format == "1:1":
            sq = os.path.join(work_dir, "trailer_square.mp4")
            subprocess.run([
                "ffmpeg", "-y", "-i", final_output,
                "-vf", "crop=min(iw\\,ih):min(iw\\,ih),scale=1080:1080",
                "-c:v", "libx264", "-preset", "fast", "-crf", "22", sq,
            ], capture_output=True, timeout=600)
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
        results["color_preset"] = color_preset if include_color_grade else None
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
