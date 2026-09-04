"""Offline A2P SMS kwargs — no Twilio network."""

from app.services.twilio_a2p import sms_create_kwargs


def test_prefers_messaging_service(monkeypatch):
    monkeypatch.setenv("TWILIO_MESSAGING_SERVICE_SID", "MGservice")
    monkeypatch.setenv("TWILIO_PHONE_NUMBER", "+16562318192")
    kwargs = sms_create_kwargs("+15865243969", "hello")
    assert kwargs == {
        "to": "+15865243969",
        "body": "hello",
        "messaging_service_sid": "MGservice",
    }
    assert "from_" not in kwargs


def test_legacy_messaging_sid_alias(monkeypatch):
    monkeypatch.delenv("TWILIO_MESSAGING_SERVICE_SID", raising=False)
    monkeypatch.setenv("TWILIO_MESSAGING_SID", "MGlegacy")
    kwargs = sms_create_kwargs("+15865243969", "hello")
    assert kwargs["messaging_service_sid"] == "MGlegacy"


def test_falls_back_to_from_when_no_service(monkeypatch):
    monkeypatch.delenv("TWILIO_MESSAGING_SERVICE_SID", raising=False)
    monkeypatch.delenv("TWILIO_MESSAGING_SID", raising=False)
    monkeypatch.setenv("TWILIO_FROM_NUMBER", "+16562318192")
    monkeypatch.delenv("TWILIO_PHONE_NUMBER", raising=False)
    kwargs = sms_create_kwargs("+15865243969", "hello")
    assert kwargs["from_"] == "+16562318192"


def test_returns_none_when_unconfigured(monkeypatch):
    monkeypatch.delenv("TWILIO_MESSAGING_SERVICE_SID", raising=False)
    monkeypatch.delenv("TWILIO_MESSAGING_SID", raising=False)
    monkeypatch.delenv("TWILIO_FROM_NUMBER", raising=False)
    monkeypatch.delenv("TWILIO_PHONE_NUMBER", raising=False)
    assert sms_create_kwargs("+15865243969", "hello") is None


def test_truncates_body(monkeypatch):
    monkeypatch.setenv("TWILIO_MESSAGING_SERVICE_SID", "MGservice")
    kwargs = sms_create_kwargs("+15865243969", "x" * 50, max_len=10)
    assert kwargs["body"] == "x" * 10
