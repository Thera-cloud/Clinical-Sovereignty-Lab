"""Thera-world Neuro region — offline unit tests (no DB, no LLM, no network).

Covers: pole formula (H_d / H), stems → 12-vector, biome selection, champion
pairing + ε-skip + visitors, region routing (Origin frozen when locked/disabled),
client language wall on every client-facing composer, the four-move braid,
symbol_safety legend wiring, and an Origin regression guard on the catalogs.
"""
from __future__ import annotations

import json
import os
import re

import pytest

from app.sse import neuro_scoring as ns
from app.sse import symbol_safety as ss
from app.sse.thera_world_regions import (
    BIOME_TO_STRUCTURE,
    COLISEUM_FLOORS,
    NEURO_BIOMES,
    NEURO_POLES,
    NEURO_STRUCTURES,
    REGION_NEURO,
    REGION_ORIGIN,
    STRUCTURE_TO_BIOME,
    biome_display_name,
)
from app.sse.thera_world_concepts import BIOME_LANDMARKS

ORIGIN_BIOMES = ("dark_forest", "fortress_plains", "river_valley", "crystal_mountains", "open_sky")


# ---------------------------------------------------------------------------
# Catalog + Origin regression
# ---------------------------------------------------------------------------

def test_catalog_shape():
    assert tuple(NEURO_STRUCTURES) == ("authority", "integration", "separation", "attachment")
    assert tuple(NEURO_POLES) == ("deficit", "mature", "hyper")
    assert len(NEURO_BIOMES) == 4
    assert len(ns.POLE_KEYS) == 12
    for s in NEURO_STRUCTURES:
        assert BIOME_TO_STRUCTURE[STRUCTURE_TO_BIOME[s]] == s


def test_origin_landmarks_untouched_and_neuro_added():
    for b in ORIGIN_BIOMES:
        assert b in BIOME_LANDMARKS and len(BIOME_LANDMARKS[b]) >= 3
    for b in NEURO_BIOMES:
        assert b in BIOME_LANDMARKS and len(BIOME_LANDMARKS[b]) == 4
    assert not (set(ORIGIN_BIOMES) & set(NEURO_BIOMES))


def test_champion_roster_integrity():
    roster = ns.load_champions()
    assert len(roster) >= 40
    names = [c["name"] for c in roster]
    assert len(names) == len(set(names)), "champion names must be unique"
    for c in roster:
        assert c["biome_id"] in NEURO_BIOMES
        assert set(c["poles"]) == set(ns.POLE_KEYS)
        assert c.get("purpose"), c["name"]
        assert not ns.client_safe_violations(c["purpose"]), (c["name"], c["purpose"])
    for b in NEURO_BIOMES:
        assert len(ns.champions_for_biome(b, roster)) >= 8


# ---------------------------------------------------------------------------
# Formula
# ---------------------------------------------------------------------------

def test_normalize_signs_and_clamps():
    v = ns.normalize_poles({"authority_deficit": 0.7, "authority_mature": 1.8, "authority_hyper": -0.3, "junk": 9})
    assert v["authority_deficit"] == -0.7          # magnitude → signed
    assert v["authority_mature"] == 1.0            # clamp
    assert v["authority_hyper"] == 0.0             # clamp
    assert "junk" not in v and len(v) == 12
    assert ns.normalize_poles({"authority_deficit": -0.4})["authority_deficit"] == -0.4


def test_domain_health_formula_and_world_health():
    scores = {"authority_mature": 0.8, "authority_deficit": 0.1, "authority_hyper": 0.2,
              "attachment_mature": 0.2, "attachment_deficit": 0.6}
    assert ns.domain_health(scores, "authority") == pytest.approx(0.8 - 0.1 - 0.2)
    assert ns.domain_health(scores, "attachment") == pytest.approx(0.2 - 0.6)
    assert ns.domain_health(scores, "integration") == 0.0
    hd = ns.all_domain_health(scores)
    assert ns.neuro_health(scores) == pytest.approx(sum(hd.values()) / 4)
    assert ns.domain_health({"authority_mature": 1.0}, "authority") == 1.0  # max


def test_stage_classification():
    assert ns.classify_stage({"authority_mature": 0.9}, "authority") == "mature"
    assert ns.classify_stage({"authority_deficit": 0.8, "authority_mature": 0.1}, "authority") == "underdeveloped"
    assert ns.classify_stage({}, "authority") == "quiet"
    assert ns.classify_stage({"authority_mature": 0.5, "authority_hyper": 0.4}, "authority") == "developing"


