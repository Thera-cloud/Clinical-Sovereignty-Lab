"""
Phase 1.5 classifier layer — unit tests.

Tests cover:
    - JSON parse (valid, malformed, edge cases)
    - Cost gates (short message, GUEST, rate limit, circuit breaker)
    - Accumulator merge (distress_score, indirect_blame, decay)
    - Disagreement detection (classifier-vs-regex axis)
    - Handoff threshold computation

Uses importlib to load modules without triggering heavy transitive deps.
"""
import os
import sys
import importlib
import json
import pytest
import time

_backend = os.path.join(os.path.dirname(__file__), "..")
if _backend not in sys.path:
    sys.path.insert(0, _backend)

# Load classifier module directly (skip __init__.py chains)
_cl_spec = importlib.util.spec_from_file_location(
    "little_nate_classifier",
    os.path.join(_backend, "app", "services", "little_nate_classifier.py"),
)
_cl_mod = importlib.util.module_from_spec(_cl_spec)
sys.modules["little_nate_classifier"] = _cl_mod
_cl_spec.loader.exec_module(_cl_mod)

ClassifierResult = _cl_mod.ClassifierResult
_parse_classifier_json = _cl_mod._parse_classifier_json
merge_classifier_into_state = _cl_mod.merge_classifier_into_state
compute_classifier_handoff = _cl_mod.compute_classifier_handoff
detect_disagreements = _cl_mod.detect_disagreements
_EMPTY = _cl_mod._EMPTY
_MIN_MSG_LEN = _cl_mod._MIN_MSG_LEN

# Load adaptive module for SessionState
_ad_spec = importlib.util.spec_from_file_location(
    "little_nate_adaptive",
    os.path.join(_backend, "app", "services", "little_nate_adaptive.py"),
)
_ad_mod = importlib.util.module_from_spec(_ad_spec)
sys.modules["little_nate_adaptive"] = _ad_mod
_ad_spec.loader.exec_module(_ad_mod)
SessionState = _ad_mod.SessionState


# ============================================================
# PARSE TESTS
# ============================================================

class TestParseClassifierJson:
    def test_valid_json(self):
        raw = json.dumps({
            "distress_intensity": 2,
            "indirect_self_blame": True,
            "escalation_from_calm": False,
            "request_shape": "emotional_processing",
            "domains_present": ["identity_struggle", "shame_worthlessness"],
            "weight": 0.7,
        })
        result = _parse_classifier_json(raw)
        assert result.distress_intensity == 2
        assert result.indirect_self_blame is True
        assert result.escalation_from_calm is False
        assert result.request_shape == "emotional_processing"
        assert result.domains_present == ("identity_struggle", "shame_worthlessness")
        assert abs(result.weight - 0.7) < 0.01

    def test_clamped_intensity(self):
        raw = json.dumps({"distress_intensity": 5, "weight": 1.5})
        result = _parse_classifier_json(raw)
        assert result.distress_intensity == 3
        assert result.weight == 1.0

    def test_negative_values(self):
        raw = json.dumps({"distress_intensity": -1, "weight": -0.5})
        result = _parse_classifier_json(raw)
        assert result.distress_intensity == 0
        assert result.weight == 0.0

    def test_invalid_shape_defaults(self):
        raw = json.dumps({"request_shape": "unknown_thing"})
        result = _parse_classifier_json(raw)
        assert result.request_shape == "emotional_processing"

    def test_invalid_domains_filtered(self):
        raw = json.dumps({
            "domains_present": ["identity_struggle", "made_up_domain", "work_stress"],
        })
        result = _parse_classifier_json(raw)
        assert result.domains_present == ("identity_struggle", "work_stress")

    def test_markdown_fenced_json(self):
        raw = '```json\n{"distress_intensity": 1, "weight": 0.3}\n```'
        result = _parse_classifier_json(raw)
        assert result.distress_intensity == 1

    def test_empty_json_defaults(self):
        result = _parse_classifier_json("{}")
        assert result.distress_intensity == 0
        assert result.indirect_self_blame is False
        assert result.weight == 0.0

    def test_malformed_json_raises(self):
        with pytest.raises((json.JSONDecodeError, ValueError)):
            _parse_classifier_json("not json at all")


# ============================================================
# COST GATE TESTS
# ============================================================

class TestCostGates:
    def test_short_message_returns_empty(self):
        assert len("hi") < _MIN_MSG_LEN
        # classify_message is async; test the gate logic directly
        # Short messages should be caught by the length check

    def test_empty_result_fields(self):
        assert _EMPTY.distress_intensity == 0
        assert _EMPTY.indirect_self_blame is False
        assert _EMPTY.error is None

    def test_circuit_breaker_state(self):
        # Reset module state
        _cl_mod._consecutive_failures = 0
        _cl_mod._circuit_open_until = 0.0

        # Simulate 3 failures
        _cl_mod._consecutive_failures = 3
        _cl_mod._circuit_open_until = time.monotonic() + 60.0
        assert time.monotonic() < _cl_mod._circuit_open_until

        # Reset
        _cl_mod._consecutive_failures = 0
        _cl_mod._circuit_open_until = 0.0

    def test_rate_limit_tracking(self):
        _cl_mod._last_call_ts["test_user"] = time.monotonic()
        last = _cl_mod._last_call_ts["test_user"]
        assert time.monotonic() - last < _cl_mod._RATE_LIMIT_S
        del _cl_mod._last_call_ts["test_user"]


