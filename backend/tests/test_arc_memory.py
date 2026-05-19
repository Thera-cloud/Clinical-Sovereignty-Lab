"""
Phase 2 — Tests for conversation arc memory (little_nate_arc_memory.py).

Covers:
  - Domain accumulation and decay
  - Threshold trigger
  - Persistence round-trip (serialize/load)
  - Cross-session TTL expiry
  - Topic pivot unlock phrase detection
  - Arc reset
"""
import importlib.util
import os
import sys
import time

import pytest

# ── Load modules via importlib to avoid heavy transitive deps ──
_SERVICES = os.path.join(
    os.path.dirname(__file__), "..", "app", "services"
)


def _load(name: str, filename: str):
    path = os.path.join(_SERVICES, filename)
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


_ad = _load("little_nate_adaptive", "little_nate_adaptive.py")
_arc = _load("little_nate_arc_memory", "little_nate_arc_memory.py")


SessionState = _ad.SessionState
merge_domains_into_arc = _arc.merge_domains_into_arc
evaluate_arc_scope = _arc.evaluate_arc_scope
mark_arc_triggered = _arc.mark_arc_triggered
reset_arc = _arc.reset_arc
serialize_arc = _arc.serialize_arc
load_arc_into_state = _arc.load_arc_into_state
detect_topic_pivot = _arc.detect_topic_pivot
get_arc_topic_groups = _arc.get_arc_topic_groups


def _state(turn=1) -> SessionState:
    s = SessionState()
    s.turn_count = turn
    return s


# ========================================================
# ACCUMULATION
# ========================================================

class TestMergeDomainsIntoArc:
    def test_single_domain_add(self):
        s = _state(1)
        arc = merge_domains_into_arc(s, ["grief_loss"], 0.7)
        assert "grief_loss" in arc
        assert arc["grief_loss"] == pytest.approx(0.7, abs=0.01)

    def test_multiple_domains_add(self):
        s = _state(1)
        arc = merge_domains_into_arc(s, ["grief_loss", "trauma_abuse"], 0.5)
        assert arc["grief_loss"] == pytest.approx(0.5, abs=0.01)
        assert arc["trauma_abuse"] == pytest.approx(0.5, abs=0.01)

    def test_cumulative_same_domain(self):
        s = _state(1)
        merge_domains_into_arc(s, ["grief_loss"], 0.4)
        s.turn_count = 2
        merge_domains_into_arc(s, ["grief_loss"], 0.4)
        # First weight decays by ARC_DECAY_RATE, then 0.4 added
        expected = 0.4 * _arc.ARC_DECAY_RATE + 0.4
        assert s.arc_domain_weights["grief_loss"] == pytest.approx(expected, abs=0.02)

    def test_decay_removes_tiny_weights(self):
        s = _state(1)
        merge_domains_into_arc(s, ["noise_domain"], 0.02)
        s.turn_count = 2
        # After decay, 0.02 * 0.85 = 0.017 — close to threshold
        merge_domains_into_arc(s, ["other"], 0.5)
        s.turn_count = 3
        merge_domains_into_arc(s, ["other"], 0.5)
        # noise_domain should be pruned after enough decay
        # 0.02 * 0.85^2 = ~0.014 — still above 0.01
        # 0.02 * 0.85^3 = ~0.012 — still above
        # Let it decay further
        for t in range(4, 12):
            s.turn_count = t
            merge_domains_into_arc(s, ["other"], 0.01)
        assert s.arc_domain_weights.get("noise_domain", 0) < 0.01


# ========================================================
# THRESHOLD TRIGGER
# ========================================================

class TestEvaluateArcScope:
    def test_no_trigger_below_threshold(self):
        s = _state(1)
        merge_domains_into_arc(s, ["grief_loss", "trauma_abuse", "identity_struggle"], 0.5)
        fire, doms, cnt = evaluate_arc_scope(s)
        assert not fire
        assert cnt == 3

    def test_trigger_at_threshold(self):
        s = _state(1)
        domains = ["grief_loss", "trauma_abuse", "identity_struggle", "marital_conflict"]
        merge_domains_into_arc(s, domains, 0.5)
        fire, doms, cnt = evaluate_arc_scope(s)
        assert fire
        assert cnt == 4
        assert set(doms) == set(domains)

    def test_no_double_trigger(self):
        s = _state(1)
        domains = ["grief_loss", "trauma_abuse", "identity_struggle", "marital_conflict"]
        merge_domains_into_arc(s, domains, 0.5)
        fire1, _, _ = evaluate_arc_scope(s)
        assert fire1
        mark_arc_triggered(s)
        fire2, _, _ = evaluate_arc_scope(s)
        assert not fire2

    def test_only_counts_above_min_weight(self):
        s = _state(1)
        merge_domains_into_arc(s, ["grief_loss"], 0.5)
        merge_domains_into_arc(s, ["trauma_abuse"], 0.5)
        merge_domains_into_arc(s, ["identity_struggle"], 0.5)
        merge_domains_into_arc(s, ["marital_conflict"], 0.1)  # below min weight
        fire, doms, cnt = evaluate_arc_scope(s)
        assert not fire
        assert cnt == 3


