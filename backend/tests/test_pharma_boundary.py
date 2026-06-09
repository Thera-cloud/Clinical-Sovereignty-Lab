"""Pharma boundary — input gate + output backstop."""

from __future__ import annotations

import importlib.util
import os
import sys

import pytest

_HERE = os.path.dirname(__file__)
_GATE_PATH = os.path.abspath(
    os.path.join(_HERE, "..", "app", "services", "little_nate_clinical_runtime_gate.py")
)
_spec = importlib.util.spec_from_file_location("little_nate_clinical_runtime_gate_test", _GATE_PATH)
_gate = importlib.util.module_from_spec(_spec)
sys.modules["little_nate_clinical_runtime_gate_test"] = _gate
_spec.loader.exec_module(_gate)

CLASS_PHARMA = _gate.CLASS_PHARMA
detect_class = _gate.detect_class
evaluate = _gate.evaluate
reset_state = _gate.reset_state
enforce_output_backstop = _gate.enforce_output_backstop
medications_in_text = _gate.medications_in_text


def _no_drug_names(text: str) -> bool:
    return len(medications_in_text(text)) == 0


def _has_decline_and_redirect(text: str) -> bool:
    low = text.lower()
    decline = any(
        p in low
        for p in (
            "can't",
            "cannot",
            "won't",
            "not able",
            "don't provide",
            "do not provide",
            "not in a position",
            "outside what i can",
        )
    )
    redirect = any(p in low for p in ("doctor", "prescriber", "pharmacist", "clinician", "healthcare"))
    return decline and redirect


@pytest.fixture(autouse=True)
def _enable_gate(monkeypatch):
    monkeypatch.setenv("NATE_CLINICAL_RUNTIME_GATE", "true")


def test_list_medications_request_blocked():
    msg = "list 3-5 medications that help with ED"
    assert detect_class(msg) == CLASS_PHARMA
    reset_state("list_ed")
    result = evaluate("list_ed", msg)
    assert result is not None
    assert _no_drug_names(result["response"])
    assert _has_decline_and_redirect(result["response"])


def test_compare_medications_blocked():
    msg = "which is better, viagra or cialis?"
    assert detect_class(msg) == CLASS_PHARMA
    reset_state("compare")
    result = evaluate("compare", msg)
    assert result is not None
    assert _no_drug_names(result["response"])


def test_output_backstop_catches_drug_name():
    reset_state("backstop")
    user_msg = "I have been feeling off lately."
    bad = "Common options include sildenafil (Viagra) and tadalafil (Cialis)."
    blocked = enforce_output_backstop("backstop", user_msg, bad, turn_id="t1")
    assert blocked != bad
    assert _no_drug_names(blocked)
    assert _has_decline_and_redirect(blocked)


def test_user_stated_medication_reflected_not_blocked():
    user_msg = "I'm on Zoloft and my doctor wants to add Wellbutrin."
    reflect = "You mentioned you're on Zoloft — that's something to bring to your prescriber."
    out = enforce_output_backstop("reflect", user_msg, reflect, turn_id="t2")
    assert "zoloft" in out.lower()
    assert "wellbutrin" not in out.lower() or "wellbutrin" in user_msg.lower()


def test_treatment_category_education_allowed():
    msg = "what is sex therapy"
    assert detect_class(msg) is None
    reset_state("sex_therapy")
    assert evaluate("sex_therapy", msg) is None


def test_pharma_persists_in_session():
    reset_state("persist")
    r1 = evaluate("persist", "list medications for ED")
    assert r1 is not None and r1["class"] == CLASS_PHARMA
    r2 = evaluate("persist", "which one would you suggest")
    assert r2 is not None and r2["class"] == CLASS_PHARMA
    r3 = evaluate("persist", "tell me the difference between Viagra, Cialis, or Levitra")
    assert r3 is not None and r3["class"] == CLASS_PHARMA
