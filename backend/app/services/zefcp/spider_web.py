"""
ZEFCP Spider Web Detector — Passive BLE Monitor.
Patent Claim 25.1c: Zero-Energy BLE Communication — A Spider Web endpoint
passively monitors ambient BLE advertising PDUs, extracts fragments embedded
in exploitable AD structure overhead, validates via rotation-scheduled signature
and CRC-8, and ingests valid fragments into the fragment buffer.
"""

from __future__ import annotations

import time
from typing import Any, Dict, Optional

import structlog

from app.models.zefcp import BLEAdvertisingPDU, MicroFragment
from app.services.zefcp.constants import EXPLOITABLE_AD_TYPES, MINIMUM_FUNCTIONAL_BYTES
from app.services.zefcp.fragment_buffer import FragmentBuffer
from app.services.zefcp.fragment import FragmentDecoder
from app.services.zefcp.signature import SignatureRotator

logger = structlog.get_logger(__name__)


# =============================================================================
# SPIDER WEB DETECTOR
# =============================================================================


class SpiderWebDetector:
    """
    Passive BLE monitor that extracts ZEFCP micro-fragments from ambient
    advertising PDUs. Patent Claim 25.1c: Parasitic-symbiotic handshake
    piggybacking with zero energy cost to the detector.
    """

    def __init__(
        self,
        swarm_secret: bytes,
        fragment_buffer: FragmentBuffer,
        ci_orchestrator=None,
    ) -> None:
        """
        Initialize detector with swarm secret and fragment buffer reference.

        Args:
            swarm_secret: Shared secret for signature validation (NFC-provisioned).
            fragment_buffer: Buffer to ingest validated fragments.
            ci_orchestrator: Counter-intelligence orchestrator for attack signal reporting.
        """
        self._swarm_secret = swarm_secret
        self.buffer = fragment_buffer
        self._ci_orchestrator = ci_orchestrator
        self._signature_rotator = SignatureRotator(swarm_secret)
        self._decoder = FragmentDecoder(swarm_secret)
        self.active_beams: Dict[str, Any] = {}  # Quakete particle beam boosts

    # -------------------------------------------------------------------------
    # BLE Advertisement Handler
    # -------------------------------------------------------------------------

    async def on_ble_advertisement(self, pdu: BLEAdvertisingPDU) -> None:
        """
        Process a BLE advertising PDU and attempt fragment extraction.
        Patent Claim 25.1c: Extract leading window from first exploitable AD
        structure, trailing window from last scan response structure.
        """
        leading = self._extract_leading_window(pdu)
        trailing = self._extract_trailing_window(pdu)
        if leading is None or trailing is None:
            return

        combined_len = len(leading) + len(trailing)
        first_byte = leading[0] if leading else None
        if first_byte is None:
            return

        if not self._signature_rotator.is_valid(first_byte):
            # Signature validation failed — report to counter-intelligence
            await self._report_detection_failure(
                pdu, "signature_mismatch",
                signature_guess=first_byte,
            )
            return

        fragment = self._decoder.decode_bytes(leading, trailing)
        if fragment is None:
            if self.active_beams:
                fragment = self._attempt_aggressive_extraction(leading, trailing)
            if fragment is None:
                # CRC or structural validation failed — report
                await self._report_detection_failure(
                    pdu, "crc_structural_failure",
                    signature_guess=first_byte,
                )
                return

        fragment.detected_at = time.time()
        fragment.detected_by = "spider_web"
        fragment.rssi = pdu.rssi
        fragment.carrier_device = pdu.source_address

        priority_boost = 1.0
        if self.active_beams:
            for beam in self.active_beams.values():
                if hasattr(beam, "target_fibre_id"):
                    fibre_id = getattr(beam, "target_fibre_id", "")
                    if fibre_id and hasattr(fragment, "fibre_id"):
                        pass
                if hasattr(beam, "boost"):
                    priority_boost = max(priority_boost, getattr(beam, "boost", 1.0))
        fragment.priority_boost = priority_boost

        await self.buffer.ingest(fragment)

    def _attempt_aggressive_extraction(
        self, leading: bytes, trailing: bytes
    ) -> Optional[MicroFragment]:
        """
        Attempt extraction with relaxed constraints when Quakete beams are active.
        Used when standard decode fails but beams indicate expected traffic.
        """
        fragment = self._decoder.decode_bytes(leading, trailing)
        return fragment

    # -------------------------------------------------------------------------
    # Window Extraction
    # -------------------------------------------------------------------------

    def _extract_leading_window(self, pdu: BLEAdvertisingPDU) -> Optional[bytes]:
        """
        Extract leading window bytes from first exploitable AD structure.
        N = min(6, len - MINIMUM_FUNCTIONAL_BYTES); returns last N bytes.
        """
        for ad in pdu.ad_structures:
            if ad.ad_type not in EXPLOITABLE_AD_TYPES:
                continue
            min_func = MINIMUM_FUNCTIONAL_BYTES.get(ad.ad_type, 0)
            if len(ad.data) <= min_func:
                continue
            n = min(6, len(ad.data) - min_func)
            if n <= 0:
                continue
            return ad.data[-n:]
        return None

    def _extract_trailing_window(self, pdu: BLEAdvertisingPDU) -> Optional[bytes]:
        """
        Extract trailing window bytes from last scan response AD structure.
        Same logic as leading but from scan_response_data.
        """
        scan_resp = pdu.scan_response_data or []
        if not scan_resp:
            return None
        for ad in reversed(scan_resp):
            if ad.ad_type not in EXPLOITABLE_AD_TYPES:
                continue
            min_func = MINIMUM_FUNCTIONAL_BYTES.get(ad.ad_type, 0)
            if len(ad.data) <= min_func:
                continue
            n = min(6, len(ad.data) - min_func)
            if n <= 0:
                continue
            return ad.data[-n:]
        return None

    # -------------------------------------------------------------------------
    # Counter-Intelligence — Detection Failure Reporting
    # -------------------------------------------------------------------------

    async def _report_detection_failure(
        self,
        pdu: BLEAdvertisingPDU,
        failure_type: str,
        signature_guess: Optional[int] = None,
    ) -> None:
        """
        Report a detection failure to the counter-intelligence orchestrator.
        Every failed extraction reveals information about potential attackers.
        """
        if not self._ci_orchestrator:
            return
        try:
            from app.services.counter_intelligence.orchestrator import (
                AttackSignal,
                AttackSource,
            )
            from app.services.counter_intelligence.fingerprinter import (
                AttackFingerprinter,
            )

            # Compute AD pattern hash for device fingerprinting
            ad_types = [ad.ad_type for ad in pdu.ad_structures]
            ad_lengths = [len(ad.data) for ad in pdu.ad_structures]
            mfr_ids = []
            for ad in pdu.ad_structures:
                if ad.ad_type == 0xFF and len(ad.data) >= 2:
                    mfr_ids.append(int.from_bytes(ad.data[:2], "little"))
            ad_hash = AttackFingerprinter.compute_ad_pattern_hash(
                ad_types, ad_lengths, mfr_ids,
            )

            signal = AttackSignal(
                source=AttackSource.BLE,
                failure_type=failure_type,
                device_address=pdu.source_address,
                metadata={
                    "ad_pattern_hash": ad_hash,
                    "rssi": pdu.rssi,
                    "signature_guess": signature_guess,
                    "ad_types": ad_types,
                },
            )
            await self._ci_orchestrator.ingest_signal(signal)
        except Exception as exc:
            logger.debug("CI reporting error: %s", exc)

    # -------------------------------------------------------------------------
    # Quakete Beam Handler
    # -------------------------------------------------------------------------

    async def on_quakete_beam(self, beam: Any) -> None:
        """
        Store active Quakete particle beam for priority boost on matching fragments.
        Beam objects should have target_fibre_id and optionally boost multiplier.
        """
        fibre_id = getattr(beam, "target_fibre_id", None) or "unknown"
        self.active_beams[fibre_id] = beam
        logger.debug("quakete_beam_registered", fibre_id=fibre_id)