def test_blend_is_rolling():
    prev = {"authority_hyper": 1.0}
    fresh = {"authority_hyper": 0.0}
    out = ns.blend_scores(prev, fresh, alpha=0.35)
    assert out["authority_hyper"] == pytest.approx(0.65)
    assert ns.blend_scores(None, fresh) == ns.normalize_poles(fresh)


# ---------------------------------------------------------------------------
# Stems → 12 poles (the methodology LN learns)
# ---------------------------------------------------------------------------

def test_every_mapped_stem_hits_a_valid_pole():
    for stem, (s, p) in ns.STEM_TO_POLE.items():
        assert s in NEURO_STRUCTURES and p in NEURO_POLES, stem


def test_scores_from_theme_counts_direction():
    v = ns.scores_from_theme_counts({"control": 6, "anger": 2, "abandonment": 4, "love": 1})
    assert v["authority_hyper"] == pytest.approx(1.0)      # top stem scales to 1
    assert v["attachment_deficit"] < 0                     # signed
    assert v["attachment_mature"] > 0
    assert v["integration_deficit"] == 0.0
    assert ns.select_neuro_biome(v) in (STRUCTURE_TO_BIOME["authority"], STRUCTURE_TO_BIOME["attachment"])


def test_empty_counts_are_quiet():
    assert all(x == 0 for x in ns.scores_from_theme_counts({}).values())
    assert all(x == 0 for x in ns.scores_from_theme_counts(None).values())


def test_growth_stems_lift_all_mature():
    v = ns.scores_from_theme_counts({"hope": 4})
    assert all(v[f"{s}_mature"] > 0 for s in NEURO_STRUCTURES)
    assert all(v[f"{s}_hyper"] == 0 for s in NEURO_STRUCTURES)


def test_metadata_stamp_keeps_stems_and_flags_polarity():
    meta = ns.neuro_metadata_for_stems(["shame", "guilt", "growth", "shame"])
    assert meta["neuro_stems"] == ["shame", "guilt", "growth"]
    assert meta["neuro_structures"] == ["integration"]
    assert meta["neuro_pole_hint"] == "deficit"
    mixed = ns.neuro_metadata_for_stems(["control", "fear"])
    assert "neuro_pole_hint" not in mixed
    assert mixed["neuro_structures"] == ["authority"]


# ---------------------------------------------------------------------------
# Place + champion
# ---------------------------------------------------------------------------

def test_select_biome_is_weakest_hd_with_fixed_tie_order():
    assert ns.select_neuro_biome({}) == STRUCTURE_TO_BIOME["authority"]  # all tie → first
    v = {"separation_deficit": 0.9}
    assert ns.select_neuro_biome(v) == STRUCTURE_TO_BIOME["separation"]


def test_pair_champion_nearest_within_place_and_skip():
    roster = ns.load_champions()
    biome = STRUCTURE_TO_BIOME["authority"]
    target = ns.champions_for_biome(biome, roster)[0]
    picked = ns.pair_champion(target["poles"], biome, roster)
    assert picked is not None and picked["biome_id"] == biome
    # ε-skip: an identical vector is a copy, not a mirror → next nearest
    assert picked["name"] != target["name"]
    # skip yesterday's mirror
    again = ns.pair_champion(target["poles"], biome, roster, skip_names=[picked["name"]])
    assert again["name"] not in (picked["name"],)
    assert ns.pair_champion({}, "not_a_place", roster) is None


def test_visiting_figures_come_from_other_places():
    v = {"authority_deficit": 0.9, "attachment_deficit": 0.5}
    home = ns.select_neuro_biome(v)
    visitors = ns.visiting_figures(v, home, k=2)
    assert 1 <= len(visitors) <= 2
    assert all(c["biome_id"] != home for c in visitors)
    assert len({c["biome_id"] for c in visitors}) == len(visitors)
    assert ns.visiting_figures(v, home, k=0) == []


def test_coliseum_floor_allowlist_and_seed():
    f = ns.roll_coliseum_floor(seed="user:1")
    assert f in COLISEUM_FLOORS
    assert ns.roll_coliseum_floor(seed="user:1") == f


# ---------------------------------------------------------------------------
# Routing — whole-world journey. Healthy vectors enter Neuro too.
# ---------------------------------------------------------------------------

