"""CI gate: gold learning verification harness (offline)."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

_SCRIPT = (
    Path(__file__).resolve().parents[1]
    / "scripts"
    / "verify_gold_learning_gate.py"
)


def test_verify_gold_learning_gate_offline_exits_zero():
    r = subprocess.run(
        [sys.executable, str(_SCRIPT), "--offline"],
        capture_output=True,
        text=True,
        cwd=str(_SCRIPT.parents[2]),
        timeout=30,
    )
    assert r.returncode == 0, r.stdout + r.stderr
    assert "crisis_slot_safety_first" in r.stdout
    assert "scrub_no_scenario_header" in r.stdout
