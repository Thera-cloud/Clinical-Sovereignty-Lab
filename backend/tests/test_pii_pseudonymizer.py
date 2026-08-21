"""Unit tests for pii_pseudonymizer (Slice 3 of Bee HIV+ privacy plan)."""

from __future__ import annotations

import pytest

from app.services.pii_pseudonymizer import (
    PseudonymBook,
    StreamRestorer,
    is_enabled,
    pseudonymize_messages,
    pseudonymize_text,
    restore_text,
)

# Cursor's Write tool redacts email-looking literals as "[email protected]", so
# build all email test fixtures via character concatenation to preserve intent.
_AT = chr(64)
E_ALICE = "alice" + _AT + "example.com"
E_BOB = "bob" + _AT + "site.io"
E_USER = "user" + _AT + "host.net"


@pytest.fixture(autouse=True)
def _clean_flag(monkeypatch):
    monkeypatch.delenv("ENABLE_PROVIDER_PSEUDONYMIZATION", raising=False)
    yield


def test_flag_off_by_default():
    assert is_enabled() is False


@pytest.mark.parametrize("v", ["1", "true", "TRUE", "yes", "on"])
def test_flag_on_variants(monkeypatch, v):
    monkeypatch.setenv("ENABLE_PROVIDER_PSEUDONYMIZATION", v)
    assert is_enabled() is True


@pytest.mark.parametrize("v", ["0", "false", "no", "off", "maybe", ""])
def test_flag_off_variants(monkeypatch, v):
    monkeypatch.setenv("ENABLE_PROVIDER_PSEUDONYMIZATION", v)
    assert is_enabled() is False


def test_email_pseudonymized():
    book = PseudonymBook()
    src = "contact me at " + E_ALICE
    out = pseudonymize_text(src, book)
    assert E_ALICE not in out
    assert "PSEUDO_EMAIL_" in out
    assert restore_text(out, book) == src


def test_ssn_phone_dob_replaced():
    book = PseudonymBook()
    src = "SSN 123-45-6789 phone (555) 867-5309 DOB 07/04/1980"
    out = pseudonymize_text(src, book)
    for raw in ("123-45-6789", "(555) 867-5309", "867-5309", "07/04/1980"):
        assert raw not in out
    assert "PSEUDO_SSN_" in out
    assert "PSEUDO_PHONE_" in out
    assert "PSEUDO_DOB_" in out
    assert restore_text(out, book) == src


def test_address_replaced():
    book = PseudonymBook()
    src = "I live at 123 Main Street"
    out = pseudonymize_text(src, book)
    assert "123 Main Street" not in out
    assert "PSEUDO_ADDR_" in out
    assert restore_text(out, book) == src


def test_known_names_replaced_case_insensitive():
    book = PseudonymBook()
    src = "hi Alice, please tell alice about it"
    out = pseudonymize_text(src, book, known_names=["Alice"])
    assert "Alice" not in out and "alice" not in out
    assert out.count("PSEUDO_NAME_") == 2
    restored = restore_text(out, book)
    assert restored.count("Alice") == 2


def test_same_value_gets_same_token_within_book():
    book = PseudonymBook()
    a = pseudonymize_text("email " + E_ALICE, book)
    b = pseudonymize_text("again " + E_ALICE, book)
    tok_a = a.split()[-1]
    tok_b = b.split()[-1]
    assert tok_a == tok_b


def test_different_books_get_different_salts():
    a = PseudonymBook()
    b = PseudonymBook()
    assert a.salt != b.salt
    ta = pseudonymize_text(E_USER, a).strip()
    tb = pseudonymize_text(E_USER, b).strip()
    assert ta != tb


def test_empty_text_passthrough():
    book = PseudonymBook()
    assert pseudonymize_text("", book) == ""
    assert pseudonymize_text(None, book) is None  # type: ignore[arg-type]


def test_pseudonymize_messages_string_content():
    book = PseudonymBook()
    msgs = [
        {"role": "system", "content": "you are little nate"},
        {"role": "user", "content": "email me at " + E_BOB},
    ]
    out = pseudonymize_messages(msgs, book)
    assert out[0]["content"] == "you are little nate"
    assert E_BOB not in out[1]["content"]


def test_pseudonymize_messages_multimodal():
    book = PseudonymBook()
    msgs = [
        {
            "role": "user",
            "content": [
                {"type": "text", "text": "check " + E_ALICE},
                {"type": "image_url", "image_url": {"url": "data:image/png;base64,xxxx"}},
            ],
        }
    ]
    out = pseudonymize_messages(msgs, book)
    parts = out[0]["content"]
    assert parts[0]["type"] == "text" and E_ALICE not in parts[0]["text"]
    assert parts[1] == msgs[0]["content"][1]


def test_stream_restorer_single_shot():
    book = PseudonymBook()
    pseudonymize_text(E_ALICE, book)
    token = list(book.reverse.keys())[0]
    r = StreamRestorer(book)
    out = r.feed(f"hi {token} bye")
    out += r.flush()
    assert out == "hi " + E_ALICE + " bye"


def test_stream_restorer_split_token_across_chunks():
    book = PseudonymBook()
    pseudonymize_text(E_ALICE, book)
    token = list(book.reverse.keys())[0]
    r = StreamRestorer(book)
    mid = len(token) // 2
    a = r.feed(f"hello {token[:mid]}")
    b = r.feed(f"{token[mid:]} world")
    tail = r.flush()
    assert (a + b + tail) == "hello " + E_ALICE + " world"


def test_stream_restorer_no_mapping_passthrough():
    book = PseudonymBook()
    r = StreamRestorer(book)
    out = r.feed("plain text no tokens ")
    out += r.flush()
    assert out == "plain text no tokens "


def test_stream_restorer_incomplete_prefix_flushed_on_close():
    book = PseudonymBook()
    pseudonymize_text(E_ALICE, book)
    r = StreamRestorer(book)
    a = r.feed("prefix PSEUDO_EMAIL_")
    b = r.flush()
    assert (a + b) == "prefix PSEUDO_EMAIL_"
