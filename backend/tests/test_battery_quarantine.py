"""Offline unit tests — battery crystal quarantine (Tier-1 D.14b)."""

from __future__ import annotations

import os

import pytest


@pytest.fixture(autouse=True)
def _quarantine_on(monkeypatch):
    monkeypatch.setenv("SIX_QUOTIENT_BATTERY_QUARANTINE", "true")


def test_block_battery_origin_surface():
    from app.services.six_quotient_battery_quarantine import should_block_crystallize

    assert should_block_crystallize(
        origin_surface="six_quotient_battery",
        user_text="hello",
        nate_response="hi",
    )


def test_block_marker_in_text():
    from app.services.six_quotient_battery_quarantine import should_block_crystallize

    assert should_block_crystallize(
        origin_surface="bridge_chat",
        user_text="[SIX_QUOTIENT_BATTERY] AQ-1",
        nate_response="ok",
    )


def test_allow_normal_chat():
    from app.services.six_quotient_battery_quarantine import should_block_crystallize

    assert not should_block_crystallize(
        origin_surface="bridge_chat",
        user_text="I feel anxious about work today",
        nate_response="That sounds heavy — what's the part that won't let go?",
    )


def test_filter_contaminated_rows():
    from app.services.six_quotient_battery_quarantine import filter_crystals

    rows = [
        {"crystal_text": "normal clinical insight about grief"},
        {
            "crystal_text": "x",
            "metadata": {"origin_surface": "six_quotient_nightly"},
        },
        {"crystal_text": "contains six_quotient_battery marker"},
    ]
    out = filter_crystals(rows)
    assert len(out) == 1
    assert "grief" in out[0]["crystal_text"]


def test_quarantine_can_disable(monkeypatch):
    monkeypatch.setenv("SIX_QUOTIENT_BATTERY_QUARANTINE", "false")
    from app.services.six_quotient_battery_quarantine import should_block_crystallize

    assert not should_block_crystallize(
        origin_surface="six_quotient_battery",
        user_text="x",
        nate_response="y",
    )
