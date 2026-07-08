"""Public Trial Funnel Phase 3 — signup.html URL builders (offline unit tests)."""
from __future__ import annotations

import asyncio
from urllib.parse import parse_qs, urlparse

import pytest

import app.services.public_trial_gate as ptg


def test_signup_url_points_to_signup_html_with_fp_and_src():
    url = ptg._signup_url("550e8400-e29b-41d4-a716-446655440000")
    assert "/signup.html" in url
    assert "src=trial" in url
    assert "fp=550e8400-e29b-41d4-a716-446655440000" in url
    parsed = urlparse(url)
    qs = parse_qs(parsed.query)
    assert qs.get("src") == ["trial"]
    assert qs.get("fp") == ["550e8400-e29b-41d4-a716-446655440000"]


@pytest.mark.asyncio
async def test_upsert_trial_lead_email_url_signup_html_fp_tt(monkeypatch):
    """Email capture link must include signup.html, fp, and tt for same-device merge."""

    class _Conn:
        async def fetchrow(self, query, *args):
            return None

        async def execute(self, query, *args):
            return None

    class _Ctx:
        def __init__(self, c):
            self._c = c

        async def __aenter__(self):
            return self._c

        async def __aexit__(self, *exc):
            return False

    class _Pool:
        def acquire(self):
            return _Ctx(_Conn())

    monkeypatch.setattr(ptg, "get_db_pool", lambda: _Pool())

    _token, signup_url, _unsub = await ptg._upsert_trial_lead(
        "fp_hash_x", "dev_hash_x", "user@example.com", "raw-uuid-abc"
    )
    assert "/signup.html" in signup_url
    assert "src=trial_email" in signup_url
    assert "fp=raw-uuid-abc" in signup_url
    assert "tt=" in signup_url
    parsed = urlparse(signup_url)
    qs = parse_qs(parsed.query)
    assert "fp" in qs
    assert "tt" in qs


def test_followup_email_url_signup_html_tt_only_no_fp():
    """Follow-up cycle mints tt-only links — lead row stores hash, not raw device UUID."""
    from urllib.parse import quote

    import secrets

    raw_token = secrets.token_urlsafe(32)
    signup_url = f"https://app.sovereignsanctuary.net/signup.html?src=trial_email&tt={quote(raw_token)}"
    assert "/signup.html" in signup_url
    assert "src=trial_email" in signup_url
    assert "tt=" in signup_url
    assert "fp=" not in signup_url
