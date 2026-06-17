"""C1/C3 therapeutic path tests (buffer-audit-send exercised in bridge; audit + caps here)."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

_REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO / "backend"))

from app.services.therapeutic_controller import (  # noqa: E402
    TRANSPARENT_AUDIT_FALLBACK_MESSAGE,
    audit_therapeutic_response,
    scaled_predictability_continuity_floor,
)


@pytest.fixture
def base_audit_meta() -> dict:
    return {
        "locale": "en-US",
        "autonomic_state": "regulated",
        "max_tokens": 600,
        "mismatch_available": False,
        "dissociation_delta": None,
        "coercion_severity": None,
        "novelty_threshold": 0.30,
        "thalamic_gate_forced": False,
    }


@pytest.mark.asyncio
async def test_audit_failure_emits_transparent_message(base_audit_meta: dict) -> None:
    out = await audit_therapeutic_response(
        response_text="You'll get over this — many people feel that way.",
        audit_metadata=base_audit_meta,
        user_id="test_hw",
        db_pool=None,
    )
    assert out["audit_passed"] is False
    assert out["response_text"] == TRANSPARENT_AUDIT_FALLBACK_MESSAGE


@pytest.mark.asyncio
async def test_audit_failure_moderate_stall_suppressed(
    base_audit_meta: dict, monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.services.stall_suppression as stall_mod

    monkeypatch.setattr(stall_mod, "ENABLE_STALL_SUPPRESSION", True)
    meta = {
        **base_audit_meta,
        "bridge_event_severity": "moderate",
        "user_text_for_audit": "so I never cause my family pain again",
    }
    out = await audit_therapeutic_response(
        response_text="You'll get over this — many people feel that way.",
        audit_metadata=meta,
        user_id="test_hw",
        db_pool=None,
    )
    assert out["audit_passed"] is False
    assert out["response_text"] != TRANSPARENT_AUDIT_FALLBACK_MESSAGE


@pytest.mark.asyncio
async def test_audit_repair_via_llm_fallback(base_audit_meta: dict) -> None:
    meta = {**base_audit_meta, "mismatch_available": True}
    clean = (
        "I'm here with you. What feels most important about what you shared, "
        "in your own words?"
    )
    with patch(
        "app.sse.llm_fallback.chat_completion_with_fallback",
        new_callable=AsyncMock,
        return_value=clean,
    ):
        out = await audit_therapeutic_response(
            response_text="Everything happens for a reason, Lisa.",
            audit_metadata=meta,
            user_id="test_hw",
            db_pool=None,
        )
    assert out["audit_passed"] is True
    assert out["response_text"] == clean


def test_scaled_floor_short_input_is_floor() -> None:
    assert scaled_predictability_continuity_floor("hello") == 80


def test_scaled_floor_lisa_like_long_heavy_at_least_400() -> None:
    lisa_like = "x" * 2000 + " sexual assault grand jury testimony "
    cap = scaled_predictability_continuity_floor(lisa_like)
    assert cap >= 400
