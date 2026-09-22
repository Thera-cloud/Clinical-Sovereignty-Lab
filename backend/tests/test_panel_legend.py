"""Offline C3 legend enrichment — figure descriptives + prior-panel journey thread."""
from app.sse.symbol_safety import (
    compose_figure_in_panel,
    compose_journey_thread,
    compose_prior_note,
    enrich_panel_legend,
    figures_named_in_narrative,
    name_mentioned,
)


def test_figure_in_panel_names_core_and_role():
    text = compose_figure_in_panel(
        "The Torchbearer",
        role="carries light a few steps ahead",
        narrative="The Torchbearer waits at the edge of the dark.",
        is_core=True,
        biome="night_path",
    )
    assert "Torchbearer waits" in text
    assert "carries light" in text
    assert "emerging" not in text.lower()


def test_prior_note_links_earlier_biome():
    note = compose_prior_note("The Weaver", [
        {"character_manifest": "The Weaver", "narrative_text": "", "biome": "woven_grove"},
    ])
    assert "woven grove" in note.lower()
    assert "prior panel" in note.lower()
    assert compose_prior_note("The Weaver", []) == ""


def test_journey_thread_continues_from_prior():
    thread = compose_journey_thread(
        panel_sequence=4,
        biome="stillwater_shore",
        narrative="A lantern rests on the bank.",
        character_name="The Ferryman",
        prior_panels=[{
            "character_manifest": "The Torchbearer",
            "narrative_text": "Light held at the ridge.",
            "biome": "night_path",
        }],
        last_panel_summary="",
    )
    assert "Panel 4" in thread
    assert "lantern" in thread.lower()
    assert "continuing read" not in thread.lower()
    assert "Torchbearer" in thread
    assert "night path" in thread


def test_enrich_adds_descriptives_and_empty_scene_fallback():
    bundle = enrich_panel_legend(
        [{"display_name": "The Mender", "meaning": "Shown ordinarily."}],
        character_name="The Mender",
        narrative_text="The Mender stitches gold into torn cloth.",
        biome="healing_atelier",
        npc_details=[{"name": "The Mender", "role": "stitches torn places with gold"}],
        prior_panels=[{
            "character_manifest": "The Mender",
            "narrative_text": "Yesterday the seam was still open.",
            "biome": "quiet_room",
        }],
        panel_sequence=3,
    )
    assert bundle["panel_sequence"] == 3
    entry = bundle["legend"][0]
    assert entry["is_core"] is True
    assert entry["seen_before"] is True
    assert "gold" in (entry["role"] + entry["figure_in_panel"])
    assert "quiet room" in entry["prior_note"].lower()
    assert "Panel 3" in bundle["journey_thread"]

    empty = enrich_panel_legend(
        [],
        narrative_text="Mist over the water.",
        biome="stillwater_shore",
    )
    assert empty["legend"]
    assert empty["legend"][0]["display_name"] == "The scene"
    assert "mist" in empty["journey_thread"].lower()
    assert "continuing read" not in empty["journey_thread"].lower()


def test_name_mentioned_matches_bare_catalog_form():
    assert name_mentioned("The Weaver", "the weaver waits at the loom")
    assert name_mentioned("The Cartographer", "Cartographer refining his map")
    assert name_mentioned("Serpent", "the serpent rises from the water")
    assert not name_mentioned("The Weaver", "a bird weaves through the trees")


def test_figures_named_in_narrative_finds_catalog_and_core():
    names = figures_named_in_narrative(
        "You stand with the Cartographer when the Serpent rises from the waters."
    )
    assert "The Cartographer" in names
    assert "Serpent" in names


def test_prior_note_matches_bare_name_in_older_panel():
    note = compose_prior_note("The Weaver", [
        {"character_manifest": "Mirror", "narrative_text": "A weaver mends the torn thread.", "biome": "woven_grove"},
    ])
    assert "woven grove" in note.lower()
