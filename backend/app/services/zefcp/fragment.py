"""
ZEFCP Fragment Encoding — Micro-fragment serialization and decoding.
Patent Claim 25: Zero-Energy BLE Communication — Parasitic encoding of
observations into BLE advertising overhead; CRC-8 integrity; standard/extended modes.
"""

from __future__ import annotations

import time
from typing import Optional

from app.models.zefcp import FragmentMode, FragmentType, MicroFragment
from app.services.zefcp.constants import (
    CRC8_INIT,
    CRC8_POLYNOMIAL,
    EXTENDED_PAYLOAD_SIZE,
    EXTENDED_TOTAL_BYTES,
    STANDARD_PAYLOAD_SIZE,
    STANDARD_TOTAL_BYTES,
)
from app.services.zefcp.signature import compute_signature


# =============================================================================
# CRC-8
# =============================================================================


def crc8(data: bytes) -> int:
    """
    Compute CRC-8 checksum with polynomial 0x07 (x^8 + x^2 + x + 1).
    Patent Claim 25: Integrity check for micro-fragments to reject false positives.
    """
    crc = CRC8_INIT
    poly = CRC8_POLYNOMIAL
    for byte in data:
        crc ^= byte
        for _ in range(8):
            if crc & 0x80:
                crc = (crc << 1) ^ poly
            else:
                crc <<= 1
            crc &= 0xFF
    return crc


# =============================================================================
# FRAGMENT ENCODER
# =============================================================================


class FragmentEncoder:
    """
    Encodes observations into MicroFragments for BLE parasitic transport.
    Patent Claim 25: Standard (8-byte) and extended (12-byte) modes.
    """

    def __init__(self, swarm_secret: bytes, mode: str = "extended") -> None:
        self._swarm_secret = swarm_secret
        self._mode = FragmentMode.EXTENDED if mode == "extended" else FragmentMode.STANDARD

    def encode_fragment(
        self,
        observation_id: int,
        sequence: int,
        total: int,
        payload: bytes,
        flags: int = 0,
    ) -> MicroFragment:
        """
        Produce a MicroFragment with signature, CRC, and all fields populated.
        Patent Claim 25: Computes rotation-scheduled signature and CRC-8 checksum.
        """
        epoch_minute = int(time.time() / 60)
        signature = compute_signature(epoch_minute, self._swarm_secret)

        if self._mode == FragmentMode.STANDARD:
            if len(payload) != STANDARD_PAYLOAD_SIZE:
                raise ValueError(
                    f"Standard mode requires {STANDARD_PAYLOAD_SIZE}-byte payload, got {len(payload)}"
                )
            frag_id = observation_id % 65536
            # Build bytes for CRC (without CHK)
            data_bytes = bytes([
                signature,
                sequence & 0xFF,
                total & 0xFF,
                (frag_id >> 8) & 0xFF,
                frag_id & 0xFF,
                payload[0],
                payload[1],
            ])
            checksum = crc8(data_bytes)
            return MicroFragment(
                signature=signature,
                sequence=sequence,
                total=total,
                observation_id=None,
                flags=None,
                epoch=None,
                frag_id=frag_id,
                payload=payload,
                fragment_type=FragmentType.DATA,
                checksum=checksum,
                mode=FragmentMode.STANDARD,
            )
        else:
            if len(payload) != EXTENDED_PAYLOAD_SIZE:
                raise ValueError(
                    f"Extended mode requires {EXTENDED_PAYLOAD_SIZE}-byte payload, got {len(payload)}"
                )
            obs_byte = observation_id & 0xFF
            epoch_byte = epoch_minute % 256
            data_bytes = bytes([
                signature,
                obs_byte,
                sequence & 0xFF,
                total & 0xFF,
                flags & 0xFF,
                epoch_byte,
                payload[0],
                payload[1],
                payload[2],
                payload[3],
                payload[4],
            ])
            checksum = crc8(data_bytes)
            return MicroFragment(
                signature=signature,
                sequence=sequence,
                total=total,
                observation_id=obs_byte,
                flags=flags,
                epoch=epoch_byte,
                frag_id=None,
                payload=payload,
                fragment_type=FragmentType.DATA,
                checksum=checksum,
                mode=FragmentMode.EXTENDED,
            )

    def serialize_fragment(self, fragment: MicroFragment) -> bytes:
        """
        Serialize MicroFragment to bytes for BLE transport.
        Patent Claim 25:
        - Standard: SIG, SEQ, TOTAL, FRAG_HI, FRAG_LO, PAYLOAD[2], CHK = 8 bytes
        - Extended: SIG, OBS_ID, SEQ, TOTAL, FLAGS, EPOCH, PAYLOAD[5], CHK = 12 bytes
        """
        if fragment.mode == FragmentMode.STANDARD:
            frag_id = fragment.frag_id or 0
            return bytes([
                fragment.signature,
                fragment.sequence & 0xFF,
                fragment.total & 0xFF,
                (frag_id >> 8) & 0xFF,
                frag_id & 0xFF,
                fragment.payload[0],
                fragment.payload[1],
                fragment.checksum,
            ])
        else:
            obs_id = fragment.observation_id or 0
            flags = fragment.flags or 0
            epoch = fragment.epoch or 0
            return bytes([
                fragment.signature,
                obs_id & 0xFF,
                fragment.sequence & 0xFF,
                fragment.total & 0xFF,
                flags & 0xFF,
                epoch & 0xFF,
                fragment.payload[0],
                fragment.payload[1],
                fragment.payload[2],
                fragment.payload[3],
                fragment.payload[4],
                fragment.checksum,
            ])


# =============================================================================
# FRAGMENT DECODER
# =============================================================================


class FragmentDecoder:
    """
    Decodes leading+trailing byte pairs into MicroFragments.
    Patent Claim 25: Validates CRC before accepting; distinguishes standard vs extended by length.
    """

    def __init__(self, swarm_secret: bytes) -> None:
        self._swarm_secret = swarm_secret

    def decode_bytes(
        self,
        leading: bytes,
        trailing: bytes,
    ) -> Optional[MicroFragment]:
        """
        Validate CRC, parse bytes into MicroFragment. Returns None if CRC fails.
        Patent Claim 25: Mode detected from total length (8=standard, 12=extended).
        """
        combined = leading + trailing
        total_len = len(combined)

        if total_len == STANDARD_TOTAL_BYTES:
            data_part = combined[: STANDARD_TOTAL_BYTES - 1]
            stored_chk = combined[STANDARD_TOTAL_BYTES - 1]
            if crc8(data_part) != stored_chk:
                return None
            return MicroFragment(
                signature=combined[0],
                sequence=combined[1],
                total=combined[2],
                observation_id=None,
                flags=None,
                epoch=None,
                frag_id=(combined[3] << 8) | combined[4],
                payload=combined[5:7],
                fragment_type=FragmentType.DATA,
                checksum=stored_chk,
                mode=FragmentMode.STANDARD,
            )
        elif total_len == EXTENDED_TOTAL_BYTES:
            data_part = combined[: EXTENDED_TOTAL_BYTES - 1]
            stored_chk = combined[EXTENDED_TOTAL_BYTES - 1]
            if crc8(data_part) != stored_chk:
                return None
            return MicroFragment(
                signature=combined[0],
                sequence=combined[2],
                total=combined[3],
                observation_id=combined[1],
                flags=combined[4],
                epoch=combined[5],
                frag_id=None,
                payload=combined[6:11],
                fragment_type=FragmentType.DATA,
                checksum=stored_chk,
                mode=FragmentMode.EXTENDED,
            )
        else:
            return None
