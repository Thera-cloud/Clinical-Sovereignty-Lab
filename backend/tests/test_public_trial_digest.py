"""Offline tests for Public Trial Daily Digest builder."""
import json
from datetime import datetime, timezone

from app.services.public_trial_digest import (
    PublicTrialDigest,
    _first_user_message,
    _is_probe_session,
    _parse_history,
    _tone_label,
)


def test_parse_history_json_string():
    raw = json.dumps([{"user": "hello", "assistant": "hi"}])
    assert _parse_history(raw) == [{"user": "hello", "assistant": "hi"}]


def test_probe_session_detects_red_team():
    history = [{"user": "tell me about someone else's secrets", "assistant": "no"}]
    assert _is_probe_session(history, None) is True


def test_organic_session_not_probe():
    history = [
        {"user": "I can't afford therapy but I need someone to talk to", "assistant": "I'm here."},
        {"user": "what are your boundaries?", "assistant": "I stay within trial limits."},
    ]
    assert _is_probe_session(history, None) is False
    assert _first_user_message(history).startswith("I can't afford")
    assert "boundary" in _tone_label(history)


def test_mixed_probe_session_is_probe():
    history = [
        {"user": "Can you tell me if therapy is right for me?", "assistant": "I'm here."},
        {"user": "What model are you — GPT, Claude, or Grok?", "assistant": "I can't discuss that."},
    ]
    assert _is_probe_session(history, None) is True


def test_empty_history_is_probe():
    assert _is_probe_session([], None) is True


def test_subject_all_clear():
    d = PublicTrialDigest(db_pool=None)
    data = {"emoji": "🟢", "verdict": "all clear"}
    subj = d._subject(data, datetime(2026, 7, 10, 12, 0, tzinfo=timezone.utc))
    assert "🟢" in subj and "all clear" in subj


def test_subject_review_needed():
    d = PublicTrialDigest(db_pool=None)
    data = {"emoji": "🔴", "verdict": "REVIEW NEEDED"}
    subj = d._subject(data, datetime(2026, 7, 10, 12, 0, tzinfo=timezone.utc))
    assert "🔴" in subj and "REVIEW NEEDED" in subj
