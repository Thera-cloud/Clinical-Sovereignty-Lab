"""
account_creation_hook — shared helper called from every signup path.

Purpose
-------
After a user row is inserted, each signup path (WS register_request, Stripe
webhook, registration_finalize, dependent creation) calls
``mark_account_created()`` to:

  1. Stamp the corresponding ``user_creation_events`` row (written by the
     migration 221 trigger) with ``processed_at`` + ``created_via`` so the
     reconciler does not flag it as orphaned.
  2. Optionally enqueue side effects (the support@ notification stays in
     existing code paths for now — this hook is purely a marker, not a
     replacement, so we cannot duplicate emails).

Design constraints (WJR safety)
-------------------------------
* Fire-and-forget. Never await side effects on the signup hot path.
* Never raise. Every code path that calls this is critical (signup).
* Feature-flagged via ``ENABLE_USER_CREATION_HOOK``. Default OFF.
  If the flag is unset, this function is a complete no-op.
* Partial-data tolerant. Reads with ``.get()`` defaults — manual-SQL accounts
  with incomplete profile_data must not crash the hook.
"""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Any, Optional

logger = logging.getLogger("account_creation_hook")

_FLAG_ENV = "ENABLE_USER_CREATION_HOOK"


def _flag_enabled() -> bool:
    return os.getenv(_FLAG_ENV, "false").strip().lower() in ("1", "true", "yes", "on")


def mark_account_created(
    db_pool: Any,
    username: str,
    *,
    created_via: str,
    role: Optional[str] = None,
    tier: Optional[str] = None,
    hardware_id: Optional[str] = None,
    metadata: Optional[dict] = None,
) -> None:
    """Fire-and-forget marker. Safe to call from any signup path.

    Parameters
    ----------
    db_pool : asyncpg pool or None
        If None or the flag is off, this is a no-op.
    username : str
        The newly-created user's username (case-insensitive match).
    created_via : str
        Provenance label. Must be one of:
        ``ws_register``, ``ws_dependent``, ``stripe_finalize``,
        ``stripe_finalize_dependent``, ``stripe_finalize_paid_dependent``,
        ``admin_manual``, ``test_harness``.
    role, tier, hardware_id : optional
        Used only if the trigger row was missing them (defensive — the trigger
        writes them from NEW.*, so they should always be present).
    metadata : dict, optional
        Merged into ``source_metadata`` for forensic context.
    """
    if not _flag_enabled():
        return
    if not db_pool or not username:
        return

    try:
        loop = asyncio.get_event_loop()
        if not loop.is_running():
            return
        loop.create_task(
            _mark_async(
                db_pool, username, created_via, role, tier, hardware_id, metadata or {}
            )
        )
    except Exception as exc:
        # Never raise on the signup hot path.
        logger.warning(
            "account_creation_hook: scheduling failed for %s via %s: %s",
            username, created_via, exc,
        )


async def _mark_async(
    db_pool: Any,
    username: str,
    created_via: str,
    role: Optional[str],
    tier: Optional[str],
    hardware_id: Optional[str],
    metadata: dict,
) -> None:
    """Background marker. Best-effort. Never raises."""
    try:
        async with db_pool.acquire() as conn:
            # Mark the most-recent unprocessed event for this username.
            # The trigger fired on INSERT; this UPDATE annotates it.
            await conn.execute(
                """
                UPDATE user_creation_events
                   SET processed_at    = NOW(),
                       processed_by    = $2,
                       created_via     = $2,
                       source_metadata = COALESCE(source_metadata, '{}'::jsonb)
                                         || $3::jsonb
                 WHERE id = (
                     SELECT id FROM user_creation_events
                      WHERE LOWER(username) = LOWER($1)
                        AND processed_at IS NULL
                      ORDER BY created_at DESC
                      LIMIT 1
                 )
                """,
                username,
                created_via,
                _serialize_metadata(role, tier, hardware_id, metadata),
            )
    except Exception as exc:
        logger.warning(
            "account_creation_hook: marker UPDATE failed for %s via %s: %s",
            username, created_via, exc,
        )


def _serialize_metadata(
    role: Optional[str],
    tier: Optional[str],
    hardware_id: Optional[str],
    extra: dict,
) -> str:
    import json
    payload = {
        "hook_role": role,
        "hook_tier": tier,
        "hook_hardware_id": hardware_id,
        "hook_extra": extra,
    }
    try:
        return json.dumps(payload, default=str)
    except Exception:
        return "{}"
