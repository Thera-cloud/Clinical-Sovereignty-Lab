"""Client-initiated codeword / parts persistence from bridge WebSocket.

# QUANTUM-CRYSTAL-ARCH — v1.4 conversational enrollment into Sensitive Profile.
Plaintext codewords are hashed exactly like coach-initiated paths; never logged.
"""

from __future__ import annotations

import logging
import secrets
from typing import Any, Dict, Optional, Tuple

from fastapi import HTTPException, status

from app.routers.sensitive_profile_api import (
    ACCESS_CLINICIAN_AND_ADMIN,
    VALID_CODEWORD_TYPES,
    VALID_CODEWORD_DISCLOSURE_TYPES,
    VALID_PART_CATEGORIES,
    _emit_profile_mutation_audit,
    _hash_codeword,
    _normalize_codeword,
    _raise_if_pii,
)

logger = logging.getLogger(__name__)

CLIENT_INITIATED_ACTOR = "client_self_registration"

EVT_CODEWORD_CLIENT_INITIATED = "codeword_client_initiated"
EVT_PART_CLIENT_INITIATED = "part_client_initiated"


async def _username_enrolled_in_sensitive_bridge(db_pool, username: str) -> bool:
    if not db_pool or not username:
        return False
    try:
        async with db_pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT 1 FROM sensitive_bridge_enrollment
                 WHERE user_id = $1
                   AND cohort_label IS DISTINCT FROM 'unenrolled'
                """,
                username,
            )
        return row is not None
    except Exception as e:
        logger.warning(
            "client_initiated_sensitive_registration: enrollment check failed: %s", e
        )
        return False


async def persist_client_initiated_codeword(
    db_pool,
    *,
    canonical_username: str,
    plaintext_codeword: str,
    suggested_disclosure_type: Optional[str] = None,
    codeword_type: str = "innocuous_phrase",
    part_name: Optional[str] = None,
    part_number: Optional[int] = None,
    part_category: Optional[str] = None,
    addiction_link: Optional[str] = None,
) -> Tuple[bool, Dict[str, Any]]:
    """Insert hashed codeword for client-initiated registration. Returns (ok, body)."""
    if not db_pool:
        return False, {"ok": False, "reason": "database_unavailable"}

    if codeword_type not in VALID_CODEWORD_TYPES:
        return False, {"ok": False, "reason": "invalid_codeword_type"}

    disclosure_type = suggested_disclosure_type or "grounding_request"
    if disclosure_type not in VALID_CODEWORD_DISCLOSURE_TYPES:
        return False, {"ok": False, "reason": "invalid_disclosure_type"}

    for fld, val in (
        ("plaintext_codeword", plaintext_codeword),
        ("part_name", part_name),
    ):
        try:
            _raise_if_pii(fld, val)
        except HTTPException as he:
            return False, {"ok": False, "reason": "pii_rejected", "detail": he.detail}

    if part_category is not None and part_category not in VALID_PART_CATEGORIES:
        return False, {"ok": False, "reason": "invalid_part_category"}

    normalized = _normalize_codeword(plaintext_codeword)
    if not normalized:
        return False, {"ok": False, "reason": "codeword_normalizes_to_empty"}
    if len(normalized) > 200:
        return False, {"ok": False, "reason": "codeword_too_long"}

    if not await _username_enrolled_in_sensitive_bridge(db_pool, canonical_username):
        return False, {"ok": False, "reason": "not_enrolled_sensitive_bridge"}

    salt = secrets.token_hex(16)
    cw_hash = _hash_codeword(plaintext_codeword, salt)

    try:
        async with db_pool.acquire() as conn:
            existing = await conn.fetchrow(
                """
                SELECT codeword_hash FROM user_safety_codewords
                 WHERE user_id = $1 AND codeword_hash = $2
                """,
                canonical_username,
                cw_hash,
            )
            if existing is not None:
                return False, {"ok": False, "reason": "duplicate_codeword_hash"}

            await conn.execute(
                """
                INSERT INTO user_safety_codewords (
                    user_id, codeword_hash, codeword_salt, codeword_type,
                    codeword_label, triggers_mandatory_reporting,
                    set_by_clinician_id, active, disclosure_type, part_name,
                    part_number, part_category, addiction_link, client_initiated
                ) VALUES ($1, $2, $3, $4, $5, FALSE, $6, TRUE, $7, $8, $9, $10, $11, TRUE)
                """,
                canonical_username,
                cw_hash,
                salt,
                codeword_type,
                None,
                CLIENT_INITIATED_ACTOR,
                disclosure_type,
                part_name,
                part_number,
                part_category,
                addiction_link,
            )
    except Exception as e:
        logger.warning(
            "client_initiated_sensitive_registration: codeword insert failed: %s", e
        )
        return False, {"ok": False, "reason": "insert_failed"}

    await _emit_profile_mutation_audit(
        db_pool,
        target_user_id=canonical_username,
        actor_id=canonical_username,
        actor_role="CLIENT",
        mutation_kind="codeword_client_initiated",
        additional_fields_redacted={
            "hash_prefix": cw_hash[:12],
            "codeword_type": codeword_type,
            "disclosure_type": disclosure_type,
            "client_initiated": True,
        },
        severity="moderate",
        event_type=EVT_CODEWORD_CLIENT_INITIATED,
        access_classification=ACCESS_CLINICIAN_AND_ADMIN,
    )

    return True, {
        "ok": True,
        "hash_prefix": cw_hash[:12],
        "disclosure_type": disclosure_type,
        "message": "Codeword saved to your Sensitive Profile for clinician review.",
    }


async def persist_client_initiated_part(
    db_pool,
    *,
    canonical_username: str,
    part_name: str,
    part_number: Optional[int] = None,
    part_category: Optional[str] = None,
    addiction_link: Optional[str] = None,
    description: Optional[str] = None,
) -> Tuple[bool, Dict[str, Any]]:
    """Insert or upsert active part row for client-initiated registration."""
    if not db_pool:
        return False, {"ok": False, "reason": "database_unavailable"}

    cat = part_category or "other"
    if cat not in VALID_PART_CATEGORIES:
        return False, {"ok": False, "reason": "invalid_part_category"}

    pn = (part_name or "").strip()
    if not pn or len(pn) > 64:
        return False, {"ok": False, "reason": "invalid_part_name"}

    try:
        _raise_if_pii("part_name", pn)
        _raise_if_pii("description", description)
    except HTTPException as he:
        return False, {"ok": False, "reason": "pii_rejected", "detail": he.detail}

    if not await _username_enrolled_in_sensitive_bridge(db_pool, canonical_username):
        return False, {"ok": False, "reason": "not_enrolled_sensitive_bridge"}

    try:
        async with db_pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                INSERT INTO user_parts_registry (
                    user_id, part_name, part_number, part_category,
                    addiction_link, description, protected_exile_part_id,
                    is_active, created_by, client_initiated
                ) VALUES ($1, $2, $3, $4, $5, $6, NULL, TRUE, $7, TRUE)
                ON CONFLICT (user_id, part_name) DO NOTHING
                RETURNING id
                """,
                canonical_username,
                pn,
                part_number,
                cat,
                addiction_link,
                description,
                CLIENT_INITIATED_ACTOR,
            )
        if row is None:
            return False, {
                "ok": False,
                "reason": "part_name_already_registered",
                "detail": (
                    "That part name already exists on your profile; "
                    "ask your clinician to update it."
                ),
            }
        new_id = int(row["id"])
    except Exception as e:
        logger.warning(
            "client_initiated_sensitive_registration: part insert failed: %s", e
        )
        return False, {"ok": False, "reason": "insert_failed"}

    await _emit_profile_mutation_audit(
        db_pool,
        target_user_id=canonical_username,
        actor_id=canonical_username,
        actor_role="CLIENT",
        mutation_kind="part_client_initiated",
        additional_fields_redacted={
            "id": new_id,
            "part_name": pn,
            "part_category": cat,
            "client_initiated": True,
        },
        severity="moderate",
        event_type=EVT_PART_CLIENT_INITIATED,
        access_classification=ACCESS_CLINICIAN_AND_ADMIN,
    )

    return True, {
        "ok": True,
        "id": new_id,
        "part_name": pn,
        "message": "Part name saved to your Sensitive Profile for clinician review.",
    }
