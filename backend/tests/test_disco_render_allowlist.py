"""One-coach DISCO_RENDER allowlist — T1 step 5."""

import os

import pytest

from app.services.disco.engine import DiscoEngine
from app.services.disco.brand import TEST_COACH, TEST_HUB_PATH, TEST_METRO
from app.services.disco.flags import disco_render_coach, disco_render_hub, disco_render_metro
from app.services.disco.pipeline import register_lint
from app.services.disco.renderer import render_profile_html


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


def test_coachn_hub_is_coaching_class(monkeypatch):
    monkeypatch.setenv("DISCO_RENDER_METRO", TEST_METRO)
    monkeypatch.setenv("DISCO_RENDER_HUB", TEST_HUB_PATH)
    assert disco_render_metro() == "Detroit, MI, USA"
    assert disco_render_hub() == "coaches/trauma-coaches/detroit-mi"
    lint = register_lint(
        f"{TEST_COACH['bio']} {TEST_COACH['credential_string']} trauma coaches",
        "coaching",
    )
    assert lint["blocked"] is False, lint
    out = render_profile_html(TEST_COACH, relationship_class="coaching")
    assert out.get("blocked") is False, out.get("lint")


def test_listing_packet_coaching_class_no_clinical_terms():
    pkt = DiscoEngine().listing_packet(
        {
            "display_name": "Nathaniel Nevedal",
            "slug": "coachn",
            "bio": TEST_COACH["bio"],
            "canonical_phrases": ["family systems coaching", "presence-based coaching"],
            "area_served": ["Detroit, MI, USA"],
        }
    )
    blob = " ".join(
        [
            pkt["psychology_today"]["about"],
            pkt["psychology_today"]["category"],
            pkt["bing_places"]["category"],
            " ".join(pkt["psychology_today"]["specialties"]),
        ]
    )
    lint = register_lint(blob, "coaching")
    assert lint["blocked"] is False, lint
    assert pkt["psychology_today"]["category"] == "Life Coaching"
    assert pkt["human_step"] == "paste_and_submit"
    assert "mycounselor.online/christian-counselors/nathaniel-nevedal" in pkt["existing_public"]["mycounselor_profile"]
    assert pkt["homepage_seo"]["gbp"]["hide_address"] is True


def test_gbp_packet_hides_address_life_coach_only():
    pkt = DiscoEngine().gbp_claim_packet(
        {"display_name": "Sovereign Sanctuary", "relationship_class": "coaching"}
    )
    assert pkt["hide_address"] is True
    assert pkt["onsite_services"] is False
    assert pkt["category"] == "Life coach"
    assert pkt["additional_categories"] == []
    assert "Counselor" in pkt["do_not_add"]
    assert "Therapist" in pkt["do_not_add"]
