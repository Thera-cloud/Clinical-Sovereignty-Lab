"""Shared Thera-world palette — Little Nate and journey imagery use one world.

QUANTUM-CRYSTAL-ARCH — LN composes Thera-world; do not invent a second setting.
"""

from __future__ import annotations

from typing import Any, Iterable, Optional

# Landmarks stay inside the five biomes. LN may add 1–3 of these to a scene.
BIOME_LANDMARKS: dict[str, tuple[str, ...]] = {
    "dark_forest": (
        "a lantern cairn marking a fork",
        "a fog path that keeps inviting one more step",
        "a watch-tree with a hollow that holds a dim light",
        "a hidden spring under moss",
    ),
    "fortress_plains": (
        "a watchtower with a door left open",
        "a rope bridge with each plank distinct",
        "a low stone wall with a generous gate",
        "a signal fire kept small and steady",
    ),
    "river_valley": (
        "crystal river stepping-stones",
        "healing trees along the bank",
        "a wildflower meadow after rain",
        "a bench that still remembers company",
    ),
    "crystal_mountains": (
        "a cave that glows from within",
        "a crystal seam in the rock",
        "an overlook ledge above cloud",
        "a wind-carved stair",
    ),
    "open_sky": (
        "a ridge catching first dawn",
        "a single standing stone",
        "horizon light widening without hurry",
        "a cloak set down, no longer needed",
    ),
    # --- Neuro region (additive; Origin tuples above are byte-identical) ---
    "coliseum_of_ascendance": (
        "the Crown of Verdict hanging in still light above the floor",
        "a ring of broken champion statues on the tiers",
        "an empty stone seat at the arena's edge",
        "a gate left open onto the floor",
    ),
    "confluence_of_tides": (
        "three currents meeting — clear-fast, dark-cold, silver-bright",
        "a central platform mosaic of waves that only reads whole from every side",
        "lashed hulls creaking softly against each other",
        "a mooring rope with room to give",
    ),
    "aerolith_cloud_city": (
        "cloudstone islands bound by lightning tethers",
        "a spire beginning to cast its own shadow",
        "a bridge of light that remains but is no longer a chain",
        "the distinct lands of the world visible far below",
    ),
    "hearthworld_of_returning": (
        "the First Hearth burning steady at the center",
        "a root-bridge pulsing with soft light",
        "a second seat pulled near the fire",
        "a bridge mended where it was torn, glowing brighter there",
    ),
}

STORY_BEATS: tuple[str, ...] = (
    "threshold crossing",
    "camp rest with a second seat left open",
    "companion appearing at middle distance",
    "setting something down on a stone",
    "first light after gray",
    "mending a path one stone at a time",
    "looking into still water that answers kindly",
    "leaving a door ajar",
)

CORE_CHARACTERS: tuple[str, ...] = (
    "Mirror",
    "Serpent",
    "Pride/Shame",
    "Reflection",
    "Holy Spirit",
    "Curiosity",
)

COMPANION_NAMES: tuple[str, ...] = (
    "The Weaver",
    "The Hearthkeeper",
    "The Bridgewright",
    "The Gardener",
    "The Stillwater Monk",
    "The Veiled Pilgrim",
    "The Cartographer",
    "The Forgemaster",
    "The Torchbearer",
    "The Falconer",
    "The Root Tender",
    "The Scalekeeper",
    "The Mender",
    "The Stonecutter",
    "The Maskmaker",
    "The Goldsmith",
    "The Lantern Keeper",
    "The Ferryman",
    "The Innkeeper",
    "The Wallwright",
    "The Gatekeeper",
    "The Pilgrim Elder",
    "The Dawnsinger",
    "The Ember Carrier",
    "The Star Reader",
    "The Rainmaker",
    "The Wandering Scholar",
    "The Orchard Keeper",
    "The Archivist",
    "The Fire Tender",
    "The Cloakless Traveler",
)


def _csv(items: Iterable[str], limit: int = 12) -> str:
    seen: list[str] = []
    for raw in items:
        name = (raw or "").strip()
        if name and name not in seen:
            seen.append(name)
        if len(seen) >= limit:
            break
    return ", ".join(seen)


def format_thera_world_concept_palette(
    *,
    biome: str = "",
    core_character: str = "",
    quest_goal: str = "",
    mission_target: str = "",
    present_npcs: Optional[Iterable[Any]] = None,
    extra_landmarks: Optional[Iterable[str]] = None,
) -> str:
    """Bounded expansion list for LN + Grok Imagine. Stay in Thera-world."""
    biome_key = (biome or "dark_forest").strip().lower().replace(" ", "_")
    landmarks = list(BIOME_LANDMARKS.get(biome_key) or BIOME_LANDMARKS["dark_forest"])
    for extra in extra_landmarks or []:
        if extra and extra not in landmarks:
            landmarks.append(extra)
    present: list[str] = []
    for npc in present_npcs or []:
        if isinstance(npc, dict):
            n = (npc.get("name") or "").strip()
        else:
            n = str(npc or "").strip()
        if n:
            present.append(n)
    optional_companions = [n for n in COMPANION_NAMES if n not in present][:10]
    q = (quest_goal or "").strip()
    m = (mission_target or "").strip()
    if q.lower() in ("", "none", "none (clinical hold — no action-oriented missions)"):
        q = ""
    if m.lower() in ("", "none", "none (clinical hold)"):
        m = ""
    lines = [
        "[THERA-WORLD ↔ LITTLE NATE — one world, one voice]",
        "You are Little Nate composing Thera-world. The image the client will later ask "
        "you about must be the same place you describe now. Do not invent a city, office, "
        "stock landscape, or a second mythology.",
        f"Required setting: {(biome or 'dark_forest').replace('_', ' ')}",
        f"Required core character: {core_character or 'Mirror'}",
        "You MAY expand the imagery with 1–3 additional in-world concepts from this "
        "palette when they deepen the therapeutic moment. Expansion is optional. "
        "Do not crowd the frame. Do not leave Thera-world.",
        f"Landmarks you may add: {_csv(landmarks, 8)}",
        f"Story beats you may add: {_csv(STORY_BEATS, 8)}",
        f"Companions you may invite (middle distance, named): {_csv(optional_companions, 10)}",
        f"Core characters already in this world (do not replace the required one): {_csv(CORE_CHARACTERS)}",
    ]
    if present:
        lines.append(f"Already present today (keep them): {_csv(present, 6)}")
    if q:
        lines.append(f"Active quest object/thread you may visualize: {q[:160]}")
    if m:
        lines.append(f"Active mission thread you may visualize: {m[:160]}")
    return "\n".join(lines)
