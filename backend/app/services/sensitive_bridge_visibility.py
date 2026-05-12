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
of the three states (``hidden | disabled | active``) to render it in.

Naming contract — ``button_state``:
  • ``"hidden"``   — coach is not authorized; button must NOT render at all.
  • ``"disabled"`` — coach authorized, client NOT enrolled; render disabled
                     pill with the not-enrolled tooltip.
  • ``"active"``   — coach authorized AND client enrolled; render the
                     active cyan pill.
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
        return "disabled"
    return "active"


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
          "button_state":     "hidden" | "disabled" | "active",
          "client_username":  str | null,
        }
    """
    coach_ok = await is_coach_authorized(db_pool, coach_username)
    enrolled = await is_client_enrolled(db_pool, client_username)
    return {
        "coach_authorized": coach_ok,
        "client_enrolled": enrolled,
        "button_state": derive_button_state(coach_ok, enrolled),
        "client_username": client_username,
    }
