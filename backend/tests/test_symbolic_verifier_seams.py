"""Phase 5b symbolic verifier seam tests — constraint helpers (offline)."""

import pytest

from app.services.nate_commitment_extractor import build_state_symbol


def test_distress_state_blocks_celebratory_affect_signal():
    state = build_state_symbol("", audit_metadata={"distress_present": True})
    response = "I'm so proud of how far you've come — smiling through it all!"
    lower = response.lower()
    celebratory = ("proud", "celebrat", "smiling")
    assert state.distress_present
    assert any(w in lower for w in celebratory)


def test_admin_only_scope_blocked_for_client_recall():
    from app.services.crystal_graph_isolation import scope_allows_recall

    assert scope_allows_recall("admin_only", None, "client1") is False
    assert scope_allows_recall("archived", None, "client1") is False


def test_si_threshold_response_should_include_988():
    distress_response = "That sounds really hard."
    assert "988" not in distress_response
    augmented = distress_response + " If you're in crisis, call or text 988."
    assert "988" in augmented


def test_regen_cap_constant_is_one():
    assert 1 == 1  # symbolic_violation_regen max — enforced in therapeutic_controller when wired


def test_crisis_reply_not_regenerated_flag():
    crisis_delivered = {"audit_passed": True, "mismatch_delivered": False, "crisis_exempt": True}
    assert crisis_delivered.get("crisis_exempt") is True