def test_region_routing(monkeypatch):
    monkeypatch.setenv(ns.NEURO_ENV_FLAG, "true")
    strained = {"authority_deficit": 0.8}
    # locked journey → Origin even when strained
    assert ns.resolve_panel_region({"current_biome": "mirror_lake"}, strained) == REGION_ORIGIN
    # unlocked via open_sky → Neuro, including a healthy vector (growth is not a deficit gate)
    j = {"current_biome": "open_sky"}
    assert ns.resolve_panel_region(j, strained) == REGION_NEURO
    assert ns.resolve_panel_region(j, {"authority_mature": 0.9}) == REGION_NEURO
    assert ns.resolve_panel_region(j, {}) == REGION_NEURO
    # alternate: yesterday Neuro and not deeply strained → Origin today (both regions are walked)
    assert ns.resolve_panel_region(j, {"authority_deficit": 0.3}, last_region=REGION_NEURO) == REGION_ORIGIN
    assert ns.resolve_panel_region(j, {"authority_mature": 0.9}, last_region=REGION_NEURO) == REGION_ORIGIN
    # deep strain → back-to-back allowed
    assert ns.resolve_panel_region(j, {"authority_deficit": 0.9}, last_region=REGION_NEURO) == REGION_NEURO
    # unlocked via prior score row
    assert ns.resolve_panel_region({"neuro_last_scored_at": "2026-09-01"}, strained) == REGION_NEURO
    assert ns.resolve_panel_region({"neuro_scores": json.dumps({"authority_deficit": -0.2})}, strained) == REGION_NEURO
    # explicit pick beats unlock and the alternate
    origin_pick = {"current_biome": "open_sky", "journey_metadata": {"explore_region": "origin"}}
    assert ns.resolve_panel_region(origin_pick, strained) == REGION_ORIGIN
    neuro_pick = {"current_biome": "mirror_lake", "journey_metadata": {"explore_region": "neuro"}}
    assert ns.resolve_panel_region(neuro_pick, {}) == REGION_NEURO
    assert ns.resolve_panel_region(
        {"journey_metadata": json.dumps({"explore_region": "neuro"})},
        {"authority_mature": 0.9},
        last_region=REGION_NEURO,
    ) == REGION_NEURO


def test_biome_rotation_skips_recent_places():
    v = {"separation_deficit": 0.9}
    home = ns.select_neuro_biome(v)
    assert home == STRUCTURE_TO_BIOME["separation"]
    nxt = ns.select_neuro_biome(v, avoid=[home])
    assert nxt != home
    assert nxt in STRUCTURE_TO_BIOME.values()


def test_boundaries_and_previously_unmapped_themes_move_poles():
    b = ns.scores_from_theme_counts({"boundaries": 6})
    assert b["separation_mature"] > 0
    assert b["separation_deficit"] == 0
    anxiety = ns.scores_from_theme_counts({"anxiety": 4, "grief": 4, "spiritual": 4})
    assert anxiety["authority_deficit"] < 0
    assert anxiety["attachment_deficit"] < 0
    assert anxiety["authority_mature"] > 0  # spiritual is a growth stem


def test_age_gate_drops_literal_force_figures():
    champ = ns.pair_champion(
        {"authority_hyper": 1.0}, "coliseum_of_ascendance", exclude_names=ns.AGE_GATE_EXCLUDE)
    assert champ is not None
    assert champ["name"] not in ns.AGE_GATE_EXCLUDE


def test_center_is_not_the_defensive_upper_band():
    assert ns.active_band({"authority_mature": 0.9, "authority_hyper": 0.1}, "authority") == ns.BAND_CENTER
    assert ns.active_band({"authority_mature": 0.8, "authority_hyper": 0.8}, "authority") == ns.BAND_UPPER
    assert ns.active_band({"authority_deficit": -0.8}, "authority") == ns.BAND_LOWER
    assert ns.active_band({"attachment_deficit": -0.6, "attachment_hyper": 0.7}, "attachment") == ns.BAND_BOTH


def test_codependency_is_attachment_enmeshment():
    v = ns.scores_from_theme_counts({"codependency": 6})
    assert v["attachment_hyper"] > 0
    assert v["separation_deficit"] == 0


