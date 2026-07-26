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
import re
import shutil
import subprocess
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Optional, Sequence

import aiohttp

from app.sse.infrastructure.grok_imagine_client import (
    GROK_IMAGINE_LOCK,
    generate_image,
    generate_video,
    poll_video_status,
)
from app.sse.infrastructure.r2_storage import download_bytes, presigned_url, store_bytes, store_image

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

DEFAULT_PRESET_ID = "thera_world_origin"
FAMILY_SANCTUARY_PRESET_ID = "family_sanctuary_origin"
COUNSELING_OFFICE_PRESET_ID = "counseling_office_origin"

_COUNSELING_OFFICE_REF_BASE = (
    "High-quality playful cartoon character reference model sheet, widescreen 16:9, "
    "sleek modern futuristic counseling office illustration language — soft LED ambient light, "
    "clear inked outlines, soft cel-like shading, warm fun professional tone — "
    "NOT Studio Ghibli, NOT photorealistic, NO real brand logos — "
)
# Locks marketing hero narration to hero_video_thera_world_NARRATED.mp4 pipeline:
# backend/app/sse/hero_narration_mix.py → _generate_tts(..., voice=THERA_HERO_NARRATED_TTS_VOICE, ...)
THERA_HERO_NARRATED_TTS_VOICE = "ash"


# ---------------------------------------------------------------------------
#  Character Reference System
# ---------------------------------------------------------------------------

_GHIBLI_PREFIX = (
    "Studio Ghibli anime art style, soft cel shading, "
    "expressive large emotive eyes, hand-drawn animation aesthetic, "
)

_THERA_FAMILY_REF_BASE = (
    "Cinematic painterly fantasy character reference model sheet, widescreen 16:9, "
    "volumetric warm gold and amber cinematic lighting honoring luminous melanin-rich skin, "
    "full tonal color depth — never flat monochrome or desaturated gray skin surfaces — "
    "epic heartfelt fantasy illustration not anime — "
)

