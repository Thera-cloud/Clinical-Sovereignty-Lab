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


def test_accept_advance_decline_patterns():
    assert csp._ACCEPT_RE.search("yeah let's try that")
    assert csp._ACCEPT_RE.search("I'll practice this week")
    assert csp._ADVANCE_RE.search("I practiced the STOP skill today")
    assert csp._ADVANCE_RE.search("I finished step one")
    assert csp._DECLINE_RE.search("not now thanks")
    assert not csp._ACCEPT_RE.search("I feel sad about my mother")


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
    assert "hot thought" in block.lower()
    assert "FORBIDDEN" in block
    assert "5-4-3-2-1" in block  # named as forbidden attractor


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
