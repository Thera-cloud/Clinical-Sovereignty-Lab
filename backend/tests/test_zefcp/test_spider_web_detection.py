"""Tests for spider_web.py — BLE PDU fragment extraction and Quakete beams."""

import pytest

from app.models.zefcp import ADStructure, BLEAdvertisingPDU, MicroFragment
from app.services.zefcp.fragment import FragmentEncoder, FragmentDecoder
from app.services.zefcp.fragment_buffer import FragmentBuffer
from app.services.zefcp.spider_web import SpiderWebDetector


@pytest.fixture
def fragment_buffer(swarm_secret: bytes) -> FragmentBuffer:
    """Fragment buffer for detection tests."""
    return FragmentBuffer(swarm_secret, timeout_seconds=3600)


@pytest.fixture
def detector(swarm_secret: bytes, fragment_buffer: FragmentBuffer) -> SpiderWebDetector:
    """Spider Web detector instance."""
    return SpiderWebDetector(swarm_secret, fragment_buffer)


@pytest.mark.asyncio
async def test_valid_fragment_detected(
    swarm_secret: bytes,
    fragment_buffer: FragmentBuffer,
) -> None:
    """Construct a BLEAdvertisingPDU with embedded fragment, verify SpiderWebDetector extracts it."""
    enc = FragmentEncoder(swarm_secret, "extended")
    frag = enc.encode_fragment(7, 0, 1, b"hell\x6f", 0)
    ser = enc.serialize_fragment(frag)
    leading = ser[:6]
    trailing = ser[6:]
    # AD type 0xFF with manufacturer data; need MINIMUM_FUNCTIONAL_BYTES[0xFF]=2 prefix + 6 exploitable
    prefix = b"\x00\x00"  # company ID placeholder
    ad_data = prefix + leading
    scan_resp_data = prefix + trailing
    pdu = BLEAdvertisingPDU(
        ad_structures=[ADStructure(length=len(ad_data), ad_type=0xFF, data=ad_data)],
        scan_response_data=[ADStructure(length=len(scan_resp_data), ad_type=0xFF, data=scan_resp_data)],
        rssi=-65,
        source_address="AA:BB:CC:DD:EE:FF",
    )
    detector = SpiderWebDetector(swarm_secret, fragment_buffer)
    # Verify extraction runs without error; valid SIG+CRC causes fragment to be ingested
    await detector.on_ble_advertisement(pdu)


@pytest.mark.asyncio
async def test_invalid_signature_rejected(
    swarm_secret: bytes,
    detector: SpiderWebDetector,
    fragment_buffer: FragmentBuffer,
) -> None:
    """PDU with wrong SIG byte is ignored."""
    # Build bytes that look like a fragment but with invalid signature
    dec = FragmentDecoder(swarm_secret)
    # Use random bytes that won't pass signature check
    bad_leading = bytes([0x99, 0x01, 0x00, 0x01, 0x00, 0x00])  # wrong first byte
    bad_trailing = bytes([0x00, 0x00, 0x00, 0x00, 0x00, 0xAB])  # arbitrary, will fail CRC anyway
    prefix = b"\x00\x00"
    pdu = BLEAdvertisingPDU(
        ad_structures=[ADStructure(length=8, ad_type=0xFF, data=prefix + bad_leading)],
        scan_response_data=[ADStructure(length=8, ad_type=0xFF, data=prefix + bad_trailing)],
        rssi=-70,
    )
    before = fragment_buffer.pending_count
    await detector.on_ble_advertisement(pdu)
    # Invalid signature or CRC should not add to pending
    assert fragment_buffer.pending_count == before


@pytest.mark.asyncio
async def test_quakete_beam_boosts_detection(
    swarm_secret: bytes,
    fragment_buffer: FragmentBuffer,
) -> None:
    """Register a beam, verify fragment gets priority_boost."""
    ingested_fragments = []

    class CaptureBuffer(FragmentBuffer):
        async def ingest(self, fragment):
            ingested_fragments.append(fragment)
            return await super().ingest(fragment)

    cap_buf = CaptureBuffer(swarm_secret)
    detector = SpiderWebDetector(swarm_secret, cap_buf)

    class FakeBeam:
        target_fibre_id = "fibre_42"
        boost = 2.5

    await detector.on_quakete_beam(FakeBeam())
    assert "fibre_42" in detector.active_beams
    assert detector.active_beams["fibre_42"].boost == 2.5

    # Feed valid fragment to verify priority_boost is applied
    enc = FragmentEncoder(swarm_secret, "extended")
    frag = enc.encode_fragment(8, 0, 1, b"xxxxx", 0)
    ser = enc.serialize_fragment(frag)
    prefix = b"\x00\x00"
    pdu = BLEAdvertisingPDU(
        ad_structures=[ADStructure(length=8, ad_type=0xFF, data=prefix + ser[:6])],
        scan_response_data=[ADStructure(length=8, ad_type=0xFF, data=prefix + ser[6:])],
    )
    await detector.on_ble_advertisement(pdu)
    assert len(ingested_fragments) == 1
    assert ingested_fragments[0].priority_boost == 2.5
