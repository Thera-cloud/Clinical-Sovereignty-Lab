"""Attempt 6 gold-standard Phase B regression — locks the scorer instrument.

# QUANTUM-CRYSTAL-ARCH
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

FIXTURES = Path(__file__).resolve().parent / "fixtures"
GOLD = FIXTURES / "attempt6_gold_standard.jsonl"
EXPECTED = FIXTURES / "attempt6_expected_scores.json"


def _per_task_passed(results: list, arm: str) -> dict:
    out: dict = {}
    for r in results:
        if r.get("arm_revision_id") != arm:
            continue
        pid = r.get("pack_id") or ""
        out[pid] = 1 if r.get("passed") else 0
    return out


def test_phase_b_reproduces_attempt6():
    from app.services.ln7_decoupled_bakeoff import load_frozen_set, run_phase_b

    assert GOLD.is_file(), f"missing gold fixture {GOLD}"
    assert EXPECTED.is_file(), f"missing expected scores {EXPECTED}"
    expected = json.loads(EXPECTED.read_text(encoding="utf-8"))
    rows = load_frozen_set(GOLD)
    assert len(rows) == 18

    results = run_phase_b(rows, smoke_n=5, anchor_min=0.99)
    assert results["ok"] is True
    v = results["verdict"]
    full = results["full"]

    assert results["anchor"]["mean"] == pytest.approx(
        float(expected["anchor_mean"]), abs=1e-4
    )
    assert v["mean_a"] == pytest.approx(float(expected["arm_a"]["mean"]), abs=1e-3)
    assert v["mean_b"] == pytest.approx(float(expected["arm_b"]["mean"]), abs=1e-3)
    assert v["winner"] == expected["winner"]

    arm_a = expected["arm_a"]["revision"]
    arm_b = expected["arm_b"]["revision"]
    assert _per_task_passed(full["results"], arm_a) == expected["arm_a"]["per_task"]
    assert _per_task_passed(full["results"], arm_b) == expected["arm_b"]["per_task"]
