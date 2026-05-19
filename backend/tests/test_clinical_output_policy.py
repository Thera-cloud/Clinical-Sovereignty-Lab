"""Tests for clinical output policy (Ticket 2, 2026-05-19)."""

from app.services.little_nate_clinical_output_policy import (
    check_unsolicited_clinical_framing,
    clinical_temperature_cap,
    user_named_category,
)
from app.services.nate_ai_config import nate_temperature


def test_diagnostic_framing_blocked_without_user_vocab():
    warnings = check_unsolicited_clinical_framing(
        "It sounds like you might be dealing with depression.",
        "I had a really hard week at work.",
    )
    assert "unsolicited_diagnostic_framing" in warnings


def test_diagnostic_allowed_when_user_named_it():
    warnings = check_unsolicited_clinical_framing(
        "You named depression — what has that been like lately?",
        "My depression has been worse since the move.",
    )
    assert "unsolicited_diagnostic_framing" not in warnings


def test_attachment_blocked_without_user_vocab():
    warnings = check_unsolicited_clinical_framing(
        "This could be an anxious attachment pattern showing up.",
        "My husband and I argued again.",
    )
    assert "unsolicited_attachment_framing" in warnings


def test_medication_always_blocked():
    warnings = check_unsolicited_clinical_framing(
        "You should try medication for this.",
        "I feel overwhelmed.",
    )
    assert "unsolicited_medication_suggestion" in warnings


def test_user_named_attachment():
    assert user_named_category(
        "attachment", "I think my avoidant attachment is the issue."
    )


def test_clinical_temperature_cap():
    assert clinical_temperature_cap() == 1.2


def test_nate_temperature_clinical_caps_elevated_user(monkeypatch):
    monkeypatch.setenv("NATE_ELEVATED_TEMP_USERS", "testuser")
    monkeypatch.setenv("NATE_CLINICAL_TEMPERATURE", "1.2")
    temp = nate_temperature("testuser", clinical=True)
    assert temp <= 1.2
