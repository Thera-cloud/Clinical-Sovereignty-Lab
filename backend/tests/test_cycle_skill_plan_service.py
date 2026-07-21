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
