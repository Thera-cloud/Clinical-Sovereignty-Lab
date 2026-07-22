"""Offline unit tests for clinical technique directory (file-path import — avoid services __init__)."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

_MOD_PATH = (
    Path(__file__).resolve().parents[1]
    / "app"
    / "services"
    / "clinical_technique_directory.py"
)


def _load_mod():
    name = "clinical_technique_directory_under_test"
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, _MOD_PATH)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(autouse=True)
def _enable_directory(monkeypatch):
    monkeypatch.setenv("ENABLE_CLINICAL_TECHNIQUE_DIRECTORY", "true")
    monkeypatch.setenv("ENABLE_CLINICAL_DIRECTORY_WEB_ENRICH", "false")
    mod = _load_mod()
    mod.load_directory.cache_clear()
    yield mod
    mod.load_directory.cache_clear()


def test_load_directory_has_seed_volume(_enable_directory):
    mod = _enable_directory
    data = mod.load_directory()
    assert len(data.get("modalities") or []) >= 20
    assert len(data.get("techniques") or []) >= 70
    assert len(data.get("plan_templates") or []) >= 12


def test_search_techniques_cbt(_enable_directory):
    mod = _enable_directory
    hits = mod.search_techniques("help me with a CBT thought record for anxiety")
    assert hits
    assert any("cbt" in str(h.get("modality_id")) for h in hits)


def test_match_plan_anxiety(_enable_directory):
    mod = _enable_directory
    plan = mod.match_plan_template("I need a treatment plan for my anxiety and worry")
    assert plan is not None
    assert "anxiety" in (plan.get("id") or "") or "anxiety" in (plan.get("title") or "").lower()


def test_care_plan_request_detect(_enable_directory):
    mod = _enable_directory
    assert mod.is_care_plan_request("Can you make me a mental health care plan?")
    assert mod.is_care_plan_request("I want to switch my treatment plan")
    assert not mod.is_care_plan_request("how was your day")


def test_build_directory_context_includes_plan(_enable_directory):
    mod = _enable_directory
    ctx = mod.build_directory_context("Please build a care plan for panic and anxiety")
    assert "CARE PLAN TEMPLATE" in ctx or "CLINICAL" in ctx
    assert "DISCLAIMER" in ctx or "directory" in ctx.lower()


def test_switch_protocol_present(_enable_directory):
    mod = _enable_directory
    assert "PLAN SWITCH PROTOCOL" in mod.format_switch_protocol()
    ctx = mod.build_directory_context("I want to switch my plan to something for depression")
    assert "SWITCH" in ctx.upper() or "depression" in ctx.lower()


def test_plan_template_to_steps(_enable_directory):
    mod = _enable_directory
    plan = mod.match_plan_template("depression no energy behavioral activation")
    steps = mod.plan_template_to_step_definitions(plan)
    assert len(steps) >= 3
    assert steps[0].get("technique_ids")


def test_disabled_returns_empty(monkeypatch):
    monkeypatch.setenv("ENABLE_CLINICAL_TECHNIQUE_DIRECTORY", "false")
    mod = _load_mod()
    mod.load_directory.cache_clear()
    assert mod.build_directory_context("care plan for anxiety") == ""
