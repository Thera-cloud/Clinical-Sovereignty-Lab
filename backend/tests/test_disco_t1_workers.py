"""T1.7 / T1.8 / T1.9 / T1.16 — offline, flags default off."""

from app.services.disco.engine import DiscoEngine
from app.services.disco.t1_workers import (
    authority_roster,
    derive_area_served,
    lifecycle_plan,
    propagate_credential_lapse,
)


def test_t17_clinical_never_global_without_licensure():
    out = derive_area_served("clinical", [])
    assert out["area_served"] == []
    assert out["blocked_global"] is True
    assert out["persist"] is False


def test_t17_clinical_uses_jurisdictions_only_no_invented_compact():
    out = derive_area_served("clinical", ["MI"], compact_id="psypact")
    assert out["area_served"] == ["MI"]
    assert out["compact_expanded"] is False


def test_t17_clinical_expands_only_supplied_compact_members():
    out = derive_area_served(
        "clinical",
        ["MI"],
        compact_id="psypact",
        compact_members=["OH", "IN"],
    )
    assert out["area_served"] == ["MI", "OH", "IN"]


def test_t17_coaching_declared_metro():
    out = derive_area_served("coaching", [], declared=["Detroit, MI, USA"])
    assert out["area_served"] == ["Detroit, MI, USA"]


def test_t17_coaching_empty_is_global_virtual():
    assert derive_area_served("coaching", [])["area_served"] == ["global_virtual"]


def test_t17_coachn_defaults_detroit():
    out = derive_area_served("coaching", [], coach_id="CoachN")
    assert out["area_served"] == ["Detroit, MI, USA"]


def test_engine_area_served_compat():
    eng = DiscoEngine()
    assert eng.area_served("clinical", ["MI"]) == ["MI"]
    assert eng.area_served("coaching", []) == ["global_virtual"]


def test_t18_lapse_badge_off_strips_clinical_terms():
    rec = {
        "slug": "coachn",
        "relationship_class": "coaching",
        "credential_string": "LMFT",
        "bio": "I offer therapy and treatment for the patient.",
    }
    out = propagate_credential_lapse(rec, lapsed=True)
    assert out["applied"] is True
    assert out["badge_off"] is True
    assert out["same_day"] is True
    assert out["persist"] is False
    low = out["bio"].lower()
    for term in ("therapy", "treatment", "patient"):
        assert term not in low
    assert "/coaches/coachn" in out["cache_purge"]


def test_t18_not_lapsed_noop():
    out = propagate_credential_lapse({"slug": "x"}, lapsed=False)
    assert out["applied"] is False
    assert out["badge_off"] is False


def test_t19_depart_301_unstitch_no_404():
    plan = lifecycle_plan("departed", "coachn", coach_id="CoachN")
    assert plan["redirects"][0]["code"] == 301
    assert plan["redirects"][0]["from"] == "/coaches/coachn"
    assert plan["redirects"][0]["to"] == "/coaches/trauma-coaches/detroit-mi"
    assert plan["unstitch_sameAs"] is True
    assert plan["deindex"] is True
    assert plan["zero_404"] is True
    assert plan["persist"] is False


def test_t19_pause_keeps_sameas():
    plan = lifecycle_plan("paused", "coachn")
    assert plan["noindex"] is True
    assert plan["badge_off"] is True
    assert plan["unstitch_sameAs"] is False
    assert plan["redirects"] == []


def test_t116_packets_not_sent_when_flag_off():
    rec = {
        "display_name": "Nathaniel Nevedal",
        "credential_string": "Coach",
        "relationship_class": "coaching",
        "canonical_phrases": ["family systems coaching"],
        "area_served": ["Detroit, MI, USA"],
        "bio": "Presence-based coaching.",
    }
    eng = DiscoEngine()
    built = eng.authority_builder(rec)
    assert built["auto_sent"] is False
    assert built["persist"] is False
    assert len(built["packets"]) == 6
    assert built["packets"][0]["canonical_facts"]["website"] == "https://www.sovereignsanctuary.net/"
    roster = authority_roster(rec)
    assert all(p["human_step"] == "send_pitch" for p in roster)


def test_t116_persist_noop_when_flag_off():
    import asyncio

    rec = {"coach_id": "CoachN", "display_name": "Nathaniel Nevedal"}
    out = asyncio.run(DiscoEngine().persist_authority_placements(rec))
    assert out["written"] is False
    assert out["auto_sent"] is False


def test_authority_packet_two_arg_compat():
    pkt = DiscoEngine().authority_packet("detroit-news", "press")
    assert pkt["outlet"] == "detroit-news"
    assert pkt["angle"] == "press"
    assert pkt["auto_sent"] is False


def test_checklist_does_not_claim_t1_gate():
    tickets = DiscoEngine().checklist_state()
    assert tickets["T1.7"] == "code_ready_flag_off"
    assert tickets["T1.8"] == "code_ready_flag_off"
    assert tickets["T1.9"] == "code_ready_flag_off"
    assert tickets["T1.15"] == "human_listings_open"
    assert tickets["T1.16"] == "code_ready_flag_off"
