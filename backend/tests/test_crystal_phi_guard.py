"""Write-time PHI/name guard for global-pool crystals.

Background (2026-07-09 incident, part 3): the recall-side allowlist fix
(test_admin_only_scope_isolation.py) closes the READ path -- only
scope='global' crystals are ever served from the anonymous/global pool.
This suite covers the WRITE path: a centralized guard
(backend/app/services/crystal_phi_guard.py) that refuses to let a
crystal ever be written with scope='global' if its text contains a
live client/coach name, and a fail-closed check on
crystallize_from_conversation so an unresolved hardware_id can no
longer produce an orphaned (ownerless) user-scoped crystal at all.

Root cause of the original incident: cluster synthesis in
nate_memory_crystallizer.py concatenated fragments from multiple
sources -- including per-client "[Session Insight]" text -- into a
single scope='global' crystal, with no check on the resulting text.
This suite pins the fix so a future engineer cannot silently remove
the guard call from either write site (solo-forge and cluster
synthesis) without a test failing, and gives the detector itself
regression coverage against both false negatives (real PHI must
always block) and false positives (ordinary global content, and
scopes other than 'global', must never block).

See ci-gate-before-push.mdc for the offline-only test contract --
these tests use db_pool=None and a directly-seeded roster cache, no
real Postgres connection.
"""
from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from app.services import crystal_phi_guard as guard_mod
from app.services.crystal_phi_guard import (
    _name_to_pattern,
    guard_global_crystal_write,
    text_contains_client_name,
)

_REPO_ROOT = Path(__file__).resolve().parents[2]
_BACKEND_APP = _REPO_ROOT / "backend" / "app"


@pytest.fixture(autouse=True)
def _reset_roster_cache():
    """Every test gets a clean, deterministic roster cache."""
    original = guard_mod._ROSTER_CACHE
    original_ts = guard_mod._ROSTER_LAST_REFRESH
    guard_mod._ROSTER_CACHE = set()
    guard_mod._ROSTER_LAST_REFRESH = 0.0
    yield
    guard_mod._ROSTER_CACHE = original
    guard_mod._ROSTER_LAST_REFRESH = original_ts


def _seed(*names: str) -> None:
    guard_mod._ROSTER_CACHE = set(names)
    # Pretend the cache was just refreshed so guard_global_crystal_write's
    # internal refresh_client_name_roster() call is a no-op (db_pool=None
    # would otherwise just return the existing cache size anyway, but this
    # keeps intent explicit).
    guard_mod._ROSTER_LAST_REFRESH = __import__("time").monotonic()


# ── _name_to_pattern: conservative matching rules ──

def test_name_to_pattern_skips_short_names():
    assert _name_to_pattern("Al") is None
    assert _name_to_pattern("Jo") is None


def test_name_to_pattern_skips_single_token_names():
    # Single-token names (usernames like "longra") are not reliable
    # enough to regex-match against free text.
    assert _name_to_pattern("longra") is None
    assert _name_to_pattern("Madonna") is None


def test_name_to_pattern_accepts_two_token_names():
    pattern = _name_to_pattern("John D.")
    assert pattern is not None
    assert pattern.search("a note about John D. from last week")
    assert not pattern.search("a note about John Doe from last week")


def test_name_to_pattern_word_boundary_prevents_partial_match():
    pattern = _name_to_pattern("Lisa West")
    assert pattern is not None
    assert pattern.search("Lisa West called yesterday")
    assert not pattern.search("MelissaWesterly is unrelated")


# ── text_contains_client_name ──

def test_text_contains_client_name_true_positive():
    _seed("John D.", "Lisa West")
    matched = text_contains_client_name(
        "Session Insight referencing John D.'s progress this week"
    )
    assert matched == "John D."


def test_text_contains_client_name_true_negative_generic_content():
    _seed("John D.", "Lisa West")
    matched = text_contains_client_name(
        "Many people have struggled with feeling like they're drinking too much."
    )
    assert matched is None


def test_text_contains_client_name_empty_roster_never_blocks():
    # Roster cache empty (e.g. refresh never succeeded) -- fail open on
    # the lookup itself is acceptable ONLY because guard_global_crystal_write
    # still gates on scope; an empty roster is a degraded-but-safe state,
    # not a silent bypass of the scope check.
    matched = text_contains_client_name("John D. said something")
    assert matched is None


# ── guard_global_crystal_write: the actual gate ──

