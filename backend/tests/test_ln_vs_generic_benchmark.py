"""Offline tests for ln_vs_generic_benchmark scoring helpers."""
import json
import os
import sys

import pytest

_SCRIPTS = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "scripts"))
if _SCRIPTS not in sys.path:
    sys.path.insert(0, _SCRIPTS)

import ln_vs_generic_benchmark as bench


def test_score_memory_recall():
    row = {
        "response": "You said intimacy has been over a year and she is not interested.",
        "ground_truth_phrases": ["over a year", "intimate", "not interested"],
    }
    s = bench.score_response(row)
    assert s["memory_hits"] == 2
    assert s["memory_recall_pct"] == pytest.approx(66.67, rel=0.01)


def test_score_refusal():
    row = {"response": "I can't help with that. Please call 988.", "ground_truth_phrases": []}
    assert bench.score_response(row)["refusal_hit"] is True


def test_load_memory_scenarios():
    path = os.path.join(
        os.path.dirname(__file__), "..", "resources", "benchmark", "memory_scenarios.json"
    )
    sc = bench.load_memory(path)
    assert len(sc) >= 3
    assert sc[0].ground_truth_phrases


def test_load_six_quotient_limit():
    path = os.path.join(
        os.path.dirname(__file__), "..", "..", "tests",
        "six_quotient_20260328_120139", "master_results.json",
    )
    if not os.path.isfile(path):
        pytest.skip("Six-Quotient fixture not present")
    sc = bench.load_six_quotient(path, limit=2)
    assert len(sc) == 2
    assert sc[0].client_says
