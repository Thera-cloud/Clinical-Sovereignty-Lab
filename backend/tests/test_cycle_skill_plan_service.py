"""Offline tests for cycle → stacked skill plan orchestrator."""

from __future__ import annotations

import importlib.util
import os
from pathlib import Path

import pytest

_PATH = (
    Path(__file__).resolve().parents[1]
    / "app"
    / "services"
    / "cycle_skill_plan_service.py"
)
_spec = importlib.util.spec_from_file_location("cycle_skill_plan_service", _PATH)
csp = importlib.util.module_from_spec(_spec)
assert _spec and _spec.loader
_spec.loader.exec_module(csp)


def test_flag_default_off(monkeypatch):
    monkeypatch.delenv("ENABLE_CYCLE_SKILL_PLANS", raising=False)
    assert csp.cycle_skill_plans_enabled() is False
    monkeypatch.setenv("ENABLE_CYCLE_SKILL_PLANS", "true")
    assert csp.cycle_skill_plans_enabled() is True


def test_skill_emails_follow_plans_flag(monkeypatch):
    monkeypatch.delenv("CYCLE_SKILL_EMAILS", raising=False)
    monkeypatch.setenv("ENABLE_CYCLE_SKILL_PLANS", "false")
    monkeypatch.setenv("ENABLE_THERAPEUTIC_PLANS", "false")
    assert csp.cycle_skill_emails_enabled() is False
    monkeypatch.setenv("ENABLE_CYCLE_SKILL_PLANS", "true")
    assert csp.cycle_skill_emails_enabled() is True
    monkeypatch.setenv("ENABLE_CYCLE_SKILL_PLANS", "false")
    monkeypatch.setenv("ENABLE_THERAPEUTIC_PLANS", "true")
    assert csp.cycle_skill_emails_enabled() is True
    monkeypatch.setenv("CYCLE_SKILL_EMAILS", "false")
    assert csp.cycle_skill_emails_enabled() is False


def test_skill_plan_email_copy_covers_lifecycle():
    plan = {
        "title": "Ground & settle",
        "modality": "grounding",
        "current_step": 1,
        "total_steps": 3,
        "step_definitions": [
            {
                "step_number": 1,
                "theme": "Feet on floor",
                "practice": "Name 5 things you see",
                "check_in": "What shifted in your body?",
            }
        ],
    }
    for event in ("suggested", "activated", "advanced", "checkin_due", "completed"):
        subject, html = csp.build_skill_plan_email_copy(
            event=event, name="Alex", plan=plan
        )
        assert "Alex" in subject
        assert "Ground & settle" in html or "skills" in html.lower()
        assert "Open Sanctuary" in html


def test_coach_skill_emails_follow_plans_flag(monkeypatch):
    monkeypatch.delenv("CYCLE_SKILL_COACH_EMAILS", raising=False)
    monkeypatch.setenv("ENABLE_CYCLE_SKILL_PLANS", "true")
    assert csp.cycle_skill_coach_emails_enabled() is True
    monkeypatch.setenv("CYCLE_SKILL_COACH_EMAILS", "false")
    assert csp.cycle_skill_coach_emails_enabled() is False


def test_coach_skill_plan_copy_covers_lifecycle():
    plan = {
        "title": "Ground & settle",
        "modality": "grounding",
        "cycle_domain": "emotional_state",
        "current_step": 2,
        "total_steps": 3,
    }
    for event in (
        "suggested",
        "activated",
        "advanced",
        "checkin_due",
        "completed",
        "declined",
    ):
        subject, body = csp.build_coach_skill_plan_copy(
            event=event,
            client_name="Alex",
            client_username="client1",
            plan=plan,
        )
        assert "Alex" in subject or "client1" in subject
        assert "Ground & settle" in body or "practice" in body.lower()
        assert "Coach Portal" in body


