"""Unit tests for pii_pseudonymizer (Slice 3 of Bee HIV+ privacy plan)."""

from __future__ import annotations

import pytest

from app.services.pii_pseudonymizer import (
    PseudonymBook,
    StreamRestorer,
    is_enabled,
    maybe_pseudonymize_prompt,
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


# ------------------------------------------------------------------- #
# Slice C additions: UUID + HWID direct-identifier patterns.           #
# ------------------------------------------------------------------- #

def test_uuid_pseudonymized():
    book = PseudonymBook()
    uid = "550e8400-e29b-41d4-a716-446655440000"
    src = f"session_id={uid} rolled at 12:00"
    out = pseudonymize_text(src, book)
    assert uid not in out
    assert "PSEUDO_UUID_" in out
    assert restore_text(out, book) == src


def test_uuid_case_insensitive():
    book = PseudonymBook()
    uid = "550E8400-E29B-41D4-A716-446655440000"
    src = f"crystal {uid} recalled"
    out = pseudonymize_text(src, book)
    assert uid not in out
    assert "PSEUDO_UUID_" in out


def test_hwid_pseudonymized():
    book = PseudonymBook()
    src = "assign CLIENT_KRISTY9_ID to COACH_COACHN_ID under ADMIN_DRNEVEDAL1_ID"
    out = pseudonymize_text(src, book)
    for hw in ("CLIENT_KRISTY9_ID", "COACH_COACHN_ID", "ADMIN_DRNEVEDAL1_ID"):
        assert hw not in out
    assert out.count("PSEUDO_HWID_") == 3
    assert restore_text(out, book) == src


def test_hwid_not_matched_on_lowercase_or_partial():
    book = PseudonymBook()
    src = "client_kristy_id lower and CLIENTKRISTYID no underscore"
    out = pseudonymize_text(src, book)
    assert "PSEUDO_HWID_" not in out


# ------------------------------------------------------------------- #
# gap-fix-c: maybe_pseudonymize_prompt convenience wrapper.           #
# ------------------------------------------------------------------- #

def test_maybe_pseudonymize_prompt_flag_off_returns_originals():
    """When ENABLE_PROVIDER_PSEUDONYMIZATION is unset, the helper is a
    zero-cost passthrough so protected-file call sites are safe to wrap
    unconditionally."""
    sys_p = "You are Little Nate. Coach: hnevedal. Contact " + E_ALICE
    user_p = "Reply to Alice about her SSN 123-45-6789."
    ps, pu, book = maybe_pseudonymize_prompt(sys_p, user_p, known_names=["Alice"])
    assert ps == sys_p
    assert pu == user_p
    assert book is None


def test_maybe_pseudonymize_prompt_flag_on_scrubs_and_shares_book(monkeypatch):
    """With the flag on AND a strict cohort program_id, PII in either
    prompt is replaced by tokens from a SHARED book so a token in the
    system prompt matches the same substitution in the user prompt
    (deterministic per-book).

    gap-fix (bee-hiv-only): pseudonymization is cohort-gated. Tests must
    pass a strict ``program_id`` (see ``services.cohort``); flag alone is
    insufficient. Non-cohort behavior is covered by
    ``test_maybe_pseudonymize_prompt_flag_on_non_cohort_returns_originals``.
    """
    monkeypatch.setenv("ENABLE_PROVIDER_PSEUDONYMIZATION", "true")
    sys_p = "Coach context includes " + E_ALICE + " and client Alice."
    user_p = "Draft a reply to " + E_ALICE + " for Alice."
    ps, pu, book = maybe_pseudonymize_prompt(
        sys_p, user_p, known_names=["Alice"], program_id="bee_hiv_plus"
    )
    assert E_ALICE not in ps and E_ALICE not in pu
    assert "Alice" not in ps and "Alice" not in pu
    assert "PSEUDO_EMAIL_" in ps and "PSEUDO_EMAIL_" in pu
    assert "PSEUDO_NAME_" in ps and "PSEUDO_NAME_" in pu
    assert book is not None
    # Same email in both prompts → identical token via shared book.
    email_tokens_sys = [w for w in ps.split() if w.startswith("PSEUDO_EMAIL_")]
    email_tokens_user = [w for w in pu.split() if w.startswith("PSEUDO_EMAIL_")]
    assert email_tokens_sys[0] == email_tokens_user[0]


def test_maybe_pseudonymize_prompt_restore_round_trip(monkeypatch):
    """The book returned by the helper must round-trip through
    restore_text so provider responses can be un-pseudonymized in-place."""
    monkeypatch.setenv("ENABLE_PROVIDER_PSEUDONYMIZATION", "true")
    sys_p = "System note about " + E_BOB
    user_p = "User asks about Bob and " + E_BOB
    ps, pu, book = maybe_pseudonymize_prompt(
        sys_p, user_p, known_names=["Bob"], program_id="bee_hiv_plus"
    )
    # Simulate a provider response that echoes back tokens from both prompts.
    fake_response = f"Told {pu.split()[-1]} the info from {ps.split()[-1]}."
    restored = restore_text(fake_response, book)
    assert E_BOB in restored


def test_maybe_pseudonymize_prompt_empty_strings(monkeypatch):
    """Empty prompts must not crash and must produce no book allocation
    cost when the flag is off (fast path)."""
    monkeypatch.setenv("ENABLE_PROVIDER_PSEUDONYMIZATION", "true")
    ps, pu, book = maybe_pseudonymize_prompt(
        "", "", known_names=[], program_id="bee_hiv_plus"
    )
    assert ps == "" and pu == ""
    assert book is not None  # still allocated for consistency on the on-path


# ------------------------------------------------------------------- #
# gap-fix (bee-hiv-only): cohort-gating regression tests.             #
# ------------------------------------------------------------------- #

def test_maybe_pseudonymize_prompt_flag_on_non_cohort_returns_originals(monkeypatch):
    """With the flag ON but no strict program_id, non-cohort users
    (e.g. general population like 'John D.') must NOT see pseudonymization.

    Regression test for the 2026-08-22 leak where PSEUDO_NAME_* tokens
    surfaced in non-cohort UI because the ``program_id is None`` path
    fell back to the global flag.
    """
    monkeypatch.setenv("ENABLE_PROVIDER_PSEUDONYMIZATION", "true")
    sys_p = "Coach context includes " + E_ALICE + " and client Alice."
    user_p = "Reply to Alice about " + E_ALICE + "."
    # program_id=None (default) — general user pool.
    ps, pu, book = maybe_pseudonymize_prompt(sys_p, user_p, known_names=["Alice"])
    assert ps == sys_p
    assert pu == user_p
    assert book is None
    # Also test unknown program_id explicitly (not in STRICT_COHORT_PROGRAM_IDS).
    ps2, pu2, book2 = maybe_pseudonymize_prompt(
        sys_p, user_p, known_names=["Alice"], program_id="general_pool"
    )
    assert ps2 == sys_p
    assert pu2 == user_p
    assert book2 is None


def test_maybe_pseudonymize_prompt_force_regex_only_bypasses_cohort(monkeypatch):
    """``force_regex_only=True`` scrubs categorical PII regardless of
    cohort (used by voice pipeline — audio output, names left intact).

    Names must NOT be substituted even when provided; only regex-matched
    direct identifiers (email/phone/SSN/UUID/HWID/DOB/ADDR).
    """
    monkeypatch.setenv("ENABLE_PROVIDER_PSEUDONYMIZATION", "true")
    sys_p = "Speak with " + E_ALICE + " about Alice"
    ps, _, book = maybe_pseudonymize_prompt(
        sys_p, "", known_names=["Alice"], force_regex_only=True
    )
    assert E_ALICE not in ps
    assert "PSEUDO_EMAIL_" in ps
    # Names intentionally preserved for audio quality.
    assert "Alice" in ps
    assert "PSEUDO_NAME_" not in ps
    assert book is not None


def test_maybe_pseudonymize_prompt_force_regex_only_flag_off_passthrough(monkeypatch):
    """When the global flag is OFF, ``force_regex_only`` still respects
    the master kill switch and passes originals through untouched."""
    monkeypatch.delenv("ENABLE_PROVIDER_PSEUDONYMIZATION", raising=False)
    sys_p = "Speak with " + E_ALICE
    ps, pu, book = maybe_pseudonymize_prompt(
        sys_p, "user text", known_names=["Alice"], force_regex_only=True
    )
    assert ps == sys_p
    assert pu == "user text"
    assert book is None
