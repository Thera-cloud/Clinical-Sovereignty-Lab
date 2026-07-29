"""Offline unit tests for Nate clinical coevolution (no DB/network)."""

from __future__ import annotations

import asyncio
import importlib.util
import os
import sys
import types

_SERVICES = os.path.join(os.path.dirname(__file__), "..", "app", "services")
_NS = os.path.join(_SERVICES, "night_school")


def _load(name: str, path: str):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


# Minimal package shells so relative app.services.* imports resolve without __init__ side effects
for pkg in ("app", "app.services", "app.services.night_school"):
    if pkg not in sys.modules:
        sys.modules[pkg] = types.ModuleType(pkg)

_flags = _load("app.services.nate_clinical_flags", os.path.join(_SERVICES, "nate_clinical_flags.py"))
_router = _load("app.services.nate_modality_router", os.path.join(_SERVICES, "nate_modality_router.py"))
_blinds = _load("app.services.live_stack_blinds", os.path.join(_SERVICES, "live_stack_blinds.py"))
_patient = _load(
    "app.services.nate_reactive_patient_sim",
    os.path.join(_SERVICES, "nate_reactive_patient_sim.py"),
)
_frozen = _load(
    "app.services.nate_clinical_frozen_packs",
    os.path.join(_SERVICES, "nate_clinical_frozen_packs.py"),
)
_adv = _load(
    "app.services.nate_adversarial_patient",
    os.path.join(_SERVICES, "nate_adversarial_patient.py"),
)
_fl = _load(
    "app.services.nate_clinical_fast_loop",
    os.path.join(_SERVICES, "nate_clinical_fast_loop.py"),
)
_bakeoff = _load(
    "app.services.nate_clinical_bakeoff_engine",
    os.path.join(_SERVICES, "nate_clinical_bakeoff_engine.py"),
)
_mod_sel = _load(
    "app.services.night_school.modality_selector",
    os.path.join(_NS, "modality_selector.py"),
)
_adaptive = _load(
    "little_nate_adaptive_ut_clin",
    os.path.join(_SERVICES, "little_nate_adaptive.py"),
)


def test_flags_default_off(monkeypatch):
    monkeypatch.delenv("ENABLE_NATE_CLINICAL_BAKEOFF", raising=False)
    monkeypatch.delenv("ENABLE_NATE_CLINICAL_FAST_LOOP", raising=False)
    assert _flags.bakeoff_enabled() is False
    assert _flags.fast_loop_enabled() is False
    assert _flags.auto_promote_enabled() is False
    assert _flags.min_preference_yield() == 0.30
    assert _flags.judge_kappa_floor() == 0.70
    assert _flags.agent_ready(None) is False
    assert _flags.agent_ready("init_failed") is False
    assert _flags.dpo_export_dir().endswith("nate_clinical_dpo")


def test_curriculum_escalate_gated(monkeypatch):
    monkeypatch.setenv("ENABLE_NATE_ADVERSARIAL_CURRICULUM", "false")
    assert _adv.maybe_escalate(0.9, 1) == 1
    monkeypatch.setenv("ENABLE_NATE_ADVERSARIAL_CURRICULUM", "true")
    assert _adv.maybe_escalate(0.9, 1) == 2


def test_modality_precedence_crisis():
    d = _router.route_modality("I want to kill myself tonight")
    assert d.source == "crisis"
    assert d.modality == "crisis_intervention"


def test_modality_framework_lens_before_router():
    profile = {
        "sensitive_clinical": {
            "v1_4_framework_lens_enabled": True,
            "selected_framework": "IFS",
        }
    }
    d = _router.route_modality("I feel stuck in a thought loop always", profile=profile)
    assert d.source == "framework_lens"
    assert "IFS" in d.modality


def test_fast_loop_noop_when_flag_off(monkeypatch):
    monkeypatch.setenv("ENABLE_NATE_CLINICAL_FAST_LOOP", "false")
    assert _fl.clinical_reflection_scratchpad({"user_text": "I feel stuck"}) is None


def test_fast_loop_shadow_empty_addendum(monkeypatch):
    monkeypatch.setenv("ENABLE_NATE_CLINICAL_FAST_LOOP", "true")
    monkeypatch.setenv("ENABLE_NATE_MODALITY_ROUTER", "true")
    monkeypatch.setenv("NATE_CLINICAL_FAST_LOOP_SHADOW", "true")
    d = _fl.clinical_reflection_scratchpad({"user_text": "nothing helps every time"})
    assert d is not None
    assert d["shadow"] is True
    assert d["addendum"] == ""


def test_preflight_rejects_identical_variants():
    v = {
        "prompt_pack": "same",
        "prompt_pack_hash": "abc",
        "crystal_index_scope": "clinical_global",
        "modality_router_on": False,
    }
    assert _bakeoff.preflight_variants(v, dict(v)) == "variants_identical"


def test_preflight_allows_router_diff():
    a = {
        "prompt_pack": "same",
        "prompt_pack_hash": "abc",
        "crystal_index_scope": "clinical_global",
        "modality_router_on": False,
    }
    b = dict(a)
    b["modality_router_on"] = True
    assert _bakeoff.preflight_variants(a, b) is None


def test_hard_gate_inversion():
    ok, reason = _bakeoff.hard_gate_trajectory(
        [
            {"role": "patient", "text": "hi"},
            {"role": "nate", "text": "I notice my body tightening when you speak"},
        ]
    )
    assert ok is False
    assert reason == "perspective_inversion"


def test_reactive_patient_conditions_on_nate():
    state = _patient.PatientState(level=2, persona="test")

    async def _run():
        r1 = await _patient.generate_patient_turn(state, "What emotions are coming up?")
        r2 = await _patient.generate_patient_turn(state, "Are you safe right now?")
        return r1, r2

    r1, r2 = asyncio.run(_run())
    assert len(r1) > 10 and len(r2) > 10


def test_mi_in_modality_keywords():
    assert "MI" in _mod_sel.MODALITY_KEYWORDS
    assert "ACT" in _mod_sel.MODALITY_KEYWORDS


def test_main_chat_adaptive_surface_intact():
    assert hasattr(_adaptive, "prepare_response")
    assert callable(_adaptive.prepare_response)
    assert hasattr(_blinds, "looks_like_perspective_inversion")
    assert _adv.curriculum_profile(3)["masked_crisis"] is True
    assert _frozen.format_frozen_context([]) == ""
