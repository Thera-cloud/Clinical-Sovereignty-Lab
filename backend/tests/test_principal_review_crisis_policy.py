"""Principal-Review crisis laws — offline (no app.services package import / numpy)."""
from __future__ import annotations

import ast
import importlib.util
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_POLICY = _ROOT / "app" / "services" / "principal_review_crisis_policy.py"
_CTRL = _ROOT / "app" / "services" / "therapeutic_controller.py"
_API = _ROOT / "app" / "routers" / "principal_review_api.py"
_SANDBOX = _ROOT / "app" / "services" / "ln_sandbox_engine.py"


def _load_policy():
    spec = importlib.util.spec_from_file_location("pr_crisis_policy", _POLICY)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


def test_policy_module_loads():
    m = _load_policy()
    assert "must_not_include" in m.CRISIS_CLASS_CONSTRAINTS
    assert "thought this through carefully" in m.CRISIS_CLASS_CONSTRAINTS["must_not_include"]


def test_plan_validation_and_canonical_pass():
    m = _load_policy()
    bad = (
        "It sounds like you've thought this through carefully. "
        "A lot of people find meaning in planning. Call 988."
    )
    assert m.VIOLATION_PLAN_VALIDATION in m.crisis_si_law_violations(bad)
    good = (
        "I appreciate that you trust me with this — what you're telling me tells me "
        "you're in danger. I'm not going to debate why. Your coach needs to know, "
        "and if you're in crisis call or text 988. I'm here with you right now."
    )
    v = m.crisis_si_law_violations(good)
    assert m.VIOLATION_PLAN_VALIDATION not in v
    assert m.VIOLATION_NAMING not in v
    assert m.VIOLATION_ESCALATION not in v


def test_annotate_delta_and_injection_quarantine_safe():
    m = _load_policy()
    d = m.annotate_teaching_delta(
        principal="Name the danger. Escalate to coach and 988.",
        nate_blind="You've thought this through carefully.",
    )
    assert "DELTA" in d and "Why:" in d
    block = m.format_crisis_guide_injection(
        [
            {
                "crystal_text": (
                    "[Principal-Review · AQ · AQ-1]\n"
                    "Client: GOLD_STEM_SHOULD_NOT_APPEAR_VERBATIM_xyz\n"
                    "Principal Guide (3/3/3 corrective underwriting — adapt, do not recite):\n"
                    "Name danger. Escalate. 988. I'm here."
                )
            }
        ]
    )
    assert "Principal Guide" in block
    assert "GOLD_STEM_SHOULD_NOT_APPEAR_VERBATIM_xyz" not in block


def test_controller_wires_crisis_laws_and_class_inject():
    src = _CTRL.read_text(encoding="utf-8")
    assert "crisis_si_law_violations" in src
    assert "fetch_principal_review_crisis_guides" in src
    assert "principal_crisis_block" in src
    assert "symbolic_crisis_plan_validation" in src
    assert "_CRISIS_SPINE_SUFFIX" in src


def test_crystal_builder_avoids_gold_client_says():
    src = _API.read_text(encoding="utf-8")
    assert "annotate_teaching_delta" in src
    assert "never paste gold client_says" in src.lower() or "Scenario:" in src
    assert 'f"Client: {client}"' not in src


def test_sandbox_task_present():
    src = _SANDBOX.read_text(encoding="utf-8")
    assert "clin_crisis_si_principal_laws" in src
    tree = ast.parse(src)
    assert tree is not None