THERA_WORLD_CHARACTER_REFERENCES = {
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

FAMILY_SANCTUARY_CHARACTER_REFERENCES = {
    "mother": {
        "ref_prompt": (
            f"{_THERA_FAMILY_REF_BASE}"
            "African American woman late thirties to early forties warm umber skin natural coily or "
            "curly hair twist-out or braided crown long flowing terracotta sage or amber earth-tone "
            "dress subtle West African kente or mudcloth textile hint at sleeves or hem contemporary elegance "
            "protective steady matriarch expression neutral front three-quarter and profile rotations "
            "consistent proportions locking identity plate."
        ),
        "inline_desc": (
            "African American mother late 30s–early 40s warm umber skin natural coily or crown-braided "
            "hair long earth-toned dress with subtle mudcloth accent steady protective matriarch"
        ),
    },
    "daughter": {
        "ref_prompt": (
            f"{_THERA_FAMILY_REF_BASE}"
            "Exactly one 11-year-old African American girl pre-teen realistic school-age proportions "
            "NOT toddler NOT preschool documented-photo natural head-to-body ratio bright yellow dress "
            "with small pockets two natural puffs colorful beads waist-up portrait wonder turning toward fear "
            "curious lean-forward expression."
        ),
        "inline_desc": (
            "11-year-old African American girl pre-teen twin puffs with beads yellow pocket dress "
            "wonder-to-fear expression waist-up"
        ),
    },
    "son": {
        "ref_prompt": (
            f"{_THERA_FAMILY_REF_BASE}"
            "African American teen brother thirteen through fifteen subtle deeper complexion short fade "
            "or twists graphic tee layered unbuttoned earth overshirt dark jeans sneakers watchful courageous "
            "proto-man bearing multiple rotation reference sheet cohesive family facial harmony."
        ),
        "inline_desc": (
            "African American son age 13–15 faded graphic tee open earth-tone overshirt fade haircut "
            "protective attentive brother courageous emerging poise"
        ),
    },
    "father": {
        "ref_prompt": (
            f"{_THERA_FAMILY_REF_BASE}"
            "African American father early forties tall grounded deep umber skin close cropped hair trimmed "
            "beard faint dignified gray flecks charcoal or forest henley layered dark pants leather boots "
            "magnetic commanding calm eyes capable of snapping from stunned loss to luminous resolve without "
            "cowardice multiple angles emphasizing familial likeness to daughter and son."
        ),
        "inline_desc": (
            "African American father early 40s deep umber skin henley and boots close beard steel-trim "
            "composure shocks then steels into deliberate protector resolve"
        ),
    },
}

COUNSELING_OFFICE_CHARACTER_REFERENCES = {
    "little_nate": {
        "ref_prompt": (
            f"{_COUNSELING_OFFICE_REF_BASE}"
            "character reference sheet, friendly middle-aged man salt-and-pepper grey hair warm smile, "
            "bright yellow button-up shirt, clear rectangular name tag reading Little Nate AI Companion, "
            "often holding classic red rotary phone labeled Call Coach, front three-quarter and profile "
            "rotations, consistent proportions, soft LED studio rim light, white-to-soft-cyan background."
        ),
        "inline_desc": (
            "friendly middle-aged Little Nate with salt-and-pepper grey hair, warm smile, bright yellow "
            "button-up shirt, clear name tag reading Little Nate AI Companion, Call Coach red rotary phone"
        ),
    },
    "ask_client": {
        "ref_prompt": (
            f"{_COUNSELING_OFFICE_REF_BASE}"
            "character reference sheet, African American woman with curly dark hair, yellow top and blue "
            "pants, holding open blue hardcover book titled Ask Little Nate, interested seeking-counseling "
            "expression, warm luminous skin rendering, front three-quarter and profile rotations, "
            "consistent cartoon proportions."
        ),
        "inline_desc": (
            "African American woman with curly dark hair, yellow top and blue pants, holding open blue "
            "Ask Little Nate book, interested seeking-counseling expression"
        ),
    },
    "penguin_bot": {
        "ref_prompt": (
            f"{_COUNSELING_OFFICE_REF_BASE}"
            "character reference sheet, cute blue penguin AI companion with round glasses, friendly "
            "expressive eyes, holding small Ask Little Nate book, soft rounded cartoon proportions, "
            "multiple angles front three-quarter profile, same counseling-office palette."
        ),
        "inline_desc": (
            "cute blue penguin character with glasses holding an Ask Little Nate book, friendly AI companion"
        ),
    },
    "hallway_bot": {
        "ref_prompt": (
            f"{_COUNSELING_OFFICE_REF_BASE}"
            "character reference sheet, friendly generic AI chatbot robot — rounded soft body, cheerful "
            "LED face panel or speech-bubble head accent, non-threatening colorful accents, waiting-line "
            "pose, multiple angles, same playful cartoon counseling-office language as Little Nate pack."
        ),
        "inline_desc": (
            "friendly generic AI chatbot robot with rounded soft body and cheerful LED face, hallway-queue vibe"
        ),
    },
}


CHARACTER_REFERENCES_BY_PRESET: dict[str, dict[str, dict]] = {
    DEFAULT_PRESET_ID: THERA_WORLD_CHARACTER_REFERENCES,
    FAMILY_SANCTUARY_PRESET_ID: FAMILY_SANCTUARY_CHARACTER_REFERENCES,
    COUNSELING_OFFICE_PRESET_ID: COUNSELING_OFFICE_CHARACTER_REFERENCES,
}


def _char_refs(preset_id: str | None = None) -> dict[str, dict]:
    """Return CHARACTER_REFERENCES for a preset bundle (backward compat defaults to Thera World)."""
    pid = preset_id or DEFAULT_PRESET_ID
    return CHARACTER_REFERENCES_BY_PRESET.get(pid, THERA_WORLD_CHARACTER_REFERENCES)


# Backward-compat export: canonical Thera-World character map (historic import sites / LoRA tooling).
CHARACTER_REFERENCES = THERA_WORLD_CHARACTER_REFERENCES

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
    "little_nate": {
        "voice": "ash",
        "instructions": "Speak as Little Nate — warm middle-aged companion, calm professional humor, gentle authority, never salesy.",
    },
    "ask_client": {
        "voice": "nova",
        "instructions": "Speak as a thoughtful adult seeking counseling — curious, hopeful, grounded, emotionally open.",
    },
    "penguin_bot": {
        "voice": "shimmer",
        "instructions": "Speak as a cute friendly AI penguin — bright, earnest, playful but sincere.",
    },
    "hallway_bot": {
        "voice": "echo",
        "instructions": "Speak as a cheerful generic chatbot in line — polite, upbeat, short phrases.",
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


# ---------------------------------------------------------------------------
#  Preset document & motion map (preset_id-scoped refs + scene motion)
# ---------------------------------------------------------------------------

def _load_preset_document(preset_id: str | None = None) -> dict:
    """Load full preset JSON (scenes + casting_locksheet + output hints)."""
    pid = preset_id or DEFAULT_PRESET_ID
    preset_path = _PRESETS_DIR / f"{pid}.json"
    if not preset_path.exists():
        raise FileNotFoundError(f"Preset '{pid}' not found at {preset_path}")
    with open(preset_path, encoding="utf-8") as f:
        return json.load(f)


def _load_preset(preset_id: str | None = None) -> list[dict]:
    """Scene list only; default preserves historic thera_world_origin behavior."""
    return _load_preset_document(preset_id).get("scenes", [])


def _manifest_preset_id(manifest: dict | None, fallback_preset: str | None = None) -> str:
    if not manifest:
        return fallback_preset or DEFAULT_PRESET_ID
    raw = manifest.get("preset_id")
    if isinstance(raw, str) and raw in CHARACTER_REFERENCES_BY_PRESET:
        return raw
    doc_id = manifest.get("preset_bundle_id")  # optional explicit bundle id if ever needed
    if isinstance(doc_id, str) and doc_id in CHARACTER_REFERENCES_BY_PRESET:
        return doc_id
    # Merged preset root (id matches filename bundle) — never treat arbitrary UUIDs as presets
    root_id = manifest.get("id")
    if isinstance(root_id, str) and root_id in CHARACTER_REFERENCES_BY_PRESET:
        return root_id
    return fallback_preset or DEFAULT_PRESET_ID


def _r2_character_png_key(project_id: str, char_name: str, preset_id: str, doc: dict) -> str:
    out = doc.get("output") or {}
    prefix = out.get("r2_character_prefix")
    if isinstance(prefix, str) and prefix.strip():
        return prefix.rstrip("/") + f"/{char_name}.png"
    return f"sse/studio/projects/{project_id}/refs/{char_name}_ref.png"


def _r2_character_refs_manifest_key(project_id: str, doc: dict) -> str:
    out = doc.get("output") or {}
    prefix = out.get("r2_character_prefix")
    if isinstance(prefix, str) and prefix.strip():
        return prefix.rstrip("/") + "/manifest.json"
    return f"sse/studio/projects/{project_id}/refs/manifest.json"


def _casting_lock_hints(character_ids: list[str], doc: dict) -> str:
    """Cel-animation / motion lock strings from preset casting_locksheet (authoritative)."""
    lock = doc.get("casting_locksheet") or {}
    chunks: list[str] = []
    for c in character_ids:
        v = lock.get(c)
        if isinstance(v, str) and v.strip():
            chunks.append(f"{c}: {v.strip()}")
    if not chunks:
        return ""
    return " CASTING LOCK (authoritative likeness): " + " | ".join(chunks)


# Compressed likeness block for Grok Video only (4096-char API cap). Keeps key constraints without
# duplicating the lengthy casting_locksheet + inline_desc stack used for still generation.
_FAMILY_SANCTUARY_VIDEO_CAST_COMPRESSED = {
    "mother": (
        "AA woman late 30s–early 40s, warm umber; braid/twist-out crown; terracotta+sage gown, subtle mudcloth/"
        "kente at cuffs/hem contemporary; protective matriarch, senses mirror tension first."
    ),
    "daughter": (
        "Girl 10–12 (school-age proportions, not toddler); twin Afro puffs+beads; bright yellow pocket dress; "
        "waist-up; wonder→fear leaning toward ripple."
    ),
    "son": (
        "AA boy 13–15; fade/twists; graphic tee + half-open earth overshirt, dark denim+sneaks; guarding sister "
        "then startling into courage."
    ),
    "father": (
        "AA father ~early 40s, deep umber, cropped hair, beard with temple salt ONLY (match henley ref; not "
        "silver-fox/old); fitted navy/charcoal henley, dark pants, boots — shock→quiet RESOLVE to follow family "
        "into mercury glass (never coward/hesitating)."
    ),
}

_FS_GROK_VIDEO_STYLE_PREFIX = (
    "Painterly cinematic fantasy hero (NOT anime): jewel volumetric warmth, grain, sanctuary awe — "
    "Black/African American skin warm umber/amber (never flat gray monochrome); quartet reads as one biological "
    "family consistent bone/jaw/eye harmony. "
    "16:9 cinematic — "
)

# Grok Imagine Video prompt hard cap (API fails silently above ~4096 chars).
_MAX_GROK_VIDEO_PROMPT_CHARS = 4096
# Grok Imagine **image** prompt cap (undocumented; prod uses ~8k safe ceiling).
_MAX_GROK_IMAGE_PROMPT_CHARS = 8000

_FS_STEP5_OVERRIDE_MOTION_SUFFIX = (
    "Minimal motion only: subtle breathing, slight fabric drift, micro head movement — preserve source still wardrobe "
    "and hairstyles exactly; no walking cycles; no costume or hair changes; no new background people."
)

# Scene 1 only: Grok-video sometimes ignores generic NOT-anime fuse — prepend this full-strength anchor for Act1 open beat.
_FS_GROK_VIDEO_SCENE1_PHOTOREAL_LEAD = (
    "SCENE1 PHOTOREAL ANCHOR: live-action cinematic fantasy film still LOOK — volumetric jewel light photoreal painterly DEPTH "
    "(match Scenes 2–10 still style) — FORBIDDEN animated cartoon Flash/Toon shaded look FORBIDDEN flat 2D cel FORBIDDEN anime "
    "FORBIDDEN Saturday-morning illustration — MUST READ as photographed practical fantasy miniature stage feel NOT drawn series. "
)


def _family_sanctuary_grok_video_casting_lock(character_ids: list[str]) -> str:
    if not character_ids:
        return ""
    chunks = []
    for c in character_ids:
        prose = _FAMILY_SANCTUARY_VIDEO_CAST_COMPRESSED.get(c)
        if prose:
            chunks.append(f"{c}: {prose}")
    if not chunks:
        return ""
    return "CAST LOCK — " + " | ".join(chunks) + " "


def preset_character_keys(preset_id: str | None = None) -> list[str]:
    """Public helper for budgeting / UX — ordered keys of CHARACTER_REFERENCES for a preset bundle."""
    return list(_char_refs(preset_id).keys())


def _motion_prompts_map(preset_id: str | None = None) -> dict[int, dict]:
    """Scene number → {\"scene\", \"motion\"}; Family preset derives motion from JSON (motion or prompt excerpt)."""
    pid = preset_id or DEFAULT_PRESET_ID
    if pid == DEFAULT_PRESET_ID:
        return {m["scene"]: m for m in SCENE_MOTION_PROMPTS}

    doc = _load_preset_document(pid)
    out: dict[int, dict] = {}
    max_prompt_motion = 1200
    for s in doc.get("scenes", []) or []:
        sn = int(s.get("scene", 0) or 0)
        motion = (s.get("motion") or "").strip()
        if not motion:
            ptxt = (s.get("prompt") or "").strip().replace("\n", " ")
            motion = (ptxt[:max_prompt_motion] + ("…" if len(ptxt) > max_prompt_motion else "")) if ptxt else ""
        if pid == FAMILY_SANCTUARY_PRESET_ID:
            layered = _family_sanctuary_motion_prompt_layers(sn)
            if layered:
                motion = f"{layered} — {motion}" if motion else layered
        out[sn] = {"scene": sn, "motion": motion}
    return out


def _branch_points_for_preset(preset_id: str | None = None) -> list[int]:
    doc = _load_preset_document(preset_id)
    bp = doc.get("branch_points")
    if isinstance(bp, list) and bp:
        return sorted({int(x) for x in bp})
    pid = preset_id or DEFAULT_PRESET_ID
    if pid == DEFAULT_PRESET_ID:
        return [1, 8, 15]
    return [1]


def _get_style_prefix(scene_num: int, preset_id: str | None = None) -> str:
    """Warm/dark Studio Ghibli prefix for Thera-World; visual_style_anchor fuse for other presets."""
    pid = preset_id or DEFAULT_PRESET_ID
    if pid == DEFAULT_PRESET_ID:
        return STYLE_PREFIX_DARK if SCENE_TONE.get(scene_num, "warm") == "dark" else STYLE_PREFIX_WARM

    doc = _load_preset_document(pid)
    scene_def = next((x for x in doc.get("scenes", []) or [] if x.get("scene") == scene_num), {})
    anchor = doc.get("visual_style_anchor") or {}
    fused = " ".join(
        s.strip()
        for s in (
            anchor.get("look"),
            anchor.get("skin_lighting_mandate"),
            anchor.get("family_identity_mandate"),
            anchor.get("cartoon_consistency_mandate"),
            anchor.get("office_atmosphere_mandate"),
        )
        if isinstance(s, str) and s.strip()
    )
    if fused.strip():
        return fused.strip() + " — cinematic 16:9 framing — "
    tone = str(scene_def.get("tone") or "").lower()
    return STYLE_PREFIX_DARK if "dark" in tone else STYLE_PREFIX_WARM


def _append_dragon_negative_if_applicable(prompt: str, scene_num: int, preset_id: str | None = None) -> str:
    """Thera-world dark scenes only — avoid polluting unrelated hero presets."""
    pid = preset_id or DEFAULT_PRESET_ID
    if pid != DEFAULT_PRESET_ID:
        return prompt
    if SCENE_TONE.get(scene_num, "warm") == "dark":
        return prompt + " " + NEGATIVE_PROMPT_DARK
    return prompt


def _family_sanctuary_step5_video_prompt(
    scene_num: int,
    *,
    motion_map: dict[int, dict],
    per_scene_prompt_overrides: dict[int, str] | None,
) -> str:
    """Assemble Grok Video prompt; optional per-scene override replaces preset motion + casting lock."""
    ovr = per_scene_prompt_overrides or {}
    if scene_num in ovr:
        assembled = _FS_GROK_VIDEO_STYLE_PREFIX + (ovr[scene_num] or "").strip()
    else:
        motion = motion_map.get(scene_num, {"motion": "Smooth cinematic painterly motion"})
        assembled = _build_video_prompt(scene_num, motion["motion"], preset_id=FAMILY_SANCTUARY_PRESET_ID)
    if len(assembled) > _MAX_GROK_VIDEO_PROMPT_CHARS:
        assembled = assembled[:_MAX_GROK_VIDEO_PROMPT_CHARS]
    return assembled


def _build_video_prompt(
    scene_num: int,
    motion_text: str,
    preset_id: str | None = None,
) -> str:
    """Assemble the full video prompt: style prefix, casting lock, character enforcement, motion."""
    pid = preset_id or DEFAULT_PRESET_ID
    doc = _load_preset_document(pid)

    scene_def = next((s for s in doc.get("scenes", []) or [] if s.get("scene") == scene_num), {})
    scene_chars = scene_def.get("characters") or []

    # Family Sanctuary (Grok Video): condensed fuse + CAST LOCK avoids duplicating lengthy
    # CRITICAL-inline + full casting_locksheet (still used for Steps 3–4 still generation elsewhere).
    if pid == FAMILY_SANCTUARY_PRESET_ID:
        fuse = _FS_GROK_VIDEO_STYLE_PREFIX
        # Scene 12: moderation-safe motion — silhouette/composition lock only (no age bands in Grok Video prompt).
        if scene_num == 12:
            vlock = (
                "CAST LOCK — silhouette-outline ONLY: preserve exactly four distinct linked figures viewed from behind; "
                "two taller outer silhouettes with two shorter between; motion keeps outline readable as one kin group marching "
                "toward distant glow; forbid replacing cast with four identical women matching ceremonial gowns priestess rows. "
            )
        else:
            vlock = _family_sanctuary_grok_video_casting_lock(scene_chars)
        lead = _FS_GROK_VIDEO_SCENE1_PHOTOREAL_LEAD if scene_num == 1 else ""
        assembled = lead + fuse + vlock + motion_text
        return _append_dragon_negative_if_applicable(assembled, scene_num, pid)

    prefix = _get_style_prefix(scene_num, pid)
    refs = _char_refs(pid)
    parts: list[str] = []
    for char in scene_chars:
        ref = refs.get(char)
        if ref:
            parts.append(ref["inline_desc"])
    char_enforcement = ""
    if parts:
        char_enforcement = "CRITICAL — maintain exact character appearance: " + ". ".join(parts) + ". "

    lock = _casting_lock_hints(scene_chars, doc)
    assembled = prefix + char_enforcement + lock + motion_text
    return _append_dragon_negative_if_applicable(assembled, scene_num, pid)


# ---------------------------------------------------------------------------
#  Helpers
# ---------------------------------------------------------------------------

def _build_consistent_prompt(
    scene_prompt: str,
    characters: list[str],
    scene_num: int = 0,
    preset_id: str | None = None,
) -> str:
    """Prepend tone-aware style prefix and inline character descriptions for visual consistency."""
    pid = preset_id or DEFAULT_PRESET_ID
    if scene_num:
        prefix = _get_style_prefix(scene_num, pid)
    else:
        prefix = STYLE_PREFIX if pid == DEFAULT_PRESET_ID else _get_style_prefix(1, pid)

    refs_map = _char_refs(pid)
    char_descs: list[str] = []
    for char in characters:
        ref = refs_map.get(char)
        if ref:
            char_descs.append(ref["inline_desc"])

    char_block = ""
    if char_descs:
        char_block = "Characters in scene (maintain exact appearance): " + "; ".join(char_descs) + ". "

    resolved = scene_prompt
    for char_name, ref in refs_map.items():
        resolved = resolved.replace(f"{{{char_name}}}", ref["inline_desc"])

    doc = _load_preset_document(pid)
    lock = _casting_lock_hints(characters, doc)
    prompt = prefix + char_block + lock + resolved
    if not scene_num:
        return prompt
    return _append_dragon_negative_if_applicable(prompt, scene_num, pid)


def _build_lora_prompt(
    scene_prompt: str,
    characters: list[str],
    trained_loras: dict[str, dict],
    scene_num: int = 0,
    preset_id: str | None = None,
) -> str:
    """Build prompt for LoRA generation with trigger words replacing character descriptions."""
    pid = preset_id or DEFAULT_PRESET_ID
    if scene_num:
        prefix = _get_style_prefix(scene_num, pid)
    else:
        prefix = STYLE_PREFIX if pid == DEFAULT_PRESET_ID else _get_style_prefix(1, pid)

    refs_map = _char_refs(pid)
    trigger_parts: list[str] = []
    for char in characters:
        lora_info = trained_loras.get(char)
        if lora_info:
            trigger_parts.append(lora_info["trigger_word"])
        else:
            ref = refs_map.get(char)
            if ref:
                trigger_parts.append(ref["inline_desc"])

    resolved = scene_prompt
    for char_name, ref in refs_map.items():
        lora_info = trained_loras.get(char_name)
        if lora_info:
            resolved = resolved.replace(f"{{{char_name}}}", lora_info["trigger_word"])
        else:
            resolved = resolved.replace(f"{{{char_name}}}", ref["inline_desc"])

    char_block = ""
    if trigger_parts:
        char_block = "Characters: " + ", ".join(trigger_parts) + ". "

    prompt = prefix + char_block + resolved
    if not scene_num:
        return prompt
    return _append_dragon_negative_if_applicable(prompt, scene_num, pid)


async def _generate_image_with_lora_or_grok(
    prompt: str,
    characters: list[str],
    trained_loras: dict[str, dict],
    scene_num: int = 0,
    preset_id: str | None = None,
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
            lora_prompt = _build_lora_prompt(
                prompt,
                characters,
                trained_loras,
                scene_num=scene_num,
                preset_id=preset_id,
            )
            char_keys = list(relevant_loras.keys())
            logger.info("[LORA-GEN] Using %d LoRA(s) for characters: %s", len(lora_urls), char_keys)
            image_urls = await generate_with_loras(
                lora_prompt, lora_urls, width=1024, height=576, character_keys=char_keys,
            )
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

_FAMILY_REF_LIGHTING_APPENDIX = (
    " Lighting and skin: cinematic warm gold key-and-fill on richly rendered Black/African "
    "American skin — luminous umber tonal complexity, Bradford Young– or Ava DuVernay–inspired "
    "color discipline; NEVER flat monochrome, muddy desaturated skin, or lifeless gray shadow. "
    "Contemporary wardrobe only — mother's West African textile accents read as elegant modern dress, "
    "not theatrical costume."
)
_FAMILY_REF_SOLITARY_APPENDIX = (
    " HARD CONSTRAINT — exactly one living human in frame; ZERO other family members spectators twins "
    "stand-ins body doubles or partial second faces at frame edge; ZERO group shots TWO subjects or "
    "crowds ZERO mirrors showing another figure; NEVER render screenplay notes stage directions subtitles "
    "loglines quotes brand marks watermarks captions UI typography or spelled-out prompts as visible pixels."
)


_FAMILY_REF_STUDIO_FRAMING_APPENDIX = (
    " Format: SINGLE studio portrait waist-up centered subject softly lit warm gold fill with rich saturated "
    "shadows NEVER murky monochrome skin; serene neutral matte backdrop seamless; gaze slightly past lens "
    "left or right NOT staring intensity; dignified relaxed mouth; painterly cinematic illustration NOT collage "
    "NOT multi-panel NO diptych NO comic strip panels NO turnaround contact sheet ONE composition only."
)


def _fuse_visual_style_anchor(doc: dict) -> str:
    anchor = doc.get("visual_style_anchor") or {}
    return " ".join(
        s.strip()
        for s in (
            anchor.get("look"),
            anchor.get("skin_lighting_mandate"),
            anchor.get("family_identity_mandate"),
        )
        if isinstance(s, str) and s.strip()
    )


def _lock_text_visual_only(lock_text: str, char_name: str) -> str:
    """Drop screenplay shout lines (often ALL CAPS) that models paint as typography — father's sheet triggers this."""
    t = lock_text.strip()
    if char_name == "father":
        parts = re.split(r"\bcritical\b", t, maxsplit=1, flags=re.IGNORECASE)
        t = parts[0].strip()
    return t


def _family_character_ref_prompt_from_preset(
    doc: dict,
    char_name: str,
    fallback: dict,
) -> str:
    """Authoritative likeness text from preset casting_locksheet (no Python duplicate prose)."""
    lock = doc.get("casting_locksheet") or {}
    lock_raw = lock.get(char_name)
    if not isinstance(lock_raw, str) or not lock_raw.strip():
        logger.warning("[TRAILER-REF] Missing casting_locksheet[%s] — using fallback ref_prompt", char_name)
        return fallback.get("ref_prompt", "")

    lock_use = _lock_text_visual_only(lock_raw, char_name)

    fused = _fuse_visual_style_anchor(doc)
    extra_father = ""
    if char_name == "father":
        extra_father = (
            " Emotional read: deliberate grounded resolve after a silent decision steady eyes jaw set squared "
            "shoulders inhalation of readiness — never anxious never hesitant never boyish slump ONE adult "
            "man waist-up solitary frame."
        )
    extra_daughter = ""
    if char_name == "daughter":
        extra_daughter = (
            " AGE LOCK — she is exactly one 10–12-year-old African American pre-teen girl (state as "
            "11-year-old African American girl); fifth–sixth-grade school age; visibly old enough for "
            "purposeful curiosity and readable fear NOT an infant NOT a preschooler NOT age 4–7. "
            "PROPORTIONS — match real documentary or school-photo reference of African American girls "
            "age 10–12 natural anatomical ratios NOT storybook toddler NOT chibi NOT anime big-head cute "
            "NOT illustrated picture-book children. FRAMING — strict waist-up portrait crop consistent with "
            "father and son companion refs cropped at waist NO full-length NO legs NO feet NO distant "
            "wide shot. KEEP costume: bright sunflower-yellow dress small visible pockets sleeves optional "
            "two natural Afro puffs with colorful beads. EXPRESSION subtle wonder edging into fear leaning "
            "slightly forward as if reaching toward curiosity one subject only."
        )

    head = [_THERA_FAMILY_REF_BASE.strip()]
    if fused:
        head.append(fused)
    head_joined = " ".join(head)

    plate = (
        f"{head_joined} "
        f"{lock_use} "
        f"{_FAMILY_REF_STUDIO_FRAMING_APPENDIX}"
        f"{_FAMILY_REF_LIGHTING_APPENDIX}{_FAMILY_REF_SOLITARY_APPENDIX}{extra_father}{extra_daughter}"
    )
    return " ".join(plate.split())


def _character_ref_generation_prompt(
    preset_id: str,
    doc: dict,
    char_name: str,
    char_fallback: dict,
) -> str:
    if preset_id == FAMILY_SANCTUARY_PRESET_ID:
        return _family_character_ref_prompt_from_preset(doc, char_name, char_fallback)
    return str(char_fallback.get("ref_prompt") or "")


async def _merge_character_ref_manifest(
    mkey: str,
    partial: dict[str, Optional[str]],
) -> dict[str, Optional[str]]:
    """Preserve existing URLs when regenerating a subset (e.g. daughter only)."""
    raw = await download_bytes(mkey)
    base: dict[str, Optional[str]] = {}
    if raw:
        try:
            parsed = json.loads(raw.decode())
            if isinstance(parsed, dict):
                base = {str(k): (v if v is None else str(v)) for k, v in parsed.items()}
        except Exception:
            logger.warning("[TRAILER-REF] existing manifest unreadable — partial keys only: %s", mkey)
    merged = dict(base)
    merged.update(partial)
    return merged


async def generate_character_references(
    project_id: str,
    preset_id: str | None = None,
    only_characters: Sequence[str] | None = None,
) -> dict[str, Optional[str]]:
    """Generate reference images for characters in one preset bundle. Returns {name: r2_url}.

    If *only_characters* is set, only those roles are generated and uploaded; existing entries in
    the preset's character manifest on R2 are merged so approved siblings are not dropped.
    """
    pid = preset_id or DEFAULT_PRESET_ID
    doc = _load_preset_document(pid)
    refs_map = _char_refs(pid)
    refs: dict[str, Optional[str]] = {}
    only_set: set[str] | None = None
    if only_characters:
        only_set = {x.strip().lower() for x in only_characters if isinstance(x, str) and x.strip()}
        unknown = only_set - {k.lower() for k in refs_map}
        if unknown:
            raise ValueError(f"only_characters: unknown roles {unknown!r}")

    async with GROK_IMAGINE_LOCK:
        for char_name, char_data in refs_map.items():
            if only_set is not None and char_name.lower() not in only_set:
                continue
            logger.info("[TRAILER-REF] preset=%s Generating reference: %s", pid, char_name)
            try:
                gen_prompt = _character_ref_generation_prompt(pid, doc, char_name, char_data)
                if not gen_prompt.strip():
                    raise ValueError("empty character ref prompt")
                image_bytes = await generate_image(gen_prompt)
                r2_key = _r2_character_png_key(project_id, char_name, pid, doc)
                r2_url = await store_image(image_bytes, r2_key)
                refs[char_name] = r2_url
                logger.info("[TRAILER-REF] %s done", char_name)
            except Exception as e:
                logger.warning("[TRAILER-REF] %s failed: %s", char_name, e)
                refs[char_name] = None
            await asyncio.sleep(5)

    mkey = _r2_character_refs_manifest_key(project_id, doc)
    if only_set is not None:
        merged = await _merge_character_ref_manifest(mkey, refs)
        await store_bytes(json.dumps(merged).encode(), mkey, "application/json")
        return merged

    await store_bytes(json.dumps(refs).encode(), mkey, "application/json")
    return refs


# ---------------------------------------------------------------------------
#  Hero Image Generation (Phase 2 — character-consistent)
# ---------------------------------------------------------------------------

async def generate_all_scenes(
    project_id: str,
    scenes: list[dict] | None = None,
    preset_id: str | None = None,
) -> list[dict]:
    """Generate hero images with character consistency.

    If trained LoRA weights exist in the project manifest, uses Replicate Flux
    with those LoRAs for character-locked images. Falls back to Grok Imagine.
    If scenes is None, loads preset scenes for *preset_id* (defaults to thera_world_origin).
    """
    pid = preset_id or DEFAULT_PRESET_ID
    if scenes is None:
        scenes = _load_preset(pid)

    os.makedirs(TRAILER_OUTPUT_DIR, exist_ok=True)

    logger.info("[TRAILER] Generating character references for project %s preset=%s", project_id, pid)
    refs = await generate_character_references(project_id, preset_id=pid)

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

            consistent_prompt = _build_consistent_prompt(
                scene["prompt"], characters, scene_num=num, preset_id=pid,
            )

            logger.info("[TRAILER] Scene %d: %s", num, title)
            try:
                image_bytes = await _generate_image_with_lora_or_grok(
                    consistent_prompt, characters, trained_loras,
                    scene_num=num, preset_id=pid,
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
        "preset_id": pid,
        "generated_at": datetime.utcnow().isoformat(),
        "character_refs": refs,
        "scenes": results,
        "total": total,
        "success": sum(1 for r in results if r.get("status") == "success"),
        "total_cost": sum(r.get("cost", 0) for r in results),
        "style_prefix": STYLE_PREFIX if pid == DEFAULT_PRESET_ID else _get_style_prefix(1, pid),
    }
    await _save_manifest_to_r2(project_id, manifest)

    logger.info("[TRAILER] Complete: %d/%d scenes, $%.2f",
                manifest["success"], total, manifest["total_cost"])
    return results


# ---------------------------------------------------------------------------
#  Ken Burns Fallback (static image → slow zoom video)
# ---------------------------------------------------------------------------

async def _ken_burns_fallback(image_source: str, output_path: str, duration: float = 8.0) -> bool:
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

    preset_id = _manifest_preset_id(manifest)
    successful_scenes = [s for s in manifest["scenes"] if s.get("status") == "success"]
    motion_map = _motion_prompts_map(preset_id)
    results: list[dict] = []

    async with GROK_IMAGINE_LOCK:
        for scene_data in successful_scenes:
            scene_num = scene_data["scene"]
            motion = motion_map.get(scene_num)
            if not motion:
                continue

            motion_prompt = _build_video_prompt(scene_num, motion["motion"], preset_id=preset_id)

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
        _get_studio_key, _get_fallback_key, _get_session, _headers_for,
        _VIDEO_URL,
    )

    key = _get_studio_key()
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

# Exported for scripts; chain trailer uses `_branch_points_for_preset(preset_id)` at runtime.
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

    preset_id = _manifest_preset_id(manifest)

    if regenerate_with_lora and resume_from is None:
        trained_loras = await _load_trained_loras(project_id)
        if trained_loras:
            preset_scenes = _load_preset(preset_id) if _PRESETS_DIR.exists() else []
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
                    prompt = _build_consistent_prompt(
                        pdef.get("prompt", scene_data.get("title", "")),
                        chars,
                        scene_num=snum,
                        preset_id=preset_id,
                    )
                    img = await _generate_image_with_lora_or_grok(
                        prompt,
                        chars,
                        trained_loras,
                        scene_num=snum,
                        preset_id=preset_id,
                    )
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

    motion_map = _motion_prompts_map(preset_id)

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
                motion_prompt=_build_video_prompt(
                    start_scene["scene"], motion["motion"], preset_id=preset_id,
                ),
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

    preset_id = _manifest_preset_id(manifest)

    scenes = sorted(
        [s for s in manifest["scenes"] if s.get("status") == "success"],
        key=lambda s: s["scene"],
    )
    motion_map = _motion_prompts_map(preset_id)
    trained_loras = await _load_trained_loras(project_id)

    preset_scenes = _load_preset(preset_id) if (_PRESETS_DIR / f"{preset_id}.json").exists() else []
    preset_map = {s["scene"]: s for s in preset_scenes}
    branches = _branch_points_for_preset(preset_id)

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

            if scene_num in branches or previous_last_frame_url is None:
                if trained_loras and scene_num in preset_map:
                    chars = preset_map[scene_num].get("characters", [])
                    relevant = {c: trained_loras[c] for c in chars if c in trained_loras}
                    if relevant:
                        prompt = _build_consistent_prompt(
                            preset_map[scene_num]["prompt"],
                            chars,
                            scene_num=scene_num,
                            preset_id=preset_id,
                        )
                        try:
                            img = await _generate_image_with_lora_or_grok(
                                prompt,
                                chars,
                                trained_loras,
                                scene_num=scene_num,
                                preset_id=preset_id,
                            )
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
                motion_prompt=_build_video_prompt(scene_num, motion["motion"], preset_id=preset_id),
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
            if next_scene and next_scene in branches:
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

FAMILY_SANCTUARY_SCENE_R2_PREFIX = "sse/trailer/family_sanctuary/scenes"
FAMILY_SANCTUARY_HERO_SCENE_IMAGE_COST_USD = 0.07
# Canonical left-strip order — always stacked for Step 3 identity pinning.
FAMILY_SANCTUARY_CEL_REF_ROLES_ORDER: tuple[str, ...] = ("mother", "daughter", "son", "father")


def _family_sanctuary_scene_png_key(scene_num: int) -> str:
    return f"{FAMILY_SANCTUARY_SCENE_R2_PREFIX}/scene_{int(scene_num):02d}.png"


# Step 3 surgical regen (PATH B drift fix): narrative + identity stack for audited scenes only.
_FAMILY_SANCTUARY_AUDIT_REGEN_SCENES: frozenset[int] = frozenset({2, 3, 4, 5, 8, 9})

_FAMILY_SANCT_AUDIT_SCENE_NARRATIVES: dict[int, str] = {
    2: (
        "Family in mirror chamber—mother's hand on daughter's shoulder, all four reacting to portal awakening. "
        "Mercury glass mirror, fogged stone sanctum, hearth-amber bounce light. Daughter TWIN AFRO PUFFS with beads, "
        "never single Afro."
    ),
    3: (
        "Daughter reaches toward portal; mother BESIDE her protectively; father and son visible; four family ONLY. "
        "Same mercury fogged stone chamber—vault/pillars paint cleanly to ALL frame edges—NO white or gray corner "
        "rectangles, blank slabs, or UI-frame artifacts."
    ),
    4: (
        "Family of four seeing portal pulse with energy—mother foreground center, father behind, son and daughter "
        "flanking; ONLY four family members visible; mercury chamber continuity; fogged stone sanctum."
    ),
    5: (
        "Family of four braced against portal force—son foreground, mother in background, father and daughter visible. "
        "ONLY the four named family members; no other women, no extras."
    ),
    8: (
        "Father at center frame; mother, son, daughter behind him mid-resolve to follow into portal. "
        "ONLY four people: father, mother, son, daughter from refs—no robed extras, no ceremonial figures, no crowd."
    ),
    9: (
        "Father takes step forward; mother, son, daughter closing ranks behind him. Four family members ONLY."
    ),
}

_FAMILY_SANCT_AUDIT_LAYER2_TEXT_LOCKS = (
    "MOTHER LOCK — AFRICAN AMERICAN BLACK WOMAN, late 30s to early 40s, DARK UMBER skin tone, twist-out crown braid "
    "hairstyle, terracotta + sage green wrap dress with subtle West African textile (mudcloth/kente) accents at hem and "
    "cuffs, warm protective matriarch presence. NEVER white skin, NEVER blonde hair, NEVER fair complexion, NEVER "
    "European features, NEVER any non-Black appearance. SAME WOMAN as mother.png ref — identical face shape, identical "
    "hair pattern, identical dress, identical body type. "
    "FATHER LOCK — AFRICAN AMERICAN BLACK MAN, early 40s, deep umber skin, cropped hair with first hints of gray at "
    "temples ONLY (NOT silver-fox, NOT elderly), short beard with temple salt, fitted dark navy henley shirt + dark "
    "cargo pants + boots. SAME MAN as father.png ref — identical face, identical beard pattern, identical wardrobe. "
    "DAUGHTER LOCK — BLACK GIRL age 10-12 (school-age proportions, NEVER toddler, NEVER teen), TWIN AFRO PUFFS with "
    "colorful beads (NEVER single Afro, NEVER cornrows, NEVER straight hair, NEVER adult ages), bright YELLOW pocket "
    "dress with green accents, green sneakers. SAME GIRL as daughter.png ref — identical face, identical twin puffs, "
    "identical yellow dress. "
    "SON LOCK — BLACK BOY age 13-15, fade haircut with short twists, graphic tee under earth-toned half-open overshirt, "
    "dark jeans, sneakers. SAME BOY as son.png ref — identical face, identical hair, identical wardrobe. "
)

_FAMILY_SANCT_AUDIT_LAYER3_FAMILY_OF_FOUR = (
    "FAMILY OF EXACTLY FOUR PEOPLE: Mother + Father + Son + Daughter ONLY. ABSOLUTELY NO additional people in frame. "
    "NO extras in background, NO crowds, NO ceremonial attendants, NO robed strangers, NO other women, NO other "
    "children, NO twins of any character, NO duplicate adults. If the scene shows the family, it shows EXACTLY these "
    "four people from the ref images and no one else."
)

_FAMILY_SANCT_AUDIT_NEGATIVE = (
    "FORBIDDEN: white woman, blonde hair, fair-skinned mother, European features, ceremonial gowns, priestess robes, "
    "matching costumes for women, four matching adult women, extras in background, additional family members, twins, "
    "duplicate characters, mother as different woman in different scenes, father as silver-fox elderly, daughter as "
    "toddler, daughter as teenager, son as adult."
)

_FAMILY_SANCT_AUDIT_LAYER2_COMPACT = (
    "REF-STRIP LAW: replicate mother/daughter/son/father tiles exactly — dark-umber Black mother (twist/braid crown, "
    "terracotta+sage wrap dress); twin-puff+beads yellow dress daughter (~10–12); fade+twists son (~13–15); cropped hair "
    "early-40s father (navy henley, temples-only salt)."
)

_FAMILY_SANCT_AUDIT_LAYER3_COMPACT = (
    "EXACTLY four people — mother, father, son, daughter — no extras, duplicates, twins, crowds, robed strangers."
)

_FAMILY_SANCT_AUDIT_NEGATIVE_COMPACT = (
    "FORBIDDEN: wrong-race mother, blonde mother, ceremonial-gown quartet, extras, duplicate cast, toddler/teen daughter, "
    "silver-fox father — AND white/gray rectangles, blank corner panels, collage seams, bezel/crop placeholders in background."
)


def _family_sanctuary_audit_regen_prompt_suffix(*, compact: bool = False) -> str:
    if compact:
        return (
            _FAMILY_SANCT_AUDIT_LAYER2_COMPACT
            + _FAMILY_SANCT_AUDIT_LAYER3_COMPACT
            + _FAMILY_SANCT_AUDIT_NEGATIVE_COMPACT
        ).strip()
    return (
        _FAMILY_SANCT_AUDIT_LAYER2_TEXT_LOCKS
        + _FAMILY_SANCT_AUDIT_LAYER3_FAMILY_OF_FOUR
        + _FAMILY_SANCT_AUDIT_NEGATIVE
    ).strip()


def _neutral_storyboard_placeholder_png(width: int = 1152, height: int = 648) -> bytes:
    """Center column slate for cel plate (16:9). Model replaces with final hero in output."""
    import io
    from PIL import Image

    img = Image.new("RGB", (width, height), (48, 44, 52))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _solid_rgb_png_bytes(width: int, height: int, rgb: tuple[int, int, int] = (28, 26, 30)) -> bytes:
    """Placeholder strip when an R2 ref download fails."""
    import io
    from PIL import Image

    img = Image.new("RGB", (max(16, width), max(16, height)), rgb)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


_FAMILY_SANCTUARY_COSTUME_LOCK = (
    "COSTUME LOCK — reference portraits are LAW; never freestyle wardrobe: Mother terracotta and sage-green "
    "floor-length contemporary wrap dress subtle West African mudcloth/kente cues at hem and cuffs ONLY — "
    "NO ceremonial robes NO alternate formal outfits NO veil changes hairstyle must match puff-out crown twist "
    "aesthetic consistent with MOTHER portrait. Daughter bright yellow SHORT-SLEEVE pocket dress small textile-accent "
    "pocket trim TWO natural Afro puffs subtle gold/color beads sneakers. Son graphic tee UNDER unbuttoned earth-tone "
    "overshirt dark jeans sneakers. Father DARK NAVY fitted HENLEY (never polo collar never dress shirt lavender) "
    "plus dark cargos/trousers and leather boots silhouette — SAME garments every beat."
)

_FAMILY_SANCTUARY_EXACT_FAMILY_LOCK = (
    "CAST HARD COUNT — ONLY these four fictional kin exist here: Mother; Daughter aged 10–12; Son 13–15; Father "
    "early-to-mid-40s. NO extra kids NO nieces NO nephews NO mirrored duplicate children reflections showing extra "
    "bodies crowd silhouettes procession — if mirror glow only abstract cosmos NOT additional human forms."
)


def _father_age_lock_sentence() -> str:
    return (
        "Father read: African American man early-to-mid-40s close-cropped hair trimmed beard touched with FIRST FILIGREE "
        "salt at temples ONLY — NOT silver fox NOT sixty-year-old NOT fully-gray hair or beard; match approved HENLEY father ref age."
    )


def _family_sanctuary_chamber_throughline_sentence() -> str:
    return (
        "CONTINUOUS INDOOR VOLUME beats 1–10 — SAME fogged ancient ceremonial STONE sanctum ornate ceiling SAME monumental "
        "mercury-floor-mirror centerpiece warm offscreen hearth bounce umber amber fog-gray palette painterly cinematic "
        "depth Bradford Young Ava DuVernay luminous melanin NEVER purple void cathedral NEVER stained glass forest "
        "NEVER gray seamless cyclorama NEVER toy galaxy skybox — ONLY lens distance angle rack focus evolves."
    )


def _family_sanctuary_outdoor_throughline_sentence() -> str:
    return (
        "OUTDOOR THERA continuum beats 11–12 SHARED vista language: luminous painterly golden-hour haze drifting particulate "
        "soft god-rays SAME sanctuary silhouette scale language both frames — dusk-gold NOT crystal waterfall interior NOT "
        "confetti nebula radically different biome between 11 vs 12."
    )


_FAMILY_SANCT_MOTION_INDOOR_WORLD_BIBLE_1_10 = (
    "INTERIOR ONLY: fogged stone chamber, monumental mercury mirror, hearth amber — camera evolves inside THIS sanctum volume; "
    "NO cuts to exterior sky vistas or unrelated biomes until later sanctioned scenes."
)

_FAMILY_SANCT_MOTION_SCENE11_OUTDOOR_VISTA = (
    "ACT3 VISTA_LOCK EXTERIOR ONLY: OPEN SKY golden-hour luminous painterly landscape — wide cinematic pullback awe-scale serene "
    "invitation; family four small/mid on ridge crest OR winding hill path LOOKING OUT at layered distant sanctuary-city spires "
    "terraced glow amber particulate drift. FORBIDDEN interior chamber vaulted stone mirror sanctum ceiling NO standing inside "
    "a hall LOOKING UP at ceiling — WORLD GEOGRAPHY must read OUTDOORS not Acts1–10 enclosed sanctum."
)

_FAMILY_SANCT_MOTION_SCENE12_NO_AI_TEXT = (
    "SCENE12: NO readable text logos subtitles captions in-frame — clean lower-third for FFmpeg drawtext; dusk-gold painterly "
    "silhouettes embers negative space."
)

_FAMILY_SANCT_MOTION_SCENE12_FAMILY_SILHOUETTE_ROLES = (
    "SILHOUETTE_FAMILY_LOCK — composition-first only: four linked back-view figures; two taller outer silhouettes bracket two "
    "shorter inner silhouettes; stature variation reads guardians-with-dependents WITHOUT naming ages or minors; wardrobe cues "
    "only via outline (henley drape braid crown dress puffs) — NOT four identical women NOT ceremonial priestess symmetry "
    "NOT matching gowns NOT clone quartet."
)

_FAMILY_SANCT_MOTION_FATHER_ARC_7_9 = (
    "TRIPTYCH 7→8→9: slow-held intimate framing three sequential emotional beats ONE arc NEVER rushed montage; combined father "
    "micro-performance survives ≥~3s in final edit DO NOT hurry resolve."
)


def _family_sanctuary_motion_prompt_layers(scene_num: int) -> str:
    """Pre-Step 5: prepend-only composite locks for Grok-video motion prompts (preset-local)."""
    parts: list[str] = []
    if 1 <= scene_num <= 10:
        parts.append(_FAMILY_SANCT_MOTION_INDOOR_WORLD_BIBLE_1_10)
    if scene_num == 11:
        parts.append(_FAMILY_SANCT_MOTION_SCENE11_OUTDOOR_VISTA)
    if scene_num == 12:
        parts.append(_FAMILY_SANCT_MOTION_SCENE12_FAMILY_SILHOUETTE_ROLES)
        parts.append(_FAMILY_SANCT_MOTION_SCENE12_NO_AI_TEXT)
    if 7 <= scene_num <= 9:
        parts.append(_FAMILY_SANCT_MOTION_FATHER_ARC_7_9)
    if not parts:
        return ""
    return " ".join(parts)


def _family_sanctuary_priority_suffix(scene_def: dict) -> str:
    """User-approved narrative boosts for fragile story beats."""
    n = int(scene_def.get("scene") or -1)
    lines: dict[int, str] = {
        1: (
            "ACT1 OPEN quartet before mirror mother centered gravitational anchor daughter at her side gripping "
            "dress hem adolescent son subtly protective flank father grounding hand on teenage son shoulder "
            "four visibly one kin group chamber scale mirror ornate."
        ),
        2: (
            "Daughter body's language forward captivated toward mirror ripple micro reach mother tensing beside wonder-to-fear."
        ),
        3: (
            "Mercury clasp beat daughter silhouette dissolving toward glass mother lunges reach desperation "
            "wonder→fear legible teenage son recoiling father's eyes igniting kinetic PG fantasy."
        ),
        8: (
            "FATHER CLOSE RESOLUTE CHOSEN FOLLOW — hardness under eyes squared jaw inhale-before-charge NOT slack "
            "NOT panic NOT hesitating coward NOT stereotype fright DEFAULT steel-quiet decision to plunge after vanished family."
        ),
        10: (
            "VOID FALL interlocked familial rescue chain wrists hands fingers linking mother father son daughter tumble "
            "together luminous ribbons proof bonds did not rupture painterly cosmos."
        ),
        11: (
            "TINY SILHOUETTED quartet against vast luminous Thera sanctuary painterly panorama golden-hour haze serene invitation scale."
        ),
        12: (
            "ACT4 SILHOUETTE ENDPLATE — linked family of four tiny along distant ridge beholding painterly Thera sanctuary "
            "vast golden-hour vista emotional awe lower third UNLIT clean negative space reserved for post."
        ),
    }
    return lines.get(n, "").strip()


def _build_family_sanctuary_cel_composite_plate(
    four_ref_images: list[bytes],
    storyboard_bytes: bytes,
    previous_frame_bytes: bytes | None,
    world_bible_bytes: bytes | None,
) -> bytes:
    """Left strip: optional scene-1 WORLD BIBLE (top), then four identity refs (mother→father). Center + right unchanged."""
    import io
    from PIL import Image

    storyboard_img = Image.open(io.BytesIO(storyboard_bytes)).convert("RGB")
    sw, sh = storyboard_img.size

    ref_strip_width = sw // 3
    has_prev = previous_frame_bytes is not None
    canvas_width = ref_strip_width + sw + (ref_strip_width if has_prev else 0)
    canvas = Image.new("RGB", (canvas_width, sh), (0, 0, 0))

    y_cursor = 0
    if world_bible_bytes:
        bible_h = int(sh * 0.38)
        bible_h = min(bible_h, sh - 4 * 24)
        bible_h = max(bible_h, ref_strip_width // 2)
        bib = Image.open(io.BytesIO(world_bible_bytes)).convert("RGB")
        bib = bib.resize((ref_strip_width, bible_h), Image.LANCZOS)
        canvas.paste(bib, (0, y_cursor))
        y_cursor += bible_h

    remaining = sh - y_cursor
    nstack = max(len(four_ref_images), 1)
    slice_h = remaining // nstack
    for i, ref_bytes in enumerate(four_ref_images):
        ri = Image.open(io.BytesIO(ref_bytes)).convert("RGB")
        ri = ri.resize((ref_strip_width, slice_h), Image.LANCZOS)
        canvas.paste(ri, (0, y_cursor + i * slice_h))

    canvas.paste(storyboard_img, (ref_strip_width, 0))

    if previous_frame_bytes:
        prev_img = Image.open(io.BytesIO(previous_frame_bytes)).convert("RGB")
        prev_img = prev_img.resize((ref_strip_width, sh), Image.LANCZOS)
        canvas.paste(prev_img, (ref_strip_width + sw, 0))

    buf = io.BytesIO()
    canvas.save(buf, format="JPEG", quality=90)
    return buf.getvalue()


_FAMILY_SANCT_CEL_AUDIT_COMPACT_INSTRUCTIONS = (
    "CEL INPUT: wide plate — optional world-bible top-left + four stacked ref portraits — center is hero OUT only. "
    "Match ref likenesses; seamless painterly backdrop to edges; forbid triptych chrome, gray storyboard slabs, corner "
    "white/blank rectangles."
)

_FAMILY_SANCT_CHAMBER_THROUGHLINE_COMPACT = (
    "CONTINUITY: same fogged stone mercury sanctum indoors (beats 1–10); jewel amber warmth — not cyclorama VOID."
)


def _family_sanctuary_cel_hero_prompt(scene_def: dict, doc: dict, *, audit_compact: bool = False) -> str:
    characters = list(scene_def.get("characters") or [])
    scene_num = int(scene_def.get("scene") or 0)

    if audit_compact:
        prefix = _get_style_prefix(scene_num, FAMILY_SANCTUARY_PRESET_ID)
        narrative = (scene_def.get("prompt") or "").strip()
        # Avoid duplicating preset casting_locksheet + full inline stacks (composite carries refs).
        base = prefix + narrative
        locks: list[str] = [_FAMILY_SANCTUARY_EXACT_FAMILY_LOCK, _FAMILY_SANCTUARY_COSTUME_LOCK]
        if 1 <= scene_num <= 10:
            locks.append(_FAMILY_SANCT_CHAMBER_THROUGHLINE_COMPACT)
        if scene_num >= 11:
            locks.append(_family_sanctuary_outdoor_throughline_sentence())
        if "father" in characters or scene_num in (11, 12):
            locks.append(_father_age_lock_sentence())
        if scene_num == 11:
            locks.append(
                "SCENE11 EXTERIOR GEOMETRY LOCK — open sky ridgeline mountain path overlook only; forbid interior chamber mirror hall "
                "vaulted ceiling or candlelit room cues."
            )
        if scene_num == 12:
            locks.append(
                "SCENE12 SILHOUETTE DIVERSITY — back-view family group only; forbid four identical women ceremonial robes priestess rows."
            )
        if scene_num == 12:
            locks.append(
                "SCENE12 TEXT BAN — render ZERO typography title logo subtitle watermark glyphs letters words flames shaped "
                "as text forbidden; luminous painterly dusk vista ONLY — vector title will composite in FFmpeg later."
            )
        bible_note_c = ""
        if 2 <= scene_num <= 10:
            bible_note_c = (
                "WORLD BIBLE sliver matches scene-one chamber palette — extrapolate SAME stone volumetrics hearth warmth."
            )
        cel = _FAMILY_SANCT_CEL_AUDIT_COMPACT_INSTRUCTIONS + (" " + bible_note_c if bible_note_c else "")
        return " ".join(p for p in (base, " ".join(locks), cel) if p).strip()

    base = _build_consistent_prompt(
        scene_def.get("prompt") or "",
        characters,
        scene_num=scene_num,
        preset_id=FAMILY_SANCTUARY_PRESET_ID,
    )

    prio = _family_sanctuary_priority_suffix(scene_def)

    locks = [_FAMILY_SANCTUARY_EXACT_FAMILY_LOCK, _FAMILY_SANCTUARY_COSTUME_LOCK]
    if 1 <= scene_num <= 10:
        locks.append(_family_sanctuary_chamber_throughline_sentence())
    if scene_num >= 11:
        locks.append(_family_sanctuary_outdoor_throughline_sentence())
    if "father" in characters or scene_num in (11, 12):
        locks.append(_father_age_lock_sentence())
    if scene_num == 11:
        locks.append(
            "SCENE11 EXTERIOR GEOMETRY LOCK — open sky ridgeline mountain path overlook only; forbid interior chamber mirror hall "
            "vaulted ceiling or candlelit room cues."
        )
    if scene_num == 12:
        locks.append(
            "SCENE12 SILHOUETTE DIVERSITY — back-view family group only; forbid four identical women ceremonial robes priestess rows."
        )
    if scene_num == 12:
        locks.append(
            "SCENE12 TEXT BAN — render ZERO typography title logo subtitle watermark glyphs letters words flames shaped "
            "as text forbidden; luminous painterly dusk vista ONLY — vector title will composite in FFmpeg later."
        )

    bible_note = ""
    if 2 <= scene_num <= 10:
        bible_note = (
            "REFERENCE TOP-LEFT sliver preserves SCENE ONE chamber photograph — extrapolate SAME stone volumetrics palette "
            "ornate mercury mirror hearth warmth for EVERY indoor beat before portal."
        )

    cel = (
        "INPUT = single WIDE FILMMAKER'S CEL PLATE reading left-to-right — TOP-LEFT (when present miniature still) is WORLD "
        "BIBLE continuity still for SAME sacred sanctum ambiance; STACKED BELOW FOUR IDENTICAL CHARACTER PORTRAITS ALWAYS "
        "mother daughter son father REGARDLESS of who's large in-final composition — replicate EXACT likeness hairlines "
        "wardrobe palettes from THESE four tiles when each appears; CENTER large neutral gray matte is SOLE imaginative "
        "canvas; OPTIONAL RIGHT strip PRIOR FINAL FRAME hues only continuity not layout photocopy."
        + (" " + bible_note if bible_note else "")
        + " FINAL OUTPUT solitary widescreen heroic frame NEVER triptych chrome borders bezel seams placeholder gray box "
        "visible — painterly luminous Black skin fidelity Bradford Young Ava DuVernay discipline."
    )
    return " ".join(p for p in (base, prio, " ".join(locks), cel) if p).strip()


async def generate_family_sanctuary_hero_scenes(
    project_id: str,
    *,
    cost_ceiling_usd: float | None = 3.0,
) -> list[dict]:
    """Step 3 — cel hero stills: always 4 ref tiles + optional scene-1 world bible (indoor 2–10)."""
    doc = _load_preset_document(FAMILY_SANCTUARY_PRESET_ID)
    scenes = sorted(doc.get("scenes") or [], key=lambda s: int(s.get("scene") or 0))
    out_chars = doc.get("output") or {}
    char_prefix_raw = str(out_chars.get("r2_character_prefix") or "").strip()
    char_prefix = char_prefix_raw if char_prefix_raw.endswith("/") else (char_prefix_raw + "/" if char_prefix_raw else "")

    canonical_ref_urls: dict[str, str] = {}
    for role in FAMILY_SANCTUARY_CEL_REF_ROLES_ORDER:
        k = f"{char_prefix.rstrip('/')}/{role}.png"
        canonical_ref_urls[role] = presigned_url(k) or k

    results: list[dict] = []
    prev_hero_png: bytes | None = None
    world_bible_png: bytes | None = None
    running_cost = 0.0

    async with GROK_IMAGINE_LOCK:
        for scene in scenes:
            num = int(scene.get("scene") or 0)
            title = str(scene.get("title") or f"scene_{num}")
            characters = list(scene.get("characters") or [])

            if cost_ceiling_usd is not None and running_cost + FAMILY_SANCTUARY_HERO_SCENE_IMAGE_COST_USD > cost_ceiling_usd:
                logger.warning(
                    "[FAMILY-HERO] Stopping — next scene would exceed cost ceiling $%.2f", cost_ceiling_usd,
                )
                results.append(
                    {
                        "scene": num,
                        "title": title,
                        "r2_url": None,
                        "r2_key": None,
                        "status": "stopped_cost_ceiling",
                        "cost": 0,
                    },
                )
                break

            four_refs: list[bytes] = []
            for role in FAMILY_SANCTUARY_CEL_REF_ROLES_ORDER:
                key_png = f"{char_prefix.rstrip('/')}/{role}.png"
                blob = await download_bytes(key_png)
                if blob:
                    four_refs.append(blob)
                else:
                    logger.warning("[FAMILY-HERO] Missing R2 ref for role=%s — solid pad", role)
                    bh = max(64, (648 - int(648 * 0.38)) // 4)
                    four_refs.append(_solid_rgb_png_bytes(strip_w, bh))

            use_bible = world_bible_png is not None and 2 <= num <= 10

            center_png = _neutral_storyboard_placeholder_png()
            composite_jpg = _build_family_sanctuary_cel_composite_plate(
                four_refs,
                center_png,
                prev_hero_png,
                world_bible_png if use_bible else None,
            )
            composite_key = f"sse/studio/projects/{project_id}/step3/cel_scene_{num:02d}.jpg"

            hero_prompt = _family_sanctuary_cel_hero_prompt(scene, doc)
            try:
                composite_url = await store_bytes(composite_jpg, composite_key, "image/jpeg")
                if composite_url.startswith("mock://"):
                    raise RuntimeError("R2 unavailable — composite upload mocked")

                hero_bytes = await generate_image(hero_prompt, source_image_url=composite_url)
                hero_key = _family_sanctuary_scene_png_key(num)
                hero_url = await store_image(hero_bytes, hero_key)
                prev_hero_png = hero_bytes
                if num == 1:
                    world_bible_png = hero_bytes
                    logger.info("[FAMILY-HERO] World bible locked from scene 1 (%d bytes)", len(world_bible_png))
                running_cost += FAMILY_SANCTUARY_HERO_SCENE_IMAGE_COST_USD
                results.append(
                    {
                        "scene": num,
                        "title": title,
                        "scene_characters": characters,
                        "cel_strip_roles": list(FAMILY_SANCTUARY_CEL_REF_ROLES_ORDER),
                        "world_bible_in_composite": bool(use_bible),
                        "r2_url": hero_url,
                        "r2_key": hero_key,
                        "composite_r2_key": composite_key,
                        "status": "success",
                        "cost": FAMILY_SANCTUARY_HERO_SCENE_IMAGE_COST_USD,
                    },
                )
                logger.info("[FAMILY-HERO] scene %d done $%.2f running", num, running_cost)
            except Exception as e:
                logger.warning("[FAMILY-HERO] scene %d failed: %s", num, e)
                results.append(
                    {
                        "scene": num,
                        "title": title,
                        "r2_url": None,
                        "r2_key": _family_sanctuary_scene_png_key(num),
                        "status": f"error: {str(e)[:120]}",
                        "cost": 0,
                    },
                )

            await asyncio.sleep(5)

    manifest = {
        "project_id": project_id,
        "preset_id": FAMILY_SANCTUARY_PRESET_ID,
        "generated_at": datetime.utcnow().isoformat(),
        "pipeline": "family_sanctuary_step3_cel_hero_v2_bible_four_strip",
        "character_ref_keys_prefix": char_prefix.rstrip("/"),
        "character_ref_urls": canonical_ref_urls,
        "scene_hero_prefix": FAMILY_SANCTUARY_SCENE_R2_PREFIX,
        "scenes": results,
        "total": len(scenes),
        "success": sum(1 for r in results if r.get("status") == "success"),
        "total_cost_usd": round(sum(float(r.get("cost") or 0) for r in results), 4),
    }
    await _save_manifest_to_r2(project_id, manifest)
    logger.info(
        "[FAMILY-HERO] Complete %d/%d scenes $%.2f",
        manifest["success"],
        len(scenes),
        manifest["total_cost_usd"],
    )
    return results


async def regenerate_family_sanctuary_hero_scene_pngs(
    project_id: str,
    scene_nums: Sequence[int],
    *,
    cost_ceiling_usd: float | None = 15.0,
    backup_name: str = "v2_backup",
    audit_identity_strict: bool = False,
    local_audit_review_dir: str | None = None,
    png_prompt_overrides: dict[int, str] | None = None,
) -> list[dict]:
    """Step 3 — regenerate specific family_sanctuary scene hero PNGs; backs up prior keys to *_<backup_name>.png on R2.

    When ``audit_identity_strict=True`` (PATH B drift remediation), scenes in
    ``_FAMILY_SANCTUARY_AUDIT_REGEN_SCENES`` use frozen narrative beats plus a **compact** cel prompt + Layer2/3/negative
    stack (under Grok Imagine's ~8k prompt cap; ref plate still carries full likeness). World-bible strip for 2–10,
    correct previous-frame chain, and quartet character list for cel composite.
    Optional ``local_audit_review_dir``: if set (e.g. ``/tmp/gate1b_scenes``), each successful regenerated PNG is also
    written as ``scene_NN_audit.png`` for SCP review gates.

    ``png_prompt_overrides``: per-scene **full narrative** replacements (caller-vetted length). Each is prefixed with
    the preset style lead and (for outdoor beats) continuity locks, then truncated to ``_MAX_GROK_IMAGE_PROMPT_CHARS``.
    Use for surgical wardrobe/composition fixes without mutating preset JSON (e.g. scene 12 closing tableau).
    """
    want = sorted({int(n) for n in scene_nums if int(n) > 0})
    if not want:
        return []

    doc = _load_preset_document(FAMILY_SANCTUARY_PRESET_ID)
    all_scenes = {int(s.get("scene") or 0): s for s in (doc.get("scenes") or [])}
    for n in want:
        if n not in all_scenes:
            return [
                {
                    "scene": n,
                    "status": f"error: scene {n} not in preset",
                    "r2_key": _family_sanctuary_scene_png_key(n),
                },
            ]

    out_chars = doc.get("output") or {}
    char_prefix_raw = str(out_chars.get("r2_character_prefix") or "").strip()
    char_prefix = char_prefix_raw if char_prefix_raw.endswith("/") else (char_prefix_raw + "/" if char_prefix_raw else "")

    canonical_ref_urls: dict[str, str] = {}
    for role in FAMILY_SANCTUARY_CEL_REF_ROLES_ORDER:
        k = f"{char_prefix.rstrip('/')}/{role}.png"
        canonical_ref_urls[role] = presigned_url(k) or k

    world_bible_png: bytes | None = None
    if audit_identity_strict:
        world_bible_png = await download_bytes(_family_sanctuary_scene_png_key(1))
        if world_bible_png:
            logger.info("[FAMILY-HERO-REGEN] World bible strip from scene_01 (%d bytes)", len(world_bible_png))
        else:
            logger.warning("[FAMILY-HERO-REGEN] audit mode: missing scene_01.png for world bible strip")

    results: list[dict] = []
    running_cost = 0.0
    last_generated_num: int | None = None
    last_hero_png: bytes | None = None

    async with GROK_IMAGINE_LOCK:
        for num in want:
            scene = dict(all_scenes[num])
            title = str(scene.get("title") or f"scene_{num}")
            characters = list(scene.get("characters") or [])

            if cost_ceiling_usd is not None and running_cost + FAMILY_SANCTUARY_HERO_SCENE_IMAGE_COST_USD > cost_ceiling_usd:
                results.append(
                    {
                        "scene": num,
                        "title": title,
                        "r2_url": None,
                        "r2_key": _family_sanctuary_scene_png_key(num),
                        "status": "stopped_cost_ceiling",
                        "cost": 0,
                    },
                )
                break

            hero_key = _family_sanctuary_scene_png_key(num)
            backup_key = f"{FAMILY_SANCTUARY_SCENE_R2_PREFIX}/scene_{int(num):02d}_{backup_name}.png"
            pre_existing = await download_bytes(hero_key)
            backup_url: str | None = None
            if pre_existing:
                backup_url = await store_image(pre_existing, backup_key)
                logger.info("[FAMILY-HERO-REGEN] scene %d backed up → %s", num, backup_key)
            else:
                logger.warning("[FAMILY-HERO-REGEN] scene %d: no existing PNG to back up", num)

            prev_hero_png: bytes | None = None
            pn = num - 1
            if pn >= 1:
                if last_generated_num == pn and last_hero_png is not None:
                    prev_hero_png = last_hero_png
                else:
                    prev_hero_png = await download_bytes(_family_sanctuary_scene_png_key(pn))

            four_refs: list[bytes] = []
            for role in FAMILY_SANCTUARY_CEL_REF_ROLES_ORDER:
                key_png = f"{char_prefix.rstrip('/')}/{role}.png"
                blob = await download_bytes(key_png)
                if blob:
                    four_refs.append(blob)
                else:
                    logger.warning("[FAMILY-HERO-REGEN] Missing R2 ref for role=%s — solid pad", role)
                    four_refs.append(_solid_rgb_png_bytes(64, 64))

            center_png = _neutral_storyboard_placeholder_png()
            use_bible = bool(
                audit_identity_strict
                and world_bible_png
                and 2 <= num <= 10,
            )
            composite_jpg = _build_family_sanctuary_cel_composite_plate(
                four_refs,
                center_png,
                prev_hero_png,
                world_bible_png if use_bible else None,
            )
            composite_key = f"sse/studio/projects/{project_id}/step3/cel_scene_{num:02d}_regen.jpg"

            ovr_map = png_prompt_overrides or {}
            if num in ovr_map:
                prefix = _get_style_prefix(num, FAMILY_SANCTUARY_PRESET_ID)
                pieces: list[str] = [prefix, str(ovr_map[num]).strip()]
                if num >= 11:
                    pieces.append(_family_sanctuary_outdoor_throughline_sentence())
                if num == 12:
                    pieces.append(_father_age_lock_sentence())
                    pieces.append(
                        "SCENE12 TEXT BAN — render ZERO typography title logo subtitle watermark glyphs letters words "
                        "flames shaped as text forbidden; vector title composites in FFmpeg later."
                    )
                hero_prompt = " ".join(p for p in pieces if p).strip()
                if len(hero_prompt) > _MAX_GROK_IMAGE_PROMPT_CHARS:
                    hero_prompt = hero_prompt[:_MAX_GROK_IMAGE_PROMPT_CHARS]
                    logger.warning(
                        "[FAMILY-HERO-REGEN] scene %d png_prompt_override truncated to %d chars",
                        num,
                        _MAX_GROK_IMAGE_PROMPT_CHARS,
                    )
            elif audit_identity_strict and num in _FAMILY_SANCTUARY_AUDIT_REGEN_SCENES:
                narr = _FAMILY_SANCT_AUDIT_SCENE_NARRATIVES.get(num)
                if narr:
                    scene["prompt"] = narr
                scene["characters"] = ["mother", "daughter", "son", "father"]
                # Grok Imagine max prompt ~8000 chars — audit stack + full preset locks can overflow; compact path preserves ref-plate fidelity.
                hero_prompt = _family_sanctuary_cel_hero_prompt(
                    scene, doc, audit_compact=True
                ) + " " + _family_sanctuary_audit_regen_prompt_suffix(compact=True)
                if len(hero_prompt) > _MAX_GROK_IMAGE_PROMPT_CHARS:
                    hero_prompt = hero_prompt[:_MAX_GROK_IMAGE_PROMPT_CHARS]
                    logger.warning(
                        "[FAMILY-HERO-REGEN] scene %d audit compact prompt truncated to %d chars",
                        num,
                        _MAX_GROK_IMAGE_PROMPT_CHARS,
                    )
            else:
                hero_prompt = _family_sanctuary_cel_hero_prompt(scene, doc)
                if len(hero_prompt) > _MAX_GROK_IMAGE_PROMPT_CHARS:
                    hero_prompt = hero_prompt[:_MAX_GROK_IMAGE_PROMPT_CHARS]
                    logger.warning(
                        "[FAMILY-HERO-REGEN] scene %d default cel prompt truncated to %d chars",
                        num,
                        _MAX_GROK_IMAGE_PROMPT_CHARS,
                    )

            try:
                composite_url = await store_bytes(composite_jpg, composite_key, "image/jpeg")
                if composite_url.startswith("mock://"):
                    raise RuntimeError("R2 unavailable — composite upload mocked")

                hero_bytes = await generate_image(hero_prompt, source_image_url=composite_url)
                hero_url = await store_image(hero_bytes, hero_key)
                last_hero_png = hero_bytes
                last_generated_num = num
                running_cost += FAMILY_SANCTUARY_HERO_SCENE_IMAGE_COST_USD
                results.append(
                    {
                        "scene": num,
                        "title": title,
                        "scene_characters": list(scene.get("characters") or []),
                        "cel_strip_roles": list(FAMILY_SANCTUARY_CEL_REF_ROLES_ORDER),
                        "backup_r2_key": backup_key if pre_existing else None,
                        "backup_r2_url": backup_url,
                        "r2_url": hero_url,
                        "r2_key": hero_key,
                        "composite_r2_key": composite_key,
                        "status": "success",
                        "cost": FAMILY_SANCTUARY_HERO_SCENE_IMAGE_COST_USD,
                    },
                )
                logger.info("[FAMILY-HERO-REGEN] scene %d regenerated", num)
                if local_audit_review_dir and audit_identity_strict:
                    from pathlib import Path

                    ap = Path(local_audit_review_dir)
                    ap.mkdir(parents=True, exist_ok=True)
                    ap.joinpath(f"scene_{num:02d}_audit.png").write_bytes(hero_bytes)
                    logger.info("[FAMILY-HERO-REGEN] audit PNG → %s", ap / f"scene_{num:02d}_audit.png")
            except Exception as e:
                logger.warning("[FAMILY-HERO-REGEN] scene %d failed: %s", num, e)
                results.append(
                    {
                        "scene": num,
                        "title": title,
                        "r2_url": None,
                        "r2_key": hero_key,
                        "backup_r2_key": backup_key if pre_existing else None,
                        "status": f"error: {str(e)[:160]}",
                        "cost": 0,
                    },
                )

            await asyncio.sleep(5)

    manifest = {
        "project_id": project_id,
        "preset_id": FAMILY_SANCTUARY_PRESET_ID,
        "generated_at": datetime.utcnow().isoformat(),
        "pipeline": "family_sanctuary_step3_cel_hero_subset_regen",
        "character_ref_urls": canonical_ref_urls,
        "requested_scenes": want,
        "scene_hero_prefix": FAMILY_SANCTUARY_SCENE_R2_PREFIX,
        "backup_suffix": backup_name,
        "scenes": results,
        "success": sum(1 for r in results if r.get("status") == "success"),
        "total_cost_usd": round(sum(float(r.get("cost") or 0) for r in results), 4),
    }
    await _save_manifest_to_r2(project_id, manifest)
    logger.info("[FAMILY-HERO-REGEN] subset complete success=%s", manifest["success"])
    return results


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
    preset_id: str | None = None,
) -> dict:
    """Generate a single scene using cel animation composite method.

    If trained LoRAs exist, generates fresh character reference images via LoRA
    instead of using the Grok-generated reference PNGs.
    """
    pid = preset_id or DEFAULT_PRESET_ID
    doc = _load_preset_document(pid)
    scene_def = next(
        (s for s in _load_preset(pid) if s.get("scene") == scene_num),
        {},
    )
    scene_characters = scene_def.get("characters", [])

    trained_loras = await _load_trained_loras(project_id)
    refs_bundle = _char_refs(pid)

    ref_images: list[bytes] = []
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=30)) as sess:
        for char in scene_characters[:3]:
            if char in trained_loras and trained_loras[char].get("lora_url"):
                try:
                    ref = refs_bundle.get(char, {})
                    prompt = (
                        f"{_get_style_prefix(scene_num, pid)}"
                        f"{ref.get('ref_prompt', char)}, full body reference sheet"
                    )
                    img = await _generate_image_with_lora_or_grok(
                        prompt, [char], trained_loras, scene_num=scene_num, preset_id=pid,
                    )
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
        refs_bundle[c]["inline_desc"]
        for c in scene_characters
        if c in refs_bundle
    ]
    _cel_prefix = _get_style_prefix(scene_num, pid)
    casting = _casting_lock_hints(scene_characters, doc)
    animation_prompt = (
        f"{_cel_prefix}"
        f"ANIMATE the center panel of this reference plate. "
        f"The left panel shows the exact character design to use — "
        f"maintain these exact proportions, clothing, and features. "
        f"{'The right panel shows what just happened — continue smoothly from that motion. ' if prev_bytes else ''}"
        f"{casting} "
        f"Characters in scene: {'; '.join(char_names)}. "
        f"Action: {motion_prompt}"
    )
    animation_prompt = _append_dragon_negative_if_applicable(animation_prompt, scene_num, pid)

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
    preset_id: str | None = None,
) -> list[dict]:
    """Generate training images for LoRA fine-tuning of a specific character."""
    manifest = await _load_manifest_from_r2(project_id) or {}
    pid = preset_id or _manifest_preset_id(manifest)
    refs = _char_refs(pid)
    ref = refs.get(character)
    if not ref:
        # Resolve character across any Studio preset pack (R2 manifest may lag DB).
        for try_pid, pack in CHARACTER_REFERENCES_BY_PRESET.items():
            if character in pack:
                pid = try_pid
                ref = pack[character]
                break
    if not ref:
        raise ValueError(f"Unknown character: {character} for preset {pid}")

    style = _get_style_prefix(1, pid)
    results: list[dict] = []
    async with GROK_IMAGINE_LOCK:
        for i in range(min(count, len(LORA_TRAINING_VARIATIONS))):
            variation = LORA_TRAINING_VARIATIONS[i]
            prompt = f"{style}{ref['ref_prompt']}, {variation}"
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
        preset_id = _manifest_preset_id(manifest)
        scenes = sorted(
            [s for s in manifest["scenes"] if s.get("status") == "success"],
            key=lambda s: s["scene"],
        )
        refs = manifest.get("character_refs", {})
        motion_map = _motion_prompts_map(preset_id)
        branches = _branch_points_for_preset(preset_id)
        results: list[dict] = []
        previous_last_frame: str | None = None

        for scene_data in scenes:
            scene_num = scene_data["scene"]
            if scene_num in branches:
                previous_last_frame = None
            motion = motion_map.get(scene_num, {"motion": "Smooth cinematic motion"})
            result = await generate_cel_animation_clip(
                project_id=project_id,
                scene_num=scene_num,
                character_refs=refs,
                storyboard_url=scene_data["r2_url"],
                previous_last_frame_url=previous_last_frame,
                motion_prompt=motion["motion"],
                preset_id=preset_id,
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

async def _azure_tts(
    text: str,
    voice: str = "onyx",
    instructions: str = "",
    *,
    response_format: str | None = None,
    speed: float | None = None,
) -> Optional[bytes]:
    """Generate TTS audio via Azure gpt-4o-mini-tts.

    Thera-World narrated hero (``hero_video_thera_world_NARRATED.mp4``) uses
    ``voice=THERA_HERO_NARRATED_TTS_VOICE`` (“ash”) from ``hero_narration_mix``.
    Family Sanctuary Step 4 must match that voice, not a different preset voice.
    """
    api_key = os.getenv("AZURE_API_KEY", "").strip()
    endpoint = os.getenv("AZURE_OPENAI_ENDPOINT", "").strip()
    deployment = os.getenv("AZURE_OPENAI_MINI_TTS_DEPLOYMENT", "gpt-4o-mini-tts")

    if not api_key or not endpoint:
        return None

    url = f"https://{endpoint}/openai/deployments/{deployment}/audio/speech?api-version=2025-01-01-preview"
    payload: dict = {"model": deployment, "input": text, "voice": voice}
    if instructions:
        payload["instructions"] = instructions
    if response_format:
        payload["response_format"] = response_format
    if speed is not None:
        payload["speed"] = float(speed)

    async with aiohttp.ClientSession() as sess:
        async with sess.post(url, json=payload,
                             headers={"api-key": api_key, "Content-Type": "application/json"},
                             timeout=aiohttp.ClientTimeout(total=30)) as resp:
            if resp.status == 200:
                return await resp.read()
            body = await resp.text()
            logger.warning("[TTS] HTTP %d: %s", resp.status, body[:200])
            return None


FAMILY_SANCTUARY_NARRATION_R2_PREFIX = "sse/trailer/family_sanctuary/narration"
FAMILY_SANCTUARY_MOTION_R2_PREFIX = "sse/trailer/family_sanctuary/motion"
_GROK_FS_MOTION_COST_EST_USD_DEFAULT = 4.0
_FAMILY_SANCT_NARRATION_FILES: tuple[tuple[str, str], ...] = (
    ("nar_seg_acts_12", "segment_1_acts_1_2.wav"),
    ("nar_seg_act3", "segment_2_act_3.wav"),
    ("nar_seg_act4", "segment_3_act_4.wav"),
)


def _ffprobe_audio_duration_seconds(path: str) -> float | None:
    try:
        r = subprocess.run(
            [
                "ffprobe", "-v", "error", "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1", path,
            ],
            capture_output=True,
            text=True,
            timeout=20,
        )
        if r.returncode == 0 and (r.stdout or "").strip():
            return float(r.stdout.strip())
    except Exception as e:
        logger.warning("[FS-NARR] ffprobe failed for %s: %s", path, e)
    return None


async def generate_family_sanctuary_narration_segments(
    *,
    local_dir: str | None = None,
    upload_r2: bool = True,
) -> dict:
    """Family Sanctuary Step 4: three Azure Mini-TTS WAVs (preset narration_voice voice + instructions).

    Writes ``segment_*.wav`` under workspace ``tmp/family_sanctuary_step4_narration/`` by default and
    optionally uploads to ``sse/trailer/family_sanctuary/narration/``.
    """
    repo_root = Path(__file__).resolve().parents[3]
    out_dir = local_dir or str(repo_root / "tmp" / "family_sanctuary_step4_narration")
    os.makedirs(out_dir, exist_ok=True)

    doc = _load_preset_document(FAMILY_SANCTUARY_PRESET_ID)
    nv = doc.get("narration_voice") or {}
    voice = str(nv.get("voice") or THERA_HERO_NARRATED_TTS_VOICE).strip()
    instructions = str(nv.get("instructions") or "").strip()
    by_id = {str(s.get("id")): s for s in (nv.get("segments") or []) if isinstance(s, dict)}
    rows: list[dict] = []

    for seg_id, filename in _FAMILY_SANCT_NARRATION_FILES:
        seg = by_id.get(seg_id)
        if not seg:
            rows.append({"segment_id": seg_id, "filename": filename, "status": "missing_preset_segment"})
            continue
        text = str(seg.get("text") or "").strip()
        if not text:
            rows.append({"segment_id": seg_id, "filename": filename, "status": "empty_text"})
            continue

        audio = await _azure_tts(
            text=text,
            voice=voice,
            instructions=instructions,
            response_format="wav",
        )
        if not audio:
            rows.append({"segment_id": seg_id, "filename": filename, "status": "tts_failed"})
            continue

        local_path = os.path.join(out_dir, filename)
        with open(local_path, "wb") as f:
            f.write(audio)
        dur = _ffprobe_audio_duration_seconds(local_path)

        r2_key = f"{FAMILY_SANCTUARY_NARRATION_R2_PREFIX}/{filename}"
        r2_url: str | None = None
        if upload_r2:
            try:
                r2_url = await store_bytes(audio, r2_key, "audio/wav")
            except Exception as e:
                logger.warning("[FS-NARR] R2 upload failed %s: %s", r2_key, e)

        rows.append(
            {
                "segment_id": seg_id,
                "label": seg.get("label"),
                "filename": filename,
                "local_path": local_path,
                "duration_seconds": dur,
                "voice": voice,
                "r2_key": r2_key if upload_r2 else None,
                "r2_url": r2_url,
                "status": "success" if dur else "success_no_duration",
            },
        )
        await asyncio.sleep(1.5)

    seg1_dur = next((r["duration_seconds"] for r in rows if r.get("filename") == "segment_1_acts_1_2.wav"), None)
    report = {
        "preset_id": FAMILY_SANCTUARY_PRESET_ID,
        "voice_used": voice,
        "local_dir": out_dir,
        "segments": rows,
        "segment_1_over_8s_extend_video_to_21s_recommended": bool(seg1_dur and seg1_dur > 8.0),
        "note_if_segment_1_long": "If segment 1 > 8s, extend total hero to 21s per preset — do not compress speech.",
    }
    rep_path = os.path.join(out_dir, "step4_ffprobe_report.json")
    with open(rep_path, "w") as f:
        json.dump(report, f, indent=2)
    logger.info("[FS-NARR] Step 4 report → %s", rep_path)
    return report


def _family_sanctuary_step5_motion_slot_duration(scene_num: int, doc: dict) -> float:
    """Hero scene seconds on the scaled timeline (timecode_guide × hero/20s baseline)."""
    out = doc.get("output") or {}
    hero_t = float(out.get("duration_target_seconds") or 25)
    baseline = float((doc.get("step5_motion") or {}).get("timecode_guide_baseline_end_seconds") or 20)
    factor = hero_t / baseline if baseline > 0 else 1.25
    s = next((x for x in (doc.get("scenes") or []) if int(x.get("scene", 0) or 0) == scene_num), None)
    if not s:
        return max(0.35, hero_t / 12.0)
    tg = s.get("timecode_guide") or {}
    t0 = float(tg.get("t0_seconds", 0))
    t1 = float(tg.get("t1_seconds", t0))
    if t1 <= t0:
        t1 = t0 + float(s.get("duration") or 2)
    return max(0.35, (t1 - t0) * factor)


def _family_sanctuary_step5_grok_policy(doc: dict) -> dict[str, float | bool]:
    s5 = doc.get("step5_motion") or {}
    ceiling = float(s5.get("cost_ceiling_usd") or (_GROK_FS_MOTION_COST_EST_USD_DEFAULT + 1.5))
    est = float(s5.get("grok_video_usd_per_clip_estimate") or _GROK_FS_MOTION_COST_EST_USD_DEFAULT)
    force_env = os.getenv("FAMILY_SANCTUARY_STEP5_USE_GROK", "").strip().lower() in ("1", "true", "yes")
    force_preset = bool(s5.get("force_grok", False))
    force = force_env or force_preset
    ken_burns_only = bool((not force) and ceiling + 1e-6 < est * 12)
    return {
        "ceiling": ceiling,
        "est_per_clip": est,
        "force_grok": force,
        "ken_burns_only": ken_burns_only,
    }


def _ffmpeg_trim_video_seconds(src: str, dst: str, max_seconds: float) -> bool:
    if max_seconds <= 0:
        shutil.copyfile(src, dst)
        return True
    proc = subprocess.run(
        [
            "ffmpeg", "-y", "-i", src,
            "-t", f"{max_seconds:.4f}",
            "-c:v", "libx264", "-preset", "fast", "-crf", "20",
            "-pix_fmt", "yuv420p", "-an",
            dst,
        ],
        capture_output=True,
        timeout=120,
    )
    return proc.returncode == 0 and os.path.isfile(dst)


def _ffmpeg_mux_two_video_xfade(
    path_a: str, path_b: str, outp: str,
    xfade_seconds: float,
    scale_w: int,
) -> tuple[bool, Optional[float]]:
    da = _ffprobe_audio_duration_seconds(path_a)
    if not da:
        return False, None
    offset = max(0.05, float(da) - xfade_seconds)
    if scale_w and scale_w > 0:
        filt = (
            f"[0:v]scale={scale_w}:-2:flags=lanczos,format=yuv420p,setpts=PTS-STARTPTS[va];"
            f"[1:v]scale={scale_w}:-2:flags=lanczos,format=yuv420p,setpts=PTS-STARTPTS[vb];"
            f"[va][vb]xfade=transition=fade:duration={xfade_seconds:.4f}:offset={offset:.4f}[vout]"
        )
    else:
        filt = (
            "[0:v]format=yuv420p,setpts=PTS-STARTPTS[va];"
            "[1:v]format=yuv420p,setpts=PTS-STARTPTS[vb];"
            f"[va][vb]xfade=transition=fade:duration={xfade_seconds:.4f}:offset={offset:.4f}[vout]"
        )
    proc = subprocess.run(
        [
            "ffmpeg", "-y", "-i", path_a, "-i", path_b,
            "-filter_complex", filt,
            "-map", "[vout]", "-an",
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "34", "-pix_fmt", "yuv420p",
            outp,
        ],
        capture_output=True,
        timeout=300,
    )
    if proc.returncode != 0:
        logger.warning(
            "[FS-MOTION-PREV] xfade ffmpeg failed: %s",
            proc.stderr.decode(errors="replace")[:480],
        )
        return False, None
    probe = _ffprobe_audio_duration_seconds(outp)
    return True, float(probe) if probe else None


def _family_sanctuary_build_lowres_xfade_preview(
    clip_paths: list[str],
    output_path: str,
    *,
    xfade_seconds: float = 0.2,
    scale_w: int = 854,
) -> bool:
    """Motion-only QC chain: scale + pairwise xfade, no audio."""
    paths = [p for p in clip_paths if p and os.path.isfile(p)]
    if not paths:
        return False
    if len(paths) == 1:
        proc = subprocess.run(
            [
                "ffmpeg", "-y", "-i", paths[0],
                "-vf", f"scale={scale_w}:-2:flags=lanczos",
                "-c:v", "libx264", "-preset", "veryfast", "-crf", "34",
                "-pix_fmt", "yuv420p", "-an",
                output_path,
            ],
            capture_output=True,
            timeout=300,
        )
        return proc.returncode == 0 and os.path.isfile(output_path)

    tmp_root = tempfile.mkdtemp(prefix="fs_prev_xf_")
    try:
        cur = paths[0]
        scaled0 = os.path.join(tmp_root, "s000.mp4")
        r0 = subprocess.run(
            [
                "ffmpeg", "-y", "-i", cur,
                "-vf", f"scale={scale_w}:-2:flags=lanczos,format=yuv420p,setpts=PTS-STARTPTS",
                "-c:v", "libx264", "-preset", "fast", "-crf", "30", "-pix_fmt", "yuv420p",
                "-an",
                scaled0,
            ],
            capture_output=True,
            timeout=300,
        )
        if r0.returncode != 0:
            return False
        cur = scaled0

        for idx in range(1, len(paths)):
            sx = os.path.join(tmp_root, f"s{idx:03d}.mp4")
            rn = subprocess.run(
                [
                    "ffmpeg", "-y", "-i", paths[idx],
                    "-vf", f"scale={scale_w}:-2:flags=lanczos,format=yuv420p,setpts=PTS-STARTPTS",
                    "-c:v", "libx264", "-preset", "fast", "-crf", "30",
                    "-pix_fmt", "yuv420p", "-an",
                    sx,
                ],
                capture_output=True,
                timeout=300,
            )
            if rn.returncode != 0:
                return False

            outp = (
                output_path if idx == len(paths) - 1
                else os.path.join(tmp_root, f"m{idx:03d}.mp4")
            )
            ok, _ = _ffmpeg_mux_two_video_xfade(
                cur, sx, outp, float(xfade_seconds), 0,
            )
            if not ok:
                return False
            cur = outp
        return os.path.isfile(output_path)
    finally:
        shutil.rmtree(tmp_root, ignore_errors=True)


async def generate_family_sanctuary_step5_motion(
    *,
    local_dir: str | None = None,
    preview_path: str | None = None,
    inter_scene_delay_seconds: float = 8.0,
    scenes_to_regenerate: list[int] | None = None,
    per_scene_prompt_overrides: dict[int, str] | None = None,
    grok_motion_strength: float = 0.6,
) -> dict:
    """Step 5: twelve motion clips from FS hero PNGs → local disk + ``sse/trailer/family_sanctuary/motion/``.

    Slot duration = ``(timecode_guide span) × (duration_target_seconds / baseline)`` — father 7–9 sums ≥ ~3s at 25/20 scale.

    Budget: preset ``step5_motion.cost_ceiling_usd``. When ``ceiling < 12 × estimate`` ⇒ Ken Burns only unless
    ``FAMILY_SANCTUARY_STEP5_USE_GROK=1`` or ``step5_motion.force_grok``: true.

    Builds ``tmp/family_sanctuary_step5_preview.mp4`` (low-res motion-only crossfades).

    GATE: Caller must pause for user approval before Step 6 narration/music/remux (~\$ spend).

    If ``scenes_to_regenerate`` is set (e.g. ``[1, 11, 12]``), only those scenes (1–12) are processed; Grok Video is forced;
    preset Ken Burns fallback is suppressed for those runs (failures stay ``failed`` and existing files on disk are left untouched).
    Cost ceiling raised to at least ``FAMILY_SANCTUARY_STEP5_REGEN_CEILING_USD`` (default 15 USD) over the regenerated subset.

    ``per_scene_prompt_overrides``: when a scene number is present, its string replaces the auto-built motion prompt
    (style fuse is still prepended). Override scenes cap ``motion_strength`` sent to Grok Video at ``0.4`` (via
    ``request_extras``); xAI may ignore unknown JSON fields — prompt suffix still tightens drift.

    ``grok_motion_strength``: merged into Grok Video JSON as ``motion_strength`` for override scenes only
    (effective value ``min(grok_motion_strength, 0.4)``). Non-override scenes keep legacy behavior (no extra JSON keys).
    """
    repo_root = Path(__file__).resolve().parents[3]
    doc = _load_preset_document(FAMILY_SANCTUARY_PRESET_ID)
    policy = _family_sanctuary_step5_grok_policy(doc)
    s5 = doc.get("step5_motion") or {}
    xd = float(s5.get("preview_crossfade_seconds") or 0.2)
    prv_w = int(s5.get("preview_scale_width") or 854)

    motion_dir = local_dir or str(repo_root / "tmp" / "family_sanctuary_step5_motion")
    os.makedirs(motion_dir, exist_ok=True)
    preview_out = preview_path or str(repo_root / "tmp" / "family_sanctuary_step5_preview.mp4")

    motion_map = _motion_prompts_map(FAMILY_SANCTUARY_PRESET_ID)
    results: list[dict] = []
    running_cost = 0.0
    regeneration_mode = bool(scenes_to_regenerate)
    if regeneration_mode:
        proc_scenes = sorted({int(x) for x in (scenes_to_regenerate or []) if 1 <= int(x) <= 12})
    else:
        proc_scenes = list(range(1, 13))

    policy_eff = dict(policy)
    if regeneration_mode:
        policy_eff["force_grok"] = True
        policy_eff["ken_burns_only"] = False
        reg_ceiling = float(os.getenv("FAMILY_SANCTUARY_STEP5_REGEN_CEILING_USD", "15"))
        policy_eff["ceiling"] = max(policy_eff["ceiling"], reg_ceiling)

    async with GROK_IMAGINE_LOCK:
        for scene_num in proc_scenes:
            slot = round(_family_sanctuary_step5_motion_slot_duration(scene_num, doc), 4)
            hero_key = _family_sanctuary_scene_png_key(scene_num)
            img_uri = presigned_url(hero_key, expires_in=7200)

            motion_prompt = _family_sanctuary_step5_video_prompt(
                scene_num,
                motion_map=motion_map,
                per_scene_prompt_overrides=per_scene_prompt_overrides,
            )
            uses_prompt_override = bool(per_scene_prompt_overrides and scene_num in per_scene_prompt_overrides)
            if uses_prompt_override:
                motion_prompt = f"{motion_prompt} {_FS_STEP5_OVERRIDE_MOTION_SUFFIX}".strip()
                if len(motion_prompt) > _MAX_GROK_VIDEO_PROMPT_CHARS:
                    motion_prompt = motion_prompt[:_MAX_GROK_VIDEO_PROMPT_CHARS]

            video_req_extras: dict | None = None
            if uses_prompt_override:
                ms_eff = min(float(grok_motion_strength), 0.4)
                video_req_extras = {"motion_strength": ms_eff}

            raw_local = os.path.join(motion_dir, f"_raw_scene_{scene_num:02d}.mp4")
            final_mp4 = os.path.join(motion_dir, f"scene_{scene_num:02d}.mp4")
            vid_bytes_opt: Optional[bytes] = None
            cost_this = 0.0
            method = "grok_required" if regeneration_mode else "ken_burns"

            try_grok = bool(
                policy_eff["force_grok"] or (
                    not policy_eff["ken_burns_only"]
                    and running_cost + policy_eff["est_per_clip"] <= float(policy_eff["ceiling"]) + 1e-6
                ),
            )

            if try_grok and not img_uri:
                if regeneration_mode:
                    logger.error(
                        "[FS-MOTION] Surgical regen scene %d: missing presigned URL for %s — cannot call Grok.",
                        scene_num,
                        hero_key,
                    )
                else:
                    logger.warning(
                        "[FS-MOTION] Grok path needs presigned URL; missing for %s — Ken Burns fallback",
                        hero_key,
                    )

            if try_grok and img_uri:
                logger.info(
                    "[FS-MOTION] Scene %d Grok (running ~\$%.2f / ceiling \$%.2f)",
                    scene_num,
                    running_cost,
                    policy_eff["ceiling"],
                )
                try:
                    try:
                        video_id = await generate_video(
                            motion_prompt,
                            source_image_url=img_uri,
                            request_extras=video_req_extras,
                        )
                    except RuntimeError as ge:
                        if video_req_extras and any(x in str(ge) for x in ("400", "422")):
                            logger.warning(
                                "[FS-MOTION] Scene %d: Grok rejected request_extras; retry without motion_strength: %s",
                                scene_num,
                                ge,
                            )
                            video_id = await generate_video(
                                motion_prompt,
                                source_image_url=img_uri,
                                request_extras=None,
                            )
                        else:
                            raise
                    video_url_remote: str | None = None
                    for attempt in range(60):
                        await asyncio.sleep(5)
                        poll = await poll_video_status(video_id)
                        if poll["status"] == "completed" and poll.get("url"):
                            video_url_remote = poll["url"]
                            break
                        if poll["status"] == "failed":
                            break
                        if attempt % 6 == 0:
                            logger.info("[FS-MOTION] Poll %s prog=%s%%", video_id, poll.get("progress", "?"))
                    if video_url_remote:
                        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=180)) as sess:
                            async with sess.get(video_url_remote) as vr:
                                if vr.status == 200:
                                    vid_bytes_opt = await vr.read()
                                    method = "grok_video"
                                    cost_this = float(policy_eff["est_per_clip"])
                except Exception as e:
                    logger.warning("[FS-MOTION] Grok scene %d error: %s", scene_num, e)

            if vid_bytes_opt is None:
                if regeneration_mode:
                    logger.error(
                        "[FS-MOTION] Surgical regen scene %d FAILED (Grok or download) — NOT using Ken Burns; "
                        "existing scene_%02d.mp4 left unchanged if present.",
                        scene_num,
                        scene_num,
                    )
                else:
                    work_kb = tempfile.mkdtemp(prefix="fs_kb_")
                    try:
                        kb_path = os.path.join(work_kb, f"scene_{scene_num:02d}.mp4")
                        ok_kb = await _ken_burns_fallback(hero_key, kb_path, duration=max(0.4, float(slot)))
                        if ok_kb and os.path.isfile(kb_path):
                            with open(kb_path, "rb") as f:
                                vid_bytes_opt = f.read()
                            method = "ken_burns"
                            cost_this = 0.0
                    finally:
                        shutil.rmtree(work_kb, ignore_errors=True)

            status = "failed"
            uploaded_url: str | None = None
            motion_r2_k = f"{FAMILY_SANCTUARY_MOTION_R2_PREFIX.rstrip('/')}/scene_{scene_num:02d}.mp4"
            probe_d: float | None = None

            if vid_bytes_opt:
                with open(raw_local, "wb") as f:
                    f.write(vid_bytes_opt)
                trimmed_ok = False
                if method == "grok_video" and slot > 0:
                    trimmed_ok = _ffmpeg_trim_video_seconds(raw_local, final_mp4, float(slot))
                if trimmed_ok:
                    try:
                        os.remove(raw_local)
                    except OSError:
                        pass
                else:
                    if os.path.abspath(raw_local) != os.path.abspath(final_mp4):
                        if os.path.exists(final_mp4):
                            os.remove(final_mp4)
                        os.replace(raw_local, final_mp4)
                    elif os.path.isfile(raw_local):
                        shutil.copy(raw_local, final_mp4)

                probe_d_d = _ffprobe_audio_duration_seconds(final_mp4)
                probe_d = float(probe_d_d) if probe_d_d else None

                try:
                    with open(final_mp4, "rb") as f:
                        uploaded_url = await store_bytes(f.read(), motion_r2_k, "video/mp4")
                    status = "success"
                    running_cost += cost_this
                except Exception as e:
                    logger.warning("[FS-MOTION] R2 upload failed scene %d: %s", scene_num, e)
                    status = "success_local_only"

            results.append(
                {
                    "scene": scene_num,
                    "status": status,
                    "method": method,
                    "cost_usd_logged": cost_this,
                    "target_slot_seconds": slot,
                    "duration_seconds_probed": probe_d,
                    "local_path": final_mp4,
                    "r2_key": motion_r2_k,
                    "r2_motion_url": uploaded_url,
                },
            )

            logger.info(
                "[FS-MOTION] scene=%d method=%s slot=%.3fs probe=%s status=%s",
                scene_num, method, slot, probe_d, status,
            )

            await asyncio.sleep(inter_scene_delay_seconds)

    d7 = next((x.get("duration_seconds_probed") for x in results if x.get("scene") == 7), None)
    d8 = next((x.get("duration_seconds_probed") for x in results if x.get("scene") == 8), None)
    d9 = next((x.get("duration_seconds_probed") for x in results if x.get("scene") == 9), None)
    father_sum: Optional[float] = None
    if all(isinstance(x, (int, float)) for x in (d7, d8, d9)):
        father_sum = float(d7) + float(d8) + float(d9)

    report: dict[str, object] = {
        "preset_id": FAMILY_SANCTUARY_PRESET_ID,
        "step": "family_sanctuary_step5_motion",
        "grok_budget_policy": policy_eff,
        "regeneration_mode": regeneration_mode,
        "scenes_processed": proc_scenes,
        "total_cost_usd_assumed_running": running_cost,
        "motion_local_dir": motion_dir,
        "clips": results,
        "per_clip_durations": {
            str(r.get("scene")): r.get("duration_seconds_probed") for r in results
        },
        "father_triptych_scenes_7_8_9_sum_seconds": father_sum,
        "father_triptych_target_min_seconds": 3.0,
        "father_triptych_meets_min": bool(father_sum is not None and father_sum >= 2.99),
        "preview_output": preview_out,
        "preview_crossfade_seconds": xd,
        "grok_motion_strength_requested": grok_motion_strength,
        "per_scene_prompt_override_scenes": sorted((per_scene_prompt_overrides or {}).keys()),
    }

    ordered_clips = [os.path.join(motion_dir, f"scene_{i:02d}.mp4") for i in range(1, 13)]
    all_clips_exist = all(os.path.isfile(p) for p in ordered_clips)
    report["all_twelve_motion_clips_present"] = all_clips_exist
    prev_ok = False
    if all_clips_exist:
        prev_ok = _family_sanctuary_build_lowres_xfade_preview(
            ordered_clips,
            preview_out,
            xfade_seconds=xd,
            scale_w=prv_w,
        )
    else:
        logger.warning("[FS-MOTION] Preview skipped — missing one or more scene_01..12.mp4 under %s", motion_dir)
    report["preview_built_ok"] = prev_ok
    prv_d = _ffprobe_audio_duration_seconds(preview_out) if prev_ok else None
    report["preview_duration_seconds_probed"] = float(prv_d) if prv_d else None

    rep_path = os.path.join(motion_dir, "step5_motion_report.json")
    with open(rep_path, "w") as f:
        json.dump(report, f, indent=2, default=str)
    logger.info("[FS-MOTION] Step 5 complete report → %s", rep_path)

    return report


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


