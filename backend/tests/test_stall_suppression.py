"""Tests for Fix 5 — stall suppression."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO / "backend"))

from app.services.stall_suppression import (  # noqa: E402
    HIGH_ACUITY_SEVERITIES,
    build_content_aware_fallback,
    is_stall_fallback,
    resolve_audit_fallback,
)
from app.services.therapeutic_controller import (  # noqa: E402
    TRANSPARENT_AUDIT_FALLBACK_MESSAGE,
)


@pytest.fixture(autouse=True)
def _reset_flag(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ENABLE_STALL_SUPPRESSION", raising=False)


def test_is_stall_fallback_exact_match() -> None:
    assert is_stall_fallback(TRANSPARENT_AUDIT_FALLBACK_MESSAGE)


def test_build_content_aware_fallback_never_stall() -> None:
    csa = (
        "I remember rolling out of my grandfather's bed and crawling "
        "underneath to hide."
    )
    out = build_content_aware_fallback(csa)
    assert not is_stall_fallback(out)
    assert "grandfather" in out.lower() or "crawling" in out.lower()


def test_high_acuity_flag_on_suppresses_stall(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ENABLE_STALL_SUPPRESSION", "true")
    import app.services.stall_suppression as mod

    monkeypatch.setattr(mod, "ENABLE_STALL_SUPPRESSION", True)
    user = "so I never cause my family pain again"
    out = resolve_audit_fallback(
        user_text=user,
        bridge_event_severity="moderate",
        default_fallback=TRANSPARENT_AUDIT_FALLBACK_MESSAGE,
    )
    assert not is_stall_fallback(out)
    assert "family" in out.lower()


def test_low_acuity_flag_on_keeps_stall(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ENABLE_STALL_SUPPRESSION", "true")
    import app.services.stall_suppression as mod

    monkeypatch.setattr(mod, "ENABLE_STALL_SUPPRESSION", True)
    out = resolve_audit_fallback(
        user_text="Hmm, I'll bring a vault panel in. Stand by.",
        bridge_event_severity="info",
        default_fallback=TRANSPARENT_AUDIT_FALLBACK_MESSAGE,
    )
    assert out == TRANSPARENT_AUDIT_FALLBACK_MESSAGE


def test_flag_off_is_noop(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.services.stall_suppression as mod

    monkeypatch.setattr(mod, "ENABLE_STALL_SUPPRESSION", False)
    out = resolve_audit_fallback(
        user_text="heavy disclosure",
        bridge_event_severity="critical",
        default_fallback=TRANSPARENT_AUDIT_FALLBACK_MESSAGE,
    )
    assert out == TRANSPARENT_AUDIT_FALLBACK_MESSAGE


def test_high_acuity_severities_match_migration_enum() -> None:
    assert "moderate" in HIGH_ACUITY_SEVERITIES
    assert "info" not in HIGH_ACUITY_SEVERITIES
