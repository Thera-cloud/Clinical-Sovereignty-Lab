"""
ZEFCP Observation Serializer — Patent Claim 25
Zero-Energy BLE Communication: Serialization and deserialization of
FibreObservation for parasitic BLE transport.

Patent Claim 25: Fibre observations are serialized with fixed header
(fibre_id, fibre_type, timestamp, confidence), LZMA-compressed variable
blocks (coherence_data, cultural_signal, foresight_signal), each prefixed
with 2-byte length (or b'\\x00\\x00' if None).
"""

from __future__ import annotations

import hashlib
import lzma
import struct
from datetime import datetime
from uuid import UUID

from app.models.zefcp import FibreObservation


# =============================================================================
# OBSERVATION SERIALIZER
# =============================================================================


class ObservationSerializer:
    """
    Serializes and deserializes FibreObservation for transport.
    Patent Claim 25: Compact binary format with LZMA compression.
    """

    # Header: fibre_id (4) + fibre_type (1) + timestamp (4) + confidence (1) = 10 bytes
    HEADER_SIZE = 10
    HEADER_FORMAT = "<I B I B"  # fibre_id_hash, fibre_type_byte, timestamp, confidence_byte

    def _fibre_id_to_bytes(self, fibre_id: str) -> bytes:
        """Encode fibre_id to 4 bytes (SHA256 truncated)."""
        h = hashlib.sha256(fibre_id.encode("utf-8")).digest()
        return h[:4]

    def _fibre_id_from_bytes(self, data: bytes) -> str:
        """Decode fibre_id from 4 bytes — returns hex for round-trip (actual ID lost)."""
        return data.hex()

    def _fibre_type_to_byte(self, fibre_type: str) -> int:
        """Encode fibre_type to 1 byte (deterministic hash)."""
        h = hashlib.sha256(fibre_type.encode("utf-8")).digest()
        return h[0]

    def _fibre_type_from_byte(self, b: int) -> str:
        """Decode fibre_type — 1 byte cannot store string; return placeholder."""
        return f"FibreType_{b:02x}"

    def serialize(self, observation: FibreObservation) -> bytes:
        """
        Serialize FibreObservation to bytes.
        Patent Claim 25: Pack header, append LZMA-compressed blocks with 2-byte length.

        Args:
            observation: The FibreObservation to serialize.

        Returns:
            Serialized bytes.
        """
        fibre_id_bytes = self._fibre_id_to_bytes(observation.fibre_id)
        fibre_id_int = struct.unpack("<I", fibre_id_bytes)[0]
        fibre_type_byte = self._fibre_type_to_byte(observation.fibre_type)
        timestamp_int = int(observation.timestamp.timestamp()) & 0xFFFFFFFF
        confidence_byte = int(round(observation.confidence * 255)) & 0xFF

        header = struct.pack(
            self.HEADER_FORMAT,
            fibre_id_int,
            fibre_type_byte,
            timestamp_int,
            confidence_byte,
        )

        parts = [header]

        for block in (
            observation.coherence_data,
            observation.cultural_signal,
            observation.foresight_signal,
        ):
            if block is None:
                parts.append(b"\x00\x00")
            else:
                compressed = lzma.compress(block, preset=9)
                length = len(compressed)
                if length > 65535:
                    raise ValueError(f"Compressed block exceeds 65535 bytes: {length}")
                parts.append(struct.pack("<H", length) + compressed)

        return b"".join(parts)

    def deserialize(self, data: bytes) -> FibreObservation:
        """
        Deserialize bytes to FibreObservation.
        Patent Claim 25: Inverse of serialize.

        Args:
            data: Serialized bytes.

        Returns:
            Reconstructed FibreObservation.

        Raises:
            ValueError: If data is truncated or malformed.
        """
        if len(data) < self.HEADER_SIZE:
            raise ValueError(f"Data too short: {len(data)} < {self.HEADER_SIZE}")

        header = data[: self.HEADER_SIZE]
        fibre_id_int, fibre_type_byte, timestamp_int, confidence_byte = struct.unpack(
            self.HEADER_FORMAT, header
        )
        fibre_id_bytes = struct.pack("<I", fibre_id_int)
        fibre_id = self._fibre_id_from_bytes(fibre_id_bytes)
        fibre_type = self._fibre_type_from_byte(fibre_type_byte)
        timestamp = datetime.utcfromtimestamp(timestamp_int)
        confidence = confidence_byte / 255.0

        pos = self.HEADER_SIZE
        blocks: list[bytes | None] = []

        for _ in range(3):
            if pos + 2 > len(data):
                raise ValueError("Truncated length prefix")
            length = struct.unpack("<H", data[pos : pos + 2])[0]
            pos += 2
            if length == 0:
                blocks.append(None)
            else:
                if pos + length > len(data):
                    raise ValueError("Truncated compressed block")
                compressed = data[pos : pos + length]
                pos += length
                blocks.append(lzma.decompress(compressed))

        coherence_data, cultural_signal, foresight_signal = blocks

        return FibreObservation(
            fibre_id=fibre_id,
            fibre_type=fibre_type,
            timestamp=timestamp,
            coherence_data=coherence_data,
            cultural_signal=cultural_signal,
            foresight_signal=foresight_signal,
            confidence=confidence,
        )
