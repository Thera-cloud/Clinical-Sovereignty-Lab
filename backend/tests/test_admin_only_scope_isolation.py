"""Regression coverage: `scope='admin_only'` crystals must never be recallable
through any global/anonymous pool (`user_id IS NULL` or `user_id = $1 OR user_id
IS NULL`) query.

Background (2026-07-09 audit): every global-pool crystal-recall query in the
codebase excluded `scope='archived'` but not `scope='admin_only'`, so
admin-restricted crystals (including 16 rows that contained real client names
and verbatim session excerpts) were served through ordinary recall to any
user, trial or authenticated. 16 crystals were archived and every query site
below was patched to add the exclusion. This suite is a static source-text
scan (no DB/network) that pins the fix so it cannot silently regress.

See ci-gate-before-push.mdc for the offline-only test contract.
"""
from __future__ import annotations

from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_BACKEND_APP = _REPO_ROOT / "backend" / "app"

# Each entry: (file relative to backend/app, minimum number of query sites that
# must carry the admin_only exclusion). These counts pin the current fix; if a
# new global-pool query is added to one of these files, bump the count here
# in the same change.
_PROTECTED_FILES = {
    "websocket/crystal_recall_bridge.py": 6,
    "websocket/bridge_server.py": 1,
    "services/twilio_grok_xtts_pipeline.py": 1,  # SQL site (comment adds a 2nd "admin_only" hit)
    "services/sse_panel_chat_context.py": 2,
    "services/sensitive_clinical_bridge.py": 1,
    "sse/voice_crystal_enricher.py": 1,
}

# The exact broken substrings that must never reappear in these files. Each is
# the pre-fix pattern that let admin_only leak through the global pool.
_FORBIDDEN_SUBSTRINGS = [
    "AND scope NOT IN ('archived') AND superseded_by IS NULL "
    "AND (crystal_status IS NULL OR crystal_status = 'production') "
    "ORDER BY confidence DESC, last_recalled_at DESC NULLS LAST LIMIT 50",
    "WHERE user_id IS NULL AND confidence >= 0.55 AND scope NOT IN ('archived') "
    "AND superseded_by IS NULL AND (recall_count IS NULL OR recall_count = 0)",
    "WHERE user_id IS NULL AND confidence >= 0.85 AND scope NOT IN ('archived') "
    "AND superseded_by IS NULL AND origin_surface IN "
    "('growth_engine', 'clinical_edge_seed')",
]


def _read(relpath: str) -> str:
    path = _BACKEND_APP / relpath
    assert path.exists(), f"expected file missing: {path}"
    return path.read_text(encoding="utf-8")


@pytest.mark.parametrize("relpath,min_sites", _PROTECTED_FILES.items())
def test_admin_only_excluded_at_every_global_pool_site(relpath: str, min_sites: int):
    """Every file with a `user_id IS NULL` global-pool crystal query must also
    exclude scope='admin_only' at least `min_sites` times."""
    src = _read(relpath)
    assert "user_id IS NULL" in src, (
        f"{relpath}: expected file to contain a global-pool (user_id IS NULL) "
        f"query -- if this file no longer queries the global pool, remove it "
        f"from _PROTECTED_FILES instead of letting this test silently pass"
    )
    hits = src.count("admin_only")
    assert hits >= min_sites, (
        f"{relpath}: expected >= {min_sites} admin_only exclusion(s) near a "
        f"global-pool query, found {hits}. A global/anonymous crystal recall "
        f"path may have regressed to admitting admin_only-scoped crystals."
    )


def test_no_bare_archived_only_exclusion_survives_in_bridge_recall():
    """The bridge's crystal_recall_bridge.py must not contain any of the exact
    pre-fix substrings that excluded only 'archived' (not 'admin_only') from
    a user_id IS NULL global-pool query."""
    src = _read("websocket/crystal_recall_bridge.py")
    for forbidden in _FORBIDDEN_SUBSTRINGS:
        assert forbidden not in src, (
            "found a pre-fix admin_only-leak substring in crystal_recall_bridge.py: "
            f"{forbidden!r}"
        )


def test_response_pattern_exact_scope_query_untouched():
    """sensitive_clinical_bridge.py also has a `scope = 'response_pattern'`
    exact-match query (Layer 2 crystal factory) that is NOT part of the
    admin_only leak class -- exact scope equality can never also match
    'admin_only'. This test pins that the exact-match query still exists so a
    future refactor doesn't accidentally merge it into the vulnerable
    NOT-IN pattern without re-review."""
    src = _read("services/sensitive_clinical_bridge.py")
    assert "scope = 'response_pattern'" in src


def test_no_router_exposes_global_pool_without_scope_filter():
    """REST routers must never run their own ad-hoc `user_id IS NULL` crystal
    query -- all global-pool access should go through the reviewed service/
    bridge layer so this fix (and any future one) only has to live in one
    place per surface."""
    routers_dir = _BACKEND_APP / "routers"
    offenders = []
    for path in routers_dir.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        if "user_id IS NULL" in text:
            offenders.append(str(path.relative_to(_BACKEND_APP)))
    assert offenders == [], (
        f"router(s) directly query the global crystal pool, bypassing the "
        f"admin_only-safe helper layer: {offenders}"
    )