@pytest.mark.parametrize("scope", ["user", "admin_only", "archived", "user:some_id"])
def test_non_global_scopes_are_never_gated(scope):
    """The write-time guard only applies to scope='global'. Every other
    scope is gated by the recall-side allowlist instead -- this function
    must not add friction (or false confidence) to those paths."""
    _seed("John D.")
    result = asyncio.run(
        guard_global_crystal_write(
            None, "text mentioning John D. explicitly", scope, context="test"
        )
    )
    assert result is True


def test_global_scope_with_client_name_is_blocked():
    _seed("John D.", "Lisa West")
    result = asyncio.run(
        guard_global_crystal_write(
            None,
            "[Session Insight] Lisa West, I'm grateful you're pausing to think.",
            "global",
            context="test",
        )
    )
    assert result is False


def test_global_scope_without_client_name_is_allowed():
    _seed("John D.", "Lisa West")
    result = asyncio.run(
        guard_global_crystal_write(
            None,
            "Persistent notifications erode attention via a compounding backlog illusion.",
            "global",
            context="test",
        )
    )
    assert result is True


def test_global_scope_with_no_db_pool_and_stale_empty_roster_fails_open_by_design():
    # db_pool=None means refresh_client_name_roster() cannot query and
    # the cache stays whatever it was seeded to. If nothing was ever
    # seeded (roster genuinely empty), the guard cannot detect a name it
    # has never seen -- this is a known, documented limitation (roster
    # coverage, not the gate logic) and is why the standing auditor
    # (post-write sweep) exists as defense-in-depth alongside this
    # pre-write gate.
    result = asyncio.run(
        guard_global_crystal_write(
            None, "Some Unknown Person disclosed something private.", "global",
            context="test",
        )
    )
    assert result is True


# ── Original incident fixtures: the two real leaked crystals, verbatim style ──

def test_original_incident_crystal_181990_style_text_is_blocked():
    _seed("John D.", "Lisa West")
    leaked_text = (
        "[Session Insight] I'm so glad you're interested in exploring our "
        "therapeutic workbooks, John D. [Session Insight] Lisa, I'm grateful "
        "you're pausing to think and return to the Meredith conversation"
    )
    result = asyncio.run(
        guard_global_crystal_write(None, leaked_text, "global", context="test")
    )
    assert result is False


def test_original_incident_crystal_355292_style_text_is_blocked():
    _seed("John D.")
    leaked_text = (
        "[Session Insight] John D., I sense a bit of curiosity in your words. "
        "You're asking me to expand on something."
    )
    result = asyncio.run(
        guard_global_crystal_write(None, leaked_text, "global", context="test")
    )
    assert result is False


# ── Static source-scan: guard must be wired into both write sites ──

def test_solo_forge_write_site_calls_the_guard():
    src = (_BACKEND_APP / "services" / "nate_memory_crystallizer.py").read_text()
    solo_forge_idx = src.index("Solo forge: high-confidence fragments")
    next_section_idx = src.index("clusters = self._cluster_by_domain")
    section = src[solo_forge_idx:next_section_idx]
    assert "guard_global_crystal_write" in section, (
        "Solo-forge write path must call guard_global_crystal_write before "
        "INSERT -- this is one of the two sites the 2026-07-09 incident's "
        "write-time fix covers."
    )


def test_cluster_synthesis_write_site_calls_the_guard():
    src = (_BACKEND_APP / "services" / "nate_memory_crystallizer.py").read_text()
    insert_idx = src.index("INSERT INTO nate_intelligence_crystals\n                            (crystal_text, domain, scope, topics, source_count,\n                             generation, confidence, content_hash, context_start, context_end,")
    preceding = src[max(0, insert_idx - 1500):insert_idx]
    assert "guard_global_crystal_write" in preceding, (
        "Cluster-synthesis write path must call guard_global_crystal_write "
        "before the INSERT -- this is the exact site that produced the two "
        "PHI-bearing crystals in the 2026-07-09 incident."
    )


def test_crystallize_from_conversation_fails_closed_on_unresolved_user():
    src = (_REPO_ROOT / "backend" / "app" / "websocket" / "crystal_recall_bridge.py").read_text()
    fn_idx = src.index("async def crystallize_from_conversation(")
    next_fn_idx = src.index("\nasync def ", fn_idx + 10)
    body = src[fn_idx:next_fn_idx]
    assert "if not user_uuid" in body and "return None" in body, (
        "crystallize_from_conversation must refuse to write when hardware_id "
        "doesn't resolve to a user -- otherwise it writes an orphaned "
        "scope='user' crystal with user_id IS NULL, the exact structural "
        "pattern found in the 2026-07-09 audit."
    )