def test_domain_maps_to_modality_templates():
    assert "emotional_state" in csp._DOMAIN_TEMPLATE
    assert "addiction" in csp._DOMAIN_TEMPLATE
    assert "financial" in csp._DOMAIN_TEMPLATE
    tpl, mod, nxt = csp._DOMAIN_TEMPLATE["emotional_state"]
    assert mod == "grounding"
    assert tpl == csp._TPL_GROUND
    assert nxt == csp._TPL_DBT  # stacks to DBT after ground/mindful
    assert csp._DOMAIN_TEMPLATE["coping"][0] == csp._TPL_GROUND
    assert "harm_risk" not in csp._DOMAIN_TEMPLATE
    assert "harm_risk" in csp._SKIP_AUTO_DOMAINS


def test_advance_recognizes_grounding_practice():
    assert csp._ADVANCE_RE.search("I practiced the grounding exercise")
    assert csp._ADVANCE_RE.search("I did the 5-4-3-2-1")
    assert csp._ADVANCE_RE.search("I finished the mindful step")
    assert csp._client_advances_plan(
        "Things seen: crystals.\nthings felt: stones under my feet."
    )
    assert csp._client_advances_plan("things heard: dawn song\nthings smelt: earth")


def test_pending_stack_from_log_and_cooldown_constant():
    assert csp._STACK_COOLDOWN_HOURS >= 1
    log = [
        {"event": "completed", "at": "2026-07-23T00:00:00+00:00"},
        {
            "event": "pending_stack",
            "template_id": csp._TPL_DBT,
            "offer_after": "2026-07-25T00:00:00+00:00",
        },
    ]
    pending = csp._pending_stack_from_log(log)
    assert pending and pending["template_id"] == csp._TPL_DBT
    assert csp._pending_stack_from_log([]) is None
    assert csp._pending_stack_from_log(None) is None


def test_accept_advance_decline_patterns():
    assert csp._client_accepts_plan("yeah let's try that")
    assert csp._client_accepts_plan("I'll practice this week")
    assert csp._client_advances_plan("I practiced the STOP skill today")
    assert csp._client_advances_plan("I finished the grounding step")
    assert csp._DECLINE_RE.search("not now thanks")
    assert not csp._client_accepts_plan("I feel sad about my mother")
    # LetsGoBill false-accept regression: "not sure" must never activate
    assert not csp._client_accepts_plan(
        "I'm not sure why you would ask that?"
    )
    assert not csp._client_accepts_plan("not sure")
    assert csp._client_accepts_plan("sure, let's try")
    assert csp._client_accepts_plan("yes I'm in")
    assert csp._client_accepts_plan("yes")
    assert not csp._client_accepts_plan(
        "Lil Nate I think you are glitching. Should you contact Big Nate?"
    )
    # Soft-ack / story FPs must not activate
    for bad in (
        "OK so my wife left",
        "okay then I cried",
        "alright I hear you but no",
        "why not just leave me alone",
        "that works for some people but not me",
        "sounds good in theory but",
        "I'm in a bad place",
        "I'll try to sleep",
        "start that car",
    ):
        assert not csp._client_accepts_plan(bad), bad
    # Advance FPs: everyday past tense must not advance
    for bad in (
        "I tried to call my mom",
        "I used to drink",
        "it helped that she left",
        "I finished my coffee",
        "I did not mean that",
    ):
        assert not csp._client_advances_plan(bad), bad
    assert csp._DECLINE_RE.search("no")
    assert csp._DECLINE_RE.search("no thanks")
    # Mid-story "no" must not false-decline
    assert not csp._DECLINE_RE.search("I said no to the promotion at work")


def test_step_payload_extracts_practice():
    steps = [
        {"step_number": 1, "theme": "Name the wave", "practice": "Use STOP"},
        {"step_number": 2, "theme": "Body first", "practice": "TIPP"},
    ]
    assert csp._step_payload(steps, 2)["practice"] == "TIPP"
    assert csp._step_payload(steps, 9) == {}


@pytest.mark.asyncio
async def test_build_context_empty_when_flag_off(monkeypatch):
    monkeypatch.setenv("ENABLE_CYCLE_SKILL_PLANS", "false")
    out = await csp.build_cycle_skill_plan_context(None, "user1")
    assert out == ""


