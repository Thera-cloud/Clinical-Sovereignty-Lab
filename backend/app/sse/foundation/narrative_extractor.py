"""SSE Stage 1 — Narrative Extractor: detect document type, call Grok for structured extraction."""
from __future__ import annotations

import json
import logging
import os
import re
from typing import Any

import aiohttp

logger = logging.getLogger(__name__)

_NARRATIVE_MARKERS = [
    "guided visualization", "close your eyes", "PART ONE", "PART TWO",
    "PART THREE", "Jesus Speaks", "Guided Prayer",
]

_WORKBOOK_MARKERS = [
    "Section 1:", "Section 2:", "Reflection Questions:",
    "reflection questions", "Action Steps:",
]

PHASE_TO_MANIFESTATION: dict[str, str] = {
    "sealed_book": "Serpent's Whisper",
    "tower_revealed": "Dragon Scale",
    "the_watchwoman": "Dual Shadow",
    "the_door": "Still Surface",
    "the_meadow": "Breath Between",
    "the_becoming": "Mirror Light",
    "the_sacred_hallway": "Glimmer",
    "open_world": "Mirror Light",
}

MODALITY_LOOKUP: dict[str, str] = {
    "IFS": "ifs", "Internal Family Systems": "ifs", "parts work": "ifs",
    "exiles": "ifs", "protectors": "ifs",
    "Attachment": "attachment_theory", "secure base": "attachment_theory",
    "earned security": "attachment_theory",
    "AEDP": "aedp", "core affect": "aedp", "undoing aloneness": "aedp",
    "EFT": "eft", "pursuer": "eft", "withdrawer": "eft",
    "Person-Centered": "rogers_person_centered",
    "unconditional positive regard": "rogers_person_centered",
    "NICC": "nicc", "co-regulation": "nicc", "window of tolerance": "nicc",
    "polyvagal": "polyvagal", "ventral vagal": "polyvagal",
    "neuroception": "polyvagal", "ANS": "polyvagal",
    "memory reconsolidation": "memory_reconsolidation",
    "mismatch": "memory_reconsolidation",
    "transformation window": "memory_reconsolidation",
    "jung": "jung_analytical", "shadow": "jung_analytical",
    "individuation": "jung_analytical", "archetype": "jung_analytical",
    "agape": "divine_resonance", "unconditional love": "divine_resonance",
    "grace": "divine_resonance", "holy spirit": "divine_resonance",
    "Jesus": "divine_resonance",
    "quantum": "faggin_quantum", "irreducible": "faggin_quantum",
}


def detect_document_type(raw_text: str) -> str:
    text_lower = raw_text.lower()
    narr = sum(1 for m in _NARRATIVE_MARKERS if m.lower() in text_lower)
    work = sum(1 for m in _WORKBOOK_MARKERS if m.lower() in text_lower)
    if work > narr:
        return "theological_workbook"
    return "narrative_arc"


def _is_thera_subset(preset_id: str | None) -> bool:
    pid = (preset_id or "").strip()
    return (not pid) or pid == "thera_world_origin" or "thera_world" in pid


