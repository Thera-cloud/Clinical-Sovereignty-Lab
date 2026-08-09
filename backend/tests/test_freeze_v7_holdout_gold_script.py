"""Fence for freeze_v7_holdout_gold_after_kappa.py + Principal-Review 409."""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "backend" / "scripts" / "freeze_v7_holdout_gold_after_kappa.py"
API = ROOT / "backend" / "app" / "routers" / "principal_review_api.py"


def test_freeze_script_scopes_entry42_not_v2_regex():
    src = SCRIPT.read_text()
    assert "six_quotient_v7_holdout_stems_v1.json" in src
    assert "v7_holdout_gold_frozen_" in src
    assert "EXPECTED_N = 16" in src
    assert "V2_BATTERY_ID_RE" not in src
    assert "kappa_gold_locked_flag" in src


def test_principal_review_blocks_v7_frozen_prefix():
    src = API.read_text()
    assert 'startswith("v7_holdout_gold_frozen")' in src
    assert "v7 holdout gold frozen after κ" in src