# ========================================================
# ARC RESET
# ========================================================

class TestResetArc:
    def test_reset_clears_all(self):
        s = _state(1)
        merge_domains_into_arc(s, ["grief_loss", "trauma_abuse"], 0.5)
        mark_arc_triggered(s)
        reset_arc(s)
        assert s.arc_domain_weights == {}
        assert not s.arc_scope_triggered
        assert s.arc_last_updated_ts == 0.0


# ========================================================
# PERSISTENCE ROUND-TRIP
# ========================================================

class TestSerializeAndLoad:
    def test_serialize_empty_returns_none(self):
        s = _state(1)
        assert serialize_arc(s) is None

    def test_round_trip(self):
        s1 = _state(1)
        merge_domains_into_arc(s1, ["grief_loss", "trauma_abuse"], 0.6)
        mark_arc_triggered(s1)
        data = serialize_arc(s1)
        assert data is not None
        assert "domain_weights" in data
        assert data["triggered"] is True

        s2 = _state(1)
        loaded = load_arc_into_state(s2, data)
        assert loaded
        assert "grief_loss" in s2.arc_domain_weights
        assert s2.arc_scope_triggered is True

    def test_load_applies_time_decay(self):
        s1 = _state(1)
        merge_domains_into_arc(s1, ["grief_loss"], 0.8)
        data = serialize_arc(s1)
        # Simulate 6 hours elapsed
        data["updated_ts"] = time.time() - 6 * 3600

        s2 = _state(1)
        loaded = load_arc_into_state(s2, data)
        assert loaded
        assert s2.arc_domain_weights["grief_loss"] < 0.8


# ========================================================
# CROSS-SESSION TTL
# ========================================================

class TestCrossSessionTTL:
    def test_expired_arc_not_loaded(self):
        s1 = _state(1)
        merge_domains_into_arc(s1, ["grief_loss"], 0.8)
        data = serialize_arc(s1)
        # Simulate 25 hours elapsed (beyond 24h TTL)
        data["updated_ts"] = time.time() - 25 * 3600

        s2 = _state(1)
        loaded = load_arc_into_state(s2, data)
        assert not loaded
        assert s2.arc_domain_weights == {}

    def test_fresh_arc_loads(self):
        s1 = _state(1)
        merge_domains_into_arc(s1, ["grief_loss"], 0.8)
        data = serialize_arc(s1)
        # Simulate 1 hour elapsed
        data["updated_ts"] = time.time() - 3600

        s2 = _state(1)
        loaded = load_arc_into_state(s2, data)
        assert loaded
        assert len(s2.arc_domain_weights) > 0

    def test_missing_data_returns_false(self):
        s = _state(1)
        assert not load_arc_into_state(s, None)
        assert not load_arc_into_state(s, {})
        assert not load_arc_into_state(s, {"updated_ts": 0})


# ========================================================
# TOPIC PIVOT / UNLOCK
# ========================================================

class TestTopicPivot:
    def test_pivot_phrase_detected(self):
        assert detect_topic_pivot("Let's focus on one thing")
        assert detect_topic_pivot("I want to talk about my job")
        assert detect_topic_pivot("Can we just discuss the kids?")
        assert detect_topic_pivot("One thing at a time please")

    def test_non_pivot_not_detected(self):
        assert not detect_topic_pivot("I feel terrible about everything")
        assert not detect_topic_pivot("My marriage is falling apart")
        assert not detect_topic_pivot("Hello")

    def test_pivot_resets_triggered_arc(self):
        s = _state(1)
        domains = ["grief_loss", "trauma_abuse", "identity_struggle", "marital_conflict"]
        merge_domains_into_arc(s, domains, 0.5)
        mark_arc_triggered(s)
        assert s.arc_scope_triggered

        if detect_topic_pivot("Let's focus on just the grief"):
            reset_arc(s)
        assert not s.arc_scope_triggered
        assert s.arc_domain_weights == {}


# ========================================================
# DOMAIN-TO-GROUP MAPPING
# ========================================================

class TestArcTopicGroups:
    def test_maps_known_domains(self):
        s = _state(1)
        merge_domains_into_arc(s, ["marital_conflict", "grief_loss", "trauma_abuse"], 0.5)
        groups = get_arc_topic_groups(s)
        assert "marital_intimate" in groups
        assert "grief_loss" in groups
        assert "trauma_abuse" in groups

    def test_unknown_domain_passes_through(self):
        s = _state(1)
        merge_domains_into_arc(s, ["exotic_new_domain"], 0.5)
        groups = get_arc_topic_groups(s)
        assert "exotic_new_domain" in groups
