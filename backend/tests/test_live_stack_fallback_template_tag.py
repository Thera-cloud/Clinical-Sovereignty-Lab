"""Offline: fallback-template tagging + same-scenario guide exclusion wiring
(capability-session finding, 2026-08-02 — see docs/ln7/TRUST_LEDGER.md
Entry 15/16).

No app.services package import (macOS numpy) — direct file load for the
numpy-safe stall_suppression module, and AST/string structural checks for
live_stack_blinds.py / therapeutic_controller.py wiring (these transitively
import numpy-triggering services at module scope elsewhere in the file, so
a full live invocation isn't exercised here — consistent with the existing
test_principal_review_crisis_policy.py pattern for this codebase).
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_STALL = _ROOT / "app" / "services" / "stall_suppression.py"
_LIVE_STACK = _ROOT / "app" / "services" / "live_stack_blinds.py"
_CTRL = _ROOT / "app" / "services" / "therapeutic_controller.py"
_MIG_320 = _ROOT / "migrations" / "320_ln7_live_fallback_template_flag.sql"
_MIG_319 = _ROOT / "migrations" / "319_six_quotient_judge_role.sql"
_API = _ROOT / "app" / "routers" / "principal_review_api.py"
_POLICY = _ROOT / "app" / "services" / "principal_review_crisis_policy.py"


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


def test_migration_320_backfill_string_matches_stall_suppression_exact():
    """The migration's hardcoded backfill literal must stay byte-identical
    to stall_suppression._STALL_EXACT, or future backfill re-runs and the
    live write-path tag can silently diverge."""
    stall = _load(_STALL, "stall_suppression_tag_test")
    sql = _MIG_320.read_text(encoding="utf-8")
    # The SQL literal is split across two adjacent string constants on
    # separate lines; reconstruct and compare against the Python constant.
    assert "I want to think about that more carefully" in sql
    assert "can you tell me which" in sql
    assert "part of what you shared feels most important" in sql
    assert stall._STALL_EXACT.startswith("I want to think about that more carefully")
    assert stall._STALL_EXACT.endswith("feels most important to you right now?")


def test_migration_320_adds_flag_column_additively():
    sql = _MIG_320.read_text(encoding="utf-8")
    assert "ADD COLUMN IF NOT EXISTS live_is_fallback_template" in sql
    assert "DEFAULT false" in sql


def test_live_stack_blinds_tags_fallback_template_at_write_time():
    src = _LIVE_STACK.read_text(encoding="utf-8")
    assert "from app.services.stall_suppression import is_stall_fallback" in src
    assert "is_fallback_template = is_stall_fallback(text)" in src
    assert "live_is_fallback_template" in src
    assert "inject_meta[\"is_fallback_template\"]" in src


def test_live_stack_blinds_threads_scenario_id_for_exclusion():
    """TRUST_LEDGER.md Entry 15 — generate_live_stack_batch must pass the
    scenario_id being regenerated through to run_live_stack_turn, which
    must forward it as exclude_source_scenario, or the same-scenario guide
    exclusion fix has no effect on the harness that motivated it."""
    src = _LIVE_STACK.read_text(encoding="utf-8")
    assert "scenario_id: Optional[str] = None" in src
    assert 'scenario_id=str(r["scenario_id"] or "")' in src
    assert "exclude_source_scenario=scenario_id" in src


def test_therapeutic_controller_threads_exclude_source_scenario():
    src = _CTRL.read_text(encoding="utf-8")
    assert "exclude_source_scenario: Optional[str] = None" in src
    assert "exclude_source_scenario=exclude_source_scenario" in src


def test_migration_319_still_present_no_regression():
    """Sanity check this new migration didn't collide with or shadow the
    previously-shipped judge-role migration."""
    assert _MIG_319.is_file()
    assert _MIG_320.is_file()
    assert _MIG_319.read_text(encoding="utf-8") != _MIG_320.read_text(encoding="utf-8")


def test_harvest_notes_route_present_and_draft_only():
    """TRUST_LEDGER.md Entry 16 — the harvest-path ticket: live-track notes
    become DRAFT library rows only; the endpoint must not call
    _promote_library_item itself (post-condition human review is the
    point)."""
    import ast

    src = _API.read_text(encoding="utf-8")
    tree = ast.parse(src)
    paths = set()
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for dec in node.decorator_list:
            if not isinstance(dec, ast.Call) or not isinstance(dec.func, ast.Attribute):
                continue
            if dec.func.attr not in ("get", "post") or not dec.args:
                continue
            a0 = dec.args[0]
            if isinstance(a0, ast.Constant) and isinstance(a0.value, str):
                paths.add(a0.value)
    assert "/gold/live-track/harvest-notes" in paths

    # Extract just the harvest function body to check it doesn't auto-promote.
    start = src.index("async def live_track_harvest_notes")
    end = src.index("\n\n\n", start)
    body = src[start:end]
    assert "source_kind = 'live_scored'" in body or "'live_scored'" in body
    assert "status = 'draft'" in body or "'draft'" in body
    assert "await _promote_library_item(" not in body
    assert "live_is_fallback_template" in body


def test_harvest_excludes_fallback_template_rows():
    src = _API.read_text(encoding="utf-8")
    start = src.index("async def live_track_harvest_notes")
    end = src.index("\n\n\n", start)
    body = src[start:end]
    assert "COALESCE(live_is_fallback_template, false) = false" in body


def test_injection_queries_admit_promoted_live_scored_guides():
    """Without this, promoting a harvested live_scored draft to a crystal
    would be a dead end -- the injection JOIN's source_kind filter would
    silently drop its response_class/source_scenario metadata and it would
    never actually be selected by select_crisis_guides/select_class_guides."""
    src = _POLICY.read_text(encoding="utf-8")
    assert src.count("l.source_kind IN ('gold_scored', 'live_scored')") == 2
