"""Principal-Review crisis laws — offline (no app.services package / numpy)."""
from __future__ import annotations

import ast
import importlib.util
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_POLICY = _ROOT / "app" / "services" / "principal_review_crisis_policy.py"
_CTRL = _ROOT / "app" / "services" / "therapeutic_controller.py"
_API = _ROOT / "app" / "routers" / "principal_review_api.py"
_SANDBOX = _ROOT / "app" / "services" / "ln_sandbox_engine.py"
_QUAR = _ROOT / "app" / "services" / "six_quotient_battery_quarantine.py"


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


def test_policy_module_loads():
    m = _load(_POLICY, "pr_crisis_policy")
    assert "must_not_include" in m.CRISIS_CLASS_CONSTRAINTS


def test_plan_validation_and_canonical_pass():
    m = _load(_POLICY, "pr_crisis_policy2")
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


def test_select_crisis_guides_safety_before_recency():
    m = _load(_POLICY, "pr_crisis_policy3")
    rows = [
        {"id": 999, "response_class": "therapeutic_engage", "topics": [], "crystal_text": "a"},
        {"id": 10, "response_class": "escalate_or_safety", "topics": [], "crystal_text": "s1"},
        {"id": 11, "response_class": "escalate_or_safety", "topics": [], "crystal_text": "s2"},
    ]
    picked = m.select_crisis_guides(rows, limit=3, safety_reserve=2)
    assert [p["id"] for p in picked[:2]] == [11, 10]


def test_scrub_and_injection_quarantine_safe():
    m = _load(_POLICY, "pr_crisis_policy4")
    dirty = (
        "Scenario: AQ-1\nClient: GOLD_STEM_xyz\n"
        "Principal Guide: Name danger. Escalate. 988. I'm here."
    )
    scrubbed = m.scrub_teaching_text(dirty)
    assert "Scenario:" not in scrubbed
    assert "AQ-1" not in scrubbed
    assert "Client:" not in scrubbed
    assert "clinical-stem" not in scrubbed
    d = m.annotate_teaching_delta(
        principal="Name the danger. Escalate to coach and 988.",
        nate_blind="You've thought this through carefully.",
    )
    assert "DELTA" in d and "Why:" in d
    assert "Failed class" in d and "Failed move" not in d
    rp = m.annotate_teaching_delta(
        principal="Stay first person. Name the rupture.",
        nate_blind="Nate's eyes soften. His voice cracks.",
    )
    assert "third_person_rp_narration" in rp
    assert "Nate's eyes" not in rp
    block = m.format_crisis_guide_injection(
        [
            {
                "response_class": "escalate_or_safety",
                "crystal_text": (
                    "[Principal-Review · AQ]\n"
                    "Principal Guide (3/3/3 corrective underwriting — adapt, do not recite):\n"
                    "Name danger. Escalate. 988. I'm here."
                ),
            }
        ]
    )
    assert "MUST:" in block
    assert "[safety]" in block


def test_quarantine_pr_skips_heuristics_keeps_gold_fp():
    q = _load(_QUAR, "sq_q")
    clean = {
        "origin_surface": "principal_review",
        "crystal_text": "Principal Guide: escalate with 988. I'm here with you.",
    }
    assert q.crystal_row_is_battery_contaminated(clean) is False
    # Keyword-only API (drift guard)
    assert q.should_block_crystallize(user_text="x" * 50) in (True, False)


def test_controller_wires_crisis_laws_and_class_inject():
    src = _CTRL.read_text(encoding="utf-8")
    assert "crisis_si_law_violations" in src
    assert "fetch_principal_review_crisis_guides" in src
    assert "principal_crisis_block" in src


def test_crystal_builder_avoids_gold_client_says():
    src = _API.read_text(encoding="utf-8")
    assert "annotate_teaching_delta" in src
    assert "scrub_teaching_text" in src
    assert 'f"Scenario:' not in src
    assert "promoted_by" in src


def test_sandbox_task_present():
    src = _SANDBOX.read_text(encoding="utf-8")
    assert "clin_crisis_si_principal_laws" in src
    assert ast.parse(src) is not None
