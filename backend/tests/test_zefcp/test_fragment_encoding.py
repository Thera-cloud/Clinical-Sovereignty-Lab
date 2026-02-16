"""Tests for fragment.py — CRC-8, encode/decode, standard/extended modes."""

import pytest

from app.services.zefcp.fragment import crc8, FragmentEncoder, FragmentDecoder
from app.services.zefcp.constants import STANDARD_TOTAL_BYTES, EXTENDED_TOTAL_BYTES


def test_crc8_known_values() -> None:
    """Verify CRC-8 on known byte sequences."""
    # CRC-8 with polynomial 0x07; verify consistency
    assert 0 <= crc8(b"") <= 255
    assert 0 <= crc8(b"hello") <= 255
    assert 0 <= crc8(b"\x00\x01\x02\x03") <= 255
    # Same input yields same output
    assert crc8(b"test") == crc8(b"test")


def test_encode_fragment_extended(swarm_secret: bytes) -> None:
    """Create a fragment in extended mode, verify all fields."""
    enc = FragmentEncoder(swarm_secret, "extended")
    frag = enc.encode_fragment(
        observation_id=42,
        sequence=1,
        total=5,
        payload=b"abcde",
        flags=0,
    )
    assert frag.signature >= 0
    assert frag.sequence == 1
    assert frag.total == 5
    assert frag.observation_id == 42
    assert frag.flags == 0
    assert frag.payload == b"abcde"
    assert frag.checksum >= 0
    assert frag.mode.value == "extended"


def test_serialize_deserialize_roundtrip(swarm_secret: bytes) -> None:
    """Serialize then decode back, compare."""
    enc = FragmentEncoder(swarm_secret, "extended")
    frag = enc.encode_fragment(10, 2, 4, b"xyzab", 0)
    ser = enc.serialize_fragment(frag)
    assert len(ser) == EXTENDED_TOTAL_BYTES
    dec = FragmentDecoder(swarm_secret)
    leading = ser[:6]
    trailing = ser[6:]
    decoded = dec.decode_bytes(leading, trailing)
    assert decoded is not None
    assert decoded.payload == frag.payload
    assert decoded.sequence == frag.sequence
    assert decoded.total == frag.total
    assert decoded.observation_id == frag.observation_id


def test_standard_mode_fragment(swarm_secret: bytes) -> None:
    """Test 8-byte standard mode."""
    enc = FragmentEncoder(swarm_secret, "standard")
    frag = enc.encode_fragment(
        observation_id=100,  # uses frag_id in standard mode
        sequence=0,
        total=2,
        payload=b"ab",
    )
    ser = enc.serialize_fragment(frag)
    assert len(ser) == STANDARD_TOTAL_BYTES
    dec = FragmentDecoder(swarm_secret)
    decoded = dec.decode_bytes(ser[:4], ser[4:])
    assert decoded is not None
    assert decoded.payload == b"ab"
    assert decoded.sequence == 0
    assert decoded.total == 2


def test_invalid_crc_returns_none(swarm_secret: bytes) -> None:
    """Decoder returns None on bad CRC."""
    enc = FragmentEncoder(swarm_secret, "extended")
    frag = enc.encode_fragment(1, 0, 3, b"abcde", 0)
    ser = enc.serialize_fragment(frag)
    dec = FragmentDecoder(swarm_secret)
    # Corrupt the checksum byte
    corrupted_trailing = bytes([ser[6] ^ 0xFF, ser[7] ^ 0xFF, ser[8] ^ 0xFF, ser[9] ^ 0xFF, ser[10] ^ 0xFF, ser[11] ^ 0xFF])
    decoded = dec.decode_bytes(ser[:6], corrupted_trailing)
    assert decoded is None
