"""Client-specific session prep — insight, not last-chat echo."""

from app.services.session_prep_composer import compose_session_prep_points


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
    assert len(a) <= 5 and len(b) <= 5


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
    assert len(points) <= 5


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


def test_unresolved_anxiety_and_depression():
    points = compose_session_prep_points({
        "recent_conversations": [
            {"user": "I'm still anxious and the panic came back. I feel hopeless and can't get out of bed."},
        ],
    })
    joined = " ".join(points).lower()
    assert "anxiety" in joined
    assert "depressive" in joined or "sadness" in joined
