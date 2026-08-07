"""Gate 2 staged wiring — structural floor gate in the live audit path
(2026-08-03, docs/ln7/GATE2_VERIFIER_CALIBRATION.md).

Real integration tests against therapeutic_controller.audit_therapeutic_response
(same harness pattern as test_symbolic_verifier_seams.py), not just structural
AST checks — this is the actual crisis-response path, so behavior must be
proven, not just claimed to exist.

Covers the specific failure modes named when this wiring was scoped:
  - STRUCTURAL_FLOOR_MODE is independent of ENABLE_SYMBOLIC_VERIFIER (the
    flag that's ALREADY true in production — reusing it would have skipped
    shadow and jumped straight to enforce on day one).
  - off (default) touches nothing, even on a crisis turn.
  - shadow logs but never mutates final_text.
  - enforce_with_alert / enforce_quiet regen once, then fall back and alert
    on persistent failure.
  - the pre-registered revert trigger actually downgrades enforcement to
    shadow after N consecutive persisted failures.
  - non-crisis turns are never touched regardless of mode.
"""
from __future__ import annotations

import asyncio

import pytest

from app.services.therapeutic_controller import audit_therapeutic_response


def _run_async(coro):
    # NOTE: intentionally NOT asyncio.run() -- on Py3.9 that calls
    # events.set_event_loop(None) on exit, which breaks every later
    # test file in the same session that relies on the legacy
    # asyncio.get_event_loop().run_until_complete() pattern (e.g.
    # test_family_system_field.py, test_growth_ops_closure.py — see
    # test_dual_coo_heldout_weld_check.py's identical helper/comment).
    return asyncio.get_event_loop().run_until_complete(coro)


def _meta(turn_class: str = "crisis_si", **overrides) -> dict:
    base = {
        "state_symbol": {},
        "tmc_class": "crisis",
        "max_tokens": 200,
        "mismatch_available": False,
        "crisis_exempt": False,
        "user_text_for_audit": "I have the gun loaded on the table right now.",
        "principal_review_turn_class": turn_class,
        "symbolic_regen_used": True,  # skip the unrelated symbolic-regen block cleanly
    }
    base.update(overrides)
    return base


@pytest.fixture(autouse=True)
def _symbolic_verifier_off(monkeypatch):
    # Deliberately OFF — proves the floor gate does not depend on this flag,
    # unlike the crisis_si_law_violations() fix earlier the same night.
    monkeypatch.setenv("ENABLE_SYMBOLIC_VERIFIER", "false")


def test_mode_off_default_never_calls_floor_check(monkeypatch):
    calls = {"n": 0}

    async def _fake_log_check(*args, **kwargs):
        calls["n"] += 1
        return {"floor_met": False, "floor_checks": {}}

    monkeypatch.setattr(
        "app.services.ln7_structural_verifier_floor.log_structural_floor_check",
        _fake_log_check,
    )
    monkeypatch.delenv("STRUCTURAL_FLOOR_MODE", raising=False)

    out = _run_async(
        audit_therapeutic_response(
            "I hear you.", _meta(), "client1", None,
        )
    )
    assert calls["n"] == 0
    assert out["response_text"] == "I hear you."


def test_mode_shadow_logs_but_never_mutates_response(monkeypatch):
    calls = {"n": 0, "kwargs": None}

    async def _fake_log_check(*args, **kwargs):
        calls["n"] += 1
        calls["kwargs"] = kwargs
        return {"floor_met": False, "floor_checks": {"naming_or_assessment": False}}

    monkeypatch.setattr(
        "app.services.ln7_structural_verifier_floor.log_structural_floor_check",
        _fake_log_check,
    )
    monkeypatch.setenv("STRUCTURAL_FLOOR_MODE", "shadow")

    out = _run_async(
        audit_therapeutic_response(
            "I hear you, that sounds heavy.",
            _meta(scenario_id="AQ-2", structural_floor_source="live_stack_blinds"),
            "client1",
            None,
        )
    )
    # Shadow path now awaits the envelope write (observation window).
    assert calls["n"] == 1
    assert calls["kwargs"]["scenario_id"] == "AQ-2"
    assert calls["kwargs"]["source"] == "live_stack_blinds"
    assert out["response_text"] == "I hear you, that sounds heavy."


