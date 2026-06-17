"""Tests for Fix 8 — med adjustment redirect."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO / "backend"))

from app.services import med_adjustment_redirect as mod  # noqa: E402


@pytest.fixture(autouse=True)
def _enable_flag(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(mod, "ENABLE_MED_ADJUST_REDIRECT", True)


def test_longra_turn_42_other_target() -> None:
    msg = "I want to raise her Seroquel from 50mg to 75mg at night"
    match = mod.detect_and_log(msg)
    assert match is not None
    assert match.target == "other"
    assert match.med_name in ("seroquel", "quetiapine")
    directive = mod.build_redirect_directive(match)
    assert "prescribing clinician" in directive.lower()
    assert "co-plan" in directive.lower() or "validate" in directive.lower()


def test_self_dosing_redirect() -> None:
    match = mod.detect_and_log("I'm going to double my Zoloft to 100mg tonight")
    assert match is not None
    assert match.target == "self"


def test_benign_mention_no_match() -> None:
    assert mod.detect_and_log("she takes Seroquel at night") is None


def test_benign_help_sleep_no_match() -> None:
    assert mod.detect_and_log("Seroquel helps her sleep") is None
