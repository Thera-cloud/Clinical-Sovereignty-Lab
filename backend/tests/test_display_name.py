"""Tests for cohort-gated display_name.public_display_name.

Regression: Bee HIV+ header/recap pseudonymization (2026-08-22).
Non-cohort users must be untouched; strict cohort users must receive a
stable, non-reversible pseudonym derived from a keyed hash.
"""

from __future__ import annotations

import importlib
import os

import pytest


def _reload_module():
    """Re-import display_name so PSEUDONYM_STABLE_SALT env changes stick."""
    import app.services.display_name as m  # type: ignore

    return importlib.reload(m)


def test_non_cohort_returns_none():
    """Non-strict program_id → None sentinel (caller keeps real name)."""
    m = _reload_module()
    assert m.public_display_name("John D.", "client1", None) is None
    assert m.public_display_name("John D.", "client1", "") is None
    assert m.public_display_name("John D.", "client1", "some_random_program") is None


def test_strict_cohort_returns_stable_pseudonym(monkeypatch):
    """Strict cohort → deterministic Client-<6HEX> mask."""
    monkeypatch.setenv("PSEUDONYM_STABLE_SALT", "test-salt-2026")
    m = _reload_module()
    out1 = m.public_display_name("John D.", "client1", "bee_hiv_plus")
    out2 = m.public_display_name("John D.", "client1", "bee_hiv_plus")
    assert out1 == out2  # stable
    assert out1 is not None
    assert out1.startswith("Client-")
    assert len(out1) == len("Client-") + 6
    # No PHI substring
    assert "John" not in out1
    assert "client1" not in out1


def test_different_users_get_different_pseudonyms(monkeypatch):
    monkeypatch.setenv("PSEUDONYM_STABLE_SALT", "test-salt-2026")
    m = _reload_module()
    a = m.public_display_name("A", "user_a", "bee_hiv_plus")
    b = m.public_display_name("B", "user_b", "bee_hiv_plus")
    assert a != b


def test_salt_change_alters_pseudonym(monkeypatch):
    monkeypatch.setenv("PSEUDONYM_STABLE_SALT", "salt-one")
    m = _reload_module()
    a = m.public_display_name("John D.", "client1", "bee_hiv_plus")
    monkeypatch.setenv("PSEUDONYM_STABLE_SALT", "salt-two")
    m = _reload_module()
    b = m.public_display_name("John D.", "client1", "bee_hiv_plus")
    assert a != b


def test_empty_identifiers_fallback():
    m = _reload_module()
    # No username, no real_name, no program → None (non-cohort)
    assert m.public_display_name(None, None, None) is None
    # Strict cohort but empty identifiers → still deterministic (empty digest)
    out = m.public_display_name(None, None, "bee_hiv_plus")
    assert out == "Client"
