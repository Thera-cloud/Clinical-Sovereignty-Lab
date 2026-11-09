"""Durable "already ran this audit window" guard shared by every scheduled auditor.

Each auditor dedups its 05/17/23 UTC run with an in-memory ``_sent_windows`` set
(or by sleeping 3600s after a run). Both are lost on process restart, so a
backend deploy inside an audit hour re-ran all 50+ scorecards (hundreds of HTTP
probes + DB checks) and re-fed the Trust Enforcer. The ``skyeye_activity``
``<name>_audit_sent`` row every auditor already writes is the durable record —
this helper consults it.

Semantics
---------
* Returns ``True`` only when a row of ``activity_type`` exists with
  ``created_at >= date_trunc('hour', NOW())`` (same whole-hour window the Trust
  Enforcer reads).
* Fail-open: no pool / DB error → ``False`` so an auditor never silently stops.
* Per-process memo: once the DB confirms a window, later ticks in that hour skip
  the query (castle-style loops poll every 60s while waiting).
* Manual triggers (``/api/admin/skyeye-audit/send`` → ``_build_and_send``) bypass
  the run loop and are unaffected.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional, Set, Tuple

logger = logging.getLogger("nate.audit_window_guard")

_SQL = (
    "SELECT 1 FROM skyeye_activity WHERE type = $1 "
    "AND created_at >= date_trunc('hour', NOW()) LIMIT 1"
)

_confirmed: Set[Tuple[str, str]] = set()


def window_key(now: Optional[datetime] = None) -> str:
    now = now or datetime.now(timezone.utc)
    return f"{now.date().isoformat()}_{now.hour}"


def _prune(current_key: str) -> None:
    global _confirmed
    if len(_confirmed) > 256:
        _confirmed = {k for k in _confirmed if k[1] == current_key}


def reset_memo() -> None:
    """Test hook."""
    _confirmed.clear()


async def already_ran_this_window(
    db_pool, activity_type: str, *, now: Optional[datetime] = None
) -> bool:
    key = (activity_type, window_key(now))
    if key in _confirmed:
        return True
    if not db_pool or not hasattr(db_pool, "acquire"):
        return False
    try:
        async with db_pool.acquire() as conn:
            hit = await conn.fetchval(_SQL, activity_type)
    except Exception as e:  # fail-open
        logger.warning("audit_window_guard: %s lookup failed: %s", activity_type, e)
        return False
    if hit:
        _confirmed.add(key)
        _prune(key[1])
        logger.info(
            "audit_window_guard: %s already logged this hour — skipping re-run",
            activity_type,
        )
        return True
    return False
