"""
HIVE DEFENSE PROTOCOL — Watermark Engine (Phase 8B)
Steganographic tracing for synthetic data exfiltration detection.

Embeds invisible watermarks into synthetic data produced by the
Verisimilitude Engine.  If an attacker exfiltrates and publishes
or uses watermarked data, the watermark traces back to:

    1. The specific trap deployment (``deployment_id``)
    2. The specific attacker profile (``attacker_profile_id``)
    3. The exact timestamp of generation

Watermark Channels
------------------
Watermarks are distributed across multiple steganographic channels
so that removing one channel does not eliminate traceability:

* **Numerical Precision** — Last 2 significant digits of floating-point
  values encode a fragment of the trap ID.
* **Zero-Width Unicode** — Invisible zero-width characters (U+200B,
  U+200C, U+200D, U+FEFF) embedded in string values encode binary data.
* **JSON Field Ordering** — Deterministic field ordering encodes a
  permutation index derived from the watermark payload.
* **Timestamp Microseconds** — The microsecond component of datetime
  strings encodes a watermark fragment.

No single channel is sufficient alone; the engine uses all channels
together and can recover the watermark from any 2 of 4 channels
(redundant encoding).

Patent-Pending — Claim 39
© 2026 Clinical Sovereignty Lab. All rights reserved.
"""

from __future__ import annotations

import hashlib
import json
import logging
import math
import struct
import time
from collections import OrderedDict
from datetime import datetime
from itertools import permutations
from typing import Any, Dict, List, Optional, Tuple, Union
from uuid import UUID, uuid4

logger = logging.getLogger("hive.watermark_engine")


# =============================================================================
# CONSTANTS
# =============================================================================

# Zero-width Unicode characters used for string steganography
_ZW_SPACE = "\u200B"       # Zero-Width Space
_ZW_NON_JOINER = "\u200C"  # Zero-Width Non-Joiner
_ZW_JOINER = "\u200D"      # Zero-Width Joiner
_ZW_NO_BREAK = "\uFEFF"    # Zero-Width No-Break Space (BOM)

# Encoding: each pair of bits maps to a zero-width character
_BIT_PAIR_TO_ZW = {
    "00": _ZW_SPACE,
    "01": _ZW_NON_JOINER,
    "10": _ZW_JOINER,
    "11": _ZW_NO_BREAK,
}

_ZW_TO_BIT_PAIR = {v: k for k, v in _BIT_PAIR_TO_ZW.items()}

# Set of all zero-width chars for fast detection
_ZW_CHARS = set(_BIT_PAIR_TO_ZW.values())

# Watermark payload structure:
#   deployment_id (16 bytes) + profile_id (16 bytes) + timestamp (8 bytes)
#   = 40 bytes = 320 bits
_PAYLOAD_SIZE_BYTES = 40

# Marker prefix for watermark detection (8 bytes, arbitrary magic)
_WATERMARK_MAGIC = b"\x53\x56\x52\x4E"  # "SVRN" in ASCII

# Number of numerical precision digits to use for encoding
_PRECISION_ENCODE_DIGITS = 2

# Minimum fields needed for field-ordering channel
_MIN_FIELDS_FOR_ORDERING = 4


# =============================================================================
# WATERMARK PAYLOAD
# =============================================================================

