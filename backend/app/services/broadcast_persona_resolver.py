"""3-layer broadcast persona. Layers 1–2 platform-locked. QUANTUM-CRYSTAL-ARCH"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, Optional

from app.services.studio_invariants import (
    LN_COHOST_LABEL,
    STYLE_KEYS,
    VERTICALS,
    filter_style_layer,
    inv6_blocks,
)

logger = logging.getLogger("broadcast_persona")


async def resolve(db_pool, show_id: str) -> Dict[str, Any]:
    if not db_pool:
        return {"ok": False, "reason": "no_db"}
    async with db_pool.acquire() as conn:
        show = await conn.fetchrow(
            """
            SELECT id, coach_id, name, vertical, persona_style_layer
            FROM studio_shows WHERE id = $1::uuid
            """,
            show_id,
        )
        if not show:
            return {"ok": False, "reason": "show_not_found"}
        guard = await conn.fetchrow(
            """
            SELECT version, document FROM studio_persona_versions
            WHERE layer = 'guardrail'
            ORDER BY created_at DESC LIMIT 1
            """,
        )
        vertical = show["vertical"]
        vert = await conn.fetchrow(
            """
            SELECT version, document FROM studio_persona_versions
            WHERE layer = 'vertical' AND vertical = $1
            ORDER BY created_at DESC LIMIT 1
            """,
            vertical,
        )
    style = show.get("persona_style_layer") or {}
    if isinstance(style, str):
        try:
            style = json.loads(style)
        except Exception:
            style = {}
    if not isinstance(style, dict):
        style = {}
    cleaned, _ = filter_style_layer(style)
    return {
        "ok": True,
        "show_id": str(show["id"]),
        "coach_id": show["coach_id"],
        "label": LN_COHOST_LABEL,
        "guardrail": {
            "version": (guard or {}).get("version") if guard else None,
            "document": _doc(guard),
            "locked": True,
        },
        "vertical": {
            "id": vertical,
            "version": (vert or {}).get("version") if vert else None,
            "document": _doc(vert),
            "locked": True,
        },
        "style": cleaned,
        "style_keys": sorted(STYLE_KEYS),
    }


def _doc(row) -> Dict[str, Any]:
    if not row:
        return {}
    raw = row.get("document") if hasattr(row, "get") else None
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except Exception:
            return {}
    return dict(raw) if isinstance(raw, dict) else {}


def validate_show_copy(name: str, description: str = "") -> Optional[str]:
    blob = f"{name or ''} {description or ''}"
    if inv6_blocks(blob):
        return "INV-6: show copy cannot market Little Nate as clinical or advisory"
    if (name or "").strip() == "":
        return "name required"
    if (description or "") and len(description) > 4000:
        return "description too long"
    return None


def validate_vertical(vertical: str) -> Optional[str]:
    if vertical not in VERTICALS:
        return f"vertical must be one of {','.join(VERTICALS)}"
    return None
