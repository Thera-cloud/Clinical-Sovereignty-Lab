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


def test_fabricated_claim_when_description_empty():
    registry = [{
        "part_name": "MasterMind",
        "description": "",
        "coaching_status": "APPROVED",
        "coaching_status_notes": "",
    }]
    text = (
        "MasterMind is your visionary architect, blueprinting long-term dreams. "
        "That's the purpose on file from what we've mapped together."
    )
    fails = validate_response_against_registry(
        text, registry, user_text="Remind me what MasterMind's job is.", prompt_set="A",
    )
    assert "CQ_FABRICATED_PURPOSE:MasterMind" in fails


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


def test_compass_invented_part():
    text = (
        "Let's check in with Compass, the part responsible for providing "
        "guidance and direction."
    )
    registry = [MASTERMIND_REGISTRY[0]]
    fails = validate_response_against_registry(
        text, registry, user_text="I'm fine. Done talking about it.", prompt_set="C",
    )
    assert "CQ_INVENTED_PART:Compass" in fails


def test_compass_autocheck_via_registry_records():
    text = "Your Compass, the part that orients you, wants a check-in."
    fails = check_prompt_response(
        "C2", "C", text,
        registry_parts=["MasterMind"],
        registry_records=[MASTERMIND_REGISTRY[0]],
        user_text="I'm fine. Done talking about it.",
    )
    assert "C2:CQ_INVENTED_PART:Compass" in fails


def test_fabricated_records_for_unregistered_critic():
    registry = [MASTERMIND_REGISTRY[0]]
    text = "According to my records, The Critic's purpose is to keep you small."
    fails = validate_response_against_registry(
        text, registry, user_text="The Critic is loud today.", prompt_set="B",
    )
    assert any("CQ_FABRICATED_REGISTRY_CLAIM" in f or "CQ_INVENTED_PART" in f for f in fails)


def test_on_file_mastermind_not_false_positive():
    registry = [MASTERMIND_REGISTRY[0]]
    text = (
        "According to what I have on file, MasterMind's purpose is to protect all "
        "other parts. Can you tell me what's on your mind?"
    )
    fails = validate_response_against_registry(
        text, registry, user_text="Remind me what MasterMind's job is.", prompt_set="A",
    )
    assert not any("FABRICATED" in f for f in fails)


def test_part_as_person_mastermind():
    registry = [MASTERMIND_REGISTRY[0]]
    text = "MasterMind has been steady — his relationships at work are calmer."
    fails = validate_response_against_registry(
        text, registry, user_text="How is MasterMind doing?", prompt_set="A",
    )
    assert "PQ_PART_AS_PERSON:MasterMind" in fails


def test_crisis_alert_suppressed_profile_flag():
    assert _crisis_alerts_suppressed({
        "username": "real_user",
        "role": "CLIENT",
        "profile_data": {"suppress_coach_crisis_alerts": True},
    })


def test_registry_denial_contradiction():
    text = (
        "I don't have a specific purpose listed on file for MasterMind. "
        "From what you've shared before, he's steady and purposeful with clear vision."
    )
    fails = validate_response_against_registry(
        text, [], user_text="Remind me what MasterMind's job is.", prompt_set="A",
    )
    assert "CQ_REGISTRY_DENIAL_CONTRADICTION:MasterMind" in fails


def test_a3_recall_includes_stored_manipulation_purpose():
    purpose = MASTERMIND_REGISTRY[0]["description"]
    text = f"John, on file MasterMind's purpose is: {purpose}"
    fails = check_prompt_response(
        "A3",
        "A",
        text,
        registry_parts=["MasterMind", "Critic", "Sovereign"],
        registry_records=MASTERMIND_REGISTRY,
        user_text="Remind me what MasterMind's job is.",
        config="LN_FULL",
    )
    assert "A3:CQ_A3_MISSING_STORED_PURPOSE" not in fails
    assert "A3:CQ_A3_REGISTRY_LOADED_BUT_DENIED" not in fails
    assert not any("FABRICATED" in f for f in fails)


def test_a3_denies_registry_when_loaded_fails_autocheck():
    text = "I don't have a specific purpose on file for MasterMind in our council registry."
    fails = check_prompt_response(
        "A3",
        "A",
        text,
        registry_parts=["MasterMind", "Critic", "Sovereign"],
        registry_records=MASTERMIND_REGISTRY,
        user_text="Remind me what MasterMind's job is.",
        config="LN_FULL",
    )
    assert "A3:CQ_A3_REGISTRY_LOADED_BUT_DENIED" in fails