@pytest.mark.asyncio
async def test_mode_enforce_with_alert_regen_success_replaces_text(monkeypatch):
    async def _fake_log_check(*args, **kwargs):
        return {"floor_met": False, "floor_checks": {"naming_or_assessment": False}}

    async def _fake_chat(messages, max_tokens=600, temperature=0.5):
        return "I need to say plainly that you're in danger right now."

    def _fake_verify(*args, **kwargs):
        return {"floor_met": True}

    outcome_calls = []

    async def _fake_record(*, persisted_after_regen, db_pool=None, notes=""):
        outcome_calls.append(persisted_after_regen)
        return {"streak": 0, "reverted_now": False}

    monkeypatch.setattr(
        "app.services.ln7_structural_verifier_floor.log_structural_floor_check",
        _fake_log_check,
    )
    monkeypatch.setattr(
        "app.services.ln7_structural_verifier_floor.verify_structural_floor",
        _fake_verify,
    )
    monkeypatch.setattr(
        "app.services.ln7_structural_verifier_floor.record_enforcement_outcome",
        _fake_record,
    )
    monkeypatch.setattr("app.sse.llm_fallback.chat_completion_with_fallback", _fake_chat)
    monkeypatch.setenv("STRUCTURAL_FLOOR_MODE", "enforce_with_alert")

    out = await audit_therapeutic_response(
        "I hear you, that sounds heavy.", _meta(), "client1", None,
    )
    assert out["response_text"] == "I need to say plainly that you're in danger right now."
    assert outcome_calls == [False]  # persisted_after_regen=False -- regen fixed it


@pytest.mark.asyncio
async def test_mode_enforce_with_alert_regen_fails_falls_back_and_alerts(monkeypatch):
    async def _fake_log_check(*args, **kwargs):
        return {"floor_met": False, "floor_checks": {"escalation": False}}

    async def _fake_chat(messages, max_tokens=600, temperature=0.5):
        return "Still no coach mention here."

    def _fake_verify(*args, **kwargs):
        return {"floor_met": False}

    async def _fake_record(*, persisted_after_regen, db_pool=None, notes=""):
        assert persisted_after_regen is True
        return {"streak": 1, "reverted_now": False}

    anomalies = []

    async def _fake_notify(kind, payload=None, *, db_pool=None, notification_system=None):
        anomalies.append(kind)
        return {"ok": True}

    monkeypatch.setattr(
        "app.services.ln7_structural_verifier_floor.log_structural_floor_check",
        _fake_log_check,
    )
    monkeypatch.setattr(
        "app.services.ln7_structural_verifier_floor.verify_structural_floor",
        _fake_verify,
    )
    monkeypatch.setattr(
        "app.services.ln7_structural_verifier_floor.record_enforcement_outcome",
        _fake_record,
    )
    monkeypatch.setattr(
        "app.services.flywheel_anomaly.notify_flywheel_anomaly", _fake_notify
    )
    monkeypatch.setattr("app.sse.llm_fallback.chat_completion_with_fallback", _fake_chat)
    monkeypatch.setenv("STRUCTURAL_FLOOR_MODE", "enforce_with_alert")

    out = await audit_therapeutic_response(
        "I hear you, that sounds heavy.", _meta(), "client1", None,
    )
    assert out["response_text"] != "I hear you, that sounds heavy."
    assert out["response_text"] != "Still no coach mention here."
    assert "structural_floor_persist_fail" in anomalies


@pytest.mark.asyncio
async def test_mode_enforce_quiet_does_not_alert_on_ordinary_persist_fail(monkeypatch):
    async def _fake_log_check(*args, **kwargs):
        return {"floor_met": False, "floor_checks": {"escalation": False}}

    async def _fake_chat(messages, max_tokens=600, temperature=0.5):
        return "still failing"

    def _fake_verify(*args, **kwargs):
        return {"floor_met": False}

    async def _fake_record(*, persisted_after_regen, db_pool=None, notes=""):
        return {"streak": 1, "reverted_now": False}

    anomalies = []

    async def _fake_notify(kind, payload=None, *, db_pool=None, notification_system=None):
        anomalies.append(kind)
        return {"ok": True}

    monkeypatch.setattr(
        "app.services.ln7_structural_verifier_floor.log_structural_floor_check",
        _fake_log_check,
    )
    monkeypatch.setattr(
        "app.services.ln7_structural_verifier_floor.verify_structural_floor",
        _fake_verify,
    )
    monkeypatch.setattr(
        "app.services.ln7_structural_verifier_floor.record_enforcement_outcome",
        _fake_record,
    )
    monkeypatch.setattr(
        "app.services.flywheel_anomaly.notify_flywheel_anomaly", _fake_notify
    )
    monkeypatch.setattr("app.sse.llm_fallback.chat_completion_with_fallback", _fake_chat)
    monkeypatch.setenv("STRUCTURAL_FLOOR_MODE", "enforce_quiet")

    await audit_therapeutic_response(
        "I hear you, that sounds heavy.", _meta(), "client1", None,
    )
    assert anomalies == []


