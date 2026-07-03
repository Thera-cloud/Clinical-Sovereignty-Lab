"""Sole write path for Training Ground council rows — QUANTUM-CRYSTAL-ARCH."""

from __future__ import annotations

import re
from typing import Any, Dict, Optional

CONSENT_VERSION = "tg_v1_2026"

_PII_EMAIL = re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}")
_PII_PHONE = re.compile(r"\b\d{3}[-.\s]?\d{3}[-.\s]?\d{4}\b")
_PII_SSN = re.compile(r"\b\d{3}-\d{2}-\d{4}\b")


def screen_free_text(field: str, text: Optional[str]) -> Optional[str]:
    if not text:
        return None
    sample = str(text)
    if _PII_EMAIL.search(sample):
        return "email_in_field"
    if _PII_PHONE.search(sample):
        return "phone_in_field"
    if _PII_SSN.search(sample):
        return "ssn_in_field"
    return None


async def has_active_consent(conn: Any, username: str) -> bool:
    row = await conn.fetchrow(
        """
        SELECT 1 FROM training_ground_consent
         WHERE user_id = $1
           AND consent_version = $2
           AND revoked_at IS NULL
           AND acknowledged_non_clinical = TRUE
           AND acknowledged_coach_visibility = TRUE
           AND acknowledged_persistence = TRUE
        LIMIT 1
        """,
        username,
        CONSENT_VERSION,
    )
    return row is not None


async def insert_ilm_part(
    conn: Any,
    *,
    username: str,
    part_name: str,
    part_category: str,
    description: Optional[str] = None,
    ilm_archetype_base: Optional[str] = None,
    ifs_role: Optional[str] = None,
    thera_world_template_id: Optional[str] = None,
    activation_score: int = 0,
    created_by: str,
) -> Dict[str, Any]:
    """Insert council member — consent gate enforced inside (LB-1)."""
    if not await has_active_consent(conn, username):
        return {"ok": False, "reason": "consent_required"}

    pii_hit = screen_free_text("description", description)
    if pii_hit:
        return {"ok": False, "reason": "pii_pattern_in_field", "pattern": pii_hit}

    if part_category not in {
        "protector", "exile", "firefighter", "manager",
        "self_energy", "addict_part", "inner_critic",
        "caretaker", "dissociative_part", "other",
    }:
        return {"ok": False, "reason": "invalid_part_category"}

    row = await conn.fetchrow(
        """
        INSERT INTO user_parts_registry (
            user_id, part_name, part_category, description,
            ilm_archetype_base, ifs_role, thera_world_template_id,
            activation_score, coaching_status, origin,
            is_active, created_by
        ) VALUES (
            $1, $2, $3, $4, $5, $6, $7,
            $8, 'PENDING_APPROVAL', 'training_ground',
            TRUE, $9
        )
        ON CONFLICT (user_id, part_name) DO UPDATE
           SET is_active = TRUE,
               part_category = EXCLUDED.part_category,
               description = EXCLUDED.description,
               ilm_archetype_base = EXCLUDED.ilm_archetype_base,
               ifs_role = EXCLUDED.ifs_role,
               thera_world_template_id = EXCLUDED.thera_world_template_id,
               activation_score = EXCLUDED.activation_score,
               coaching_status = 'PENDING_APPROVAL',
               origin = 'training_ground',
               retired_at = NULL
        RETURNING id, coaching_status, origin
        """,
        username,
        part_name.strip()[:64],
        part_category,
        description,
        ilm_archetype_base,
        ifs_role,
        thera_world_template_id,
        max(0, min(100, int(activation_score))),
        created_by,
    )
    return {
        "ok": True,
        "id": int(row["id"]),
        "coaching_status": row["coaching_status"],
        "origin": row["origin"],
    }
