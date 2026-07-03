"""Training Ground chat context for ILM WS turns — QUANTUM-CRYSTAL-ARCH."""

from __future__ import annotations

from typing import Any, List, Optional

from app.services.training_ground_archetype import (
    effective_ifs_role,
    load_ilm_catalog,
    seat_for_archetype,
)

# Mapping-safe domains from the crystal field (no raw clinical depth exercises).
_TG_RECALL_DOMAINS = frozenset({"coaching", "clinical", "research", "general"})


def _filter_scoped_crystal_recall(raw: str) -> str:
    """Keep coaching/clinical/research/general crystals + clinical DNA block."""
    if not raw:
        return ""

    header = [
        "[COACHING KNOWLEDGE FIELD — mapping use only]",
        "Use to teach IFS/parts language and normalize council dialogue.",
        "Do NOT use for diagnosis, trauma processing, or unburdening.",
    ]
    body: List[str] = []
    in_clinical_dna = False

    for line in raw.split("\n"):
        text = line.strip()
        if not text:
            continue
        if "CLINICAL DNA" in text and text.endswith(":"):
            in_clinical_dna = True
            body.append(line)
            continue
        if in_clinical_dna:
            if text.startswith("- "):
                body.append(line)
                continue
            in_clinical_dna = False
        if text.startswith("- ["):
            dom = text.split("[", 1)[1].split("]", 1)[0].strip().lower()
            if dom in _TG_RECALL_DOMAINS:
                body.append(line)

    if not body:
        return ""
    return "\n".join(header + body)


async def _training_ground_crystal_recall(
    db_pool: Any,
    username: str,
    user_text: str,
) -> str:
    """Scoped crystal recall for ILM — QUANTUM-CRYSTAL-ARCH."""
    try:
        from app.websocket.crystal_recall_bridge import recall_crystals_for_context

        raw = await recall_crystals_for_context(
            db_pool,
            username,
            max_results=5,
            source="training_ground",
            query_text=user_text or "",
        )
        return _filter_scoped_crystal_recall(raw)
    except Exception:
        return ""


async def build_training_ground_context(
    db_pool: Any,
    username: str,
    *,
    exercise_mode: Optional[str] = None,
    user_text: str = "",
) -> str:
    if not db_pool or not username:
        return ""

    catalog = load_ilm_catalog()
    parts: List[str] = [
        "[TRAINING GROUND — INNER LEADERSHIP MAPPING]",
        "Non-clinical coaching space. Mapping-only IFS (no exile unburdening).",
        catalog.get("language_rule", ""),
        (
            "TWO LENSES (do not conflate): "
            "ILM archetype = coaching metaphor held lightly; "
            "IFS part_category/ifs_role = coach-approved clinical mapping label."
        ),
        (
            "PURPOSE OF INNER TEAM DIALOGUE (hearing mode): "
            "Help the client notice what each council member does for them, "
            "in language their coach approved — not to diagnose or fix."
        ),
    ]

    async with db_pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT part_name, part_category, ilm_archetype_base, ifs_role,
                   coaching_status, coaching_status_notes,
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
        parts.append("COUNCIL MEMBERS (coach-approved labels are authoritative):")
        for r in rows:
            archetype = r["ilm_archetype_base"] or "part"
            eff_role = effective_ifs_role(r["part_category"], r["ifs_role"])
            line = (
                f"- {r['part_name']}: IFS={eff_role}, category={r['part_category']}, "
                f"ILM archetype={archetype}, status={r['coaching_status']}, "
                f"activation={r['activation_score']}"
            )
            parts.append(line)
            if r["coaching_status"] == "APPROVED":
                parts.append(
                    f"  COACH-APPROVED: Use IFS role '{eff_role}' for {r['part_name']}. "
                    f"Do NOT relabel as protector/firefighter/exile unless coach set that."
                )
                notes = (r["coaching_status_notes"] or "").strip()
                if notes:
                    parts.append(f"  COACH NOTES: {notes}")
                seat = seat_for_archetype(r["ilm_archetype_base"])
                if seat and seat.get("coaching_copy"):
                    parts.append(
                        f"  ARCHETYPE HINT ({archetype}, secondary): {seat['coaching_copy']}"
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

    crystal_block = await _training_ground_crystal_recall(db_pool, username, user_text)
    if crystal_block:
        parts.append(crystal_block)

    return "\n".join(parts)