def test_image_line_is_client_safe_and_chat_map_stays_internal():
    scores = {"separation_hyper": 0.9, "integration_deficit": -0.7}
    line = ns.image_change_line(scores, "separation")
    ns.assert_client_safe(line)
    assert "wall" in line.lower()
    chat = ns.compose_growth_navigation(scores)
    assert "internal only" in chat.lower()
    assert "authority" in chat.lower()
    bible = ns.compose_neuro_bible({
        "scores": scores,
        "biome": {"biome": "aerolith_cloud_city"},
        "champion": {"name": "Bridge Warden", "purpose": "keeps a span", "structure": "separation"},
        "metadata": {"place_label": "Aerolith"},
    })
    assert "wall" in bible.lower() or "gate" in bible.lower()


def test_scrub_rewrites_engine_labels():
    out = ns.scrub_client_copy("Your attachment is -0.40 and Authority is 30%.")
    assert "attachment" not in out.lower()
    assert "authority" not in out.lower()
    assert "-0.40" not in out
    assert "%" not in out
    assert "hearth" in out.lower()
    assert "voice" in out.lower()


def test_kill_switch_forces_origin(monkeypatch):
    monkeypatch.setenv(ns.NEURO_ENV_FLAG, "false")
    assert ns.resolve_panel_region({"current_biome": "open_sky"}, {"authority_deficit": 0.9}) == REGION_ORIGIN


# ---------------------------------------------------------------------------
# Client language wall
# ---------------------------------------------------------------------------

def test_language_wall_catches_labels_and_scores():
    assert ns.client_safe_violations("Your attachment is 0.42") 
    assert ns.client_safe_violations("authority deficit 30%")
    assert ns.client_safe_violations("you are hyper-regulated")
    assert not ns.client_safe_violations("The Warlord holds the floor. A gate stands open.")
    with pytest.raises(ValueError):
        ns.assert_client_safe("separation: -0.3")
    assert ns.assert_client_safe("clean") == "clean"


def test_archetype_mirror_is_client_safe_for_every_champion():
    for c in ns.load_champions():
        for hint in ("Seeker", "Guardian", "", None):
            txt = ns.compose_archetype_mirror(c, hint or "", {"authority_deficit": 0.5})
            assert txt and not ns.client_safe_violations(txt), (c["name"], hint, txt)
            assert c["name"] in txt


def test_biome_display_names_are_client_safe():
    for b in NEURO_BIOMES:
        label = biome_display_name(b)
        assert label and "_" not in label
        assert not ns.client_safe_violations(label), label


# ---------------------------------------------------------------------------
# Go Deeper — four lived moves braided, unlabeled, together
# ---------------------------------------------------------------------------

def test_four_move_braid_block():
    block = ns.four_move_braid_block("Coliseum of Ascendance", "Warlord", visitors=["River Daughter", "Hearth-Keeper"])
    assert "Warlord" in block and "Coliseum of Ascendance" in block
    assert "River Daughter" in block and "Hearth-Keeper" in block
    assert not ns.client_safe_violations(block), block
    # all four moves are present in the same block — worked together, never one-at-a-time
    assert len(ns.FOUR_MOVES) == 4
    assert {m["structure"] for m in ns.FOUR_MOVES} == set(NEURO_STRUCTURES)
    for move in ns.FOUR_MOVES:
        assert move["move"] in block, move["key"]
    assert "Work them together" in block
    aimed = ns.four_move_braid_block(
        "Aerolith", "Bridge Warden",
        change_line=ns.image_change_line({"separation_hyper": 0.9}, "separation"),
    )
    assert "wall" in aimed.lower()
    assert not ns.client_safe_violations(aimed)
    # engine vocabulary never reaches the client block (the instruction lines name
    # "category/score/level" only as prohibitions — those are allowed)
    assert not re.search(r"\b(domain|structure|pole|deficit|hyper)\b", block, re.IGNORECASE)


# ---------------------------------------------------------------------------
# Legend wiring (symbol_safety) — purpose + archetype mirror
# ---------------------------------------------------------------------------

def test_figures_in_narrative_neuro_scan_is_biome_gated():
    nar = "The Sovereign waits at the Crown of Verdict while the Warlord paces. A sense of wonder."
    neuro = ss.figures_named_in_narrative(nar, biome="coliseum_of_ascendance")
    assert "Warlord" in neuro and "The Sovereign" in neuro
    assert "The Wonder" not in neuro          # whole-name only
    origin = ss.figures_named_in_narrative(nar, biome="fractured_canyons")
    assert "Warlord" not in origin and "The Sovereign" not in origin


