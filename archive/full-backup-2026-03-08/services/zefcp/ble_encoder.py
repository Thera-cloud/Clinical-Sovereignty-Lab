"""
ZEFCP BLE Encoder — PDU overhead byte modulation.
Patent Claim 25.2: Zero-Energy BLE Communication — Parasitic encoding by
modulating the overhead bytes of BLE advertising PDUs without altering
functional bytes required for carrier device operation.
"""

from __future__ import annotations

from typing import Any, Dict, List, Tuple

from app.models.zefcp import ADStructure, MicroFragment
from app.services.zefcp.constants import (
    EXPLOITABLE_AD_TYPES,
    EXTENDED_LEADING_BYTES,
    EXTENDED_TRAILING_BYTES,
    MINIMUM_FUNCTIONAL_BYTES,
    STANDARD_LEADING_BYTES,
    STANDARD_TRAILING_BYTES,
)
from app.services.zefcp.fragment import FragmentEncoder


# =============================================================================
# BLE ADVERTISING MODULATOR
# =============================================================================


class BLEAdvertisingModulator:
    """
    Modulates BLE advertising PDU overhead bytes to embed micro-fragments.
    Patent Claim 25.2: Identifies exploitable AD structure positions,
    writes serialized fragment bytes into leading and trailing windows,
    preserves all functional bytes required for carrier BLE operation.
    """

    def __init__(self, swarm_secret: bytes, mode: str = "extended") -> None:
        """
        Initialize modulator with swarm secret for fragment encoding.

        Args:
            swarm_secret: Shared secret for signature rotation (NFC-provisioned).
            mode: "standard" (8-byte) or "extended" (12-byte) fragment encoding.
        """
        self._swarm_secret = swarm_secret
        self._mode = mode.lower()
        self._encoder = FragmentEncoder(swarm_secret, mode=mode)

    def embed_fragment(
        self,
        pdu_data: Dict[str, Any],
        fragment: MicroFragment,
    ) -> Dict[str, Any]:
        """
        Embed a serialized fragment into the PDU's exploitable overhead positions.

        Identifies leading and trailing windows in AD structures, writes
        fragment bytes into those positions while preserving functional bytes.
        Patent Claim 25.2.

        Args:
            pdu_data: PDU representation with "ad_structures" list; each
                structure has length, ad_type, data (bytes).
            fragment: MicroFragment to serialize and embed.

        Returns:
            Modified pdu_data dict with fragment bytes written into
            exploitable positions; functional bytes unchanged.
        """
        ad_structures: List[Any] = pdu_data.get("ad_structures", [])
        leading_len, trailing_len = self._find_embedding_positions(ad_structures)
        total_needed = leading_len + trailing_len

        serialized = self._encoder.serialize_fragment(fragment)
        if len(serialized) > total_needed:
            raise ValueError(
                f"Fragment requires {len(serialized)} bytes but only "
                f"{total_needed} embedding positions available"
            )

        # Split fragment: leading bytes go to leading window, rest to trailing
        split = min(leading_len, len(serialized))
        leading_bytes = serialized[:split]
        trailing_bytes = serialized[split:]

        # Copy structures to avoid mutating input
        modified_structures = []
        leading_written = 0
        trailing_to_write = list(trailing_bytes)
        trailing_written = 0

        for struct in ad_structures:
            if isinstance(struct, dict):
                ad_type = struct.get("ad_type", 0)
                data = bytearray(struct.get("data", b""))
                length = struct.get("length", len(data))
            else:
                ad_type = struct.ad_type
                data = bytearray(struct.data)
                length = struct.length

            min_func = MINIMUM_FUNCTIONAL_BYTES.get(ad_type, 0)
            if ad_type not in EXPLOITABLE_AD_TYPES or len(data) <= min_func:
                modified_structures.append(
                    {"length": length, "ad_type": ad_type, "data": bytes(data)}
                    if isinstance(struct, dict)
                    else ADStructure(length=length, ad_type=ad_type, data=bytes(data))
                )
                continue

            exploitable_start = min_func
            exploitable_end = len(data)
            exploitable_len = exploitable_end - exploitable_start

            # Write leading fragment bytes into start of exploitable region
            for i in range(min(exploitable_len, len(leading_bytes) - leading_written)):
                data[exploitable_start + i] = leading_bytes[leading_written + i]
                leading_written += 1

            # Write trailing fragment bytes into end of exploitable region
            trail_needed = len(trailing_to_write) - trailing_written
            if trail_needed > 0 and exploitable_len >= trail_needed:
                for i in range(trail_needed):
                    data[exploitable_end - 1 - (trail_needed - 1 - i)] = (
                        trailing_to_write[trailing_written + i]
                    )
                trailing_written += trail_needed

            modified_structures.append(
                {"length": length, "ad_type": ad_type, "data": bytes(data)}
                if isinstance(struct, dict)
                else ADStructure(length=length, ad_type=ad_type, data=bytes(data))
            )

        result = dict(pdu_data)
        result["ad_structures"] = modified_structures
        return result

    def _find_embedding_positions(self, ad_structures: List[Any]) -> Tuple[int, int]:
        """
        Find leading and trailing window byte counts across exploitable AD structures.

        Leading window: bytes at the start of the first exploitable region.
        Trailing window: bytes at the end of the last exploitable region.
        Patent Claim 25.2.

        Args:
            ad_structures: List of AD structures (dict or ADStructure).

        Returns:
            (leading_byte_count, trailing_byte_count) available for embedding.
        """
        if self._mode == "extended":
            target_leading = EXTENDED_LEADING_BYTES
            target_trailing = EXTENDED_TRAILING_BYTES
        else:
            target_leading = STANDARD_LEADING_BYTES
            target_trailing = STANDARD_TRAILING_BYTES

        total_leading = 0
        total_trailing = 0

        for struct in ad_structures:
            if isinstance(struct, dict):
                ad_type = struct.get("ad_type", 0)
                data = struct.get("data", b"")
            else:
                ad_type = struct.ad_type
                data = struct.data

            if ad_type not in EXPLOITABLE_AD_TYPES:
                continue

            min_func = MINIMUM_FUNCTIONAL_BYTES.get(ad_type, 0)
            exploitable_len = len(data) - min_func
            if exploitable_len <= 0:
                continue

            half = exploitable_len // 2
            leading_avail = min(half, target_leading - total_leading)
            trailing_avail = min(exploitable_len - half, target_trailing - total_trailing)

            total_leading += leading_avail
            total_trailing += trailing_avail

            if total_leading >= target_leading and total_trailing >= target_trailing:
                break

        return (total_leading, total_trailing)
