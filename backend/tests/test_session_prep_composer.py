"""Client-specific session prep — insight, not last-chat echo."""

from app.services.session_prep_composer import (
    compose_panel_prep_points,
    compose_session_prep_points,
)


def test_prep_splits_pattern_vs_secondary():
    a = compose_session_prep_points({
        "recent_conversations": [
            {"user": "I keep disappearing when Kristy asks what I need."},
        ],
        "crystal_memory": [
            {"domain": "clinical", "content_summary": "John withdraws when asked to name a need."},
        ],
    })
    b = compose_session_prep_points({
        "recent_conversations": [
            {"user": "The shame hits before I even walk into the room."},
        ],
        "crystal_memory": [
            {"domain": "clinical", "content_summary": "Lisa's shame spike arrives at the doorway."},
        ],
    })
    joined_a = " ".join(a).lower()
    joined_b = " ".join(b).lower()
    assert "withdraw" in joined_a
    assert "shame" in joined_b
    assert "secondary" in joined_b
    assert "conviction" in joined_b
    assert "open on what they last" not in joined_a
    assert not any(p.lower().startswith("register:") for p in a + b)
    assert not any("companion into the wound" in p.lower() for p in a + b)
    assert 3 <= len(a) <= 5 and 3 <= len(b) <= 5


def test_skips_template_crystals():
    points = compose_session_prep_points({
        "crystal_memory": [
            {
                "domain": "clinical",
                "content_summary": "Here is the synthesized insight crystal for the clinical domain: shame.",
            }
        ],
        "intake_summary": {"has_any_answers": False, "section_1_completion_pct": 0},
    })
    joined = " ".join(points).lower()
    assert "synthesized insight crystal" not in joined
    assert "no personal thread" in joined
    assert 3 <= len(points) <= 5


def test_skips_zoom_hello_leftover():
    points = compose_session_prep_points({
        "recent_conversations": [{"user": "Hello?"}],
        "prior_session_summaries": [
            {"summary": "Quick recap The meeting began with Nathaniel saying Hello?"},
        ],
    })
    joined = " ".join(points).lower()
    assert "quick recap" not in joined
    assert "saying hello" not in joined


def test_trauma_beats_thrive_coaching():
    points = compose_session_prep_points({
        "growth_phase": {"phase": "thrive"},
        "recent_conversations": [
            {"user": "The flashback came back last night after they hurt me."},
        ],
    })
    joined = " ".join(points).lower()
    assert "traumatic" in joined
    assert "not in trauma repair" not in joined
    assert 3 <= len(points) <= 5


def test_thrive_coaching_when_not_repair():
    points = compose_session_prep_points({
        "growth_phase": {"phase": "thrive"},
        "recent_conversations": [
            {"user": "I want to finish my calendar this week and get the deadline off my back."},
        ],
    })
    joined = " ".join(points).lower()
    assert "not in trauma repair" in joined
    assert "calendar" in joined
    assert "register:" not in joined
    assert "companion into the wound" not in joined
    assert 3 <= len(points) <= 5


def test_unresolved_anxiety_and_depression():
    points = compose_session_prep_points({
        "recent_conversations": [
            {"user": "I'm still anxious and the panic came back. I feel hopeless and can't get out of bed."},
        ],
    })
    joined = " ".join(points).lower()
    assert "anxiety" in joined
    assert "depressive" in joined or "sadness" in joined
    assert 3 <= len(points) <= 5


def test_panel_prep_is_client_thera_world_not_slogans():
    points = compose_panel_prep_points({
        "recent_panel_insights": [
            {
                "source": "delivery",
                "clinical_translation": {
                    "clinical_summary": (
                        "In this IFS-informed panel, the client engages an explorer "
                        "archetype with Curiosity, the Orchard Keeper, and the Cloakless Traveler."
                    ),
                    "therapeutic_modality": "IFS",
                    "narrative_text": (
                        "The Cloakless Traveler sets the cloak on a stone in the dark forest "
                        "and does not pick it back up."
                    ),
                },
            }
        ],
        "thera_world_scene": {
            "biome": "dark_forest",
            "character": "Cloakless Traveler",
            "narrative": (
                "The Cloakless Traveler sets the cloak on a stone in the dark forest "
                "and does not pick it back up."
            ),
            "npcs": ["Bridgewright", "Archivist"],
        },
        "crystal_memory": [
            {"domain": "clinical", "content_summary": "John withdraws when asked to name a need."},
        ],
        "recent_conversations": [
            {"user": "I keep disappearing when Kristy asks what I need."},
        ],
    })
    joined = " ".join(points).lower()
    assert 3 <= len(points) <= 3
    assert "cloakless" in joined
    assert "withdraw" in joined or "disappear" in joined or "need" in joined
    assert "dark forest" in joined or "cloak" in joined
    assert "who protects, who structures" not in joined
    assert "the image is the door" not in joined
    assert "art-as-witness" not in joined
    assert '"clinical_summary"' not in joined
    assert "ifs-informed panel" not in joined


def test_panel_prep_differs_by_client_memory():
    a = compose_panel_prep_points({
        "thera_world_scene": {
            "biome": "dark_forest",
            "character": "Cloakless Traveler",
            "narrative": "The traveler leaves the cloak on a stone.",
            "npcs": ["Bridgewright"],
        },
        "crystal_memory": [
            {"domain": "clinical", "content_summary": "John withdraws when asked to name a need."},
        ],
        "recent_conversations": [
            {"user": "I keep disappearing when Kristy asks what I need."},
        ],
        "recent_panel_insights": [{"clinical_translation": {"narrative_text": "cloak on a stone"}}],
    })
    b = compose_panel_prep_points({
        "thera_world_scene": {
            "biome": "river_valley",
            "character": "Serpent",
            "narrative": "Ripples circle the bank and never strike.",
            "npcs": ["The Stillwater Monk"],
        },
        "crystal_memory": [
            {"domain": "clinical", "content_summary": "Lisa's shame spike arrives at the doorway."},
        ],
        "recent_conversations": [
            {"user": "The shame hits before I even walk into the room."},
        ],
        "recent_panel_insights": [{"clinical_translation": {"narrative_text": "ripples on the bank"}}],
    })
    ja, jb = " ".join(a).lower(), " ".join(b).lower()
    assert a != b
    assert "cloakless" in ja or "withdraw" in ja
    assert "shame" in jb
    assert "serpent" in jb or "stillwater" in jb or "ripples" in jb
    assert "who protects, who structures" not in ja + jb
    assert "the image is the door" not in ja + jb


def test_panel_prep_empty_without_world():
    assert compose_panel_prep_points({
        "recent_conversations": [{"user": "I keep disappearing when asked."}],
    }) == []
