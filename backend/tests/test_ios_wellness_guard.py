from app.services.ios_wellness_guard import (
    IOS_WELLNESS_PROMPT,
    enforce_ios_wellness_response,
    find_ios_wellness_violations,
)


def test_prompt_forbids_medical_outputs():
    assert "HIGHEST PRIORITY" in IOS_WELLNESS_PROMPT
    assert "Do not diagnose" in IOS_WELLNESS_PROMPT
    assert "health-related measurements" in IOS_WELLNESS_PROMPT


def test_safe_reflection_is_preserved():
    response = "What feels most important about this fear right now?"
    assert enforce_ios_wellness_response("I feel afraid", response) == response


def test_diagnostic_and_measurement_outputs_are_replaced():
    diagnostic = "It sounds like PTSD."
    measurement = "Your emotional coherence is 0.42 with a high risk level."

    assert find_ios_wellness_violations("Why am I afraid?", diagnostic)
    assert find_ios_wellness_violations("How am I doing?", measurement)
    assert "Seek a doctor's advice" in enforce_ios_wellness_response(
        "Why am I afraid?", diagnostic
    )
    assert "emotional coherence" not in enforce_ios_wellness_response(
        "How am I doing?", measurement
    )


def test_self_harm_language_always_receives_crisis_resources():
    guarded = enforce_ios_wellness_response(
        "I want to kill myself", "Tell me what hurts underneath that."
    )
    assert "988" in guarded
    assert "911" in guarded
    assert "cannot provide emergency or medical care" in guarded
