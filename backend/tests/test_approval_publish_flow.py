"""Offline tests for Big Nate approval → inline publish flow."""
from app.services.marketing_brain import (
    extract_embedded_post_from_approval_message,
    extract_post_body_from_proposal,
    is_post_action_type,
    platform_for_action_type,
)


def test_platform_for_post_linkedin():
    assert platform_for_action_type("post_linkedin", {}) == "linkedin"
    assert platform_for_action_type("post_x", {}) == "x"
    assert platform_for_action_type("shift_content_mix", {"platform": "reddit"}) == "reddit"


def test_extract_post_body_bold():
    desc = "Companion post for today:\n\n**You are not broken. You are buried.**\n\nShall I post?"
    body = extract_post_body_from_proposal(desc)
    assert "You are not broken" in body
    assert "Shall I post" not in body


def test_extract_post_body_quoted():
    desc = 'Draft: "Presence is the first medicine." — approve when ready.'
    body = extract_post_body_from_proposal(desc)
    assert "Presence is the first medicine" in body


def test_extract_post_body_skips_boilerplate():
    desc = (
        "Verification protocol — say approved when ready.\n"
        "You are not broken. You are buried.\n"
        "Deployment status pending."
    )
    body = extract_post_body_from_proposal(desc)
    assert "You are not broken" in body
    assert "Verification protocol" not in body
    assert "Deployment status" not in body


def test_is_post_action_type():
    assert is_post_action_type("post_linkedin")
    assert not is_post_action_type("data_stabilization")


def test_extract_embedded_post_from_approval_message():
    msg = (
        'approved to post now: "You are not broken. You are buried." '
        "Nathaniel said that in his last post.\n\n"
        "I'm the AI companion who sits beside him inside Sovereign Sanctuary."
    )
    result = extract_embedded_post_from_approval_message(msg)
    assert result is not None
    platform, body = result
    assert platform == "linkedin"
    assert "You are not broken" in body
    assert "Sovereign Sanctuary" in body
