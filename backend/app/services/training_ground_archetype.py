"""ILM archetype catalog helpers — QUANTUM-CRYSTAL-ARCH."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

_CATALOG_PATH = (
    Path(__file__).resolve().parents[2]
    / "resources"
    / "training_ground"
    / "ilm_archetype_catalog.json"
)

_CATALOG_CACHE: Optional[Dict[str, Any]] = None


def load_ilm_catalog() -> Dict[str, Any]:
    global _CATALOG_CACHE
    if _CATALOG_CACHE is not None:
        return _CATALOG_CACHE
    try:
        _CATALOG_CACHE = json.loads(_CATALOG_PATH.read_text(encoding="utf-8"))
    except Exception:
        _CATALOG_CACHE = {"seats": [], "language_rule": ""}
    return _CATALOG_CACHE


def seat_for_archetype(ilm_archetype_base: Optional[str]) -> Optional[Dict[str, Any]]:
    if not ilm_archetype_base:
        return None
    key = ilm_archetype_base.strip()
    for seat in load_ilm_catalog().get("seats") or []:
        if seat.get("ilm_archetype_base") == key:
            return seat
    return None


def resolve_propose_defaults(
    *,
    part_category: Optional[str],
    ifs_role: Optional[str],
    ilm_archetype_base: Optional[str],
) -> Tuple[str, Optional[str], Optional[str]]:
    """Apply catalog defaults when client proposes a council seat."""
    archetype = (ilm_archetype_base or "").strip() or None
    seat = seat_for_archetype(archetype)
    category = (part_category or "").strip() or None
    role = (ifs_role or "").strip() or None

    if seat:
        if not category:
            default_cat = seat.get("ifs_role_default")
            if default_cat:
                category = str(default_cat)
        if not role:
            default_role = seat.get("ifs_role_default")
            if default_role:
                role = str(default_role)

    if not category:
        category = "manager"
    if not role:
        role = category if category in {
            "manager", "firefighter", "exile", "self_energy", "protector",
        } else None

    return category, role, archetype


def effective_ifs_role(part_category: Optional[str], ifs_role: Optional[str]) -> str:
    role = (ifs_role or "").strip()
    if role:
        return role
    category = (part_category or "").strip()
    return category or "part"