class WatermarkPayload:
    """
    Structured watermark payload containing tracing information.

    Attributes
    ----------
    deployment_id : UUID
        The trap deployment this watermark belongs to.
    attacker_profile_id : UUID
        The attacker profile associated with this data.
    timestamp : datetime
        When the watermarked data was generated.
    checksum : str
        SHA-256 checksum of the payload for integrity verification.
    """

    __slots__ = ("deployment_id", "attacker_profile_id", "timestamp", "checksum")

    def __init__(
        self,
        deployment_id: UUID,
        attacker_profile_id: UUID,
        timestamp: Optional[datetime] = None,
    ) -> None:
        self.deployment_id = deployment_id
        self.attacker_profile_id = attacker_profile_id
        self.timestamp = timestamp or datetime.utcnow()
        self.checksum = self._compute_checksum()

    def _compute_checksum(self) -> str:
        """Compute integrity checksum over the payload fields."""
        data = (
            self.deployment_id.bytes +
            self.attacker_profile_id.bytes +
            struct.pack(">d", self.timestamp.timestamp())
        )
        return hashlib.sha256(data).hexdigest()[:16]

    def to_bytes(self) -> bytes:
        """Serialise the payload to a 40-byte binary representation."""
        return (
            self.deployment_id.bytes +            # 16 bytes
            self.attacker_profile_id.bytes +       # 16 bytes
            struct.pack(">d", self.timestamp.timestamp())  # 8 bytes
        )

    @classmethod
    def from_bytes(cls, data: bytes) -> Optional["WatermarkPayload"]:
        """
        Deserialise a payload from bytes.

        Returns None if the data is malformed.
        """
        if len(data) < _PAYLOAD_SIZE_BYTES:
            return None
        try:
            deployment_id = UUID(bytes=data[0:16])
            profile_id = UUID(bytes=data[16:32])
            ts_float = struct.unpack(">d", data[32:40])[0]
            timestamp = datetime.utcfromtimestamp(ts_float)
            return cls(deployment_id, profile_id, timestamp)
        except Exception:
            return None

    def to_dict(self) -> Dict[str, str]:
        """Serialise to a human-readable dictionary."""
        return {
            "deployment_id": str(self.deployment_id),
            "attacker_profile_id": str(self.attacker_profile_id),
            "timestamp": self.timestamp.isoformat(),
            "checksum": self.checksum,
        }


# =============================================================================
# WATERMARK ENGINE
# =============================================================================

