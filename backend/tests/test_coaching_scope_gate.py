"""Tests for Coaching Scope Gate (Phase 1) and related adaptive changes.

Covers:
- Tier 6 multi-topic clinical opening detection
- Scope lock continuation
- Scope unlock via topic shift
- Single-topic passthrough (no gate)
- Dissatisfaction pushback patterns (Gap 9)
- Neurodivergent masking co-occurrence (Gap 13)
- SessionState scope fields
"""

import os
import sys
import importlib
import types
import pytest

# Ensure the backend dir is on the path but avoid pulling in
# app.services.__init__ which triggers heavy transitive imports (numpy etc.).
_backend = os.path.join(os.path.dirname(__file__), "..")
if _backend not in sys.path:
    sys.path.insert(0, _backend)

# ============================================================
# Scope gate unit tests — load via importlib to skip heavy __init__
# ============================================================

_sg_spec = importlib.util.spec_from_file_location(
    "little_nate_coaching_scope_gate",
    os.path.join(_backend, "app", "services", "little_nate_coaching_scope_gate.py"),
)
_sg_mod = importlib.util.module_from_spec(_sg_spec)
_sg_spec.loader.exec_module(_sg_mod)

evaluate_scope_gate = _sg_mod.evaluate_scope_gate
_detect_topic_groups = _sg_mod._detect_topic_groups
_detect_topic_shift = _sg_mod._detect_topic_shift
_detect_continuation = _sg_mod._detect_continuation
STABILIZATION_RESPONSE = _sg_mod.STABILIZATION_RESPONSE
K_MAX_TURN = _sg_mod.K_MAX_TURN
N_MIN_GROUPS = _sg_mod.N_MIN_GROUPS


class TestTopicDetection:
    def test_marital_keyword(self):
        groups = _detect_topic_groups("My wife and I are struggling with intimacy.")
        assert "marital_intimate" in groups

    def test_grief_keyword(self):
        groups = _detect_topic_groups("I've been grieving since her death last year.")
        assert "grief_loss" in groups

    def test_multiple_groups_single_message(self):
        msg = (
            "My wife rejected me, I feel like a failure, my faith is shaken, "
            "and I was abused as a child."
        )
        groups = _detect_topic_groups(msg)
        assert len(groups) >= 4
        assert "marital_intimate" in groups
        assert "shame_worthlessness" in groups
        assert "faith_spiritual" in groups
        assert "trauma_abuse" in groups

    def test_no_clinical_content(self):
        groups = _detect_topic_groups("What a beautiful day for a walk.")
        assert groups == []

    def test_work_financial(self):
        groups = _detect_topic_groups("I was fired last week and I'm drowning in debt.")
        assert "work_financial" in groups

    def test_suicidal_self_harm(self):
        groups = _detect_topic_groups("I don't want to be alive anymore.")
        assert "suicidal_self_harm" in groups


class TestTopicShiftDetection:
    def test_explicit_shift(self):
        assert _detect_topic_shift("Let's talk about something else.")

    def test_focus_request(self):
        assert _detect_topic_shift("Can we focus on my marriage only?")

    def test_no_shift(self):
        assert not _detect_topic_shift("I've been feeling really down.")


class TestContinuationDetection:
    def test_and_also(self):
        assert _detect_continuation("And also, there's the grief I haven't dealt with.")

    def test_another_thing(self):
        assert _detect_continuation("Another thing I want to bring up...")

    def test_no_continuation(self):
        assert not _detect_continuation("I feel sad today.")


