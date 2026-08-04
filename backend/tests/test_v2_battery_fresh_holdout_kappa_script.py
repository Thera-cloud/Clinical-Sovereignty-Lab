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