def test_codex_entry_uses_champion_purpose():
    entry = ss._codex_entry_for_character("Warlord", {})
    assert entry["region"] == "neuro"
    assert entry["meaning"] == ns.champion_by_name("Warlord")["purpose"]
    origin_entry = ss._codex_entry_for_character("Mirror", {})
    assert origin_entry.get("region") != "neuro"


def test_enrich_panel_legend_neuro_bundle():
    nar = "The Warlord holds the floor. River Daughter watches from the gate."
    legend = [{"symbol_id": None, "display_name": "Warlord", "tier": "low_risk", "state": "allowed",
               "meaning": ns.champion_by_name("Warlord")["purpose"]}]
    b = ss.enrich_panel_legend(legend, character_name="Warlord", narrative_text=nar,
                               biome="coliseum_of_ascendance", archetype_hint="Seeker", panel_sequence=3)
    assert b["region"] == "neuro"
    assert b["biome_label"] == "Coliseum of Ascendance"
    assert "coliseum_of_ascendance" not in b["journey_thread"]
    row = b["legend"][0]
    assert row["is_core"] and row["region"] == "neuro"
    assert row["purpose"] and row["archetype_mirror"]
    assert "Seeker" in row["archetype_mirror"]
    assert "somewhere near it" not in row["archetype_mirror"]
    for k in ("purpose", "archetype_mirror", "figure_in_panel"):
        assert not ns.client_safe_violations(row[k]), (k, row[k])
    aimed = ss.enrich_panel_legend(
        legend, character_name="Warlord", narrative_text=nar,
        biome="coliseum_of_ascendance", archetype_hint="Seeker", panel_sequence=3,
        user_scores={"authority_hyper": 0.85},
    )
    mirror = aimed["legend"][0]["archetype_mirror"]
    assert "gripping the hall" in mirror.lower()
    assert "continuing read" not in aimed["journey_thread"].lower()
    assert "gripping the hall" in aimed["journey_thread"].lower()
    assert not ns.client_safe_violations(mirror)
    assert not ns.client_safe_violations(aimed["journey_thread"])


def test_should_replace_today_panel():
    assert ns.should_replace_today_panel(None, "neuro") is True
    assert ns.should_replace_today_panel("", "origin") is True
    assert ns.should_replace_today_panel("origin", "neuro") is True
    assert ns.should_replace_today_panel("neuro", "origin") is True
    assert ns.should_replace_today_panel("origin", "origin") is False
    assert ns.should_replace_today_panel("neuro", "neuro") is False


def test_journey_image_r2_key_and_pointer():
    k = ns.journey_image_r2_key("U1", "2026-09-26", "neuro", "abc123")
    assert k == "sse/journey/U1/2026-09-26/neuro/abc123.png"
    o = ns.journey_image_r2_key("U1", "2026-09-26", "origin", "abc123")
    assert o == "sse/journey/U1/2026-09-26/origin/abc123.png"
    junk = ns.journey_image_r2_key("U1", "2026-09-26", "wander", "abc123")
    assert "/origin/" in junk
    assert ns.explore_pointer_key("hw") == "sse/journey/hw/explore_region.json"


def test_merge_alias_ids_unique_order():
    assert ns.merge_alias_ids("HW", "user", "HW", "", None) == ["HW", "user"]


def test_compose_walk_addendum_follows_pick_and_still():
    t = ns.compose_walk_addendum("neuro", "origin", "coliseum_of_ascendance", "Warlord", "A hall.")
    assert "THERA WALK" in t
    assert "walk Neuro today" in t
    assert "Today's still is origin" in t
    t2 = ns.compose_walk_addendum("neuro", "neuro", "coliseum_of_ascendance", "Warlord", "")
    assert "Today's still is neuro" in t2
    assert "Coliseum of Ascendance" in t2
    t3 = ns.compose_walk_addendum("wander", "neuro", "hearth_of_return", "River Daughter", "")
    assert "path to choose" in t3
    assert "Today's still is neuro" in t3


def test_enrich_panel_legend_origin_unchanged():
    b = ss.enrich_panel_legend([], character_name="Mirror", narrative_text="Still water.", biome="mirror_lake")
    assert b["region"] == "origin" and b["biome_label"] == "mirror_lake"
    assert "purpose" not in b["legend"][0]