class TestScopeGateEvaluator:
    """Core evaluator logic."""

    def test_magicguy72_opening_fires(self):
        """Dense 5-group opening on turn 1 => stabilization."""
        msg = (
            "My wife and I have struggled with intimacy and rejection for 30 years. "
            "I feel like there's something wrong with me. My faith is shaken. "
            "I've been carrying this shame since childhood abuse."
        )
        result = evaluate_scope_gate(
            turn_count=1, user_msg=msg, scope_topics_active=(), scope_lock_since_turn=None,
        )
        assert result.direct_response == STABILIZATION_RESPONSE
        assert result.group_count >= 4
        assert "multi_topic_clinical_opening" in result.telemetry_labels

    def test_single_topic_no_gate(self):
        """Single-topic message on turn 1 => no gate."""
        msg = "My boss is impossible and I'm thinking about quitting."
        result = evaluate_scope_gate(
            turn_count=1, user_msg=msg, scope_topics_active=(), scope_lock_since_turn=None,
        )
        assert result.direct_response is None
        assert result.group_count <= 2

    def test_beyond_k_turns_no_gate(self):
        """Even dense content after K turns does not fire Tier 6."""
        msg = (
            "My wife left, I'm grieving, my identity is shattered, "
            "I feel worthless, and I was abused."
        )
        result = evaluate_scope_gate(
            turn_count=K_MAX_TURN + 1,
            user_msg=msg,
            scope_topics_active=(),
            scope_lock_since_turn=None,
        )
        assert result.direct_response is None

    def test_continuation_while_locked(self):
        """After gate fires, continuation clinical content re-fires."""
        locked_topics = ("marital_intimate", "grief_loss", "faith_spiritual", "shame_worthlessness")
        msg = "And also I've been drinking a lot lately."
        result = evaluate_scope_gate(
            turn_count=2,
            user_msg=msg,
            scope_topics_active=locked_topics,
            scope_lock_since_turn=1,
        )
        assert result.direct_response == STABILIZATION_RESPONSE
        assert "scope_gate_continuation" in result.telemetry_labels

    def test_unlock_via_topic_shift(self):
        """Explicit topic shift unlocks the scope gate."""
        locked_topics = ("marital_intimate", "grief_loss", "faith_spiritual", "shame_worthlessness")
        msg = "Let's talk about something else — I want to focus on my marriage only."
        result = evaluate_scope_gate(
            turn_count=3,
            user_msg=msg,
            scope_topics_active=locked_topics,
            scope_lock_since_turn=1,
        )
        assert result.unlocked is True
        assert result.direct_response is None
        assert "scope_unlocked_topic_shift" in result.telemetry_labels

    def test_locked_nonclinical_passthrough(self):
        """When locked, non-clinical messages pass through without gate."""
        locked_topics = ("marital_intimate", "grief_loss", "faith_spiritual", "shame_worthlessness")
        msg = "The weather is nice today."
        result = evaluate_scope_gate(
            turn_count=3,
            user_msg=msg,
            scope_topics_active=locked_topics,
            scope_lock_since_turn=1,
        )
        assert result.direct_response is None

    def test_accumulation_across_turns(self):
        """Topics accumulate across first K turns."""
        # Turn 1: 2 groups
        r1 = evaluate_scope_gate(1, "My wife left me and I'm grieving.", (), None)
        assert r1.direct_response is None
        topics = r1.scope_locked_topics

        # Turn 2: 2 more groups => 4 total, triggers gate
        r2 = evaluate_scope_gate(
            2,
            "My faith is shattered and I feel like a worthless failure.",
            topics, None,
        )
        assert r2.direct_response == STABILIZATION_RESPONSE
        assert len(r2.scope_locked_topics) >= N_MIN_GROUPS


# ============================================================
# Dissatisfaction pushback patterns (Gap 9)
# ============================================================

_adaptive_spec = importlib.util.spec_from_file_location(
    "little_nate_adaptive",
    os.path.join(_backend, "app", "services", "little_nate_adaptive.py"),
)
_adaptive_mod = importlib.util.module_from_spec(_adaptive_spec)
_adaptive_spec.loader.exec_module(_adaptive_mod)

DISSATISFACTION_PHRASES = _adaptive_mod.DISSATISFACTION_PHRASES
import re


class TestDissatisfactionPushback:
    def _match_any(self, text: str) -> bool:
        return any(re.search(p, text, re.IGNORECASE) for p in DISSATISFACTION_PHRASES)

    def test_already_do_that(self):
        assert self._match_any("I already do that and it doesn't change anything.")

    def test_tried_that(self):
        assert self._match_any("Yeah I tried that.")

    def test_doesnt_help(self):
        assert self._match_any("That doesn't help me.")

    def test_tell_me_something_new(self):
        assert self._match_any("Tell me something new, that's the same advice.")

    def test_already_tried(self):
        assert self._match_any("I've already tried everything you're suggesting.")

    def test_ive_done_that(self):
        assert self._match_any("I've done that before, it didn't work.")


# ============================================================
# Neurodivergent co-occurrence masking (Gap 13)
# ============================================================

detect_neurodivergent = _adaptive_mod.detect_neurodivergent
SessionState = _adaptive_mod.SessionState


class TestNeurodivergentCoOccurrence:
    def test_masking_alone_does_not_fire(self):
        """Single masking pattern without load should NOT fire (Gap 13)."""
        state = SessionState()
        fired, should_lock = detect_neurodivergent(state, "Everyone else seems to get it.")
        assert not fired

    def test_self_id_fires_alone(self):
        """Self-identification fires by itself."""
        state = SessionState()
        fired, should_lock = detect_neurodivergent(state, "I have ADHD and it makes everything harder.")
        assert fired
        assert should_lock

    def test_masking_plus_load_fires(self):
        """Masking + load co-occurrence fires."""
        state = SessionState()
        msg = "Everyone else seems to get it and there's too much information coming at me."
        fired, should_lock = detect_neurodivergent(state, msg)
        assert fired


# ============================================================
# SessionState scope fields
# ============================================================


class TestSessionStateScopeFields:
    def test_default_scope_empty(self):
        state = SessionState()
        assert state.scope_topics_active == ()
        assert state.scope_lock_since_turn is None

    def test_scope_fields_mutable(self):
        state = SessionState()
        state.scope_topics_active = ("grief_loss", "trauma_abuse")
        state.scope_lock_since_turn = 2
        assert len(state.scope_topics_active) == 2
        assert state.scope_lock_since_turn == 2
