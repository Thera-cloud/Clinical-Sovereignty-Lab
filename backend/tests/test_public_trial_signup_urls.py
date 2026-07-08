"""Public Trial Funnel Phase 3 — signup URL builders (offline unit tests)."""
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


def test_email_signup_link_short_api_redirect_with_fp_and_tt():
    url = ptg._email_signup_link(tt="raw-token-abc", fp="raw-uuid-abc")
    assert "/api/public-trial/signup" in url
    assert "api.sovereignsanctuary.net" in url
    parsed = urlparse(url)
    qs = parse_qs(parsed.query)
    assert qs.get("src") == ["trial_email"]
    assert qs.get("tt") == ["raw-token-abc"]
    assert qs.get("fp") == ["raw-uuid-abc"]


def test_email_signup_link_followup_tt_only_no_fp():
    url = ptg._email_signup_link(tt="raw-token-abc")
    assert "/api/public-trial/signup" in url
    assert "fp=" not in url
    parsed = urlparse(url)
    qs = parse_qs(parsed.query)
    assert qs.get("tt") == ["raw-token-abc"]


def test_sendgrid_trial_tracking_disabled():
    settings = ptg._sendgrid_trial_tracking_settings()
    assert settings["click_tracking"]["enable"] is False
    assert settings["click_tracking"]["enable_text"] is False
    assert settings["open_tracking"]["enable"] is False


@pytest.mark.asyncio
async def test_upsert_trial_lead_email_url_api_signup_fp_tt(monkeypatch):
    """Email capture link uses short API redirect with fp + tt for same-device merge."""

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
    assert "/api/public-trial/signup" in signup_url
    assert "src=trial_email" in signup_url
    assert "fp=raw-uuid-abc" in signup_url
    assert "tt=" in signup_url
    parsed = urlparse(signup_url)
    qs = parse_qs(parsed.query)
    assert "fp" in qs
    assert "tt" in qs
