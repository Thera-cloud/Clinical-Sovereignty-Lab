"""World Story Bible adapter — visual manifestation directives from
core_character_foundation.md Section VII.

Provides phase-specific and archetype-category-aware visual suffixes
that anchor every generated panel in the Thera-World's origin story.
"""
from __future__ import annotations

import json
import logging
import os
from typing import Optional

logger = logging.getLogger(__name__)

_LIB_PATH = os.path.join(
    os.path.dirname(__file__),
    "..", "..", "..",
    "resources", "therapeutic_library", "imagery_guides",
    "archetypes", "sse_archetype_reference_library.json",
)

_ARCHETYPE_LIB: dict | None = None


def _load_archetype_lib() -> dict:
    global _ARCHETYPE_LIB
    if _ARCHETYPE_LIB is not None:
        return _ARCHETYPE_LIB
    try:
        with open(os.path.normpath(_LIB_PATH)) as f:
            _ARCHETYPE_LIB = json.load(f)
    except Exception as e:
        logger.warning("world_story_bible: could not load archetype library: %s", e)
        _ARCHETYPE_LIB = {}
    return _ARCHETYPE_LIB


# Section VII phase → visual manifestation mapping
_PHASE_MANIFESTATIONS: dict[str, str] = {
    "fog": (
        "gentle fog or luminous particles drift through the scene, "
        "moving with purpose but without direction, connecting without binding, "
        "the atmosphere feels alive and witnessing, the light within the fog casts no shadow"
    ),
    "encounter": (
        "a warm golden-white luminescence fills the space between elements, "
        "not as a beam but as a glow that belongs to neither and both, "
        "the light is the relationship between things made visible"
    ),
    "reflection": (
        "a perfectly still surface reflects not what is above but what is truest, "
        "the reflection subtly different — more open, more sovereign, more at rest, "
        "as if the reflection knows something the figure has not yet remembered"
    ),
    "sovereignty": (
        "a single small point of light catches on a natural surface, "
        "barely noticeable, not magical, just present, "
        "the kind of light that might be something or nothing, "
        "the kind of light that rewards the viewer who pauses to look"
    ),
}

# Archetype-category visual flavoring (drawn from Section VII secondary elements)
_CATEGORY_MANIFESTATION: dict[str, str] = {
    "warriors": "the figure casts two distinct shadows, evidence of light from more than one source",
    "guardians": "a gate stands open but the guardian is still present, choosing to let what is beyond come through",
    "explorers": "roots mirror branches in the water below, what grows upward has equal structure growing downward",
    "mystics": "faint iridescent patterns in crystal suggest movement without moving, the beauty undeniable even as its source is uncertain",
    "nature": "the atmosphere breathes with luminous particles, the boundary between figure and environment softens",
    "creative": "the surrounding space vibrates with the faintest shimmer at its edges, two realities coexist without collapsing",
    "mythical": "the figure casts two distinct shadows, one warmer than the other, overlapping where two lights meet",
    "royal": "power that does not need to be occupied to be real, the space defines authority without filling it",
    "shadow": "a single iridescent scale rests on the ground, detached, no longer armor, beautiful in isolation",
    "child": "a small point of light illuminates from within, not external, a glowing bloom of innate worth",
    "technological": "faint circuit-light patterns interweave with organic forms, the digital and living finding common ground",
    "animal": "the atmosphere holds both stillness and alertness, the space between creature and world feels charged",
}

# Map archetype_hint (from identity forge) → category key
_HINT_TO_CATEGORY: dict[str, str] = {
    "warrior": "warriors",
    "sage": "mystics",
    "healer": "mystics",
    "guardian": "guardians",
    "explorer": "explorers",
    "seraph": "mythical",
}

# Map DB phase names to canonical Section VII keys
_PHASE_MAP: dict[str, str] = {
    "the_becoming": "fog",
    "the_fog": "fog",
    "fog": "fog",
    "the_encounter": "encounter",
    "encounter": "encounter",
    "the_reflection": "reflection",
    "reflection": "reflection",
    "the_sovereignty": "sovereignty",
    "sovereignty": "sovereignty",
}


def get_visual_style_for_archetype(archetype_hint: str) -> dict[str, str]:
    """Return the visual_style dict for a specific archetype from the library.

    Falls back to an empty dict if the archetype is not found.
    """
    lib = _load_archetype_lib()
    hint_lower = (archetype_hint or "").lower().strip()
    for cat_data in lib.get("categories", {}).values():
        for arch in cat_data.get("archetypes", []):
            if arch.get("id") == hint_lower or hint_lower in arch.get("name", "").lower():
                return arch.get("visual_style", {})
    return {}


async def get_character_manifestation(
    phase: str,
    archetype_category: str | None = None,
    archetype_hint: str | None = None,
) -> str:
    """Build a visual directive suffix from Section VII of core_character_foundation.md.

    Combines a phase-specific manifestation with a category-specific
    visual element. Returns a 1-3 sentence string suitable for appending
    to a Grok Imagine prompt.

    Parameters:
        phase: the user's current therapeutic phase (DB value like 'the_becoming')
        archetype_category: optional category key (e.g. 'warriors', 'mystics')
        archetype_hint: optional hint from sse_identity_forge (e.g. 'warrior', 'sage')
    """
    canonical_phase = _PHASE_MAP.get(phase, "fog")
    phase_suffix = _PHASE_MANIFESTATIONS.get(canonical_phase, _PHASE_MANIFESTATIONS["fog"])

    cat = archetype_category
    if not cat and archetype_hint:
        cat = _HINT_TO_CATEGORY.get(archetype_hint.lower().strip(), "explorers")
    cat = cat or "explorers"

    cat_suffix = _CATEGORY_MANIFESTATION.get(cat, "")

    parts = [phase_suffix]
    if cat_suffix:
        parts.append(cat_suffix)
    return ", ".join(parts)


def get_visual_style_suffix(archetype_hint: str | None) -> str:
    """Return an art-direction string from the archetype's visual_style fields."""
    if not archetype_hint:
        return ""
    vs = get_visual_style_for_archetype(archetype_hint)
    if not vs:
        return ""
    parts = []
    if vs.get("art_direction"):
        parts.append(vs["art_direction"])
    if vs.get("color_palette"):
        parts.append(vs["color_palette"])
    if vs.get("lighting"):
        parts.append(vs["lighting"])
    if vs.get("atmosphere"):
        parts.append(vs["atmosphere"])
    return ", ".join(parts)
