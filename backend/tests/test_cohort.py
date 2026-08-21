"""Unit tests for ``app.services.cohort``.

Covers:
- ``normalize_program_id`` edge cases (None, empty, whitespace, casing).
- ``is_strict_cohort`` / ``is_known_cohort`` membership + casing.
- ``get_strict_mfa_window_seconds`` env override, clamping, fallback.

No network, no DB. Pure module.
"""

from __future__ import annotations

import importlib
import sys
from typing import Any

import pytest


def _reload_cohort(monkeypatch: pytest.MonkeyPatch, **env: str) -> Any:
    """Set env then import (or re-import) cohort so it sees fresh values."""
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    if "app.services.cohort" in sys.modules:
        return importlib.reload(sys.modules["app.services.cohort"])
    import app.services.cohort as coh  # type: ignore

    return coh


# --------------------------------------------------------------------------- #
# normalize_program_id                                                        #
# --------------------------------------------------------------------------- #


def test_normalize_none_returns_none(monkeypatch: pytest.MonkeyPatch) -> None:
    coh = _reload_cohort(monkeypatch)
    assert coh.normalize_program_id(None) is None


def test_normalize_empty_string_returns_none(monkeypatch: pytest.MonkeyPatch) -> None:
    coh = _reload_cohort(monkeypatch)
    assert coh.normalize_program_id("") is None


def test_normalize_whitespace_returns_none(monkeypatch: pytest.MonkeyPatch) -> None:
    coh = _reload_cohort(monkeypatch)
    assert coh.normalize_program_id("   ") is None


def test_normalize_lowercases_and_trims(monkeypatch: pytest.MonkeyPatch) -> None:
    coh = _reload_cohort(monkeypatch)
    assert coh.normalize_program_id("  Bee_HIV_Plus  ") == "bee_hiv_plus"


def test_normalize_non_string_coerces(monkeypatch: pytest.MonkeyPatch) -> None:
    """Defensive: DB drivers sometimes hand us unexpected types."""
    coh = _reload_cohort(monkeypatch)
    assert coh.normalize_program_id(123) == "123"


# --------------------------------------------------------------------------- #
# is_strict_cohort / is_known_cohort                                          #
# --------------------------------------------------------------------------- #


def test_is_strict_cohort_true_for_bee_hiv_plus(monkeypatch: pytest.MonkeyPatch) -> None:
    coh = _reload_cohort(monkeypatch)
    assert coh.is_strict_cohort("bee_hiv_plus") is True


def test_is_strict_cohort_case_insensitive(monkeypatch: pytest.MonkeyPatch) -> None:
    coh = _reload_cohort(monkeypatch)
    assert coh.is_strict_cohort("BEE_HIV_PLUS") is True
    assert coh.is_strict_cohort("Bee_Hiv_Plus") is True


def test_is_strict_cohort_false_for_unknown(monkeypatch: pytest.MonkeyPatch) -> None:
    coh = _reload_cohort(monkeypatch)
    assert coh.is_strict_cohort("general_pool") is False
    assert coh.is_strict_cohort("some_other_program") is False


def test_is_strict_cohort_false_for_none_and_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    coh = _reload_cohort(monkeypatch)
    assert coh.is_strict_cohort(None) is False
    assert coh.is_strict_cohort("") is False
    assert coh.is_strict_cohort("   ") is False


def test_is_known_cohort_currently_equals_is_strict(monkeypatch: pytest.MonkeyPatch) -> None:
    """Contract: is_known_cohort is an alias-like helper for callers who
    only care that we recognize the cohort, not its enforcement level."""
    coh = _reload_cohort(monkeypatch)
    for pid in ("bee_hiv_plus", "general_pool", "", None):
        assert coh.is_known_cohort(pid) is coh.is_strict_cohort(pid)


def test_strict_cohort_program_ids_frozenset_is_immutable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A regression-guard for accidental mutation of the policy set."""
    coh = _reload_cohort(monkeypatch)
    with pytest.raises((AttributeError, TypeError)):
        coh.STRICT_COHORT_PROGRAM_IDS.add("new_cohort")  # type: ignore[attr-defined]


# --------------------------------------------------------------------------- #
# get_strict_mfa_window_seconds                                               #
# --------------------------------------------------------------------------- #


def test_strict_window_default_is_five_minutes(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("MFA_GATE_STRICT_WINDOW_SECONDS", raising=False)
    coh = _reload_cohort(monkeypatch)
    assert coh.get_strict_mfa_window_seconds() == 300


def test_strict_window_env_override(monkeypatch: pytest.MonkeyPatch) -> None:
    coh = _reload_cohort(monkeypatch, MFA_GATE_STRICT_WINDOW_SECONDS="600")
    assert coh.get_strict_mfa_window_seconds() == 600


def test_strict_window_clamped_low(monkeypatch: pytest.MonkeyPatch) -> None:
    coh = _reload_cohort(monkeypatch, MFA_GATE_STRICT_WINDOW_SECONDS="10")
    assert coh.get_strict_mfa_window_seconds() == 60


def test_strict_window_clamped_high(monkeypatch: pytest.MonkeyPatch) -> None:
    coh = _reload_cohort(monkeypatch, MFA_GATE_STRICT_WINDOW_SECONDS="9999999")
    assert coh.get_strict_mfa_window_seconds() == 86_400


def test_strict_window_invalid_falls_back(monkeypatch: pytest.MonkeyPatch) -> None:
    coh = _reload_cohort(monkeypatch, MFA_GATE_STRICT_WINDOW_SECONDS="not-an-int")
    assert coh.get_strict_mfa_window_seconds() == 300


def test_strict_window_empty_falls_back(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MFA_GATE_STRICT_WINDOW_SECONDS", "")
    coh = _reload_cohort(monkeypatch)
    assert coh.get_strict_mfa_window_seconds() == 300
