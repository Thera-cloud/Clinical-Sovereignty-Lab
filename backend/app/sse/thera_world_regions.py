"""Thera-world regions — Origin (The Path of Five) + Neuro.

QUANTUM-CRYSTAL-ARCH — additive. Origin ids, thresholds and characters are
untouched; this module only names the region a biome belongs to and loads the
Neuro biome catalog. Constants only — no DB, no LLM.

Client language wall: the four Neuro structure keys (authority / integration /
separation / attachment) are ENGINE-ONLY. Never surface them in client copy.
"""

from __future__ import annotations

import json
import os
from typing import Any, Dict, List, Optional

REGION_ORIGIN = "origin"
REGION_NEURO = "neuro"
REGIONS = (REGION_ORIGIN, REGION_NEURO)

ORIGIN_BIOMES: tuple[str, ...] = (
    "dark_forest",
    "fortress_plains",
    "river_valley",
    "crystal_mountains",
    "open_sky",
)

# Engine-only structure keys (never shown to clients).
NEURO_STRUCTURES: tuple[str, ...] = ("authority", "integration", "separation", "attachment")
NEURO_POLES: tuple[str, ...] = ("deficit", "mature", "hyper")

NEURO_BIOMES: tuple[str, ...] = (
    "coliseum_of_ascendance",
    "confluence_of_tides",
    "aerolith_cloud_city",
    "hearthworld_of_returning",
)

# structure -> biome (setting doorway) and back
STRUCTURE_TO_BIOME: Dict[str, str] = {
    "authority": "coliseum_of_ascendance",
    "integration": "confluence_of_tides",
    "separation": "aerolith_cloud_city",
    "attachment": "hearthworld_of_returning",
}
BIOME_TO_STRUCTURE: Dict[str, str] = {v: k for k, v in STRUCTURE_TO_BIOME.items()}

# Coliseum floor roll — every Coliseum panel picks one (stored on panel_metadata.floor_id).
COLISEUM_FLOORS: tuple[str, ...] = (
    "sand",
    "obsidian_glass",
    "shallow_water",
    "mosaic_of_former_crowns",
    "iron_grate",
    "living_grass",
    "cracked_marble",
    "mist_well",
)
COLISEUM_FLOOR_VISUAL: Dict[str, str] = {
    "sand": "a floor of pale raked sand",
    "obsidian_glass": "a floor of black obsidian glass reflecting the crown",
    "shallow_water": "a floor of shallow still water an inch deep",
    "mosaic_of_former_crowns": "a floor mosaic of former crowns in worn tile",
    "iron_grate": "a floor of wide iron grate over a dim drop",
    "living_grass": "a floor of living grass pushing through the stone",
    "cracked_marble": "a floor of cracked marble veined with starlight",
    "mist_well": "a floor of low mist with a well at its center",
}

_DATA_PATH = os.path.join(os.path.dirname(__file__), "data", "thera_world_regions.json")
_catalog_cache: Optional[Dict[str, Any]] = None


def load_region_catalog() -> Dict[str, Any]:
    global _catalog_cache
    if _catalog_cache is None:
        with open(_DATA_PATH, "r", encoding="utf-8") as fh:
            _catalog_cache = json.load(fh)
    return _catalog_cache


def region_for_biome(biome_id: str) -> str:
    """Origin unless the biome is a Neuro place. Unknown ids default to origin."""
    if (biome_id or "") in NEURO_BIOMES:
        return REGION_NEURO
    return REGION_ORIGIN


def neuro_biome_spec(biome_id: str) -> Dict[str, Any]:
    """Catalog row for a Neuro biome (display_name, description, bright_description, ...)."""
    for region in load_region_catalog().get("regions", []):
        if region.get("region_id") != REGION_NEURO:
            continue
        for b in region.get("biomes", []):
            if b.get("biome_id") == biome_id:
                return dict(b)
    return {}


def biome_display_name(biome_id: str) -> str:
    """Client-safe place name for any biome id (Origin or Neuro)."""
    for region in load_region_catalog().get("regions", []):
        for b in region.get("biomes", []):
            if b.get("biome_id") == biome_id:
                return b.get("display_name") or biome_id.replace("_", " ").title()
    return (biome_id or "").replace("_", " ").title()


def list_neuro_biomes() -> List[Dict[str, Any]]:
    for region in load_region_catalog().get("regions", []):
        if region.get("region_id") == REGION_NEURO:
            return [dict(b) for b in region.get("biomes", [])]
    return []
