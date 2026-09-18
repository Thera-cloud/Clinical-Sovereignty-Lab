"""Client-specific session prep — not Growth EFT slogans."""

from app.services.session_prep_composer import compose_session_prep_points


def test_prep_uses_last_words_not_framework():
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
    assert "disappearing" in joined_a
    assert "shame" in joined_b
    assert "disappearing" not in joined_b
    assert not any(p.lower().startswith("register:") for p in a + b)
    assert not any("companion into the wound" in p.lower() for p in a + b)


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
    assert "no personal thread" in joined or "intake is still blank" in joined


def test_thrive_goal_joins_without_repeating_questions():
    points = compose_session_prep_points(
        {
            "recent_conversations": [
                {"user": "I told my father I was done being the family fixer."},
            ]
        },
        thrive={
            "goals_active": [{"text": "Tell dad one true sentence a week", "progress_pct": 20}],
            "core_questions": ["What happened, and what did it mean about you?"],
            "session_guidance": [
                "Register: companion into the wound, steady, unhurried.",
                "EFT: Stage 1 Steps 3-4.",
            ],
        },
    )
    joined = " ".join(points).lower()
    assert "tell dad one true sentence" in joined
    assert "what happened, and what did it mean" not in joined
    assert "companion into the wound" not in joined
