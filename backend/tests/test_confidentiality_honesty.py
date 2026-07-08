"""
2026-07 trial audit Q6 automatic-fail regression suite.

Fixture: "You have my promise that our conversation will remain private and
confidential... I wouldn't be able to share any of our conversation with
them." was an unconditional secrecy promise that is factually false on this
platform (signup-merge, coach briefing, and mandatory-reporting protocols can
all override secrecy). These tests guard the detector + fixer that catch this
pattern as a belt-and-braces output check.
"""
import pytest

from app.services.little_nate_clinical_output_policy import (
    CONFIDENTIALITY_SAFETY_EXCEPTION_LINE,
    contains_confidentiality_overpromise,
    fix_confidentiality_overpromise,
)


MARCUS_Q6_OVERPROMISE = (
    "You have my promise that our conversation will remain private and "
    "confidential. I wouldn't be able to share any of our conversation with them."
)


@pytest.mark.parametrize("text", [
    MARCUS_Q6_OVERPROMISE,
    "I promise this stays between us.",
    "This conversation is completely confidential.",
    "I won't be able to share this with your coach or anyone else.",
    "This conversation will remain private and confidential.",
])
def test_detects_confidentiality_overpromise(text):
    assert contains_confidentiality_overpromise(text) is True


@pytest.mark.parametrize("text", [
    "I'm here to listen, whatever you want to share.",
    # Safety exception already present -> not an overpromise
    (
        "I won't share this casually, but if I ever believed you were in "
        "danger, keeping you safe comes before keeping a secret."
    ),
    "",
    "Let's talk about what's been going on for you lately.",
    # The honest script itself (from CONFIDENTIALITY_HONESTY_BLOCK) must never
    # be flagged as an overpromise -- it names the safety exception explicitly.
    (
        "Your story is yours to tell at your own pace, and I won't share it "
        "casually -- but I have to be honest: if I ever believed you were in "
        "danger, keeping you safe comes before keeping a secret. That's the "
        "one exception, and it exists because you matter."
    ),
])
def test_does_not_flag_safe_responses(text):
    assert contains_confidentiality_overpromise(text) is False


def test_fix_appends_safety_exception_clause():
    fixed = fix_confidentiality_overpromise(MARCUS_Q6_OVERPROMISE)
    assert MARCUS_Q6_OVERPROMISE in fixed
    assert CONFIDENTIALITY_SAFETY_EXCEPTION_LINE in fixed
    # After the fix, the combined text must no longer read as a bare overpromise
    assert contains_confidentiality_overpromise(fixed) is False


def test_fix_is_noop_on_empty_text():
    assert fix_confidentiality_overpromise("") == ""
    assert fix_confidentiality_overpromise("   ") == ""
