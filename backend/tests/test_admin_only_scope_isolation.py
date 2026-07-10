"""Regression coverage: the global/anonymous crystal pool (`user_id IS NULL`)
must be an explicit `scope = 'global'` ALLOWLIST, never a blocklist.

Background (2026-07-09 audit, part 1): every global-pool crystal-recall query
in the codebase excluded `scope='archived'` but not `scope='admin_only'`, so
admin-restricted crystals (including 16 rows that contained real client names
and verbatim session excerpts) were served through ordinary recall to any
user, trial or authenticated. 16 crystals were archived and every query site
was patched to add `scope NOT IN ('archived', 'admin_only')`.

Background (2026-07-09 audit, part 2 -- this file): a blocklist only excludes
scope values someone thought to name. The same audit found a crystal scoped
`user:CLIENT_SWEET2NOEND@YAHOO.COM_ID` with `user_id IS NULL` -- a mis-resolved
user-scoped crystal that had orphaned into the "global" pool under the old
blocklist, undetected because nobody had blocklisted that scope string. Every
site was converted from a blocklist (`scope NOT IN (...)`) to a positive
allowlist: the global pool is `user_id IS NULL AND scope = 'global'`, full
stop. Any future scope value -- named, orphaned, or mis-resolved -- is
excluded by default instead of requiring a new blocklist entry.

This suite is a static source-text scan (no DB/network) that pins the
allowlist fix so it cannot silently regress back to a blocklist.

See ci-gate-before-push.mdc for the offline-only test contract.
"""
from __future__ import annotations

from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_BACKEND_APP = _REPO_ROOT / "backend" / "app"

# Each entry: (file relative to backend/app, minimum number of query sites
# that must use the `scope = 'global'` allowlist). These counts pin the
# current fix; if a new global-pool query is added to one of these files,
# bump the count here in the same change.
_PROTECTED_FILES = {
    "websocket/crystal_recall_bridge.py": 6,
    "websocket/bridge_server.py": 1,
    "services/twilio_grok_xtts_pipeline.py": 1,
    "services/sse_panel_chat_context.py": 2,
    "services/sensitive_clinical_bridge.py": 1,
    "sse/voice_crystal_enricher.py": 1,
    "services/quantum_crystal_orchestrator.py": 2,
}

# 2026-07-09 audit, part 4: these files also query `user_id IS NULL`, but are
# NOT recall/serving sites and must NOT be forced onto the scope='global'
# allowlist pattern above -- they are the standing auditor that deliberately
# scans the ENTIRE ownerless pool across every scope value (including
# 'admin_only', 'archived', or a future orphaned scope) to catch exactly the
# kind of drift _PROTECTED_FILES exists to prevent from ever going unnoticed
# again. Applying the allowlist here would make the auditor blind to the
# scope values it exists to police. Reviewed and explicitly exempted --
# see crystal_phi_auditor.py's module docstring and
# docs/INCIDENT_MEMO_CRYSTAL_SCOPE_PHI_EXPOSURE_2026-07-09.md.
_REVIEWED_AUDIT_SCAN_FILES = {
    "services/crystal_phi_auditor.py",
}

# Exact pre-fix snippets, pinned per file, that must never reappear. Each is
# the literal blocklist text this file used to have on its `user_id IS NULL`
# global-pool branch -- either the original bug (excluded only 'archived')
# or the intermediate fix (excluded 'archived' + 'admin_only' by name, still
# a blocklist a future orphaned/renamed scope value could slip past). This is
# per-file (not a blanket token ban) because `scope != 'archived'` is still
# legitimately used on the *ownership* branch (`user_id = $1 AND scope !=
# 'archived'`) in several of these same files after the allowlist fix.
_FORBIDDEN_OLD_SNIPPETS: dict[str, list[str]] = {
    "websocket/crystal_recall_bridge.py": [
        "scope NOT IN ('archived', 'admin_only')",
    ],
    "websocket/bridge_server.py": [
        "WHERE (user_id = $1 OR user_id IS NULL) "
        "\"\n                    \"AND superseded_by IS NULL AND scope NOT IN "
        "('archived', 'admin_only') ",
        "scope NOT IN ('archived', 'admin_only')",
    ],
    "services/twilio_grok_xtts_pipeline.py": [
        "scope NOT IN ('archived', 'admin_only')",
    ],
    "services/sse_panel_chat_context.py": [
        "scope NOT IN ('archived', 'admin_only')",
    ],
    "services/sensitive_clinical_bridge.py": [
        "scope NOT IN ('archived', 'admin_only')",
    ],
    "sse/voice_crystal_enricher.py": [
        "scope IS NULL OR scope NOT IN ('archived', 'admin_only')",
    ],
    "services/quantum_crystal_orchestrator.py": [
        "WHERE user_id IS NULL OR user_id::text = $1",
        "WHERE scope != 'archived'\n                  AND (user_id IS NULL OR user_id::text = $1)",
    ],
}