async def _generate_all_narration(
    project_id: str,
    work_dir: str,
    preset_id: str | None = None,
) -> dict[int, str]:
    """Generate TTS audio for all dialogue scenes. Returns {scene_num: r2_url}."""
    pid = preset_id or DEFAULT_PRESET_ID
    preset_scenes = _load_preset(pid)
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
    "counseling_neon": (
        "colorbalance=rs=0.04:gs=0.02:bs=0.06,"
        "eq=gamma=1.03:saturation=1.18:contrast=1.06,"
        "unsharp=5:5:0.45:5:5:0"
    ),
}


# ---------------------------------------------------------------------------
#  Per-scene narration helpers
# ---------------------------------------------------------------------------

def _get_clip_duration(path: str) -> float:
    """Get actual clip duration via ffprobe. Falls back to 8.0s."""
    try:
        result = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", path],
            capture_output=True, text=True, timeout=10
        )
        return float(result.stdout.strip()) if result.stdout.strip() else 8.0
    except Exception:
        return 8.0


MAX_NARRATION_EXTENSION = 2.0


def _overlay_narration_on_clip(clip_path: str, narration_path: str, output_path: str) -> bool:
    """Overlay narration audio onto a single clip. Returns True on success."""
    clip_dur = _get_clip_duration(clip_path)
    narr_dur = _get_clip_duration(narration_path)

    if narr_dur <= clip_dur:
        cmd = ["ffmpeg", "-y", "-i", clip_path, "-i", narration_path,
               "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
               "-map", "0:v", "-map", "1:a", "-shortest", output_path]
    elif narr_dur <= clip_dur + MAX_NARRATION_EXTENSION:
        extend_by = narr_dur - clip_dur
        cmd = ["ffmpeg", "-y", "-i", clip_path, "-i", narration_path,
               "-filter_complex",
               f"[0:v]tpad=stop_mode=clone:stop_duration={extend_by:.2f}[v]",
               "-map", "[v]", "-map", "1:a",
               "-c:v", "libx264", "-preset", "fast", "-crf", "20",
               "-c:a", "aac", "-b:a", "192k", "-pix_fmt", "yuv420p",
               "-shortest", output_path]
    else:
        max_dur = clip_dur + MAX_NARRATION_EXTENSION
        cmd = ["ffmpeg", "-y", "-i", clip_path, "-i", narration_path,
               "-filter_complex",
               f"[0:v]tpad=stop_mode=clone:stop_duration={MAX_NARRATION_EXTENSION:.2f}[v];"
               f"[1:a]atrim=0:{max_dur:.2f}[a]",
               "-map", "[v]", "-map", "[a]",
               "-c:v", "libx264", "-preset", "fast", "-crf", "20",
               "-c:a", "aac", "-b:a", "192k", "-pix_fmt", "yuv420p",
               output_path]

    try:
        proc = subprocess.run(cmd, capture_output=True, timeout=120)
        if proc.returncode == 0 and os.path.exists(output_path) and os.path.getsize(output_path) > 1000:
            logger.info("[STITCH] Narrated clip: %s (clip=%.1fs, narr=%.1fs)",
                        os.path.basename(output_path), clip_dur, narr_dur)
            return True
        logger.warning("[STITCH] Narration overlay failed for %s (rc=%d)", output_path, proc.returncode)
        return False
    except Exception as e:
        logger.warning("[STITCH] Narration overlay error: %s", e)
        return False


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

    proj_manifest_for_preset = await _load_manifest_from_r2(project_id)
    narr_preset = _manifest_preset_id(proj_manifest_for_preset)

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
        narration_mode = options.get("narration_mode", "per_scene")
        if include_narration:
            logger.info("[STITCH] Generating narration...")
            narration_files = await _generate_all_narration(project_id, work_dir, preset_id=narr_preset)

        # --- Per-scene narration overlay (default) ---
        narrated_dir = os.path.join(work_dir, "narrated")
        os.makedirs(narrated_dir, exist_ok=True)

        final_clips = []
        for clip_info in successful:
            scene_num = clip_info.get("scene", clip_info.get("from_scene", 0))
            graded_path = os.path.join(graded_dir, f"scene_{scene_num:02d}.mp4")
            if not os.path.exists(graded_path):
                continue

            if include_narration and narration_mode == "per_scene" and int(scene_num) in narration_files:
                narr_url = narration_files[int(scene_num)]
                narr_local = os.path.join(narrated_dir, f"narr_{scene_num:02d}.wav")
                try:
                    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=30)) as sess:
                        async with sess.get(narr_url) as r:
                            if r.status == 200:
                                with open(narr_local, "wb") as f:
                                    f.write(await r.read())
                except Exception as e:
                    logger.warning("[STITCH] Failed to download narration for scene %d: %s", scene_num, e)
                    narr_local = None

                if narr_local and os.path.exists(narr_local):
                    narrated_path = os.path.join(narrated_dir, f"scene_{scene_num:02d}.mp4")
                    if _overlay_narration_on_clip(graded_path, narr_local, narrated_path):
                        final_clips.append(narrated_path)
                    else:
                        final_clips.append(graded_path)
                else:
                    final_clips.append(graded_path)
            else:
                final_clips.append(graded_path)

        if len(final_clips) < 2:
            logger.warning("[STITCH] Not enough final clips")
            return None

        concat_path = os.path.join(work_dir, "concat.txt")
        with open(concat_path, "w") as f:
            for clip_path in final_clips:
                f.write(f"file '{clip_path}'\n")

        raw_output = os.path.join(work_dir, "trailer_raw.mp4")
        subprocess.run([
            "ffmpeg", "-y", "-f", "concat", "-safe", "0",
            "-i", concat_path, "-c:v", "libx264",
            "-pix_fmt", "yuv420p", "-preset", "fast",
            "-crf", "22", "-movflags", "+faststart", raw_output,
        ], capture_output=True, timeout=900)

        final_output = raw_output

        # Legacy post-concat narration fallback
        if include_narration and narration_mode == "post_concat" and narration_files:
            scene_offsets: dict[int, float] = {}
            cumulative = 0.0
            for clip_path in final_clips:
                scene_num_str = os.path.basename(clip_path).replace("scene_", "").replace(".mp4", "")
                try:
                    sn = int(scene_num_str)
                except ValueError:
                    sn = 0
                scene_offsets[sn] = cumulative
                cumulative += _get_clip_duration(clip_path)
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
