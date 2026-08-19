"""INV-3 approve then publish; 409 if open flags."""

from _studio_load import load_svc

_ep = load_svc("studio_episode_service")
_inv = load_svc("studio_invariants")
add_cuts = _ep.add_cuts
episode_can_approve = _inv.episode_can_approve
episode_can_publish = _inv.episode_can_publish
live_tier_unlocked = _inv.live_tier_unlocked
override_requires_admin = _inv.override_requires_admin


def test_approve_requires_in_review_and_zero_flags():
    assert episode_can_approve("in_review", 0) is True
    assert episode_can_approve("in_review", 1) is False
    assert episode_can_approve("draft", 0) is False


def test_publish_requires_approved():
    assert episode_can_publish("approved") is True
    assert episode_can_publish("in_review") is False
    assert episode_can_publish("published") is False


def test_empty_cuts_422():
    import asyncio

    out = asyncio.run(add_cuts(None, "x", "coach", []))
    assert out["ok"] is False
    assert out["code"] == 422


def test_high_override_admin_only():
    assert override_requires_admin("high") is True
    assert override_requires_admin("med") is False
    assert override_requires_admin("low") is False


def test_live_tier_one_clean_episode():
    assert live_tier_unlocked(0) is False
    assert live_tier_unlocked(1) is True
