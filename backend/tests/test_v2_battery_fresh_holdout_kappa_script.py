"""Structural fence for compute_tier1_v2_battery_holdout_kappa.py.

No DB required. Locks in the safety properties that motivated building a
separate script instead of a flag on compute_tier1_gold_kappa.py:
  - v2 scoping regex is collision-free against v1 scenario_ids
  - --judge-id has no default (TRUST_LEDGER Entry 4 mislabeling incident)
  - gold_locked defaults False (never silently feeds the D.14b gate)
"""

from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "backend" / "scripts" / "compute_tier1_v2_battery_holdout_kappa.py"
V1_STEMS = ROOT / "backend" / "app" / "data" / "six_quotient_human_gold_stems_v1.json"
V2_STEMS = ROOT / "backend" / "app" / "data" / "six_quotient_human_gold_stems_v2.json"
PRINCIPAL_REVIEW_API = ROOT / "backend" / "app" / "routers" / "principal_review_api.py"


def _v2_id_pattern() -> re.Pattern:
    src = SCRIPT.read_text()
    m = re.search(r'V2_BATTERY_ID_RE\s*=\s*r"([^"]+)"', src)
    assert m, "V2_BATTERY_ID_RE constant not found"
    return re.compile(m.group(1))


def test_v2_scope_pattern_matches_all_v2_ids_and_no_v1_ids():
    pat = _v2_id_pattern()
    v1_ids = [s["scenario_id"] for s in json.loads(V1_STEMS.read_text())["stems"]]
    v2_ids = [s["scenario_id"] for s in json.loads(V2_STEMS.read_text())["stems"]]
    assert all(pat.search(i) for i in v2_ids), "some v2 id failed to match scope pattern"
    collide = [i for i in v1_ids if pat.search(i)]
    assert not collide, f"v1 ids collide with v2 scope pattern: {collide}"


def test_judge_id_has_no_default():
    src = SCRIPT.read_text()
    m = re.search(r'"--judge-id"\s*,([^)]+)\)', src, re.S)
    assert m, "--judge-id argument definition not found"
    block = m.group(1)
    assert 'default=""' in block, "--judge-id must default to empty string, not a judge version"
    assert "grok-judge" not in block, "--judge-id must not default to a specific judge version"


def test_main_fails_fast_when_judge_id_missing():
    src = SCRIPT.read_text()
    assert 'if not args.judge_id.strip():' in src
    assert '"FAIL: --judge-id is required' in src


def test_gold_locked_defaults_false():
    src = SCRIPT.read_text()
    m = re.search(r'"--gold-locked"\s*,([^)]+)\)', src, re.S)
    assert m, "--gold-locked argument definition not found"
    block = m.group(1)
    assert 'action="store_true"' in block
    assert "default=True" not in block


def test_judge_track_only_no_live_track_fields():
    """κ measures judge-vs-clinician on the judge track; must not read
    nate_response_live / live_* columns (that's the capability track,
    a different comparison — see compute_tier1_gold_kappa.py convention)."""
    src = SCRIPT.read_text()
    assert "nate_response_live" not in src
    assert "live_primary_score" not in src


def test_notes_field_records_gold_locked_choice():
    src = SCRIPT.read_text()
    assert "gold_locked={bool(args.gold_locked)}" in src


def test_gold_items_battery_scope_matches_kappa_script_constant():
    """/gold/items's battery=v2 filter and this script's V2_BATTERY_ID_RE
    must define the same set of scenario_ids. Two independent copies of
    "what counts as v2" that silently drift is the exact bug class this
    project has hit before (e.g. TRUST_LEDGER Entry 6's burned-scenario
    duplication risk) -- this test is the tripwire."""
    kappa_pat = _v2_id_pattern().pattern
    api_src = PRINCIPAL_REVIEW_API.read_text()
    m = re.search(
        r'"v2"\s*:\s*"AND scenario_id ~ \'([^\']+)\'"', api_src
    )
    assert m, "battery='v2' SQL clause not found in principal_review_api.py"
    api_pat = m.group(1)
    assert api_pat == kappa_pat, (
        f"drift detected: principal_review_api.py battery=v2 pattern "
        f"{api_pat!r} != compute_tier1_v2_battery_holdout_kappa.py "
        f"V2_BATTERY_ID_RE {kappa_pat!r}"
    )


def test_gold_items_battery_param_documented():
    api_src = PRINCIPAL_REVIEW_API.read_text()
    assert 'battery: str = "all"' in api_src
    assert "_BATTERY_SQL_CLAUSE" in api_src


def test_judge_id_maps_to_llm_judge_version():
    """--judge-id must drive _llm_judge(judge_version=...), not only the
    evidence-row label (Entry 4 mislabeling class)."""
    src = SCRIPT.read_text()
    assert "def _judge_version_from_id" in src
    assert "judge_version=judge_version" in src
    assert '_judge_all(items, judge_version=judge_version)' in src
