"""Tests for CEO external notify staging isolation."""

from app.ceo_notify_policy import (
    ceo_external_notify_enabled,
    resolve_ceo_notify_email,
)


def test_external_notify_off_in_staging_by_default(monkeypatch):
    monkeypatch.delenv("ENABLE_CEO_INBOX_EXTERNAL_NOTIFY", raising=False)
    monkeypatch.setenv("ENVIRONMENT", "staging")
    assert ceo_external_notify_enabled() is False


def test_external_notify_on_in_production_by_default(monkeypatch):
    monkeypatch.delenv("ENABLE_CEO_INBOX_EXTERNAL_NOTIFY", raising=False)
    monkeypatch.setenv("ENVIRONMENT", "production")
    assert ceo_external_notify_enabled() is True


def test_explicit_flag_overrides_staging(monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "staging")
    monkeypatch.setenv("ENABLE_CEO_INBOX_EXTERNAL_NOTIFY", "true")
    assert ceo_external_notify_enabled() is True


def test_resolve_ceo_notify_email_prefers_metadata(monkeypatch):
    monkeypatch.setenv("CEO_NOTIFY_EMAIL", "ceo@example.com")
    email = resolve_ceo_notify_email(
        {"metadata": {"ceo_notify_email": "stored@example.com"}}
    )
    assert email == "stored@example.com"


def test_resolve_ceo_notify_email_falls_back_to_env(monkeypatch):
    monkeypatch.setenv("CEO_NOTIFY_EMAIL", "ceo@example.com")
    assert resolve_ceo_notify_email({}) == "ceo@example.com"
