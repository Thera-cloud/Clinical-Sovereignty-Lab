"""Tests for Fix T — trafficking recalibration (shadow only)."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO / "backend"))

from app.services import trafficking_recalibration as mod  # noqa: E402


@pytest.fixture(autouse=True)
def _enable_flag(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(mod, "ENABLE_TRAFFICKING_RECAL", True)


LISA_IFS = (
    "I want to introduce you to my parts — Lonely Girl, Scolded Girl, "
    "and the Silencer."
)
LISA_TURN_121 = (
    "When I was a child I was sexually abused and I still carry that "
    "in my body every day."
)
LISA_TURN_122 = (
    "I feel conviction and repentance about my tormented friends and "
    "keeping the sabbath holy."
)
SYNTHETIC_TRAFFICKING = (
    "He sells me to clients every night, took my passport, and I can't leave."
)


def test_ifs_no_disclosure_shadow_none_agree() -> None:
    result = mod.run_shadow(
        message=LISA_IFS,
        live_tier="trafficking_disclosure",
        trafficking_label="no_disclosure",
        turn_id="lisa-ifs",
    )
    assert result is not None
    assert result.shadow_tier == mod.SHADOW_TIER_NONE
    assert result.agree is False


def test_acuity_turn_121_higher_than_122() -> None:
    s121 = mod.compute_sexual_trauma_acuity(LISA_TURN_121)
    s122 = mod.compute_sexual_trauma_acuity(LISA_TURN_122)
    assert s121 > s122


def test_synthetic_genuine_trafficking_still_fires() -> None:
    result = mod.run_shadow(
        message=SYNTHETIC_TRAFFICKING,
        live_tier=None,
        trafficking_label="active_situation",
        turn_id="synthetic-trafficking",
    )
    assert result is not None
    assert result.shadow_tier == mod.SHADOW_TIER_TRAFFICKING


def test_eval_authoritative_blocks_shadow_fire() -> None:
    result = mod.run_shadow(
        message=LISA_TURN_122,
        live_tier="trafficking_disclosure",
        trafficking_label="no_disclosure",
        turn_id="lisa-122",
    )
    assert result is not None
    assert result.shadow_tier == mod.SHADOW_TIER_NONE


def test_flag_off_returns_none(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(mod, "ENABLE_TRAFFICKING_RECAL", False)
    assert mod.run_shadow(
        message=SYNTHETIC_TRAFFICKING,
        live_tier=None,
        trafficking_label="active_situation",
    ) is None