@pytest.mark.asyncio
async def test_tick_noop_when_flag_off(monkeypatch):
    monkeypatch.setenv("ENABLE_CYCLE_SKILL_PLANS", "false")
    out = await csp.maybe_tick_cycle_skill_plan(
        object(), user_id="u1", user_text="yes let's try"
    )
    assert out["action"] == "noop"


def test_fidelity_directive_locks_cbt_not_grounding():
    block = csp.build_fidelity_directive(
        modality="CBT",
        status="suggested",
        title="Thought check practice (CBT-informed)",
        theme="Catch the automatic thought",
        practice="Catch one hot thought: write situation + the automatic thought.",
        skill="thought_record",
        step_num=1,
        total_steps=3,
    )
    assert "SKILL FIDELITY LOCK (CBT)" in block
    assert "OPTIONAL OFFER" in block
    assert "stated need" in block.lower() or "WHAT THEY SAID" in block
    assert "hot thought" in block.lower()
    assert "FORBIDDEN" in block
    assert "5-4-3-2-1" in block  # named as forbidden attractor
    active = csp.build_fidelity_directive(
        modality="CBT",
        status="active",
        title="Thought check",
        theme="Catch",
        practice="Catch one hot thought.",
        skill="thought_record",
        step_num=1,
        total_steps=3,
    )
    assert "AGREED PRACTICE" in active
    assert "current need" in active.lower()


def test_score_skill_offer_fidelity_penalizes_grounding_for_cbt():
    bad = (
        "Would a simple grounding practice help, something like noticing "
        "your feet on the ground? Let's try 5-4-3-2-1."
    )
    good = (
        "If you want, we can catch one hot thought: write the situation and "
        "the automatic thought in one sentence — no fixing yet."
    )
    assert csp.score_skill_offer_fidelity(bad, modality="CBT") <= 2
    assert csp.score_skill_offer_fidelity(good, modality="CBT") >= 4
    dbt = (
        "Let's try the STOP skill: Stop, take a step back, observe your body "
        "and urges without acting, then proceed mindfully."
    )
    assert csp.score_skill_offer_fidelity(dbt, modality="DBT") >= 4
    act = (
        'Would you like to try defusion? Say once: "I notice I am having the '
        'thought that…" and finish the sentence.'
    )
    assert csp.score_skill_offer_fidelity(act, modality="ACT") >= 4


def test_score_grounding_offer_high_when_on_modality():
    text = (
        "Optional 5-4-3-2-1: name 5 things you see, 4 you feel, 3 you hear, "
        "2 you smell, 1 taste."
    )
    assert (
        csp.score_skill_offer_fidelity(
            text, modality="grounding", skill="5_4_3_2_1", practice="5-4-3-2-1"
        )
        >= 4
    )


def test_compose_skill_teach_block_includes_practice():
    block = csp.compose_skill_teach_block(
        modality="CBT",
        skill="thought_record",
        practice="Catch one hot thought in one sentence.",
        accepting=True,
    )
    assert "hot thought" in block.lower()
    assert "CBT" in block or "cbt" in block.lower()


@pytest.mark.asyncio
async def test_build_family_skill_plan_context_empty(monkeypatch):
    monkeypatch.setenv("ENABLE_CYCLE_SKILL_PLANS", "true")
    assert await csp.build_family_skill_plan_context(None, []) == ""
    assert await csp.build_family_skill_plan_context(None, [{"name": "A"}]) == ""


def test_schedule_skill_plan_post_turn_noop_when_disabled(monkeypatch):
    monkeypatch.setenv("ENABLE_CYCLE_SKILL_PLANS", "false")
    csp.schedule_skill_plan_post_turn(
        object(),
        user_id="u1",
        user_text="hello",
        nate_response="hi",
        origin_surface="bridge_chat",
    )
    csp.schedule_skill_plan_post_turn_with_ws(
        object(),
        sockets={},
        uid="u1",
        user_id="u1",
        user_text="hello",
        nate_response="hi",
    )


