import pytest

from app.services.intake_form_service import (
    format_identity_forge_for_nate,
    get_nate_client_memory,
    get_section1_for_nate,
    validate_style_guidance_text,
)


class _FakeConn:
    def __init__(self, row):
        self._row = row

    async def fetchrow(self, *_args, **_kwargs):
        return self._row


@pytest.mark.asyncio
async def test_s1_context_empty_contract_returns_empty_string():
    conn = _FakeConn(
        {
            "user_id": "client_a",
            "coach_nate_style_guidance": "",
            "q1_preferred_name": None,
            "q2_pronouns": None,
            "q3_household_relationship": None,
            "q4_bringing_you_in": None,
            "q5_how_long": None,
            "q6_hope_to_get": None,
            "q7_successful_outcome": None,
            "q8_biggest_things_weighing": None,
            "q9_support_network": None,
            "q10_current_wellbeing": None,
            "q11_communication_preferences": None,
            "q12_anything_else_upfront": None,
        }
    )
    out = await get_section1_for_nate(conn, "client_a")
    assert out == ""


@pytest.mark.asyncio
async def test_s1_context_includes_style_guidance_and_no_section2_fields():
    conn = _FakeConn(
        {
            "user_id": "client_a",
            "coach_nate_style_guidance": "Use concise choices and leave 4-5 seconds before suggestions.",
            "q1_preferred_name": "Alex",
            "q2_pronouns": "they/them",
            "q3_household_relationship": None,
            "q4_bringing_you_in": "I keep shutting down in conflict.",
            "q5_how_long": None,
            "q6_hope_to_get": None,
            "q7_successful_outcome": None,
            "q8_biggest_things_weighing": None,
            "q9_support_network": None,
            "q10_current_wellbeing": None,
            "q11_communication_preferences": None,
            "q12_anything_else_upfront": None,
        }
    )
    out = await get_section1_for_nate(conn, "client_a")
    assert "CLIENT INTAKE (SAVED)" in out
    assert "Alex" in out
    assert "Coach rapport guidance" in out
    assert "q13_emergency_contact_name" not in out
    assert "Emergency contact" not in out


def test_validate_style_guidance_accepts_behavioral_guidance():
    ok, err = validate_style_guidance_text(
        "Use concrete options and check understanding before moving to solutions."
    )
    assert ok is True
    assert err is None


def test_validate_style_guidance_rejects_clinical_diagnostic_language():
    ok, err = validate_style_guidance_text(
        "Client likely has PTSD and should be treated as bipolar."
    )
    assert ok is False
    assert "diagnosis language" in (err or "")


def test_identity_forge_formats_eleven_user_answers():
    hist = []
    for i in range(11):
        hist.append({"role": "assistant", "content": f"q{i+1}"})
        hist.append({"role": "user", "content": f"answer {i+1} remembered"})
    out = format_identity_forge_for_nate(hist)
    assert "IDENTITY FORGE (SAVED" in out
    assert "Never recast them as a victim" in out
    assert "11. Story symbols that must never appear: answer 11 remembered" in out
    assert "What brought them here: answer 2 remembered" in out


class _SplitConn:
    def __init__(self, form_row, forge_row):
        self._form_row = form_row
        self._forge_row = forge_row

    async def fetchrow(self, sql, *_args, **_kwargs):
        if "sse_identity_forge" in sql:
            return self._forge_row
        return self._form_row


@pytest.mark.asyncio
async def test_nate_client_memory_appends_identity_forge():
    conn = _SplitConn(
        {
            "user_id": "client_a",
            "coach_nate_style_guidance": "",
            "q1_preferred_name": "Alex",
            "q2_pronouns": None,
            "q3_household_relationship": None,
            "q4_bringing_you_in": None,
            "q5_how_long": None,
            "q6_hope_to_get": None,
            "q7_successful_outcome": None,
            "q8_biggest_things_weighing": None,
            "q9_support_network": None,
            "q10_current_wellbeing": None,
            "q11_communication_preferences": None,
            "q12_anything_else_upfront": None,
        },
        {
            "conversation_history": [
                {"role": "assistant", "content": "ok?"},
                {"role": "user", "content": "yes remember this"},
            ]
        },
    )
    out = await get_nate_client_memory(conn, "client_a")
    assert "CLIENT INTAKE (SAVED)" in out
    assert "IDENTITY FORGE (SAVED" in out
    assert "yes remember this" in out
