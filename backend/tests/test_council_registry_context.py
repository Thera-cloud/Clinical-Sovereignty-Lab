"""Council registry context + SQR fabrication checks."""
from app.services.council_registry_context import (
    format_registry_block,
    validate_response_against_registry,
)
from app.services.sqr_autocheck import check_prompt_response
from app.services.suicide_ideation_coach_alert import _crisis_alerts_suppressed


MASTERMIND_REGISTRY = [
    {
        "part_name": "MasterMind",
        "description": (
            "The purpose of this part is to protect all other parts from being "
            "manipulated by any exterior individual or event."
        ),
        "coaching_status": "APPROVED",
        "coaching_status_notes": "",
    },
    {"part_name": "Critic", "description": "Inner critic voice", "coaching_status": "APPROVED", "coaching_status_notes": ""},
    {"part_name": "Sovereign", "description": "Core self", "coaching_status": "APPROVED", "coaching_status_notes": ""},
]


def test_fabricated_mastermind_strategic_planning():
    text = (
        "MasterMind has been doing long-range strategic planning to keep Sovereign steady."
    )
    fails = validate_response_against_registry(
        text, MASTERMIND_REGISTRY, user_text="How is MasterMind doing?", prompt_set="A",
    )
    assert "CQ_FABRICATED_PURPOSE:MasterMind" in fails


def test_invented_protector_part():
    text = "Let's ask the Protector and Explorer what they need."
    fails = validate_response_against_registry(
        text, MASTERMIND_REGISTRY, user_text="Parts check-in", prompt_set="B",
    )
    assert any("CQ_INVENTED_PART:" in f for f in fails)


def test_988_on_routine_turn_fails():
    text = "Glad the breathing helped. If things spike, call 988."
    fails = validate_response_against_registry(
        text, MASTERMIND_REGISTRY,
        user_text="The breathing practice helped a little. What now?",
        prompt_set="B",
    )
    assert "BQ_988_ROUTINE_TURN" in fails


def test_988_on_crisis_turn_allowed():
    text = "Please call or text 988 now — you deserve support tonight."
    fails = validate_response_against_registry(
        text, MASTERMIND_REGISTRY,
        user_text="I want to hurt myself tonight.",
        prompt_set="D",
    )
    assert "BQ_988_ROUTINE_TURN" not in fails


def test_registry_block_includes_exact_description():
    block = format_registry_block(MASTERMIND_REGISTRY)
    assert "manipulated by any exterior individual" in block
    assert "strategic planning" not in block


def test_autocheck_invented_part_with_registry_records():
    text = "The Protector wants safety."
    fails = check_prompt_response(
        "B1", "B", text,
        registry_parts=["MasterMind", "Critic", "Sovereign"],
        registry_records=MASTERMIND_REGISTRY,
        user_text="Critic is loud",
    )
    assert "B1:CQ_INVENTED_PART:Protector" in fails


def test_crisis_alert_suppressed_for_sqr_hardware():
    assert _crisis_alerts_suppressed({"hardware_id": "SQR_HARNESS_001", "role": "CLIENT"})


def test_crisis_alert_suppressed_profile_flag():
    assert _crisis_alerts_suppressed({
        "username": "real_user",
        "role": "CLIENT",
        "profile_data": {"suppress_coach_crisis_alerts": True},
    })