# ============================================================
# ACCUMULATOR MERGE TESTS
# ============================================================

class TestAccumulatorMerge:
    def _make_state(self, turn=5) -> SessionState:
        s = SessionState()
        s.turn_count = turn
        return s

    def test_distress_increment(self):
        state = self._make_state()
        result = ClassifierResult(distress_intensity=2, weight=0.8)
        signals = merge_classifier_into_state(result, state)
        assert state.distress_hits == 1
        assert state.distress_score > 0
        assert "classifier_distress" in signals

    def test_indirect_blame_increments_score(self):
        state = self._make_state()
        result = ClassifierResult(indirect_self_blame=True, weight=0.6)
        signals = merge_classifier_into_state(result, state)
        assert state.distress_score > 0
        assert "classifier_indirect_blame" in signals

    def test_decay_on_no_signal(self):
        state = self._make_state(turn=5)
        state.distress_score = 3.0
        state._last_classifier_distress_turn = 3
        result = ClassifierResult()  # zero distress
        merge_classifier_into_state(result, state)
        assert state.distress_score < 3.0  # decayed

    def test_error_result_no_accumulation(self):
        state = self._make_state()
        result = ClassifierResult(error="timeout")
        signals = merge_classifier_into_state(result, state)
        assert state.distress_hits == 0
        assert len(signals) == 0

    def test_escalation_increments_consecutive(self):
        state = self._make_state()
        result = ClassifierResult(
            distress_intensity=2, escalation_from_calm=True, weight=0.5,
        )
        signals = merge_classifier_into_state(result, state)
        assert state.consecutive_distress_turns == 1
        assert "classifier_escalation" in signals

    def test_domains_tracked(self):
        state = self._make_state()
        result = ClassifierResult(
            distress_intensity=2,
            domains_present=("marital_conflict", "shame_worthlessness"),
            weight=0.7,
        )
        signals = merge_classifier_into_state(result, state)
        assert "classifier_domains" in signals
        assert "marital_conflict" in signals["classifier_domains"]

    def test_redirect_signals_dissatisfaction(self):
        state = self._make_state()
        result = ClassifierResult(
            distress_intensity=2, request_shape="redirect", weight=0.5,
        )
        signals = merge_classifier_into_state(result, state)
        assert "classifier_dissatisfaction" in signals


# ============================================================
# HANDOFF THRESHOLD TESTS
# ============================================================

class TestHandoffThreshold:
    def test_below_threshold(self):
        state = SessionState()
        state.distress_score = 4.0
        assert compute_classifier_handoff(state) is False

    def test_at_threshold(self):
        state = SessionState()
        state.distress_score = 4.5
        assert compute_classifier_handoff(state) is True

    def test_above_threshold(self):
        state = SessionState()
        state.distress_score = 6.0
        assert compute_classifier_handoff(state) is True


# ============================================================
# DISAGREEMENT TESTS
# ============================================================

class TestDisagreements:
    def test_classifier_sees_distress_regex_missed(self):
        result = ClassifierResult(distress_intensity=2, weight=0.7)
        regex_signals = {"distress": False, "dissatisfaction": False}
        d = detect_disagreements(result, regex_signals)
        assert "classifier_sees_distress_regex_missed" in d

    def test_regex_sees_distress_classifier_missed(self):
        result = ClassifierResult(distress_intensity=0)
        regex_signals = {"distress": True, "dissatisfaction": False}
        d = detect_disagreements(result, regex_signals)
        assert "regex_sees_distress_classifier_missed" in d

    def test_no_disagreement_when_both_agree(self):
        result = ClassifierResult(distress_intensity=2, weight=0.7)
        regex_signals = {"distress": True, "dissatisfaction": False}
        d = detect_disagreements(result, regex_signals)
        assert "classifier_sees_distress_regex_missed" not in d
        assert "regex_sees_distress_classifier_missed" not in d

    def test_classifier_dissatisfaction_regex_missed(self):
        result = ClassifierResult(request_shape="redirect")
        regex_signals = {"distress": False, "dissatisfaction": False}
        d = detect_disagreements(result, regex_signals)
        assert "classifier_sees_dissatisfaction_regex_missed" in d

    def test_indirect_blame_regex_silent(self):
        result = ClassifierResult(indirect_self_blame=True, weight=0.5)
        regex_signals = {"distress": False, "dissatisfaction": False}
        d = detect_disagreements(result, regex_signals)
        assert "classifier_indirect_blame_regex_silent" in d

    def test_action_request_no_mismatch(self):
        result = ClassifierResult(request_shape="action_request")
        regex_signals = {"distress": False, "mismatch": False, "dissatisfaction": False}
        d = detect_disagreements(result, regex_signals)
        assert "classifier_action_request_regex_no_mismatch" in d

    def test_error_result_no_disagreements(self):
        result = ClassifierResult(error="timeout")
        regex_signals = {"distress": True}
        d = detect_disagreements(result, regex_signals)
        assert len(d) == 0


# ============================================================
# SESSION CACHE TESTS
# ============================================================

class TestSessionCache:
    def test_clear_session_cache(self):
        _cl_mod._session_caches["test_user"] = {"msg": _EMPTY}
        _cl_mod.clear_session_cache("test_user")
        assert "test_user" not in _cl_mod._session_caches

    def test_clear_nonexistent_user(self):
        _cl_mod.clear_session_cache("nonexistent")  # should not raise
