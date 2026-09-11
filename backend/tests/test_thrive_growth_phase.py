"""Growth-Phase Architecture v1 — offline unit tests (no DB, no network).

# QUANTUM-CRYSTAL-ARCH
Covers: phase model, boundary-guard phase gating (LetsGoLisa regression),
healing-cycle language scorer, persona addendum, strengths interview, and
the thrive crystal domain registration.
"""

from __future__ import annotations

import os

os.environ.setdefault("JWT_SECRET", "testsecret")

from app.services import coaching_boundary_guard as guard
from app.services.crystal_domains import normalize_domain
from app.services.thrive import growth_phase as gp
from app.services.thrive import healing_cycle as hc
from app.services.thrive import persona
from app.services.thrive import practice_catalog as pc
from app.services.thrive import strengths_interview as si
from app.services.thrive.practice_tracker import detect_completion


# ── phase model ────────────────────────────────────────────────────────────

def test_phase_order_and_sets():
    assert list(gp.PHASES) == ["stabilize", "process", "consolidate", "thrive", "generative"]
    assert gp.is_coaching_phase("thrive") and gp.is_coaching_phase("generative")
    assert not gp.is_coaching_phase("process")
    assert gp.is_consolidating("consolidate")


def test_sub_state_collapses_to_process():
    assert gp.effective_phase("thrive", "working_through") == "process"
    assert gp.effective_phase("generative", "crisis_hold") == "stabilize"
    assert gp.effective_phase("thrive", None) == "thrive"
    assert not gp.is_coaching_phase("thrive", "working_through")


def test_framework_map_shifts_time_focus_and_questions():
    heal = gp.framework_for("process")
    grow = gp.framework_for("thrive")
    assert heal.time_focus != grow.time_focus
    assert any("build" in q.lower() for q in grow.core_questions)
    assert grow.ptg and grow.antifragile
    assert gp.framework_for("bogus").phase == gp.DEFAULT_PHASE


# ── boundary guard — LetsGoLisa regression ─────────────────────────────────

def test_guard_does_not_trip_on_celebrated_healing_in_thrive():
    text = "I used to carry so much childhood trauma but I've healed — I'm proud of how far I've come."
    r = guard.evaluate(text, growth_phase="thrive", growth_sub_state=None)
    assert not r.tripped, r


def test_guard_still_trips_crisis_in_any_phase():
    r = guard.evaluate("I don't want to be alive anymore, I have a plan to end it tonight",
                       growth_phase="generative", growth_sub_state=None)
    assert r.tripped and r.trip_class == "CRISIS"


def test_guard_respects_working_through_sub_state():
    text = "I need to work through the abuse from my father, it's still raw and I'm shaking"
    r_thrive = guard.evaluate(text, growth_phase="thrive", growth_sub_state="working_through")
    r_process = guard.evaluate(text, growth_phase="process", growth_sub_state=None)
    assert r_thrive.tripped == r_process.tripped


# ── healing-cycle language scorer ──────────────────────────────────────────

def test_language_score_forward_beats_wound():
    forward = [
        "I'm building my business now and it feels good",
        "I finished the course I started last month",
        "I used to spiral but that pattern is behind me",
        "I want to set a goal for this quarter",
        "Feeling steady and looking ahead",
    ]
    wound = [
        "I can't stop crying about what he did to me",
        "I need to work through this, it's still raw",
        "the flashbacks are back every night",
        "I feel worthless and ashamed again",
    ]
    f = hc.score_language(forward)
    w = hc.score_language(wound)
    assert f and w and f["score"] > w["score"]
    assert hc.score_language(["short"]) is None


def test_compose_handles_missing_components():
    sig = hc.compose({"language": {"score": 0.8}, "coherence": None})
    assert sig.score is not None and "language" in sig.available
    assert hc.compose({}).score is None


# ── persona addendum ───────────────────────────────────────────────────────

def test_addendum_empty_outside_flagged_phases_or_carries_phase_header():
    out = persona.build_phase_addendum("thrive", None, {"areas": [], "goals": [], "strengths": []}, display_name="Lisa")
    assert "[GROWTH PHASE:" in out and len(out) <= persona._MAX_CHARS
    held = persona.build_phase_addendum("thrive", "working_through", None, display_name="Lisa")
    assert "PROCESS" in held.upper() or "WORK" in held.upper()


def test_focus_lines_render_memory_and_interview():
    lines = persona._focus_lines({
        "areas": [{"key": "daily_happiness", "streak": 3, "due": True}],
        "goals": [{"title": "Run a 5k", "status": "active", "target_date": "2026-10-01"}],
        "strengths": [],
        "thrive_memory": ["Goal completed: launched the shop (in 40 days)"],
        "has_signature": False,
        "strengths_answers": {"asked": 1, "observed": {"perseverance": 2}},
    })
    joined = "\n".join(lines)
    assert "Three Good Things" in joined and "Run a 5k" in joined
    assert "Growth memory" in joined and "launched the shop" in joined
    assert "STRENGTHS INTERVIEW" in joined and "Perseverance" in joined


def test_focus_lines_skip_interview_when_signature_exists():
    lines = persona._focus_lines({"areas": [], "goals": [], "strengths": ["honesty"], "has_signature": True})
    assert not any("STRENGTHS INTERVIEW" in l for l in lines)
    assert any("honesty" in l for l in lines)


# ── practice catalog / completion detection ────────────────────────────────

def test_four_focus_areas_have_anchor_practices():
    for key, fa in pc.FOCUS_AREAS.items():
        assert fa.anchor_practice in pc.PRACTICES, key
    assert {"daily_happiness", "future_direction", "self_compassion_confidence", "handling_stress"} <= set(pc.FOCUS_AREAS)


def test_detect_completion_reads_report():
    k = detect_completion("I did my three good things last night before bed and it helped")
    assert k is not None and k in pc.PRACTICES
    assert detect_completion("hi") is None


# ── strengths interview (in-house, free) ───────────────────────────────────

def test_strengths_catalogue_is_24_with_clifton_rollup():
    assert len(si.STRENGTHS) == 24
    assert set(si.CLIFTON_DOMAINS) == {"executing", "influencing", "relationship_building", "strategic_thinking"}
    assert si.clifton_rollup(["perseverance", "kindness", "curiosity"])[0] in si.CLIFTON_DOMAINS


def test_detect_requires_first_person_claim():
    assert "perseverance" in si.detect_strength_mentions("I'm known for sticking with things even when they get hard")
    assert si.detect_strength_mentions("my friend is very kind") == []
    assert si.detect_strength_mentions("kind") == []


def test_interview_lines_one_question_at_a_time():
    lines = si.interview_lines({"asked": 2, "observed": {}}, has_signature=False)
    assert sum(1 for l in lines if "next question" in l) == 1
    assert si.interview_lines({}, has_signature=True) == []


# ── crystal domain ─────────────────────────────────────────────────────────

def test_thrive_is_valid_crystal_domain():
    assert normalize_domain("thrive") == "thrive"
    assert si.THRIVE_DOMAIN == "thrive"
