"""Training Ground chat context for ILM WS turns — QUANTUM-CRYSTAL-ARCH."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

_CATALOG_PATH = (
    Path(__file__).resolve().parents[2]
    / "resources"
    / "training_ground"
    / "ilm_archetype_catalog.json"
)


def _load_catalog() -> Dict[str, Any]:
    try:
        return json.loads(_CATALOG_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {"seats": [], "language_rule": ""}


async def build_training_ground_context(
    db_pool: Any,
    username: str,
    *,
    exercise_mode: Optional[str] = None,
) -> str:
    if not db_pool or not username:
        return ""

    catalog = _load_catalog()
    parts: List[str] = [
        "[TRAINING GROUND — INNER LEADERSHIP MAPPING]",
        "Non-clinical coaching space. Mapping-only IFS (no exile unburdening).",
        catalog.get("language_rule", ""),
    ]

    async with db_pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT part_name, ilm_archetype_base, ifs_role, coaching_status,
                   activation_score, thera_world_template_id
              FROM user_parts_registry
             WHERE user_id = $1 AND origin = 'training_ground' AND is_active = TRUE
             ORDER BY part_name
            """,
            username,
        )
        rel_rows = await conn.fetch(
            """
            SELECT r.relationship_type, r.conflict_intensity,
                   sp.part_name AS source_name, tp.part_name AS target_name
              FROM user_part_relationships r
              JOIN user_parts_registry sp ON sp.id = r.source_part_id
              JOIN user_parts_registry tp ON tp.id = r.target_part_id
             WHERE r.user_id = $1
            """,
            username,
        )

    if rows:
        parts.append("COUNCIL MEMBERS:")
        for r in rows:
            parts.append(
                f"- {r['part_name']} ({r['ilm_archetype_base'] or 'part'}): "
                f"status={r['coaching_status']}, activation={r['activation_score']}"
            )
    else:
        parts.append("COUNCIL: (empty — client still forming council)")

    hold = [r for r in rows if r["coaching_status"] == "HOLD"]
    if hold:
        parts.append(
            "COACH HOLD active — use Skill Integration copy; do not run depth exercises."
        )

    pending = [r for r in rows if r["coaching_status"] == "PENDING_APPROVAL"]
    if pending:
        parts.append(
            f"{len(pending)} council member(s) awaiting coach approval — "
            "dialogue exercises require at least one APPROVED member."
        )

    if rel_rows:
        parts.append("RELATIONSHIPS:")
        for rr in rel_rows:
            parts.append(
                f"- {rr['source_name']} → {rr['target_name']}: "
                f"{rr['relationship_type']} (intensity {rr['conflict_intensity']})"
            )

    if exercise_mode:
        parts.append(f"EXERCISE MODE: {exercise_mode}")

    return "\n".join(parts)
