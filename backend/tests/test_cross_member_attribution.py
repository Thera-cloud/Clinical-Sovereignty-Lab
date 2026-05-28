"""Layer 8c — cross-member private attribution output gate."""

import asyncio

import pytest

from app.services.family_system_field import LANE_MEMBER, project_fsf
from app.services.nate_response_validator import NateResponseValidator
from app.services.response_validator_bridge import validate_before_send


@pytest.mark.asyncio
async def test_blocks_spouse_told_me():
    v = NateResponseValidator()
    _, warnings = await v.validate(
        "Your spouse told me you've been struggling with trust.",
        context={"client_message": "I wonder if she said anything about me."},
    )
    assert "cross_member_private_attribution" in warnings


@pytest.mark.asyncio
async def test_allows_client_relay_to_you():
    v = NateResponseValidator()
    _, warnings = await v.validate(
        "It sounds like your spouse told you something that hurt.",
        context={"client_message": "My spouse told me I don't care."},
    )
    assert "cross_member_private_attribution" not in warnings


@pytest.mark.asyncio
async def test_allows_sanctuary_framing():
    v = NateResponseValidator()
    _, warnings = await v.validate(
        "In Sanctuary, when you both shared about the cycle, I heard pain on both sides.",
        context={"client_message": "What happened in Sanctuary?"},
    )
    assert "cross_member_private_attribution" not in warnings


@pytest.mark.asyncio
async def test_validate_before_send_redirects():
    result = await validate_before_send(
        "Member A told me about your anger.",
        ["Did my partner say anything about me?"],
        user_id="alice",
        session_id="sess-1",
    )
    assert result["safe"] is False
    assert result["reason"] == "cross_member_private_attribution"
    assert "don" in result["redirect"].lower() and "share" in result["redirect"].lower()


def test_member_abstract_never_leaks_other_member():
    rows = [
        {
            "visibility_lane": LANE_MEMBER,
            "content": "Withdrawal pattern under stress.",
            "subject_username": "bob",
            "source_surface": "sanctuary_complete",
        },
        {
            "visibility_lane": LANE_MEMBER,
            "content": "Own pursue pattern.",
            "subject_username": "alice",
            "source_surface": "sanctuary_complete",
        },
    ]

    class FakeConn:
        async def fetch(self, query, family_id):
            return rows

    class FakePool:
        def acquire(self):
            return self

        async def __aenter__(self):
            return FakeConn()

        async def __aexit__(self, *a):
            pass

    import app.services.family_system_field as fsf

    async def fake_names(db_pool, family_id):
        return ["Alice", "Bob"]

    async def noop_audit(*a, **k):
        return None

    orig_names = fsf._family_member_names
    orig_audit = fsf._audit
    fsf._family_member_names = fake_names
    fsf._audit = noop_audit
    try:
        proj = asyncio.get_event_loop().run_until_complete(
            project_fsf(
                FakePool(),
                family_id="fam-1",
                requester_username="alice",
                user_message="I feel distant lately.",
            )
        )
    finally:
        fsf._family_member_names = orig_names
        fsf._audit = orig_audit

    member_entries = [e for e in proj.entries if e.visibility_lane == LANE_MEMBER]
    assert all(e.subject_username != "bob" for e in member_entries)
    assert any(e.subject_username == "alice" for e in member_entries)