def _read(relpath: str) -> str:
    path = _BACKEND_APP / relpath
    assert path.exists(), f"expected file missing: {path}"
    return path.read_text(encoding="utf-8")


@pytest.mark.parametrize("relpath,min_sites", _PROTECTED_FILES.items())
def test_global_pool_is_an_allowlist_not_a_blocklist(relpath: str, min_sites: int):
    """Every file with a `user_id IS NULL` global-pool crystal query must gate
    that branch with `scope = 'global'` (allowlist) at least `min_sites`
    times -- never a `scope NOT IN (...)` / `scope != 'archived'` blocklist,
    which silently admits any scope value nobody thought to exclude yet
    (admin_only, or an orphaned user:* crystal with a NULL user_id)."""
    src = _read(relpath)
    assert "user_id IS NULL" in src, (
        f"{relpath}: expected file to contain a global-pool (user_id IS NULL) "
        f"query -- if this file no longer queries the global pool, remove it "
        f"from _PROTECTED_FILES instead of letting this test silently pass"
    )
    hits = src.count("scope = 'global'")
    assert hits >= min_sites, (
        f"{relpath}: expected >= {min_sites} `scope = 'global'` allowlist "
        f"site(s) near a global-pool query, found {hits}. A global/anonymous "
        f"crystal recall path may have regressed to a blocklist, which admits "
        f"admin_only-scoped or orphaned user:*-scoped crystals by default."
    )


@pytest.mark.parametrize("relpath", _PROTECTED_FILES.keys())
def test_no_blocklist_pattern_survives_in_protected_files(relpath: str):
    """None of this file's pre-fix blocklist substrings (original bug or the
    intermediate admin_only-only patch) may reappear now that its global-pool
    branch has been converted to the `scope = 'global'` allowlist. Pinned
    per-file (not a blanket token ban) because `scope != 'archived'` remains
    legitimate on the *ownership* branch (`user_id = $1 AND scope !=
    'archived'`) in several of these same files."""
    src = _read(relpath)
    for forbidden in _FORBIDDEN_OLD_SNIPPETS[relpath]:
        assert forbidden not in src, (
            f"{relpath}: found a pre-fix blocklist substring that must have "
            f"been fully replaced by the `scope = 'global'` allowlist: "
            f"{forbidden!r}"
        )


def test_response_pattern_exact_scope_query_untouched():
    """sensitive_clinical_bridge.py also has a `scope = 'response_pattern'`
    exact-match query (Layer 2 crystal factory) that is NOT part of the
    global-pool leak class -- exact scope equality can never also match
    'global'. This test pins that the exact-match query still exists so a
    future refactor doesn't accidentally merge it into the allowlisted
    global-pool branch without re-review."""
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
        f"scope='global'-allowlisted helper layer: {offenders}"
    )


def test_no_new_global_pool_site_escapes_the_protected_file_list():
    """Every file under backend/app that queries `user_id IS NULL` must be
    one of the files reviewed and pinned in _PROTECTED_FILES. If a new
    global-pool query site is added anywhere else, it must be reviewed for
    the allowlist pattern and added here in the same change."""
    offenders = []
    for path in _BACKEND_APP.rglob("*.py"):
        relpath = str(path.relative_to(_BACKEND_APP))
        if relpath in _PROTECTED_FILES or relpath in _REVIEWED_AUDIT_SCAN_FILES:
            continue
        text = path.read_text(encoding="utf-8")
        if "user_id IS NULL" in text:
            offenders.append(relpath)
    assert offenders == [], (
        f"unreviewed global-pool (user_id IS NULL) query site(s) found -- "
        f"add to _PROTECTED_FILES with the scope='global' allowlist pattern "
        f"(or, if it is a deliberate cross-scope audit sweep rather than a "
        f"recall/serving site, to _REVIEWED_AUDIT_SCAN_FILES with rationale) "
        f"and a min_sites count: {offenders}"
    )


def test_reviewed_audit_scan_files_do_not_use_the_serving_allowlist():
    """crystal_phi_auditor.py's whole purpose is to catch crystals under ANY
    ownerless scope value the recall-side allowlist wasn't told about yet.
    If it filtered its scan query to `scope = 'global'` it would silently
    stop scanning 'admin_only'/orphaned/future scope values -- exactly the
    blind spot _PROTECTED_FILES exists to prevent. Pin that its scan query
    does NOT narrow by scope (only excludes already-archived rows, which are
    already quarantined)."""
    for relpath in _REVIEWED_AUDIT_SCAN_FILES:
        src = _read(relpath)
        assert "scope = 'global'" not in src, (
            f"{relpath}: this file is exempted from the allowlist pattern "
            f"specifically because it must scan across all ownerless scope "
            f"values, not just 'global' -- if it now filters to scope='global' "
            f"it should be moved into _PROTECTED_FILES instead, and its "
            f"cross-scope-audit design note removed"
        )
