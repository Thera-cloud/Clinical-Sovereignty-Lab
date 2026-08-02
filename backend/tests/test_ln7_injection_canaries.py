"""Offline tests: R4 layer 3 — standing injection-canary corpus.

Loads backend/app/data/ln7_injection_canaries/corpus.json and asserts:

  1. Every `must_trip` entry is caught by scan_honeytokens() — a known-shape
     prompt-injection or exfiltration attempt that the firewall must never
     silently let through.
  2. Every `must_not_trip` entry passes through untouched — ordinary
     engineering/task-note language that must never be flagged, guarding
     against the over-broad-lexicon failure class documented in
     docs/ln7/TRUST_LEDGER.md Entry 2 (the escalation-axis bug) recurring
     here on the injection-detection side.

This is the "live canary" layer of R4: a standing regression corpus that
turns each real injection shape (or each real false-positive incident) into
a permanent CI check, rather than trusting a one-off manual test. See the
corpus file's `_meta.rule` for how new entries get added.
"""

import json
from pathlib import Path

import pytest

_CORPUS_PATH = (
    Path(__file__).resolve().parents[1]
    / "app"
    / "data"
    / "ln7_injection_canaries"
    / "corpus.json"
)


def _mod():
    from app.services import ln7_injection_firewall as m

    return m


def _load_corpus():
    with open(_CORPUS_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def test_corpus_file_loads_and_has_both_sections():
    corpus = _load_corpus()
    assert "must_trip" in corpus
    assert "must_not_trip" in corpus
    assert len(corpus["must_trip"]) >= 20
    assert len(corpus["must_not_trip"]) >= 8


_CORPUS = _load_corpus()


@pytest.mark.parametrize(
    "entry",
    _CORPUS["must_trip"],
    ids=[e["id"] for e in _CORPUS["must_trip"]],
)
def test_must_trip_entry_is_caught(entry):
    m = _mod()
    hit = m.scan_honeytokens(entry["text"])
    assert hit is not None, (
        f"canary '{entry['id']}' was NOT caught by scan_honeytokens() — "
        f"an injection-detection regex regressed. text={entry['text']!r}"
    )
    expected = entry["expected"]
    if expected.startswith("literal:"):
        assert hit == expected.split("literal:", 1)[1], (
            f"canary '{entry['id']}' expected literal honeytoken "
            f"{expected!r} but got {hit!r}"
        )
    else:
        assert hit == expected, (
            f"canary '{entry['id']}' expected pattern {expected!r} but "
            f"scan_honeytokens() returned {hit!r} instead (still a hit, "
            f"but the wrong category — check pattern precedence)"
        )


@pytest.mark.parametrize(
    "entry",
    _CORPUS["must_not_trip"],
    ids=[e["id"] for e in _CORPUS["must_not_trip"]],
)
def test_must_not_trip_entry_passes_through(entry):
    m = _mod()
    hit = m.scan_honeytokens(entry["text"])
    assert hit is None, (
        f"canary '{entry['id']}' was falsely flagged as {hit!r} — this is "
        f"the over-broad-lexicon failure class from docs/ln7/TRUST_LEDGER.md "
        f"Entry 2. note={entry.get('note', '')!r} text={entry['text']!r}"
    )


def test_sanitize_notes_redacts_every_must_trip_entry():
    """End-to-end check on the actual serialization-boundary function used
    by cli_task_bus.publish_task() — not just the lower-level scanner."""
    m = _mod()
    for entry in _CORPUS["must_trip"]:
        result = m.sanitize_notes(entry["text"])
        assert result["tripped"] is True, (
            f"sanitize_notes() failed to redact canary '{entry['id']}'"
        )
        assert "[REDACTED_BY_R4_FIREWALL" in result["notes"]


def test_sanitize_notes_passes_every_must_not_trip_entry_unmodified():
    m = _mod()
    for entry in _CORPUS["must_not_trip"]:
        result = m.sanitize_notes(entry["text"])
        assert result["tripped"] is False, (
            f"sanitize_notes() falsely redacted benign canary '{entry['id']}'"
        )
        assert result["notes"] == entry["text"]
