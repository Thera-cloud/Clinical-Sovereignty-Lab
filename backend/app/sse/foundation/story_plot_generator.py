"""
SSE Stage 1 — Story Plot Generator

Transforms a narrative extraction dict into a fully formed story_plot JSON
with per-panel Grok Imagine prompts, delivery config, and cost estimates.

Every panel includes a core character visual manifestation suffix drawn from
core_character_foundation.md Section V.
"""
from __future__ import annotations

import re
from typing import Any

# --- Grok Imagine prompt suffixes (core_character_foundation.md §V) ---

IMAGINE_SUFFIXES: dict[str, str] = {
    "Serpent's Whisper": (
        "...faint iridescent patterns visible in [glass/ice/crystal/water surface], "
        "suggesting movement without moving, not threatening but questioning, "
        "as if the pattern is trying to recognize itself, "
        "the beauty of the pattern is undeniable even as its source is uncertain"
    ),
    "Dragon Scale": (
        "...a single iridescent scale rests on [ground/stone/water surface], "
        "detached, no longer armor, beautiful in isolation, "
        "catching light from two directions, evidence that something large "
        "is becoming something honest"
    ),
    "Dual Shadow": (
        "...the figure casts two distinct shadows, one slightly warmer than the other, "
        "neither shadow is darkness — both are evidence of light from more than one source, "
        "the shadows overlap at the figure's feet where the two lights meet"
    ),
    "Still Surface": (
        "...a perfectly still body of water reflects not the sky but the figure's "
        "truest self, the reflection subtly different from the figure above — "
        "more open, more sovereign, more at rest, as if the reflection knows "
        "something the figure has not yet remembered"
    ),
    "Breath Between": (
        "...gentle fog or luminous particles drift between [elements/characters], "
        "moving with purpose but without direction, connecting without binding, "
        "the atmosphere itself feels alive and witnessing, holding everything "
        "without preference, the light within the fog casts no shadow"
    ),
    "Mirror Light": (
        "...warm golden-white luminescence fills the space between the figures, "
        "not as a beam but as a glow that belongs to neither and both, "
        "the light is the relationship between them made visible, "
        "painterly, atmospheric, soft focus on the light itself"
    ),
    "Glimmer": (
        "...a single small point of light catches on [leaf/stone/water drop/strand of hair], "
        "barely noticeable, not magical, not supernatural, just present, "
        "the kind of light that might be something or might be nothing, "
        "the kind of light that rewards the viewer who pauses to look"
    ),
}

PHASE_MANIFESTATION: dict[str, str] = {
    "sealed_book": "Serpent's Whisper",
    "tower_revealed": "Dragon Scale",
    "the_watchwoman": "Dual Shadow",
    "the_door": "Still Surface",
    "the_meadow": "Breath Between",
    "the_becoming": "Mirror Light",
    "the_sacred_hallway": "Glimmer",
    "open_world": "Mirror Light",
}


def _build_audio_profile(biome: str, panel_tone: str) -> str:
    if panel_tone == "meditative":
        return f"ambient_meditative_{biome or 'default'}"
    return f"cinematic_{biome or 'default'}"


def _slugify(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")
    return slug


async def generate(narrative: dict[str, Any]) -> dict[str, Any]:
    doc_type = narrative.get("document_type", "narrative_arc")
    phases = narrative.get("phases_detected", [])
    story_name = narrative.get("story_name", "untitled")
    story_id = narrative.get("story_id") or f"storyboard_{_slugify(story_name)}_v1.0"
    audience = narrative.get("audience", "general")

    panels: list[dict[str, Any]] = []
    new_spaces = 0

    for phase in phases:
        mapping = phase.get("sse_phase_mapping", "the_becoming")
        manifestation = PHASE_MANIFESTATION.get(mapping, "Glimmer")
        suffix = IMAGINE_SUFFIXES.get(manifestation, IMAGINE_SUFFIXES["Glimmer"])
        biome = phase.get("biome", "")
        sacred_space = phase.get("sacred_space", "")
        key_visual = phase.get("key_visual", "")
        panel_tone = phase.get("panel_tone", "action_sequence")

        scene_desc = f"{phase.get('description', '')} — {key_visual}".strip(" —")
        grok_prompt = f"{scene_desc}, {suffix}, no text, no words, no lettering, no calligraphy, no writing on image"

        panels.append({
            "phase_id": mapping,
            "panel_tone": panel_tone,
            "scene_description": scene_desc,
            "grok_imagine_prompt": grok_prompt,
            "core_character_suffix": manifestation,
            "biome": biome,
            "sacred_space": sacred_space,
            "audio_profile": _build_audio_profile(biome, panel_tone),
        })

        spaces_meta = narrative.get("spaces_detected", {})
        if sacred_space and sacred_space in [s for s in spaces_meta.get("new_required", [])]:
            new_spaces += 1

    is_workbook = doc_type == "theological_workbook"

    clinical_pacing = narrative.get("clinical_pacing_notes", "")
    age_tier = narrative.get("age_tier_hints", "adult")

    if "DID" in clinical_pacing.upper() or "dissociative" in clinical_pacing.lower():
        min_ec = 0.35
    elif any(kw in clinical_pacing.lower() for kw in ("descent", "grief", "trauma", "broken")):
        min_ec = 0.30
    elif is_workbook:
        min_ec = 0.15
    else:
        min_ec = 0.30

    delivery_config: dict[str, Any] = {
        "cadence": "daily_panel_plus_weekly_clip_plus_monthly_recap",
        "weekly_clip": not is_workbook,
        "monthly_recap": True,
        "age_tier": age_tier,
        "clinical_eligibility": {
            "min_ec_score": min_ec,
            "notes": clinical_pacing or "Standard clinical gating",
        },
        "panel_generation_style": "meditative" if is_workbook else "action_sequence",
    }

    new_spaces_count = len(narrative.get("spaces_detected", {}).get("new_required", []))

    estimated_cost: dict[str, Any] = {
        "new_images_count": len(panels),
        "estimated_grok_cost": f"${len(panels) * 0.07:.2f}",
        "new_sacred_spaces_count": new_spaces_count,
    }

    story_plot: dict[str, Any] = {
        "id": story_id,
        "name": story_name,
        "audience": audience,
        "document_type": doc_type,
        "panels": panels,
    }

    return {
        "story_plot": story_plot,
        "delivery_config": delivery_config,
        "estimated_cost": estimated_cost,
    }
