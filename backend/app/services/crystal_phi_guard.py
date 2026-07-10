"""
Write-time PHI/name guard for global-pool-eligible crystals.

QUANTUM-CRYSTAL-ARCH: 2026-07-09 incident (see
docs/INCIDENT_MEMO_CRYSTAL_SCOPE_PHI_EXPOSURE_2026-07-09.md) — a client's
personalized "Session Insight" text was concatenated into a scope='global'
crystal during cluster synthesis and later recalled by two other clients.
The recall-side fix (allowlist scope='global' only) closes the read path.
This module closes the write path: before any crystal is written with a
scope that is retrievable from the global pool (i.e., no specific
user_id — see crystal_recall_bridge.py's allowlist), the candidate text is
checked against the live client-name roster. If a resolvable client name
appears in text that would otherwise become global-pool-eligible, the
write is refused (fail closed) rather than silently admitted.

This is deliberately conservative: false positives (a global crystal
that happens to contain a common word matching a client's name) are an
acceptable cost against the alternative of a second cross-client PHI
exposure incident.
"""
import logging
import re
import time
from typing import Optional

logger = logging.getLogger(__name__)

# In-memory roster cache — refreshed on a TTL so this guard adds no
# per-write DB round trip on the hot path (crystal writes happen on
# every qualifying conversation turn).
_ROSTER_CACHE: set[str] = set()
_ROSTER_LAST_REFRESH: float = 0.0
_ROSTER_TTL_SECONDS = 900  # 15 minutes


def _name_to_pattern(name: str) -> Optional[re.Pattern]:
    """
    Build a conservative, case-sensitive, word-boundary regex for a
    full name (e.g. "John D." or "Lisa West"). Single-word names and
    names shorter than 4 characters are skipped — they produce too
    many false positives (e.g. "Bill" as a noun) to be useful signal.
    """
    cleaned = re.sub(r"\s+", " ", (name or "").strip())
    if len(cleaned) < 4:
        return None
    parts = [p for p in cleaned.split(" ") if p]
    if len(parts) < 2:
        # Single-token names (e.g. usernames like "longra") are not
        # reliable enough to regex-match against free text; skip.
        return None
    escaped = re.escape(cleaned)
    try:
        # Use lookaround, not \b, on both ends: \b requires a transition
        # between a word char and a non-word char, which FAILS to match
        # when a name ends in punctuation (e.g. "John D." -- the period is
        # already non-word, so \b never fires between "." and a following
        # space). (?<!\w) / (?!\w) assert "not preceded/followed by a word
        # char" regardless of what character (if any) is actually there.
        return re.compile(r"(?<!\w)" + escaped + r"(?!\w)")
    except re.error:
        return None


async def refresh_client_name_roster(db_pool, force: bool = False) -> int:
    """
    Refresh the in-memory cache of live client/coach full names from
    profile_data->>'name'. Returns the number of names cached.

    Safe to call frequently — it no-ops unless the TTL has expired or
    force=True. Never raises; failures leave the previous cache intact
    (fail safe toward "keep guarding with stale data" rather than
    "guard with nothing").
    """
    global _ROSTER_CACHE, _ROSTER_LAST_REFRESH
    now = time.monotonic()
    if not force and _ROSTER_CACHE and (now - _ROSTER_LAST_REFRESH) < _ROSTER_TTL_SECONDS:
        return len(_ROSTER_CACHE)
    if not db_pool:
        return len(_ROSTER_CACHE)
    try:
        async with db_pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT DISTINCT profile_data->>'name' AS name
                FROM users
                WHERE role IN ('CLIENT', 'COACH')
                  AND profile_data->>'name' IS NOT NULL
                  AND profile_data->>'name' != ''
                """
            )
        names = {r["name"].strip() for r in rows if r["name"] and r["name"].strip()}
        if names:
            _ROSTER_CACHE = names
            _ROSTER_LAST_REFRESH = now
            logger.info("crystal_phi_guard: roster refreshed (%d names)", len(names))
        return len(_ROSTER_CACHE)
    except Exception as e:
        logger.warning("crystal_phi_guard: roster refresh failed (keeping stale cache): %s", e)
        return len(_ROSTER_CACHE)


def text_contains_client_name(text: str) -> Optional[str]:
    """
    Return the matched client name if `text` contains a live client/coach
    full name, else None. Pure/sync — operates on the cached roster only.
    """
    if not text or not _ROSTER_CACHE:
        return None
    for name in _ROSTER_CACHE:
        pattern = _name_to_pattern(name)
        if pattern and pattern.search(text):
            return name
    return None


async def guard_global_crystal_write(
    db_pool,
    crystal_text: str,
    scope: str,
    context: str = "",
) -> bool:
    """
    Returns True if the write should proceed, False if it must be
    blocked. Only applies the name check when `scope` would land the
    crystal in the global-pool-eligible set (scope == 'global'); any
    other scope (user-owned, admin_only, archived) is not gated here —
    those are gated by the recall-side allowlist instead.

    `context` is a short caller-identifying string included in the
    warning log (e.g. "cluster_synthesis", "solo_forge",
    "wisdom_absorption") to make audit trail attribution easy.
    """
    if scope != "global":
        return True
    await refresh_client_name_roster(db_pool)
    matched = text_contains_client_name(crystal_text)
    if matched:
        logger.warning(
            "crystal_phi_guard: BLOCKED global-scope crystal write — text contains "
            "live client name %r (context=%s, text_prefix=%r)",
            matched, context or "unknown", (crystal_text or "")[:120],
        )
        return False
    return True
