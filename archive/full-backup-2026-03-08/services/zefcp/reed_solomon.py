"""
ZEFCP Reed-Solomon Fragment Encoder — Patent Claim 25.4
Zero-Energy BLE Communication: Reed-Solomon error correction with
configurable redundancy and PARITY_INTERLEAVE_INTERVAL pattern.

Patent Claim 25.4: Fragments are protected by Reed-Solomon codes with
redundancy factor and interleaved parity (every 4th fragment) for burst
loss resilience over parasitic BLE transport.
"""

from __future__ import annotations

import math
from typing import Dict, List

from reedsolo import RSCodec, ReedSolomonError

from app.services.zefcp.constants import (
    MAX_FRAGMENTS_PER_OBSERVATION,
    PARITY_INTERLEAVE_INTERVAL,
)


# =============================================================================
# REED-SOLOMON FRAGMENT ENCODER
# =============================================================================


class ReedSolomonFragmentEncoder:
    """
    Reed-Solomon encoder/decoder for fragment-level error correction.
    Patent Claim 25.4: Configurable redundancy, interleaved parity pattern.
    """

    def __init__(self, redundancy_factor: float = 0.3) -> None:
        """
        Initialize with redundancy factor (e.g. 0.3 = 30% parity overhead).
        """
        if redundancy_factor < 0.0 or redundancy_factor > 1.0:
            raise ValueError("redundancy_factor must be in [0.0, 1.0]")
        self._redundancy = redundancy_factor

    @property
    def redundancy(self) -> float:
        """Re redundancy factor."""
        return self._redundancy

    def encode(self, data: bytes, payload_size: int) -> List[bytes]:
        """
        Encode data into fragment payloads with Reed-Solomon parity.
        Patent Claim 25.4: Pad, split, RS encode, interleave data/parity
        every PARITY_INTERLEAVE_INTERVAL.

        Args:
            data: Raw bytes to encode.
            payload_size: Bytes per fragment (2 or 5).

        Returns:
            List of fragment payloads (data and parity interleaved).

        Raises:
            ValueError: If total fragments would exceed MAX_FRAGMENTS_PER_OBSERVATION.
        """
        if payload_size < 1:
            raise ValueError("payload_size must be >= 1")

        # Pad to exact multiple of payload_size
        pad_len = (payload_size - (len(data) % payload_size)) % payload_size
        if pad_len:
            data = data + b"\x00" * pad_len

        data_fragments = len(data) // payload_size
        parity_fragments = math.ceil(data_fragments * self._redundancy)
        total_fragments = data_fragments + parity_fragments

        if total_fragments > MAX_FRAGMENTS_PER_OBSERVATION:
            raise ValueError(
                f"Total fragments {total_fragments} exceeds "
                f"MAX_FRAGMENTS_PER_OBSERVATION ({MAX_FRAGMENTS_PER_OBSERVATION})"
            )

        # Reed-Solomon: nsym = parity bytes (symbols in GF(256))
        nsym = parity_fragments * payload_size
        if nsym <= 0:
            nsym = 1  # RSCodec requires at least 1

        rs = RSCodec(nsym)
        encoded = rs.encode(data)

        # Split into data and parity chunks
        data_bytes_len = data_fragments * payload_size
        data_chunks = [
            encoded[i : i + payload_size]
            for i in range(0, data_bytes_len, payload_size)
        ]
        parity_chunks = [
            encoded[data_bytes_len + i : data_bytes_len + i + payload_size]
            for i in range(0, len(encoded) - data_bytes_len, payload_size)
        ]

        # Interleave: data, data, data, parity (every PARITY_INTERLEAVE_INTERVAL)
        result: List[bytes] = []
        data_idx = 0
        parity_idx = 0
        pos = 0

        while data_idx < len(data_chunks) or parity_idx < len(parity_chunks):
            if (pos + 1) % PARITY_INTERLEAVE_INTERVAL == 0 and parity_idx < len(parity_chunks):
                result.append(parity_chunks[parity_idx])
                parity_idx += 1
            elif data_idx < len(data_chunks):
                result.append(data_chunks[data_idx])
                data_idx += 1
            elif parity_idx < len(parity_chunks):
                result.append(parity_chunks[parity_idx])
                parity_idx += 1
            pos += 1

        return result

    def decode(self, fragments: Dict[int, bytes], total: int, payload_size: int) -> bytes:
        """
        Reconstruct data from fragment payloads (with possible gaps).
        Patent Claim 25.4: Uses Reed-Solomon to reconstruct missing symbols.

        Args:
            fragments: Dict of {sequence: payload} (missing entries = erasures).
            total: Total number of fragments in the original encoding.
            payload_size: Bytes per fragment (must match encoding).

        Returns:
            Reconstructed data bytes.

        Raises:
            ValueError: If too few fragments for reconstruction.
        """
        if total < 1 or total > MAX_FRAGMENTS_PER_OBSERVATION:
            raise ValueError(f"total must be in [1, {MAX_FRAGMENTS_PER_OBSERVATION}]")
        if payload_size < 1:
            raise ValueError("payload_size must be >= 1")

        # De-interleave: rebuild encoded byte sequence in order
        # We need fragments in sequence order; missing = erasure
        ordered: List[bytes | None] = [None] * total
        for seq, payload in fragments.items():
            if 0 <= seq < total and len(payload) == payload_size:
                ordered[seq] = payload

        # Flatten to byte string, marking erasures
        # RSCodec.decode can handle erasures via erase_pos
        decoded_bytes = bytearray()
        erase_positions: List[int] = []
        pos = 0

        for seq in range(total):
            if ordered[seq] is not None:
                decoded_bytes.extend(ordered[seq])
            else:
                for _ in range(payload_size):
                    decoded_bytes.append(0)  # Placeholder for erasure
                    erase_positions.append(pos)
                    pos += 1
                continue
            pos += payload_size

        # Calculate data length (total - parity)
        data_fragments = math.ceil(
            (total * payload_size) / (1 + self._redundancy)
        ) / (1 + self._redundancy)
        # Simpler: total_fragments = data + parity, parity = ceil(data * r)
        # So data_fragments = total / (1 + r) approximately
        data_fragment_count = int(total / (1 + self._redundancy))
        parity_fragment_count = total - data_fragment_count
        nsym = parity_fragment_count * payload_size
        data_len = data_fragment_count * payload_size

        if len(decoded_bytes) < data_len + nsym:
            raise ValueError(
                "Insufficient fragments for Reed-Solomon reconstruction"
            )

        try:
            rs = RSCodec(nsym)
            reconstructed = rs.decode(bytes(decoded_bytes))
            # Remove padding (trailing zeros that we added)
            result = bytes(reconstructed[:data_len])
            # Strip trailing null padding from original encode
            pad_count = 0
            for i in range(len(result) - 1, -1, -1):
                if result[i] == 0:
                    pad_count += 1
                else:
                    break
            # Only strip if it looks like padding (at block boundary)
            if pad_count > 0 and pad_count < payload_size:
                result = result[: -pad_count]
            return result
        except Exception as e:
            raise ValueError(f"Reed-Solomon decode failed: {e}") from e
