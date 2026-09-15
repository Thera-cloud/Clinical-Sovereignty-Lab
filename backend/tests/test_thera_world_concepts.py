"""Thera-world concept palette — LN and journey imagery share one world."""

from app.sse.thera_world_concepts import (
    COMPANION_NAMES,
    format_thera_world_concept_palette,
)


def test_palette_names_core_world_and_expansion_room():
    block = format_thera_world_concept_palette(
        biome="river_valley",
        core_character="Mirror",
        quest_goal="mend the stepping stones",
        mission_target="walk with The Mender",
        present_npcs=[{"name": "The Cartographer"}],
    )
    assert "Little Nate" in block
    assert "Thera-world" in block
    assert "river_valley" in block.replace(" ", "_") or "river valley" in block
    assert "Mirror" in block
    assert "The Cartographer" in block
    assert "The Weaver" in block
    assert "1–3" in block or "1-3" in block
    assert "Do not invent a city" in block
    assert "mend the stepping stones" in block
    assert len(COMPANION_NAMES) >= 20


def test_palette_omits_clinical_hold_quest_noise():
    block = format_thera_world_concept_palette(
        biome="dark_forest",
        core_character="Serpent",
        quest_goal="none (clinical hold — no action-oriented missions)",
        mission_target="none (clinical hold)",
    )
    assert "clinical hold" not in block.lower()
    assert "Serpent" in block