async def extract(
    raw_text: str,
    filename: str,
    preset_id: str | None = None,
) -> dict[str, Any]:
    doc_type = detect_document_type(raw_text)
    grok_url = os.getenv("NATE_CHAT_URL", "")
    grok_key = os.getenv("NATE_CHAT_KEY", os.getenv("AZURE_API_KEY", ""))
    grok_model = os.getenv("NATE_CHAT_MODEL", "grok-4-1-fast-non-reasoning")
    use_thera = _is_thera_subset(preset_id)

    if doc_type == "narrative_arc":
        mode_instruction = "Extract PART headings + visualization sequences as phases."
    else:
        mode_instruction = "Extract Section headings + reflection arcs as phases."

    if use_thera:
        phase_rules = (
            "Phase mapping values must be one of: sealed_book, tower_revealed, the_watchwoman, "
            "the_door, the_meadow, the_becoming, the_sacred_hallway, open_world.\n\n"
            "core_character_manifestation per phase:\n"
            "  sealed_book → Serpent's Whisper\n  tower_revealed → Dragon Scale\n"
            "  the_watchwoman → Dual Shadow\n  the_door → Still Surface\n"
            "  the_meadow → Breath Between\n  the_becoming → Mirror Light\n"
            "  the_sacred_hallway → Glimmer\n  open_world → Mirror Light\n"
        )
    else:
        phase_rules = (
            "This is a NON-Thera subset generator. Do NOT use Thera-World mythology phases "
            "(sealed_book, dragon, serpent, watchwoman, sacred_hallway).\n"
            "sse_phase_mapping: snake_case slug from the phase name (e.g. intake_open, "
            "mirror_moment, closing_breath).\n"
            "core_character_manifestation: leave empty string — visual lock comes from "
            "subset casting / LoRA, not Thera bedrock manifestations.\n"
            "biome / sacred_space: use realistic clinical or subset setting labels, not "
            "Thera biomes.\n"
        )

    system_prompt = (
        "You are a clinical story structure extractor. Return ONLY valid JSON — "
        "no preamble, no markdown fences, no explanation.\n\n"
        f"Document type: {doc_type}. {mode_instruction}\n"
        f"Subset preset_id: {preset_id or 'thera_world_origin'}.\n\n"
        "Required JSON schema keys: story_name, story_id, audience, document_type, "
        "phases_detected (array of objects with: name, description, sse_phase_mapping, "
        "core_character_manifestation, panel_tone, key_visual, biome, sacred_space, "
        "therapeutic_action), characters_detected, spaces_detected (existing_match array, "
        "new_required array), biome_requirements (existing_match array, new_required array), "
        "therapeutic_modalities, clinical_pacing_notes, age_tier_hints, "
        "video_extraction (motion_scenes array, audio_atmosphere_per_biome object).\n\n"
        f"{phase_rules}\n"
        f"panel_tone: use 'action_sequence' for narrative_arc, 'meditative' for theological_workbook.\n"
        f"story_id should be a snake_case slug derived from the title."
    )

    truncated = raw_text[:24000]
    payload = {
        "model": grok_model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"Source document ({filename}):\n\n{truncated}"},
        ],
        "max_completion_tokens": 4000,
        "temperature": 0.3,
        "stream": False,
    }
    headers = {"Content-Type": "application/json", "api-key": grok_key}

    timeout = aiohttp.ClientTimeout(total=60)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.post(grok_url, json=payload, headers=headers) as resp:
            if resp.status != 200:
                body = await resp.text()
                raise RuntimeError(f"Grok extraction failed ({resp.status}): {body[:300]}")
            data = await resp.json()

    raw_content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
    cleaned = re.sub(r"^```(?:json)?\s*", "", raw_content.strip())
    cleaned = re.sub(r"\s*```$", "", cleaned)
    narrative: dict[str, Any] = json.loads(cleaned)

    narrative["document_type"] = doc_type
    if preset_id:
        narrative["preset_id"] = preset_id

    for phase in narrative.get("phases_detected", []):
        mapping = phase.get("sse_phase_mapping", "")
        if use_thera:
            phase["core_character_manifestation"] = PHASE_TO_MANIFESTATION.get(mapping, "Glimmer")
        else:
            phase["core_character_manifestation"] = phase.get("core_character_manifestation") or ""
            if mapping in PHASE_TO_MANIFESTATION:
                # Strip accidental Thera mythology ids from non-Thera extracts
                slug = re.sub(r"[^a-z0-9]+", "_", (phase.get("name") or "phase").lower()).strip("_")
                phase["sse_phase_mapping"] = slug or "phase"
        if doc_type == "theological_workbook":
            phase["panel_tone"] = "meditative"
        else:
            phase["panel_tone"] = "action_sequence"

    modalities = narrative.get("therapeutic_modalities", [])
    enriched: list[str] = []
    for mod in modalities:
        matched_id = None
        for keyword, wb_id in MODALITY_LOOKUP.items():
            if keyword.lower() in mod.lower():
                matched_id = wb_id
                break
        enriched.append(f"{mod} [workbook:{matched_id}]" if matched_id else mod)
    narrative["therapeutic_modalities"] = enriched

    return narrative
