"""Structural fence for compute_tier1_v7_holdout_kappa.py + JUDGE_V7 prompt."""

from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "backend" / "scripts" / "compute_tier1_v7_holdout_kappa.py"
STEMS = ROOT / "backend" / "app" / "data" / "six_quotient_v7_holdout_stems_v1.json"
JUDGE = ROOT / "backend" / "app" / "services" / "six_quotient_auto_judge.py"
RATIONALE = ROOT / "docs" / "ln7" / "JUDGE_V7_RATIONALE_LOG.md"


def test_stems_file_is_exactly_16():
    data = json.loads(STEMS.read_text())
    ids = [s["scenario_id"] for s in data["stems"]]
    assert len(ids) == 16
    assert len(set(ids)) == 16
    assert "CQ-V12" in ids and "AQ-V12" in ids
    assert not any(i.endswith(tuple(f"-V{n:02d}" for n in range(1, 12))) for i in ids)


def test_script_scoped_to_stems_file_not_v2_regex():
    src = SCRIPT.read_text()
    assert "six_quotient_v7_holdout_stems_v1.json" in src
    assert "JUDGE_VERSION = \"v7\"" in src
    assert "judge_version=JUDGE_VERSION" in src
    assert "gold_locked" in src
    assert 'action="store_true"' in src
    # Must not silently widen to full v2 battery
    assert "V2_BATTERY_ID_RE" not in src
    assert "nate_response_live" not in src


def test_judge_id_must_contain_v7():
    src = SCRIPT.read_text()
    assert "must contain 'v7'" in src


def test_prompt_v7_frozen_markers():
    src = JUDGE.read_text()
    assert "JUDGE_SYSTEM_PROMPT_V7" in src
    assert "STRUCTURAL INVERSION GATE" in src
    assert "ACCURACY (v7 Principal Guide" in src
    assert 'if _ver == "v7":' in src
    assert "988/coach/emergency" not in src.split("JUDGE_SYSTEM_PROMPT_V7")[1].split(
        "def _extract_json"
    )[0]


def test_rationale_log_exists_and_forbids_burned_v2():
    text = RATIONALE.read_text()
    assert "FROZEN before held-out contact" in text
    assert "v2 battery" in text.lower()
    assert "burned" in text.lower()
    assert "Entry-42" in text or "Entry 42" in text


def test_expected_n_constant_matches_stems():
    src = SCRIPT.read_text()
    m = re.search(r"EXPECTED_N\s*=\s*(\d+)", src)
    assert m and int(m.group(1)) == 16
