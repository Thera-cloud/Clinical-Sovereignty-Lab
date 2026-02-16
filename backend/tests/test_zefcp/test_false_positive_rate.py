"""Tests for overall false positive rate — random bytes should rarely pass checks."""

import os

import pytest

from app.services.zefcp.constants import EXTENDED_TOTAL_BYTES
from app.services.zefcp.fragment import FragmentDecoder
from app.services.zefcp.signature import SignatureRotator

SECRET = b"test-swarm-secret-32-bytes-long!"


def test_false_positive_rate_below_threshold() -> None:
    """Generate 10000 random 12-byte sequences, verify rate < 0.01%."""
    decoder = FragmentDecoder(SECRET)
    rotator = SignatureRotator(SECRET)
    passes = 0
    n = 10000
    for _ in range(n):
        leading = os.urandom(6)
        trailing = os.urandom(6)
        if not rotator.is_valid(leading[0]):
            continue
        decoded = decoder.decode_bytes(leading, trailing)
        if decoded is not None:
            passes += 1
    rate = passes / n
    assert rate < 0.0001, f"False positive rate {rate:.6f} exceeds 0.01% threshold"
