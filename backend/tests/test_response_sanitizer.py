"""Tests for foreign-script garble detection (Lisa transcript 2026-05-19)."""
from app.services.response_sanitizer import (
    is_chunk_garbled,
    sanitize_response,
    _sentence_has_isolated_foreign_script,
    garble_detection_reason,
)


def test_thai_token_in_english_sentence_is_garbled():
    s = (
        "Behind theประกาศ of adjusting plans and letting go of certain "
        "commitments, there is often a deeper pattern."
    )
    assert _sentence_has_isolated_foreign_script(s)
    assert is_chunk_garbled(s)
    assert garble_detection_reason(s) == "foreign_script"


def test_sanitize_strips_thai_pollution_sentence():
    raw = (
        "You are doing a lot. Behind theประกาศ of adjusting plans you may "
        "need rest. Take care of yourself today."
    )
    cleaned = sanitize_response(raw)
    assert "ประกาศ" not in cleaned
    assert "Take care" in cleaned


def test_pure_english_not_garbled():
    s = "Your self-criticism is linked to an insecure attachment issue."
    assert not _sentence_has_isolated_foreign_script(s)
    assert not is_chunk_garbled(s)


def test_mixed_cjk_latin_chunk_garbled():
    chunk = "Hello world this is a test with 你好 mixed in the middle of speech"
    assert is_chunk_garbled(chunk)
