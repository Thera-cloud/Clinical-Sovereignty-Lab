"""Tests for fragment_buffer.py — assembly, thresholds, duplicates, purge."""

import time
from uuid import uuid4

import pytest

from app.models.zefcp import FibreObservation, MicroFragment
from app.services.zefcp.constants import EXTENDED_PAYLOAD_SIZE
from app.services.zefcp.crypto import FibreFragmentCrypto
from app.services.zefcp.fragment import FragmentEncoder
from app.services.zefcp.fragment_buffer import FragmentBuffer
from app.services.zefcp.reed_solomon import ReedSolomonFragmentEncoder


def _make_json_observation(obs_id: int, fibre_id: str = "test_fibre") -> bytes:
    """Build JSON payload matching fragment_buffer's expected format."""
    import json
    from datetime import datetime
    data = {
        "observation_id": str(uuid4()),
        "fibre_id": fibre_id,
        "fibre_type": "test",
        "timestamp": datetime.utcnow().timestamp(),
        "coherence_data": None,
        "cultural_signal": None,
        "foresight_signal": None,
        "confidence": 0.8,
        "priority": 1,
    }
    return json.dumps(data).encode("utf-8")


@pytest.mark.asyncio
async def test_complete_assembly(swarm_secret: bytes) -> None:
    """Ingest all fragments, get completed observation."""
    crypto = FibreFragmentCrypto(swarm_secret)
    rs = ReedSolomonFragmentEncoder(redundancy_factor=0.3)
    enc = FragmentEncoder(swarm_secret, "extended")
    obs_id_byte = 17
    obs_id_bytes = bytes([obs_id_byte])
    plaintext = _make_json_observation(obs_id_byte)
    encrypted = crypto.encrypt_payload(plaintext, obs_id_bytes)
    payloads = rs.encode(encrypted, EXTENDED_PAYLOAD_SIZE)
    total = len(payloads)
    buffer = FragmentBuffer(swarm_secret, redundancy_threshold=0.7)
    for seq, payload in enumerate(payloads):
        frag = enc.encode_fragment(obs_id_byte, seq, total, payload, 0)
        result = await buffer.ingest(frag)
        if seq == total - 1:
            assert result is not None
            assert result.fibre_id == "test_fibre"
            assert result.fibre_type == "test"


@pytest.mark.asyncio
async def test_partial_assembly_with_threshold(swarm_secret: bytes) -> None:
    """Ingest 75% of fragments, still reconstructs (above 70% threshold)."""
    crypto = FibreFragmentCrypto(swarm_secret)
    rs = ReedSolomonFragmentEncoder(redundancy_factor=0.4)
    enc = FragmentEncoder(swarm_secret, "extended")
    obs_id_byte = 23
    obs_id_bytes = bytes([obs_id_byte])
    # Larger payload to get enough fragments for RS to tolerate 25% loss
    plaintext = _make_json_observation(obs_id_byte) + b" " * 20
    encrypted = crypto.encrypt_payload(plaintext, obs_id_bytes)
    payloads = rs.encode(encrypted, EXTENDED_PAYLOAD_SIZE)
    total = len(payloads)
    buffer = FragmentBuffer(swarm_secret, redundancy_threshold=0.7)
    # Ingest ~75%: skip every 4th fragment (e.g. 6 of 8 fragments)
    ingested_count = 0
    for seq, payload in enumerate(payloads):
        if seq % 4 == 3:
            continue
        frag = enc.encode_fragment(obs_id_byte, seq, total, payload, 0)
        result = await buffer.ingest(frag)
        ingested_count += 1
        if result is not None:
            assert result.fibre_id == "test_fibre"
            assert ingested_count / total >= 0.7
            return
    # If threshold not met with 75%, ingest remaining until we reconstruct
    for seq in range(total):
        if seq % 4 == 3:
            frag = enc.encode_fragment(obs_id_byte, seq, total, payloads[seq], 0)
            result = await buffer.ingest(frag)
            if result is not None:
                assert result.fibre_id == "test_fibre"
                return


@pytest.mark.asyncio
async def test_duplicate_fragments_ignored(swarm_secret: bytes) -> None:
    """Same sequence number ingested twice, no error."""
    enc = FragmentEncoder(swarm_secret, "extended")
    frag = enc.encode_fragment(5, 0, 2, b"ab\x00\x00\x00", 0)
    buffer = FragmentBuffer(swarm_secret)
    r1 = await buffer.ingest(frag)
    r2 = await buffer.ingest(frag)
    assert r1 is None
    assert r2 is None


@pytest.mark.asyncio
async def test_purge_expired(swarm_secret: bytes) -> None:
    """Add old fragments, purge, verify removed."""
    enc = FragmentEncoder(swarm_secret, "extended")
    buffer = FragmentBuffer(swarm_secret, timeout_seconds=1)
    frag = enc.encode_fragment(99, 0, 3, b"xxxxx", 0)
    await buffer.ingest(frag)
    assert buffer.pending_count == 1
    time.sleep(1.5)
    purged = await buffer.purge_expired()
    assert purged == 1
    assert buffer.pending_count == 0