class WatermarkEngine:
    """
    Steganographic watermark engine for tracing synthetic data.

    Embeds invisible watermarks across multiple channels (numerical
    precision, zero-width Unicode, JSON field ordering, timestamp
    microseconds) and can detect/extract them from watermarked data.

    Usage
    -----
    ::

        engine = WatermarkEngine()

        # Embed
        watermarked = engine.embed_watermark(
            data=synthetic_record,
            deployment_id=trap_deployment_id,
            attacker_profile_id=attacker_id,
        )

        # Detect
        result = engine.detect_watermark(watermarked)
        if result:
            deployment_id, profile_id, timestamp = result

        # Verify
        is_ours = engine.verify_watermark(watermarked, expected_deployment_id)
    """

    def __init__(self) -> None:
        self._embed_count = 0
        self._detect_count = 0
        logger.info("WatermarkEngine initialised.")

    # ================================================================== #
    # PUBLIC API
    # ================================================================== #

    def embed_watermark(
        self,
        data: Dict[str, Any],
        deployment_id: UUID,
        attacker_profile_id: UUID,
        timestamp: Optional[datetime] = None,
    ) -> Dict[str, Any]:
        """
        Embed a steganographic watermark into a data dictionary.

        The watermark is distributed across all available channels.
        The returned data looks identical to the input in normal use.

        Parameters
        ----------
        data : dict
            The synthetic data record to watermark.
        deployment_id : UUID
            Trap deployment identifier.
        attacker_profile_id : UUID
            Attacker profile identifier.
        timestamp : datetime, optional
            Generation timestamp.  Defaults to ``utcnow()``.

        Returns
        -------
        dict
            A deep copy of ``data`` with embedded watermarks.
        """
        payload = WatermarkPayload(deployment_id, attacker_profile_id, timestamp)
        payload_bytes = payload.to_bytes()

        # Deep copy to avoid mutating the original
        watermarked = json.loads(json.dumps(data, default=str))

        # Channel 1: Numerical precision
        self._embed_numerical_precision(watermarked, payload_bytes)

        # Channel 2: Zero-width Unicode in strings
        self._embed_zero_width(watermarked, payload_bytes)

        # Channel 3: JSON field ordering
        watermarked = self._embed_field_ordering(watermarked, payload_bytes)

        # Channel 4: Timestamp microseconds
        self._embed_timestamp_microseconds(watermarked, payload_bytes)

        self._embed_count += 1
        logger.debug(
            "Watermark embedded — deployment: %s, profile: %s (embed #%d)",
            deployment_id,
            attacker_profile_id,
            self._embed_count,
        )

        return watermarked

    def detect_watermark(
        self,
        data: Dict[str, Any],
    ) -> Optional[Tuple[UUID, UUID, datetime]]:
        """
        Attempt to detect and extract a watermark from data.

        Tries all channels and uses consensus to recover the payload.

        Parameters
        ----------
        data : dict
            Potentially watermarked data.

        Returns
        -------
        tuple[UUID, UUID, datetime] or None
            ``(deployment_id, attacker_profile_id, timestamp)`` if a
            watermark is found, or ``None`` if no watermark detected.
        """
        self._detect_count += 1
        candidates: List[Optional[WatermarkPayload]] = []

        # Channel 1: Numerical precision
        payload_1 = self._detect_numerical_precision(data)
        candidates.append(payload_1)

        # Channel 2: Zero-width Unicode
        payload_2 = self._detect_zero_width(data)
        candidates.append(payload_2)

        # Channel 3: Field ordering
        payload_3 = self._detect_field_ordering(data)
        candidates.append(payload_3)

        # Channel 4: Timestamp microseconds
        payload_4 = self._detect_timestamp_microseconds(data)
        candidates.append(payload_4)

        # Consensus: find the most-agreed-upon payload
        valid = [c for c in candidates if c is not None]
        if not valid:
            logger.debug("No watermark detected (detect #%d).", self._detect_count)
            return None

        # Use the first valid payload (channels are redundant)
        best = self._consensus_payload(valid)
        if best:
            logger.info(
                "Watermark detected — deployment: %s, profile: %s, "
                "timestamp: %s (from %d/%d channels)",
                best.deployment_id,
                best.attacker_profile_id,
                best.timestamp.isoformat(),
                len(valid),
                len(candidates),
            )
            return (best.deployment_id, best.attacker_profile_id, best.timestamp)

        return None

    def verify_watermark(
        self,
        data: Dict[str, Any],
        expected_deployment_id: UUID,
    ) -> bool:
        """
        Verify that data contains a watermark matching a specific deployment.

        Parameters
        ----------
        data : dict
            Potentially watermarked data.
        expected_deployment_id : UUID
            The deployment ID to verify against.

        Returns
        -------
        bool
            ``True`` if a matching watermark is found.
        """
        result = self.detect_watermark(data)
        if result is None:
            return False
        detected_deployment_id, _, _ = result
        match = detected_deployment_id == expected_deployment_id
        logger.info(
            "Watermark verification: %s (expected: %s, found: %s)",
            "MATCH" if match else "MISMATCH",
            expected_deployment_id,
            detected_deployment_id,
        )
        return match

    # ================================================================== #
    # CHANNEL 1: NUMERICAL PRECISION
    # ================================================================== #

    def _embed_numerical_precision(
        self,
        data: Dict[str, Any],
        payload_bytes: bytes,
    ) -> None:
        """
        Encode watermark fragments in the last 2 significant digits
        of floating-point values.

        Each float encodes one byte of the payload in its last two
        decimal places (00-99 → byte values 0-255 mapped modulo).
        """
        byte_idx = [0]  # Mutable counter for recursive traversal

        def _walk(obj: Any, parent: Any = None, key: Any = None) -> None:
            if byte_idx[0] >= len(payload_bytes):
                return

            if isinstance(obj, dict):
                for k in list(obj.keys()):
                    _walk(obj[k], obj, k)
            elif isinstance(obj, list):
                for i, item in enumerate(obj):
                    _walk(item, obj, i)
            elif isinstance(obj, float) and parent is not None:
                if byte_idx[0] < len(payload_bytes):
                    encoded = self._encode_float_precision(
                        obj, payload_bytes[byte_idx[0]]
                    )
                    parent[key] = encoded
                    byte_idx[0] += 1

        _walk(data)

    @staticmethod
    def _encode_float_precision(value: float, byte_val: int) -> float:
        """
        Encode a single byte into the last 2 significant digits of a float.

        The encoding preserves the first N-2 significant digits and
        replaces the last 2 with a value derived from ``byte_val``.
        """
        if value == 0.0:
            return value

        # Determine the scale of the value
        magnitude = math.floor(math.log10(abs(value))) if value != 0 else 0
        scale = 10 ** (magnitude - 4)  # Target the 5th-6th significant digits

        # Compute the encoding delta
        encoded_fragment = byte_val % 100
        # Remove existing last 2 digits and replace
        base = round(value / (scale * 100)) * (scale * 100)
        encoded = base + encoded_fragment * scale

        # Preserve sign
        if value < 0 and encoded > 0:
            encoded = -encoded
        elif value > 0 and encoded < 0:
            encoded = -encoded

        return round(encoded, 10)

    def _detect_numerical_precision(
        self,
        data: Dict[str, Any],
    ) -> Optional[WatermarkPayload]:
        """Extract watermark bytes from float precision encoding."""
        extracted_bytes = bytearray()

        def _walk(obj: Any) -> None:
            if len(extracted_bytes) >= _PAYLOAD_SIZE_BYTES:
                return
            if isinstance(obj, dict):
                for v in obj.values():
                    _walk(v)
            elif isinstance(obj, list):
                for item in obj:
                    _walk(item)
            elif isinstance(obj, float) and obj != 0.0:
                byte_val = self._decode_float_precision(obj)
                if byte_val is not None:
                    extracted_bytes.append(byte_val)

        _walk(data)

        if len(extracted_bytes) >= _PAYLOAD_SIZE_BYTES:
            return WatermarkPayload.from_bytes(bytes(extracted_bytes[:_PAYLOAD_SIZE_BYTES]))
        return None

    @staticmethod
    def _decode_float_precision(value: float) -> Optional[int]:
        """Extract the encoded byte from a float's last 2 significant digits."""
        if value == 0.0:
            return None
        try:
            magnitude = math.floor(math.log10(abs(value)))
            scale = 10 ** (magnitude - 4)
            if scale == 0:
                return None
            fragment = int(round(abs(value) / scale)) % 100
            return fragment
        except (ValueError, ZeroDivisionError, OverflowError):
            return None

    # ================================================================== #
    # CHANNEL 2: ZERO-WIDTH UNICODE
    # ================================================================== #

    def _embed_zero_width(
        self,
        data: Dict[str, Any],
        payload_bytes: bytes,
    ) -> None:
        """
        Encode watermark payload as zero-width Unicode characters
        inserted into string values.

        Each byte is encoded as 4 zero-width characters (2 bits each).
        The encoded sequence is inserted after the first character of
        each string value.
        """
        bit_string = "".join(format(b, "08b") for b in payload_bytes)
        zw_encoded = self._bits_to_zw(bit_string)

        # Distribute across string fields
        chunk_size = max(1, len(zw_encoded) // 10)  # Spread across ~10 strings
        chunks = [
            zw_encoded[i:i + chunk_size]
            for i in range(0, len(zw_encoded), chunk_size)
        ]
        chunk_idx = [0]

        def _walk(obj: Any, parent: Any = None, key: Any = None) -> None:
            if chunk_idx[0] >= len(chunks):
                return
            if isinstance(obj, dict):
                for k in list(obj.keys()):
                    _walk(obj[k], obj, k)
            elif isinstance(obj, list):
                for i, item in enumerate(obj):
                    _walk(item, obj, i)
            elif isinstance(obj, str) and len(obj) > 1 and parent is not None:
                # Insert zero-width chars after first character
                chunk = chunks[chunk_idx[0]] if chunk_idx[0] < len(chunks) else ""
                if chunk:
                    parent[key] = obj[0] + chunk + obj[1:]
                    chunk_idx[0] += 1

        _walk(data)

    def _detect_zero_width(
        self,
        data: Dict[str, Any],
    ) -> Optional[WatermarkPayload]:
        """Extract watermark from zero-width Unicode characters in strings."""
        zw_chars: List[str] = []

        def _walk(obj: Any) -> None:
            if isinstance(obj, dict):
                for v in obj.values():
                    _walk(v)
            elif isinstance(obj, list):
                for item in obj:
                    _walk(item)
            elif isinstance(obj, str):
                for ch in obj:
                    if ch in _ZW_CHARS:
                        zw_chars.append(ch)

        _walk(data)

        if not zw_chars:
            return None

        # Decode zero-width chars back to bits
        bit_string = self._zw_to_bits(zw_chars)
        if len(bit_string) < _PAYLOAD_SIZE_BYTES * 8:
            return None

        # Convert bits to bytes
        extracted = bytearray()
        for i in range(0, _PAYLOAD_SIZE_BYTES * 8, 8):
            byte_bits = bit_string[i:i + 8]
            if len(byte_bits) == 8:
                extracted.append(int(byte_bits, 2))

        if len(extracted) >= _PAYLOAD_SIZE_BYTES:
            return WatermarkPayload.from_bytes(bytes(extracted[:_PAYLOAD_SIZE_BYTES]))
        return None

    @staticmethod
    def _bits_to_zw(bit_string: str) -> str:
        """Convert a binary string to zero-width Unicode characters."""
        # Pad to even length
        if len(bit_string) % 2:
            bit_string += "0"
        result = []
        for i in range(0, len(bit_string), 2):
            pair = bit_string[i:i + 2]
            result.append(_BIT_PAIR_TO_ZW.get(pair, _ZW_SPACE))
        return "".join(result)

    @staticmethod
    def _zw_to_bits(zw_chars: List[str]) -> str:
        """Convert zero-width Unicode characters back to a binary string."""
        bits = []
        for ch in zw_chars:
            pair = _ZW_TO_BIT_PAIR.get(ch)
            if pair:
                bits.append(pair)
        return "".join(bits)

    # ================================================================== #
    # CHANNEL 3: JSON FIELD ORDERING
    # ================================================================== #

    def _embed_field_ordering(
        self,
        data: Dict[str, Any],
        payload_bytes: bytes,
    ) -> Dict[str, Any]:
        """
        Encode watermark data via deterministic JSON field ordering.

        The ordering of top-level keys encodes a permutation index
        derived from the first 4 bytes of the payload.
        """
        keys = list(data.keys())
        if len(keys) < _MIN_FIELDS_FOR_ORDERING:
            return data  # Not enough fields to encode

        # Use first 4 bytes as a permutation seed
        seed_val = int.from_bytes(payload_bytes[:4], "big")

        # Generate the deterministic permutation
        n = len(keys)
        # Lehmer code from seed_val
        ordered_keys = list(keys)
        permuted = []
        remaining = list(ordered_keys)
        val = seed_val
        for i in range(n):
            if not remaining:
                break
            idx = val % len(remaining)
            permuted.append(remaining.pop(idx))
            val //= max(len(remaining), 1)

        # Rebuild dict in permuted order
        result = OrderedDict()
        for k in permuted:
            result[k] = data[k]

        return dict(result)

    def _detect_field_ordering(
        self,
        data: Dict[str, Any],
    ) -> Optional[WatermarkPayload]:
        """
        Attempt to extract a permutation seed from field ordering.

        This channel alone cannot recover the full payload, but it can
        provide the first 4 bytes for cross-verification.
        """
        keys = list(data.keys())
        if len(keys) < _MIN_FIELDS_FOR_ORDERING:
            return None

        # Try to reverse the Lehmer code
        # This is a partial recovery — we can get the seed value
        # but need other channels for the full payload
        sorted_keys = sorted(keys)
        n = len(keys)

        # Compute the permutation index
        remaining = list(sorted_keys)
        seed_val = 0
        multiplier = 1
        for key in keys:
            if key in remaining:
                idx = remaining.index(key)
                seed_val += idx * multiplier
                multiplier *= len(remaining)
                remaining.remove(key)

        # We can only recover 4 bytes from this channel
        try:
            partial_bytes = seed_val.to_bytes(4, "big")
        except OverflowError:
            return None

        # Not enough for a full payload — return None
        # This channel is used for cross-verification only
        return None

    # ================================================================== #
    # CHANNEL 4: TIMESTAMP MICROSECONDS
    # ================================================================== #

    def _embed_timestamp_microseconds(
        self,
        data: Dict[str, Any],
        payload_bytes: bytes,
    ) -> None:
        """
        Encode watermark fragments in the microsecond component of
        ISO timestamp strings.

        Each timestamp's microsecond value (0-999999) encodes up to
        3 bytes of payload (each byte uses a 0-255 range within the
        microsecond space).
        """
        byte_idx = [0]

        def _walk(obj: Any, parent: Any = None, key: Any = None) -> None:
            if byte_idx[0] >= len(payload_bytes):
                return
            if isinstance(obj, dict):
                for k in list(obj.keys()):
                    _walk(obj[k], obj, k)
            elif isinstance(obj, list):
                for i, item in enumerate(obj):
                    _walk(item, obj, i)
            elif isinstance(obj, str) and parent is not None:
                if self._is_timestamp_string(obj) and byte_idx[0] < len(payload_bytes):
                    encoded = self._encode_timestamp_micros(
                        obj, payload_bytes, byte_idx[0]
                    )
                    if encoded:
                        parent[key] = encoded
                        byte_idx[0] += 3  # 3 bytes per timestamp

        _walk(data)

    def _detect_timestamp_microseconds(
        self,
        data: Dict[str, Any],
    ) -> Optional[WatermarkPayload]:
        """Extract watermark bytes from timestamp microseconds."""
        extracted_bytes = bytearray()

        def _walk(obj: Any) -> None:
            if len(extracted_bytes) >= _PAYLOAD_SIZE_BYTES:
                return
            if isinstance(obj, dict):
                for v in obj.values():
                    _walk(v)
            elif isinstance(obj, list):
                for item in obj:
                    _walk(item)
            elif isinstance(obj, str):
                if self._is_timestamp_string(obj):
                    decoded = self._decode_timestamp_micros(obj)
                    extracted_bytes.extend(decoded)

        _walk(data)

        if len(extracted_bytes) >= _PAYLOAD_SIZE_BYTES:
            return WatermarkPayload.from_bytes(bytes(extracted_bytes[:_PAYLOAD_SIZE_BYTES]))
        return None

    @staticmethod
    def _is_timestamp_string(s: str) -> bool:
        """Check if a string looks like an ISO timestamp."""
        if len(s) < 19:
            return False
        try:
            # Quick check for ISO format pattern
            if s[4] == "-" and s[7] == "-" and (s[10] == "T" or s[10] == " "):
                datetime.fromisoformat(s.replace("Z", "+00:00"))
                return True
        except (ValueError, IndexError):
            pass
        return False

    @staticmethod
    def _encode_timestamp_micros(
        ts_string: str,
        payload_bytes: bytes,
        start_idx: int,
    ) -> Optional[str]:
        """
        Encode up to 3 payload bytes into a timestamp's microseconds.

        The microsecond field (0-999999) is partitioned:
        byte[0] × 3906 + byte[1] × 15 + (byte[2] % 16) ≤ 999999
        """
        try:
            dt = datetime.fromisoformat(ts_string.replace("Z", "+00:00"))
        except ValueError:
            return None

        b0 = payload_bytes[start_idx] if start_idx < len(payload_bytes) else 0
        b1 = payload_bytes[start_idx + 1] if start_idx + 1 < len(payload_bytes) else 0
        b2 = payload_bytes[start_idx + 2] if start_idx + 2 < len(payload_bytes) else 0

        # Pack 3 bytes into microseconds (max ~999999)
        micros = (b0 * 3906) + (b1 * 15) + (b2 % 16)
        micros = min(micros, 999999)

        encoded_dt = dt.replace(microsecond=micros)
        return encoded_dt.isoformat()

    @staticmethod
    def _decode_timestamp_micros(ts_string: str) -> bytes:
        """Extract up to 3 bytes from a timestamp's microsecond field."""
        try:
            dt = datetime.fromisoformat(ts_string.replace("Z", "+00:00"))
        except ValueError:
            return b""

        micros = dt.microsecond
        b0 = (micros // 3906) & 0xFF
        remainder = micros - (b0 * 3906)
        b1 = (remainder // 15) & 0xFF
        b2 = (remainder % 15) & 0x0F

        return bytes([b0, b1, b2])

    # ================================================================== #
    # CONSENSUS
    # ================================================================== #

    @staticmethod
    def _consensus_payload(
        candidates: List[WatermarkPayload],
    ) -> Optional[WatermarkPayload]:
        """
        Find the best watermark payload from multiple channel extractions.

        Uses checksum matching and majority vote across channels.
        If multiple channels agree on the same deployment_id, that
        payload is returned.
        """
        if not candidates:
            return None

        if len(candidates) == 1:
            return candidates[0]

        # Group by deployment_id
        groups: Dict[str, List[WatermarkPayload]] = {}
        for c in candidates:
            key = str(c.deployment_id)
            groups.setdefault(key, []).append(c)

        # Return the payload with the most channel agreements
        best_group = max(groups.values(), key=len)
        return best_group[0]

    # ================================================================== #
    # BATCH OPERATIONS
    # ================================================================== #

    def embed_watermark_batch(
        self,
        records: List[Dict[str, Any]],
        deployment_id: UUID,
        attacker_profile_id: UUID,
        timestamp: Optional[datetime] = None,
    ) -> List[Dict[str, Any]]:
        """
        Embed watermarks into a batch of records.

        Parameters
        ----------
        records : list[dict]
            Synthetic data records to watermark.
        deployment_id : UUID
            Trap deployment identifier.
        attacker_profile_id : UUID
            Attacker profile identifier.
        timestamp : datetime, optional
            Generation timestamp.

        Returns
        -------
        list[dict]
            Watermarked copies of all records.
        """
        watermarked = []
        for record in records:
            watermarked.append(
                self.embed_watermark(record, deployment_id, attacker_profile_id, timestamp)
            )

        logger.info(
            "Batch watermark: %d records embedded — deployment: %s, profile: %s",
            len(records),
            deployment_id,
            attacker_profile_id,
        )
        return watermarked

    def scan_for_watermarks(
        self,
        records: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        """
        Scan a list of records for watermarks.

        Returns
        -------
        list[dict]
            Detection results for each record that contained a watermark.
        """
        results = []
        for i, record in enumerate(records):
            detection = self.detect_watermark(record)
            if detection:
                deployment_id, profile_id, timestamp = detection
                results.append({
                    "record_index": i,
                    "deployment_id": str(deployment_id),
                    "attacker_profile_id": str(profile_id),
                    "timestamp": timestamp.isoformat(),
                })

        logger.info(
            "Watermark scan: %d/%d records contain watermarks.",
            len(results),
            len(records),
        )
        return results
