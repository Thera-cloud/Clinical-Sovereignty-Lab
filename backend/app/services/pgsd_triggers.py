"""
PGSD safe trigger facade.  # QUANTUM-CRYSTAL-ARCH

All producers call notify_user() — never schedule_for_user directly.
Never raises into the producer path.
"""

from __future__ import annotations

import logging
import os
from typing import Any, Optional

logger = logging.getLogger(__name__)

# Surfaces that bypass the 1h debounce (10-minute floor instead).
_FAST_SOURCES = frozenset({
    "live_activation",
    "sensitive_bridge_enroll",
})

_FAST_DEBOUNCE_SECONDS = 600


def _pgsd_master_enabled() -> bool:
    return os.environ.get("PGSD_ENABLED", "").strip().lower() in ("1", "true", "yes", "on")


def _is_quarantined(raw_id: str, source: str) -> bool:
    """Skip audit_* accounts, SIX_QUOTIENT battery, and battery-flagged surfaces."""
    rid = (raw_id or "").strip().lower()
    if not rid:
        return True
    if rid.startswith("audit_"):
        return True
    src = (source or "").lower()
    if "six_quotient" in src or "battery" in src:
        return True
    try:
        from app.services.six_quotient_battery_quarantine import should_block_crystallize

        if should_block_crystallize(
            origin_surface=source or "",
            user_text="",
            nate_response="",
        ):
            return True
    except Exception:
        pass
    return False


def _resolve_router() -> Any:
    try:
        from app.websocket import bridge_server as _bs

        return getattr(_bs, "_pgsd_router", None)
    except Exception:
        return None


def notify_user(raw_id: str, source: str = "auto") -> bool:
    """
    Resolve subject → hardware_id, skip quarantine, schedule debounced snapshot.
    Returns True if a task was scheduled. Never raises.
    """
    try:
        if not _pgsd_master_enabled():
            return False
        if _is_quarantined(raw_id, source):
            return False
        router = _resolve_router()
        if router is None or not getattr(router, "enabled", False):
            return False

        subject = (raw_id or "").strip()
        if not subject:
            return False

        # Prefer sync schedule with optional fast path for live activation.
        if source in _FAST_SOURCES and hasattr(router, "schedule_for_user_fast"):
            return bool(router.schedule_for_user_fast(subject, source=source))
        return bool(router.schedule_for_user(subject, source=source))
    except Exception as e:
        logger.debug("pgsd_triggers.notify_user failed (non-fatal): %s", e)
        return False


async def notify_user_async(
    db_pool: Any,
    raw_id: str,
    source: str = "auto",
) -> bool:
    """
    Async variant that resolves via PGSDEngine when available so callers
    with only a username still land on hardware_id debounce keys.
    """
    try:
        if not _pgsd_master_enabled():
            return False
        if _is_quarantined(raw_id, source):
            return False
        resolved_id = raw_id
        if db_pool is not None:
            try:
                from app.services.pgsd_engine import PGSDEngine

                eng = PGSDEngine(db_pool=db_pool)
                keys = await eng.resolve_pgsd_subject(raw_id)
                if keys and keys.get("hardware_id"):
                    resolved_id = keys["hardware_id"]
            except Exception:
                pass
        return notify_user(resolved_id, source=source)
    except Exception as e:
        logger.debug("pgsd_triggers.notify_user_async failed (non-fatal): %s", e)
        return False
