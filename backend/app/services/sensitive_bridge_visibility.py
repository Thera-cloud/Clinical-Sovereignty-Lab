"""Sensitive Clinical Bridge — visibility & authorization helpers.

Centralizes the two gate lookups consumed by the View Brief modal and the
Path-C coach-initiated enrollment endpoint:

  1. ``is_coach_authorized`` — reads ``coach_profiles.coach_sensitive_bridge_authorized``.
  2. ``is_client_enrolled``  — reads ``sensitive_bridge_enrollment``.

Both lookups are intentionally tiny and side-effect-free so they can be called
from multiple call sites (the WS bridge, the REST router, the auditor) without
duplicating SQL or risking drift.

The combined ``compute_visibility`` returns the dict the bridge attaches to
``presession_brief.sensitive_bridge_visibility``; the Flutter View Brief modal
uses it to decide whether to render the "Sensitive Profile" button and which
of the three states (``hidden | enroll_available | active``) to render it in.

Naming contract — ``button_state``:
  • ``"hidden"``           — coach is not authorized; pill must NOT render.
  • ``"enroll_available"`` — coach authorized, client NOT enrolled; pill
                             renders muted and **is tappable** — navigates to
                             ``SensitiveClinicalProfileScreen`` where Path-C
                             enrollment UI lives.
  • ``"active"``           — coach authorized AND client enrolled; pill
                             renders emphasized and opens the profile screen.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


async def is_coach_authorized(db_pool, coach_username: Optional[str]) -> bool:
    """Return True iff coach_profiles.coach_sensitive_bridge_authorized=TRUE.

    Looks up by ``username`` (the bridge's principal identifier). Returns
    False on missing pool, missing username, missing row, or on any DB
    error — closed-by-default is the safe answer for a 7-year-retention
    clinical surface.
    """
    if db_pool is None or not coach_username:
        return False
    try:
        async with db_pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT coach_sensitive_bridge_authorized
                  FROM coach_profiles
                 WHERE username = $1
                """,
                coach_username,
            )
    except Exception as e:
        logger.warning(
            "sensitive_bridge_visibility: coach auth lookup failed for %s: %s",
            coach_username, e,
        )
        return False
    if row is None:
        return False
    return bool(row["coach_sensitive_bridge_authorized"])


async def is_client_enrolled(db_pool, client_username: Optional[str]) -> bool:
    """Return True iff a row exists in sensitive_bridge_enrollment for the
    client. Returns False on missing pool / username / row.
    """
    if db_pool is None or not client_username:
        return False
    try:
        async with db_pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT 1
                  FROM sensitive_bridge_enrollment
                 WHERE user_id = $1
                """,
                client_username,
            )
    except Exception as e:
        logger.warning(
            "sensitive_bridge_visibility: enrollment lookup failed for %s: %s",
            client_username, e,
        )
        return False
    return row is not None


def derive_button_state(coach_authorized: bool, client_enrolled: bool) -> str:
    """Map the two booleans to one of the three documented button states."""
    if not coach_authorized:
        return "hidden"
    if not client_enrolled:
        return "enroll_available"
    return "active"


_ADDICTION_BRANCH_KEYS = (
    "substance_status",
    "sex_addiction_status",
    "gambling_status",
    "gaming_status",
    "spending_compulsion_status",
    "food_compulsion_status",
    "work_compulsion_status",
    "codependency_status",
)


async def _addiction_summary(
    db_pool, client_username: Optional[str],
) -> Dict[str, Any]:
    """Return lightweight addiction overlay for the View Brief pill.

    {
      "active_count":  int,   — branches at 'active' or 'crisis'
      "crisis_count":  int,   — branches at 'crisis' only
      "active_branches": ["substance", "gambling", ...],
    }
    """
    empty: Dict[str, Any] = {
        "active_count": 0,
        "crisis_count": 0,
        "active_branches": [],
        "cross_addiction_active": False,
        "cross_addiction_overlay_saved": False,
    }
    if db_pool is None or not client_username:
        return empty
    try:
        async with db_pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT profile_data FROM users WHERE username = $1",
                client_username,
            )
    except Exception as e:
        logger.warning("sensitive_bridge_visibility: addiction summary failed for %s: %s", client_username, e)
        return empty
    if row is None:
        return empty
    pd = row["profile_data"]
    if pd is None:
        return empty
    if isinstance(pd, str):
        import json as _json
        try:
            pd = _json.loads(pd)
        except Exception:
            return empty
    active_branches = []
    crisis_count = 0
    cross_active = False
    cross_overlay_saved = False
    cap = pd.get("cross_addiction_profile")
    if isinstance(cap, dict):
        cross_active = bool(cap.get("cross_addiction_active"))
        cross_overlay_saved = bool(cap.get("overlay_applied"))
    for key in _ADDICTION_BRANCH_KEYS:
        val = (pd.get(key) or "none").lower()
        if val in ("active", "crisis"):
            branch_label = key.replace("_status", "").replace("_", " ")
            active_branches.append(branch_label)
            if val == "crisis":
                crisis_count += 1
    return {
        "active_count": len(active_branches),
        "crisis_count": crisis_count,
        "active_branches": active_branches,
        "cross_addiction_active": cross_active,
        "cross_addiction_overlay_saved": cross_overlay_saved,
    }


async def compute_visibility(
    db_pool,
    *,
    coach_username: Optional[str],
    client_username: Optional[str],
) -> Dict[str, Any]:
    """Single dict consumed by the View Brief modal payload.

    Shape (sealed contract — Flutter side parses these exact keys):
        {
          "coach_authorized": bool,
          "client_enrolled":  bool,
          "button_state":     "hidden" | "enroll_available" | "active",
          "client_username":  str | null,
          "addiction_summary": { active_count, crisis_count, active_branches,
            cross_addiction_active, cross_addiction_overlay_saved },
        }
    """
    coach_ok = await is_coach_authorized(db_pool, coach_username)
    enrolled = await is_client_enrolled(db_pool, client_username)
    addiction = await _addiction_summary(db_pool, client_username)
    return {
        "coach_authorized": coach_ok,
        "client_enrolled": enrolled,
        "button_state": derive_button_state(coach_ok, enrolled),
        "client_username": client_username,
        "addiction_summary": addiction,
    }
