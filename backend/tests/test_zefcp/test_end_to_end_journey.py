"""Integration test: encode → detect → reassemble observation."""

import json
from datetime import datetime
from uuid import uuid4

import pytest

from app.models.zefcp import ADStructure, BLEAdvertisingPDU, FibreObservation
from app.services.zefcp.constants import EXTENDED_PAYLOAD_SIZE
from app.services.zefcp.crypto import FibreFragmentCrypto
from app.services.zefcp.fragment import FragmentEncoder
from app.services.zefcp.fragment_buffer import FragmentBuffer
from app.services.zefcp.reed_solomon import ReedSolomonFragmentEncoder
from app.services.zefcp.spider_web import SpiderWebDetector


def _observation_to_json_payload(obs: FibreObservation) -> bytes:
    """Serialize observation to JSON matching fragment_buffer's expected format."""
    data = {
        "observation_id": str(obs.observation_id),
        "fibre_id": obs.fibre_id,
        "fibre_type": obs.fibre_type,
        "timestamp": obs.timestamp.timestamp(),
        "coherence_data": None,
        "cultural_signal": None,
        "foresight_signal": None,
        "confidence": obs.confidence,
        "priority": obs.priority,
    }
    return json.dumps(data).encode("utf-8")


@pytest.mark.asyncio
async def test_observation_encode_detect_reassemble(swarm_secret: bytes) -> None:
    """Full pipeline: FibreObservation → encode → detect → reassemble."""
    # Create minimal FibreObservation
    obs_id = uuid4()
    obs = FibreObservation(
        observation_id=obs_id,
        fibre_id="test_fibre_xyz",
        fibre_type="coherence",
        timestamp=datetime.utcnow(),
        coherence_data=None,
        cultural_signal=None,
        foresight_signal=None,
        confidence=0.85,
        priority=2,
    )
    # Use obs_id byte that matches extended-mode fragment (low byte of UUID)
    obs_id_byte = obs_id.bytes[0]
    obs_id_bytes = bytes([obs_id_byte])

    # Encode manually with JSON (ObservationEncoder uses binary serializer;
    # FragmentBuffer expects JSON for reconstruction)
    crypto = FibreFragmentCrypto(swarm_secret)
    rs = ReedSolomonFragmentEncoder(redundancy_factor=0.3)
    enc = FragmentEncoder(swarm_secret, "extended")

    plaintext = _observation_to_json_payload(obs)
    encrypted = crypto.encrypt_payload(plaintext, obs_id_bytes)
    payloads = rs.encode(encrypted, EXTENDED_PAYLOAD_SIZE)
    total = len(payloads)

    # Create fragments
    fragments = []
    for seq, payload in enumerate(payloads):
        frag = enc.encode_fragment(obs_id_byte, seq, total, payload, 0)
        fragments.append(frag)

    # Simulate detection: embed each fragment in BLE PDU, feed to SpiderWebDetector
    class CapturingBuffer(FragmentBuffer):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.reconstructed = None

        async def ingest(self, fragment):
            result = await super().ingest(fragment)
            if result is not None:
                self.reconstructed = result
            return result

    buffer = CapturingBuffer(swarm_secret, redundancy_threshold=0.7)
    detector = SpiderWebDetector(swarm_secret, buffer)

    for frag in fragments:
        ser = enc.serialize_fragment(frag)
        leading = ser[:6]
        trailing = ser[6:]
        prefix = b"\x00\x00"
        pdu = BLEAdvertisingPDU(
            ad_structures=[ADStructure(length=8, ad_type=0xFF, data=prefix + leading)],
            scan_response_data=[ADStructure(length=8, ad_type=0xFF, data=prefix + trailing)],
        )
        await detector.on_ble_advertisement(pdu)

    reconstructed = buffer.reconstructed
    assert reconstructed is not None
    assert reconstructed.fibre_id == "test_fibre_xyz"
    assert reconstructed.fibre_type == "coherence"
    assert reconstructed.confidence == 0.85
    assert reconstructed.priority == 2
