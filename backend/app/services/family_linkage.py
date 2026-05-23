"""
Family linkage Phase 1 — canonical parent/HoH stamps on profile_data + users columns.

Shared by WebSocket register_new_user, UserStore upsert, and backfill scripts.
Does not touch family_members junction (Phase 2 / migration 196).
"""

from __future__ import annotations

import logging
import re
from typing import Any, Dict, Optional

logger = logging.getLogger("family_linkage")

_UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    re.I,
)

_HEAD_ROLES = frozenset({"HEAD", "HEAD_OF_HOUSEHOLD"})


def is_uuid(value: Any) -> bool:
    return bool(_UUID_RE.match(str(value or "").strip()))


def guardian_ref_matches(
    guardian_ref: Any,
    member_hardware_id: str,
    member_user_id: Any = None,
) -> bool:
    """Dual-read: guardian_ref may be HoH hardware_id or users.id UUID."""
    if not guardian_ref or not member_hardware_id:
        return False
    g = str(guardian_ref).strip()
    if g == str(member_hardware_id).strip():
        return True
    if member_user_id and g == str(member_user_id).strip():
        return True
    return False


def extract_family_columns(profile: Dict[str, Any]) -> Dict[str, Any]:
    """Map enriched profile fields to dedicated users-table columns."""
    guardian_uuid = None
    linked_uuid = None
    for key in ("guardian_id", "linked_by", "parent_id", "head_of_household_id"):
        val = profile.get(key)
        if is_uuid(val):
            if guardian_uuid is None:
                guardian_uuid = str(val)
            if linked_uuid is None:
                linked_uuid = str(val)
    family_role = (profile.get("family_role") or "").strip().lower() or None
    is_minor = bool(profile.get("is_minor"))
    return {
        "guardian_id": guardian_uuid,
        "linked_by": linked_uuid,
        "family_role": family_role,
        "is_minor": is_minor,
    }


async def _fetch_user_by_identifier(conn, identifier: str):
    ident = str(identifier or "").strip()
    if not ident:
        return None
    if is_uuid(ident):
        return await conn.fetchrow(
            """
            SELECT id, username, hardware_id, family_id
            FROM users
            WHERE id = $1::uuid AND deleted_at IS NULL
            LIMIT 1
            """,
            ident,
        )
    return await conn.fetchrow(
        """
        SELECT id, username, hardware_id, family_id
        FROM users
        WHERE deleted_at IS NULL
          AND (
            LOWER(username) = LOWER($1)
            OR hardware_id = $1
            OR profile_data->>'hardware_id' = $1
          )
        LIMIT 1
        """,
        ident,
    )


async def _fetch_hoh_for_family(conn, family_uuid) -> Optional[dict]:
    return await conn.fetchrow(
        """
        SELECT u.id, u.username, u.hardware_id, u.family_id
        FROM families f
        JOIN users u ON u.id = f.head_of_household_id
        WHERE f.id = $1
        LIMIT 1
        """,
        family_uuid,
    )


async def enrich_family_profile(
    conn,
    *,
    profile: Dict[str, Any],
    parent_username: Optional[str] = None,
    family_role: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Stamp parent_username, parent_id, head_of_household_id, UUID guardian_id/linked_by.
    Additive: does not clear existing UUID guardian fields or parent_username.
    """
    out = dict(profile or {})
    role = (family_role or out.get("family_role") or "").upper()
    if role:
        out["family_role"] = role
    if role in _HEAD_ROLES:
        return out

    parent_row = None
    pu = (parent_username or out.get("parent_username") or "").strip()
    if pu:
        parent_row = await _fetch_user_by_identifier(conn, pu)

    if not parent_row:
        for key in ("linked_by", "guardian_id", "parent_id", "head_of_household_id"):
            ref = out.get(key)
            if ref and not is_uuid(ref):
                parent_row = await _fetch_user_by_identifier(conn, str(ref))
                if parent_row:
                    break

    if not parent_row:
        fam_str = str(out.get("family_id") or "").strip()
        family_uuid = None
        if is_uuid(fam_str):
            family_uuid = fam_str
        elif fam_str:
            row = await conn.fetchrow(
                "SELECT id FROM families WHERE family_code = $1 LIMIT 1",
                fam_str,
            )
            if row:
                family_uuid = row["id"]
        if family_uuid:
            parent_row = await _fetch_hoh_for_family(conn, family_uuid)

    if not parent_row:
        return out

    if not (out.get("parent_username") or "").strip():
        out["parent_username"] = parent_row["username"]
    if not (out.get("parent_id") or "").strip() or not is_uuid(out.get("parent_id")):
        out["parent_id"] = str(parent_row["id"])
    if not (out.get("head_of_household_id") or "").strip() or not is_uuid(
        out.get("head_of_household_id")
    ):
        out["head_of_household_id"] = str(parent_row["id"])
    if not is_uuid(out.get("guardian_id")):
        out["guardian_id"] = str(parent_row["id"])
    if not is_uuid(out.get("linked_by")):
        out["linked_by"] = str(parent_row["id"])
    return out


async def enrich_family_profile_if_needed(
    conn,
    profile: Dict[str, Any],
    family_uuid,
) -> Dict[str, Any]:
    """Repair-on-write for bridge/registry saves — fill only when linkage is incomplete."""
    out = dict(profile or {})
    role = (out.get("family_role") or "").upper()
    if role in _HEAD_ROLES:
        return out

    has_parent = bool((out.get("parent_username") or "").strip())
    has_uuid_guardian = is_uuid(out.get("guardian_id")) or is_uuid(out.get("linked_by"))
    if has_parent and has_uuid_guardian:
        return out

    hoh = await _fetch_hoh_for_family(conn, family_uuid)
    pu = (out.get("parent_username") or "").strip() or (
        hoh["username"] if hoh else ""
    )
    return await enrich_family_profile(
        conn,
        profile=out,
        parent_username=pu or None,
        family_role=role or None,
    )