@pytest.mark.asyncio
async def test_fidelity_guard_appends_teach_when_off_modality(monkeypatch):
    monkeypatch.setenv("ENABLE_CYCLE_SKILL_PLANS", "true")

    class _Conn:
        async def fetchrow(self, *a, **k):
            return {
                "id": "p1",
                "title": "Thought check",
                "total_steps": 3,
                "current_step": 1,
                "step_definitions": [
                    {
                        "step_number": 1,
                        "skill": "thought_record",
                        "modality": "CBT",
                        "theme": "Catch",
                        "practice": "Catch one hot thought in one sentence.",
                    }
                ],
                "status": "suggested",
                "source": "cycle_skill",
                "cycle_domain": "financial",
                "modality": "CBT",
                "parent_plan_id": None,
                "next_checkin_at": None,
            }

        async def fetchval(self, *a, **k):
            return None

        async def fetch(self, *a, **k):
            return []

        async def execute(self, *a, **k):
            return None

    class _Pool:
        class _Ctx:
            def __init__(self, c):
                self.c = c

            async def __aenter__(self):
                return self.c

            async def __aexit__(self, *a):
                return False

        def acquire(self):
            return _Pool._Ctx(_Conn())

    bad = (
        "Would a simple grounding practice help, noticing your feet on the ground? "
        "Let's try 5-4-3-2-1."
    )
    out = await csp.apply_skill_fidelity_guard(
        _Pool(), "client1", "yes let's try", bad
    )
    assert "hot thought" in out.lower()
    assert csp.score_skill_offer_fidelity(out, modality="CBT") >= 4

    # Suggested + no accept: never append practice (topic takeover guard)
    out_noop = await csp.apply_skill_fidelity_guard(
        _Pool(), "client1", "OK so my wife left", bad
    )
    assert out_noop == bad
    out_meta = await csp.apply_skill_fidelity_guard(
        _Pool(),
        "client1",
        "the picture of me looks like a female",
        bad,
    )
    assert out_meta == bad
    # Suggested + practice evidence: do not append next-step teach
    out_adv = await csp.apply_skill_fidelity_guard(
        _Pool(),
        "client1",
        "things seen: lamp\nthings felt: chair\nthings heard: fan",
        "Thanks for sharing that inventory.",
    )
    assert "For the next step" not in out_adv


@pytest.mark.asyncio
async def test_augment_recall_only_when_active(monkeypatch):
    monkeypatch.setenv("ENABLE_CYCLE_SKILL_PLANS", "true")

    class _Conn:
        def __init__(self, status):
            self.status = status

        async def fetchrow(self, *a, **k):
            return {
                "id": "p1",
                "title": "Thought check",
                "total_steps": 3,
                "current_step": 1,
                "step_definitions": [
                    {
                        "step_number": 1,
                        "skill": "thought_record",
                        "modality": "CBT",
                        "theme": "Catch",
                        "practice": "Catch one hot thought in one sentence.",
                    }
                ],
                "status": self.status,
                "source": "cycle_skill",
                "cycle_domain": "financial",
                "modality": "CBT",
                "parent_plan_id": None,
                "next_checkin_at": None,
            }

        async def fetchval(self, *a, **k):
            return None

    class _Pool:
        def __init__(self, status):
            self.status = status

        class _Ctx:
            def __init__(self, c):
                self.c = c

            async def __aenter__(self):
                return self.c

            async def __aexit__(self, *a):
                return False

        def acquire(self):
            return _Pool._Ctx(_Conn(self.status))

    q = await csp.augment_recall_query_for_skill_plan(
        _Pool("suggested"), "client1", "my wife left"
    )
    assert q == "my wife left"
    assert "hot thought" not in q.lower()
    q2 = await csp.augment_recall_query_for_skill_plan(
        _Pool("active"), "client1", "my wife left"
    )
    assert "thought record" in q2.lower() or "CBT" in q2
    assert "hot thought" not in q2.lower()
