"""Program (cohort) isolation for crystals.

Slice 4 of the Bee HIV+ privacy plan. Prevents a program's disclosures
from bleeding into users outside that program, and prevents other programs'
crystals from influencing a program's members.

Feature-flagged via ENABLE_PROGRAM_ISOLATION. Off by default — zero
behavior change until an operator flips the flag.

Legal grounding:
  • BAA §8.7A — program isolation.

Write-side stamping is handled by a Postgres trigger (see migration 414).
This module provides the read-side filter used by crystal_recall_bridge.
"""

from __future__ import annotations

import logging
import os
import time as _time
from typing import Any, Iterable, List, Optional

logger = logging.getLogger(__name__)

_CACHE_TTL_SEC = 300.0

# In-process caches. Non-persistent so a program change is picked up within
# _CACHE_TTL_SEC. Small enough to be safe unbounded in the sizes we expect
# (thousands of users at most per process).
_user_program_cache: dict[str, tuple[float, Optional[str]]] = {}
_crystal_program_cache: dict[int, tuple[float, Optional[str]]] = {}
_CRYSTAL_CACHE_TTL_SEC = 600.0


def is_enabled() -> bool:
    """Return True when ENABLE_PROGRAM_ISOLATION is truthy."""
    raw = (os.environ.get("ENABLE_PROGRAM_ISOLATION") or "").strip().lower()
    return raw in ("1", "true", "yes", "on")


async def get_user_program_id(db_pool, user_ref: str) -> Optional[str]:
    """Return users.program_id for the given ref, or None.

    ``user_ref`` may be a hardware_id, username, or UUID string. Uses a
    small in-process cache to avoid an extra query on every recall.
    """
    if not db_pool or not user_ref:
        return None
    key = str(user_ref)
    now = _time.monotonic()
    hit = _user_program_cache.get(key)
    if hit and hit[0] > now:
        return hit[1]
    program_id: Optional[str] = None
    try:
        async with db_pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT program_id FROM users "
                "WHERE hardware_id = $1 OR username = $1 OR id::text = $1 "
                "LIMIT 1",
                key,
            )
            if row is not None:
                program_id = row["program_id"]
    except Exception as exc:
        # Column may not exist yet on databases that haven't run 414. Cache the
        # None result so we don't hammer the DB on every recall.
        logger.debug("program_isolation: user lookup failed for %s: %s", key[:32], exc)
        program_id = None
    _user_program_cache[key] = (now + _CACHE_TTL_SEC, program_id)
    return program_id


def invalidate_user_cache(user_ref: str) -> None:
    """Drop a single user_ref from the cache (call after program_id writes)."""
    _user_program_cache.pop(str(user_ref), None)


def _crystal_id(row: Any) -> Optional[int]:
    """Extract the id field from a crystal row (asyncpg Record or dict)."""
    try:
        return int(row["id"])
    except Exception:
        try:
            return int(row.get("id"))  # type: ignore[union-attr]
        except Exception:
            return None


def _row_program_id(row: Any) -> Optional[str]:
    """Return program_id from a crystal row if the column is present."""
    try:
        if "program_id" in row.keys():
            return row["program_id"]
    except Exception:
        pass
    try:
        return row.get("program_id")  # type: ignore[union-attr]
    except Exception:
        return None


async def _fetch_program_ids_bulk(db_pool, crystal_ids: List[int]) -> dict[int, Optional[str]]:
    """Return {id: program_id} for the given crystal ids.

    Reads the ``program_id`` column on ``nate_intelligence_crystals``. If the
    column doesn't exist yet (migration 414 not applied), returns an empty
    mapping — the caller treats "no data" as "no filter needed" so recall
    still works on lagged environments.
    """
    if not db_pool or not crystal_ids:
        return {}
    out: dict[int, Optional[str]] = {}
    # Serve from cache first.
    now = _time.monotonic()
    to_fetch: List[int] = []
    for cid in crystal_ids:
        hit = _crystal_program_cache.get(cid)
        if hit and hit[0] > now:
            out[cid] = hit[1]
        else:
            to_fetch.append(cid)
    if not to_fetch:
        return out
    try:
        async with db_pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT id, program_id FROM nate_intelligence_crystals "
                "WHERE id = ANY($1::int[])",
                to_fetch,
            )
        exp = now + _CRYSTAL_CACHE_TTL_SEC
        for r in rows:
            cid = int(r["id"])
            pid = r["program_id"]
            out[cid] = pid
            _crystal_program_cache[cid] = (exp, pid)
        for cid in to_fetch:
            if cid not in out:
                # Row not found — treat as no program.
                out[cid] = None
                _crystal_program_cache[cid] = (exp, None)
    except Exception as exc:
        logger.debug("program_isolation: bulk program_id fetch failed: %s", exc)
        # Fall back to "no program info" for the missing ids.
        for cid in to_fetch:
            out.setdefault(cid, None)
    return out


def filter_crystals_by_program(
    crystals: Iterable[Any],
    user_program_id: Optional[str],
    id_to_program: Optional[dict[int, Optional[str]]] = None,
) -> List[Any]:
    """Filter ``crystals`` per program isolation rules.

    Rules:
      • If isolation is disabled globally (env flag off) return the input as
        a list unchanged.
      • If the caller has a program_id, keep only crystals whose program_id
        is NULL or equals the caller's program_id.
      • If the caller has no program_id (general population), drop crystals
        with any program_id set — program-specific disclosures must not
        influence general-pool recall.

    ``id_to_program`` may be provided to avoid a DB fetch when the caller
    already knows each crystal's program_id (either from the row itself or
    from a prior bulk fetch). When a crystal has no ``program_id`` column and
    no entry in the map, it is treated as ``None`` (general pool).
    """
    crystals_list = list(crystals)
    if not is_enabled() or not crystals_list:
        return crystals_list
    kept: List[Any] = []
    for row in crystals_list:
        pid = _row_program_id(row)
        if pid is None and id_to_program is not None:
            cid = _crystal_id(row)
            if cid is not None:
                pid = id_to_program.get(cid)
        if user_program_id:
            if pid is None or pid == user_program_id:
                kept.append(row)
        else:
            if pid is None:
                kept.append(row)
    return kept


async def filter_crystals_by_program_async(
    db_pool,
    crystals: Iterable[Any],
    user_program_id: Optional[str],
) -> List[Any]:
    """DB-aware wrapper around ``filter_crystals_by_program``.

    Batches a single ``SELECT id, program_id`` query for any crystal rows
    that don't already carry ``program_id``, then applies the same filter
    rules. When the flag is off or the input is empty, no DB call is made.
    """
    crystals_list = list(crystals)
    if not is_enabled() or not crystals_list:
        return crystals_list
    # Only fetch for rows that don't already expose program_id (e.g. legacy
    # SELECTs that predate migration 414 additions to the SELECT list).
    missing: List[int] = []
    for row in crystals_list:
        try:
            if "program_id" in row.keys():
                continue
        except Exception:
            if isinstance(row, dict) and "program_id" in row:
                continue
        cid = _crystal_id(row)
        if cid is not None:
            missing.append(cid)
    id_to_program: dict[int, Optional[str]] = {}
    if missing:
        id_to_program = await _fetch_program_ids_bulk(db_pool, missing)
    return filter_crystals_by_program(crystals_list, user_program_id, id_to_program)
