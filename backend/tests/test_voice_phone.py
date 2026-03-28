"""voice_phone — Twilio From → digit variants for profile lookup."""

from app.services.littlenate_realtime import _twilio_stream_custom_parameters
from app.services.voice_phone import phone_digits_only, twilio_lookup_digit_variants


def test_phone_digits_only_strips_formatting():
    assert phone_digits_only("+1 (415) 555-1234") == "14155551234"
    assert phone_digits_only("") == ""


def test_twilio_lookup_variants_nanp():
    v = twilio_lookup_digit_variants("+14155551234")
    assert "4155551234" in v
    assert "14155551234" in v


def test_twilio_lookup_variants_short():
    assert twilio_lookup_digit_variants("5551234") == ["5551234"]


def test_twilio_stream_custom_parameters_dict():
    start = {"customParameters": {"user_id": "u1", "max_call_seconds": "900"}}
    assert _twilio_stream_custom_parameters(start)["user_id"] == "u1"


def test_twilio_stream_custom_parameters_list():
    start = {
        "customParameters": [
            {"name": "call_sid", "value": "CAxxx"},
            {"name": "tier", "value": "STANDARD"},
        ]
    }
    p = _twilio_stream_custom_parameters(start)
    assert p["call_sid"] == "CAxxx"
    assert p["tier"] == "STANDARD"
