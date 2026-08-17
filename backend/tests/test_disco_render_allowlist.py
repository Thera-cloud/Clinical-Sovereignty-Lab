"""One-coach DISCO_RENDER allowlist — T1 step 5."""

import os

import pytest

from app.services.disco.engine import DiscoEngine
from app.services.disco.flags import disco_render_coach


def test_allowlist_env_defaults_empty(monkeypatch):
    monkeypatch.delenv("DISCO_RENDER_COACH", raising=False)
    assert disco_render_coach() == ""


@pytest.mark.asyncio
async def test_public_profile_404_when_flag_off(monkeypatch):
    monkeypatch.setenv("DISCO_RENDER", "false")
    out = await DiscoEngine().public_profile_html("coachn")
    assert out["ok"] is False
    assert out["status"] == 404


@pytest.mark.asyncio
async def test_allowlist_rejects_other_slug(monkeypatch):
    monkeypatch.setenv("DISCO_RENDER", "true")
    monkeypatch.setenv("DISCO_RENDER_COACH", "CoachN")

    class _Eng(DiscoEngine):
        async def get_profile(self, slug):
            return {
                "coach_id": "OtherCoach",
                "slug": slug,
                "profile_status": "active",
                "display_name": "Other",
            }

    out = await _Eng().public_profile_html("other")
    assert out["ok"] is False
    assert out["reason"] == "not_in_render_allowlist"