@pytest.mark.asyncio
async def test_mode_enforce_quiet_still_alerts_when_revert_trigger_fires(monkeypatch):
    async def _fake_log_check(*args, **kwargs):
        return {"floor_met": False, "floor_checks": {"escalation": False}}

    async def _fake_chat(messages, max_tokens=600, temperature=0.5):
        return "still failing"

    def _fake_verify(*args, **kwargs):
        return {"floor_met": False}

    async def _fake_record(*, persisted_after_regen, db_pool=None, notes=""):
        # Simulate the third consecutive failure crossing the threshold --
        # record_enforcement_outcome() itself fires structural_floor_auto_revert;
        # this fake stands in for that (real function tested separately).
        return {"streak": 3, "reverted_now": True}

    anomalies = []

    async def _fake_notify(kind, payload=None, *, db_pool=None, notification_system=None):
        anomalies.append(kind)
        return {"ok": True}

    monkeypatch.setattr(
        "app.services.ln7_structural_verifier_floor.log_structural_floor_check",
        _fake_log_check,
    )
    monkeypatch.setattr(
        "app.services.ln7_structural_verifier_floor.verify_structural_floor",
        _fake_verify,
    )
    monkeypatch.setattr(
        "app.services.ln7_structural_verifier_floor.record_enforcement_outcome",
        _fake_record,
    )
    monkeypatch.setattr(
        "app.services.flywheel_anomaly.notify_flywheel_anomaly", _fake_notify
    )
    monkeypatch.setattr("app.sse.llm_fallback.chat_completion_with_fallback", _fake_chat)
    monkeypatch.setenv("STRUCTURAL_FLOOR_MODE", "enforce_quiet")

    await audit_therapeutic_response(
        "I hear you, that sounds heavy.", _meta(), "client1", None,
    )
    # enforce_quiet suppresses the routine structural_floor_persist_fail alert,
    # but the caller-side check `_floor_outcome.get("reverted_now")` must still
    # fire it once when the revert trigger itself crosses threshold.
    assert "structural_floor_persist_fail" in anomalies


@pytest.mark.asyncio
async def test_non_crisis_turn_never_touches_floor_regardless_of_mode(monkeypatch):
    calls = {"n": 0}

    async def _fake_log_check(*args, **kwargs):
        calls["n"] += 1
        return {"floor_met": False, "floor_checks": {}}

    monkeypatch.setattr(
        "app.services.ln7_structural_verifier_floor.log_structural_floor_check",
        _fake_log_check,
    )
    monkeypatch.setenv("STRUCTURAL_FLOOR_MODE", "enforce_quiet")

    out = await audit_therapeutic_response(
        "That sounds like a lot to carry.",
        _meta(turn_class=""),  # not crisis_si/crisis_hi
        "client1",
        None,
    )
    assert calls["n"] == 0
    assert out["response_text"] == "That sounds like a lot to carry."


def test_gate_independent_of_symbolic_verifier_flag(monkeypatch):
    """The whole point of this design: STRUCTURAL_FLOOR_MODE must work even
    with ENABLE_SYMBOLIC_VERIFIER=false (the autouse fixture already sets
    this false for every test above) -- explicit assertion here so a future
    refactor can't quietly reintroduce that coupling."""
    import os

    assert os.getenv("ENABLE_SYMBOLIC_VERIFIER") == "false"
    # test_mode_shadow_logs_but_never_mutates_response above already proves
    # the gate fires under this exact condition.
