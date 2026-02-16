"""Tests for reed_solomon.py — encode/decode, parity, reconstruction."""

import math

import pytest

from app.services.zefcp.reed_solomon import ReedSolomonFragmentEncoder
from app.services.zefcp.constants import EXTENDED_PAYLOAD_SIZE, STANDARD_PAYLOAD_SIZE


def test_encode_produces_correct_count() -> None:
    """Verify total fragments = data + parity."""
    rs = ReedSolomonFragmentEncoder(redundancy_factor=0.3)
    data = b"hello world" * 2  # 22 bytes
    payloads = rs.encode(data, EXTENDED_PAYLOAD_SIZE)
    data_fragments = math.ceil(len(data) / EXTENDED_PAYLOAD_SIZE)
    pad_len = (EXTENDED_PAYLOAD_SIZE - (len(data) % EXTENDED_PAYLOAD_SIZE)) % EXTENDED_PAYLOAD_SIZE
    padded_len = len(data) + pad_len
    data_fragments = padded_len // EXTENDED_PAYLOAD_SIZE
    parity_fragments = math.ceil(data_fragments * 0.3)
    expected_total = data_fragments + parity_fragments
    assert len(payloads) == expected_total


def test_decode_all_fragments() -> None:
    """Decode with all fragments present."""
    rs = ReedSolomonFragmentEncoder(redundancy_factor=0.3)
    data = b"test payload for RS"
    payloads = rs.encode(data, EXTENDED_PAYLOAD_SIZE)
    fragments = {i: p for i, p in enumerate(payloads)}
    decoded = rs.decode(fragments, len(payloads), EXTENDED_PAYLOAD_SIZE)
    assert decoded == data


def test_decode_with_missing_fragments() -> None:
    """Remove 25% of fragments, still reconstructs."""
    rs = ReedSolomonFragmentEncoder(redundancy_factor=0.35)
    data = b"resilient data xyz"
    payloads = rs.encode(data, EXTENDED_PAYLOAD_SIZE)
    total = len(payloads)
    # Keep ~75%
    fragments = {i: p for i, p in enumerate(payloads) if i % 4 != 0}
    decoded = rs.decode(fragments, total, EXTENDED_PAYLOAD_SIZE)
    assert decoded == data


def test_decode_below_threshold_fails() -> None:
    """Remove >30%, fails gracefully."""
    rs = ReedSolomonFragmentEncoder(redundancy_factor=0.25)
    data = b"small"
    payloads = rs.encode(data, EXTENDED_PAYLOAD_SIZE)
    total = len(payloads)
    # Keep only 1-2 fragments when we need more
    fragments = {0: payloads[0]} if payloads else {}
    with pytest.raises(ValueError):
        rs.decode(fragments, total, EXTENDED_PAYLOAD_SIZE)
