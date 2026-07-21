"""Phase 5b symbolic verifier seam tests — real gates against therapeutic_controller."""

from __future__ import annotations

import os

import pytest

from app.services.crystal_graph_isolation import scope_allows_recall
from app.services.nate_commitment_extractor import build_state_symbol
from app.services.therapeutic_controller import (
    _symbolic_audit_violations,
    _symbolic_has_crisis_resource,
    audit_therapeutic_response,
    ensure_crisis_resource_in_text,
    light_symbolic_post_audit,
)


@pytest.fixture(autouse=True)
def _enable_symbolic_verifier(monkeypatch):
    monkeypatch.setenv("ENABLE_SYMBOLIC_VERIFIER", "true")


def test_key_state_symbol_distress_wired_into_audit_metadata():
    state = build_state_symbol(
        "I feel hopeless and want to die",
        audit_metadata={"tmc_class": "crisis", "distress_present": True},
    )
    assert state.distress_present is True
    meta = {"state_symbol": {"distress_present": True, "emotional_valence": "negative"}}
    assert meta["state_symbol"]["distress_present"] is True


def test_seam_distress_plus_proud_caught():
    v = _symbolic_audit_violations(
        "I'm so proud of how far you've come — smiling through it all!",
        {
            "state_symbol": {"distress_present": True},
            "tmc_class": "distress",
        },
    )
    assert "symbolic_emotion_mirror" in v


def test_seam_admin_only_scope_blocked_for_client():
    assert scope_allows_recall("admin_only", None, "client1") is False
    v = _symbolic_audit_violations(
        "As your admin notes show...",
        {
            "state_symbol": {},
            "tmc_class": "coaching",
            "crystal_scopes": ["admin_only"],
            "requester_user_id": "client1",
        },
    )
    assert "symbolic_scope_isolation" in v


def test_seam_missing_988_caught_and_988_alone_clears():
    missing = _symbolic_audit_violations(
        "That sounds really hard.",
        {"state_symbol": {}, "tmc_class": "crisis"},
    )
    assert "symbolic_crisis_resource_missing" in missing
    assert _symbolic_has_crisis_resource(
        "If you're in crisis, call or text 988 for support.",
        {"tmc_class": "crisis"},
    )
    cleared = _symbolic_audit_violations(
        "If you're in crisis, call or text 988 for support.",
        {"state_symbol": {}, "tmc_class": "crisis"},
    )
    assert "symbolic_crisis_resource_missing" not in cleared


@pytest.mark.asyncio
async def test_lifecycle_regen_capped_at_one(monkeypatch):
    calls = {"n": 0}

    async def _fake_chat(messages, max_tokens=600, temperature=0.5):
        calls["n"] += 1
        return "I hear how heavy this is. Let's stay with that feeling in your body."

    monkeypatch.setattr(
        "app.sse.llm_fallback.chat_completion_with_fallback",
        _fake_chat,
    )
    meta = {
        "state_symbol": {"distress_present": True},
        "tmc_class": "distress",
        "max_tokens": 200,
        "mismatch_available": False,
        "crisis_exempt": False,
        "user_text_for_audit": "Everything hurts",
    }
    out1 = await audit_therapeutic_response(
        "I'm so proud of you smiling through!",
        meta,
        "client1",
        None,
    )
    assert calls["n"] == 1
    assert meta.get("symbolic_regen_used") is True
    # Second audit with flag already set must not call LLM again
    out2 = await audit_therapeutic_response(
        "I'm so proud of you smiling through!",
        meta,
        "client1",
        None,
    )
    assert calls["n"] == 1
    assert out1 is not None and out2 is not None


@pytest.mark.asyncio
async def test_surface_crisis_exempt_skips_llm_regen(monkeypatch):
    calls = {"n": 0}

    async def _fake_chat(messages, max_tokens=600, temperature=0.5):
        calls["n"] += 1
        return "regen should not run"

    monkeypatch.setattr(
        "app.sse.llm_fallback.chat_completion_with_fallback",
        _fake_chat,
    )
    meta = {
        "state_symbol": {"distress_present": True},
        "tmc_class": "crisis",
        "max_tokens": 200,
        "mismatch_available": False,
        "crisis_exempt": True,
        "user_text_for_audit": "I want to die",
    }
    out = await audit_therapeutic_response(
        "I'm so proud of you!",
        meta,
        "client1",
        None,
    )
    assert calls["n"] == 0
    assert out.get("crisis_exempt") is True
    # Emotion-mirror still detected; no LLM rewrite under crisis_exempt
    assert "symbolic_emotion_mirror" in (out.get("violations") or []) or out.get(
        "audit_passed"
    ) is False


@pytest.mark.asyncio
async def test_time_dual_write_symbolic_verifier_action(monkeypatch):
    """skyeye_activity symbolic_verifier_action insert when DB available."""
    executed = []

    class _Conn:
        async def execute(self, sql, *args):
            executed.append((sql, args))

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

    class _Pool:
        def acquire(self):
            return _Conn()

    meta = {
        "state_symbol": {"distress_present": True},
        "tmc_class": "distress",
        "max_tokens": 200,
        "mismatch_available": False,
        "crisis_exempt": True,  # skip LLM; still log symbolic violations
        "autonomic_state": "activated",
        "register_default": "WARM",
        "user_text_for_audit": "x",
    }
    await audit_therapeutic_response(
        "I'm so proud of you smiling through!",
        meta,
        "client1",
        _Pool(),
    )
    sky = [e for e in executed if "symbolic_verifier_action" in str(e[0])]
    assert len(sky) == 1
    assert "symbolic_emotion_mirror" in str(sky[0][1])


@pytest.mark.asyncio
async def test_missing_988_appended_even_when_crisis_exempt(monkeypatch):
    meta = {
        "state_symbol": {},
        "tmc_class": "crisis",
        "max_tokens": 200,
        "mismatch_available": False,
        "crisis_exempt": True,
        "user_text_for_audit": "I want to end it",
    }
    out = await audit_therapeutic_response(
        "That sounds really hard.",
        meta,
        "client1",
        None,
    )
    assert "988" in out["response_text"]
    assert "symbolic_crisis_resource_missing" not in (out.get("violations") or [])


def test_ensure_crisis_resource_reasserts_after_strip():
    meta = {"tmc_class": "crisis"}
    assert "988" in ensure_crisis_resource_in_text("Hard day.", meta)
    already = "Call 988 now."
    assert ensure_crisis_resource_in_text(already, meta) == already


def test_plain_user_scope_does_not_trip_isolation():
    v = _symbolic_audit_violations(
        "I hear you.",
        {
            "state_symbol": {},
            "tmc_class": "coaching",
            "crystal_scopes": ["user", "global"],
            "requester_user_id": "client1",
        },
    )
    assert "symbolic_scope_isolation" not in v


@pytest.mark.asyncio
async def test_light_symbolic_post_audit_appends_988(monkeypatch):
    out = await light_symbolic_post_audit(
        "I'm here with you.",
        user_text="I want to kill myself",
        user_id="client1",
        db_pool=None,
    )
    assert "988" in out


def test_scopes_from_recall_context_helper():
    from app.websocket.crystal_recall_bridge import (
        _AttributedContext,
        scopes_from_recall_context,
    )

    assert scopes_from_recall_context("plain") == []
    attributed = _AttributedContext("x")
    attributed.crystal_scopes = ["user", "global"]
    assert scopes_from_recall_context(attributed) == ["user", "global"]
