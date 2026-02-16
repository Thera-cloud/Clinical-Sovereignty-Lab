"""Tests for signature.py — deterministic sig, period rotation, valid set, cache."""

import pytest

from app.services.zefcp.signature import (
    compute_signature,
    get_valid_signatures,
    SignatureRotator,
    ROTATION_PERIOD_MINUTES,
)


def test_compute_signature_deterministic(swarm_secret: bytes) -> None:
    """Same inputs produce same output."""
    sig1 = compute_signature(1000, swarm_secret)
    sig2 = compute_signature(1000, swarm_secret)
    assert sig1 == sig2
    assert 0 <= sig1 <= 255


def test_different_periods_different_signatures(swarm_secret: bytes) -> None:
    """Adjacent periods produce different sigs."""
    period_a = 0
    period_b = ROTATION_PERIOD_MINUTES
    period_c = ROTATION_PERIOD_MINUTES * 2
    sig_a = compute_signature(period_a, swarm_secret)
    sig_b = compute_signature(period_b, swarm_secret)
    sig_c = compute_signature(period_c, swarm_secret)
    assert sig_a != sig_b or sig_b != sig_c or sig_a != sig_c


def test_valid_signatures_includes_adjacent(swarm_secret: bytes) -> None:
    """get_valid_signatures returns 3 values."""
    valid = get_valid_signatures(swarm_secret)
    assert len(valid) == 3
    assert all(0 <= s <= 255 for s in valid)


def test_signature_rotator_caches(swarm_secret: bytes) -> None:
    """SignatureRotator returns consistent value within period."""
    rot = SignatureRotator(swarm_secret)
    sig1 = rot.current_sig
    sig2 = rot.current_sig
    assert sig1 == sig2
    assert rot.is_valid(sig1)
