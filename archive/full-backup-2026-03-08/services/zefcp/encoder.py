"""
ZEFCP Observation Encoder — Patent Claim 25
Zero-Energy BLE Communication: Full pipeline from FibreObservation to
MicroFragments for parasitic BLE transport.

Patent Claim 25: Serialize → Encrypt → Reed-Solomon encode → MicroFragment
with redundancy, rotation signature, and CRC-8 integrity.
"""

from __future__ import annotations

import math
from typing import List

from app.models.zefcp import FibreObservation, MicroFragment
from app.services.zefcp.constants import (
    DEFAULT_REDUNDANCY_FACTOR,
    EXTENDED_PAYLOAD_SIZE,
    MAX_FRAGMENTS_PER_OBSERVATION,
    STANDARD_PAYLOAD_SIZE,
)
from app.services.zefcp.crypto import FibreFragmentCrypto
from app.services.zefcp.fragment import FragmentEncoder
from app.services.zefcp.observation import ObservationSerializer
from app.services.zefcp.reed_solomon import ReedSolomonFragmentEncoder


# =============================================================================
# FRAGMENTATION ERROR
# =============================================================================


class FragmentationError(ValueError):
    """Raised when an observation is too large to fragment within BLE constraints."""


# =============================================================================
# OBSERVATION ENCODER
# =============================================================================


class ObservationEncoder:
    """
    Full pipeline from FibreObservation to MicroFragments.
    Patent Claim 25: Serialize, encrypt, Reed-Solomon encode, create fragments.
    """

    def __init__(
        self,
        swarm_secret: bytes,
        mode: str = "extended",
        redundancy: float = DEFAULT_REDUNDANCY_FACTOR,
    ) -> None:
        """
        Initialize the encoding pipeline.

        Args:
            swarm_secret: Shared swarm secret for encryption and signature.
            mode: 'standard' (2B payload) or 'extended' (5B payload).
            redundancy: Reed-Solomon redundancy factor (e.g. 0.3).
        """
        payload_size = EXTENDED_PAYLOAD_SIZE if mode == "extended" else STANDARD_PAYLOAD_SIZE
        self._serializer = ObservationSerializer()
        self._crypto = FibreFragmentCrypto(swarm_secret)
        self._reed_solomon = ReedSolomonFragmentEncoder(redundancy_factor=redundancy)
        self._fragment_encoder = FragmentEncoder(swarm_secret=swarm_secret, mode=mode)
        self._mode = mode
        self._payload_size = payload_size

    def encode_observation(self, observation: FibreObservation) -> List[MicroFragment]:
        """
        Encode a FibreObservation into a list of MicroFragments.
        Patent Claim 25: Serialize → Encrypt → RS encode → Fragment.

        Args:
            observation: The FibreObservation to encode.

        Returns:
            List of MicroFragment instances.

        Raises:
            FragmentationError: If observation exceeds MAX_FRAGMENTS_PER_OBSERVATION.
        """
        # Step 1: Serialize
        serialized = self._serializer.serialize(observation)

        # Step 2: Encrypt
        obs_id_bytes = observation.observation_id.bytes
        encrypted = self._crypto.encrypt_payload(serialized, obs_id_bytes)

        # Step 3: Reed-Solomon encode
        try:
            payloads = self._reed_solomon.encode(encrypted, self._payload_size)
        except ValueError as e:
            raise FragmentationError(str(e)) from e

        total = len(payloads)
        if total > MAX_FRAGMENTS_PER_OBSERVATION:
            raise FragmentationError(
                f"Fragment count {total} exceeds MAX_FRAGMENTS_PER_OBSERVATION ({MAX_FRAGMENTS_PER_OBSERVATION})"
            )

        # Step 4: Create MicroFragment for each payload
        obs_id_int = int.from_bytes(obs_id_bytes[:2], "big") if len(obs_id_bytes) >= 2 else 0
        fragments: List[MicroFragment] = []
        for seq, payload in enumerate(payloads):
            mf = self._fragment_encoder.encode_fragment(
                observation_id=obs_id_int,
                sequence=seq,
                total=total,
                payload=payload,
                flags=0,
            )
            fragments.append(mf)

        return fragments

    def get_fragment_count(self, observation: FibreObservation) -> int:
        """
        Estimate fragment count without full encoding.
        Patent Claim 25: Uses serialized size and redundancy to approximate.
        """
        serialized = self._serializer.serialize(observation)
        encrypted = self._crypto.encrypt_payload(
            serialized,
            observation.observation_id.bytes,
        )
        data_len = len(encrypted)
        pad_len = (self._payload_size - (data_len % self._payload_size)) % self._payload_size
        padded_len = data_len + pad_len
        data_fragments = padded_len // self._payload_size
        parity_fragments = math.ceil(data_fragments * self._reed_solomon.redundancy)
        return data_fragments + parity_fragments
