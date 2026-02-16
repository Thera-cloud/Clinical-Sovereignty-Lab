"""
ZEFCP Fragment Buffer — Thread-Safe Accumulation and Reassembly.
Patent Claim 25.1d: Zero-Energy BLE Communication — Fragment buffer provides
thread-safe accumulation of micro-fragments, Reed-Solomon reconstruction when
sufficient fragments received, decryption, and deserialization to FibreObservation.
"""

from __future__ import annotations

import asyncio
import base64
import json
import time
from datetime import datetime
from typing import Any, Dict, Optional
from uuid import UUID, uuid4

import structlog

from app.models.zefcp import (
    FibreObservation,
    FragmentMode,
    MicroFragment,
    ObservationAssembly,
)
from app.services.zefcp.constants import (
    DEFAULT_REDUNDANCY_FACTOR,
    EXTENDED_PAYLOAD_SIZE,
    RECONSTRUCTION_THRESHOLD,
    STANDARD_PAYLOAD_SIZE,
)
from app.services.zefcp.crypto import FibreFragmentCrypto
from app.services.zefcp.reed_solomon import ReedSolomonFragmentEncoder

logger = structlog.get_logger(__name__)


def _decode_bytes(val: Any) -> Optional[bytes]:
    """Decode base64 string to bytes; return None for None."""
    if val is None:
        return None
    if isinstance(val, str):
        return base64.b64decode(val)
    if isinstance(val, bytes):
        return val
    return None


# =============================================================================
# FRAGMENT BUFFER
# =============================================================================


class FragmentBuffer:
    """
    Thread-safe fragment accumulation and reassembly.
    Patent Claim 25.1d: Pending observations, eviction when at max,
    Reed-Solomon decode, decrypt, deserialize to FibreObservation.
    """

    def __init__(
        self,
        swarm_secret: bytes,
        max_pending: int = 256,
        timeout_seconds: int = 3600,
        redundancy_threshold: float = 0.7,
    ) -> None:
        """
        Initialize fragment buffer.

        Args:
            swarm_secret: Shared secret for decryption (NFC-provisioned).
            max_pending: Maximum pending observation assemblies.
            timeout_seconds: Eviction age for stale assemblies.
            redundancy_threshold: Minimum received/total ratio for reconstruction.
        """
        self._swarm_secret = swarm_secret
        self._max_pending = max_pending
        self._timeout_seconds = timeout_seconds
        self._redundancy_threshold = redundancy_threshold
        self.pending: Dict[str, ObservationAssembly] = {}
        self._lock = asyncio.Lock()
        self._crypto = FibreFragmentCrypto(swarm_secret)
        self._rs_decoder = ReedSolomonFragmentEncoder(
            redundancy_factor=DEFAULT_REDUNDANCY_FACTOR
        )

    # -------------------------------------------------------------------------
    # Ingest
    # -------------------------------------------------------------------------

    async def ingest(self, fragment: MicroFragment) -> Optional[FibreObservation]:
        """
        Ingest a micro-fragment and attempt reconstruction if possible.
        Patent Claim 25.1d: Acquire lock, get/create assembly, skip duplicates,
        check can_reconstruct, then Reed-Solomon decode, decrypt, deserialize.
        """
        async with self._lock:
            key = self._compute_observation_key(fragment)
            slot = self.pending.get(key)

            if slot is None:
                if len(self.pending) >= self._max_pending:
                    self._evict_oldest()
                now = time.time()
                slot = ObservationAssembly(
                    observation_key=key,
                    total_fragments=fragment.total,
                    received_sequences=[],
                    fragments={},
                    created_at=now,
                    last_fragment_at=now,
                    is_trail=bool(fragment.flags and (fragment.flags & 0x80)),
                )
                self.pending[key] = slot

            if fragment.sequence in slot.received_sequences:
                return None

            slot.received_sequences.append(fragment.sequence)
            slot.fragments[fragment.sequence] = fragment
            slot.last_fragment_at = time.time()

            if not self._can_reconstruct(slot):
                return None

            try:
                observation = self._reconstruct(slot)
                del self.pending[key]
                return observation
            except Exception as e:
                logger.warning("reconstruction_failed", key=key, error=str(e))
                del self.pending[key]
                return None

    def _can_reconstruct(self, assembly: ObservationAssembly) -> bool:
        """
        True if received/total >= redundancy_threshold or exactly 1.0.
        """
        total = assembly.total_fragments
        received = len(assembly.received_sequences)
        ratio = received / total if total > 0 else 0.0
        return ratio >= self._redundancy_threshold or ratio == 1.0

    def _compute_observation_key(self, fragment: MicroFragment) -> str:
        """
        Compute key for assembly slot from observation_id (extended) or frag_id (standard).
        """
        if fragment.observation_id is not None:
            return f"obs-{fragment.observation_id}-{fragment.total}"
        frag_id = fragment.frag_id or 0
        return f"frag-{frag_id}-{fragment.total}"

    def _reconstruct(self, assembly: ObservationAssembly) -> FibreObservation:
        """
        Reed-Solomon decode, decrypt, deserialize to FibreObservation.
        """
        payload_size = EXTENDED_PAYLOAD_SIZE
        first = next(
            (assembly.fragments[s] for s in sorted(assembly.fragments) if s in assembly.fragments),
            None,
        )
        if first is None:
            raise ValueError("Assembly has no fragments")
        if first.mode == FragmentMode.STANDARD:
            payload_size = STANDARD_PAYLOAD_SIZE

        fragments_payloads: Dict[int, bytes] = {
            seq: assembly.fragments[seq].payload
            for seq in assembly.fragments
        }

        ciphertext = self._rs_decoder.decode(
            fragments_payloads,
            assembly.total_fragments,
            payload_size,
        )

        obs_id_bytes = self._observation_id_bytes(assembly, first)
        plaintext = self._crypto.decrypt_payload(ciphertext, obs_id_bytes)

        data = json.loads(plaintext.decode("utf-8"))
        obs_id = data.get("observation_id")
        if isinstance(obs_id, str):
            obs_id = UUID(obs_id)
        ts = data.get("timestamp")
        if isinstance(ts, (int, float)):
            ts = datetime.utcfromtimestamp(ts)
        elif isinstance(ts, str):
            ts = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        else:
            ts = datetime.utcnow()
        observation = FibreObservation(
            observation_id=obs_id or uuid4(),
            fibre_id=data.get("fibre_id") or "unknown",
            fibre_type=data.get("fibre_type") or "unknown",
            timestamp=ts,
            coherence_data=_decode_bytes(data.get("coherence_data")),
            cultural_signal=_decode_bytes(data.get("cultural_signal")),
            foresight_signal=_decode_bytes(data.get("foresight_signal")),
            confidence=float(data.get("confidence", 0.5)),
            priority=int(data.get("priority", 1)),
            ed25519_signature=_decode_bytes(data.get("ed25519_signature")),
            assembly_total_fragments=assembly.total_fragments,
            assembly_local_count=len(assembly.received_sequences),
            assembly_remote_count=None,
            assembly_duration_seconds=time.time() - assembly.created_at,
            assembly_endpoint_id=None,
        )
        return observation

    def _observation_id_bytes(self, assembly: ObservationAssembly, first: MicroFragment) -> bytes:
        """Derive observation ID bytes for key derivation."""
        if first.observation_id is not None:
            return bytes([first.observation_id])
        fid = first.frag_id or 0
        return fid.to_bytes(2, "big")

    def _evict_oldest(self) -> None:
        """Remove oldest assembly by last_fragment_at."""
        if not self.pending:
            return
        oldest_key = min(
            self.pending.keys(),
            key=lambda k: self.pending[k].last_fragment_at,
        )
        del self.pending[oldest_key]
        logger.debug("evicted_oldest_assembly", key=oldest_key)

    # -------------------------------------------------------------------------
    # Purge Expired
    # -------------------------------------------------------------------------

    async def purge_expired(self) -> int:
        """
        Remove stale assemblies older than timeout_seconds.
        Returns count purged.
        """
        async with self._lock:
            now = time.time()
            to_remove = [
                k for k, a in self.pending.items()
                if now - a.last_fragment_at > self._timeout_seconds
            ]
            for k in to_remove:
                del self.pending[k]
            if to_remove:
                logger.info("purged_expired_assemblies", count=len(to_remove), keys=to_remove)
            return len(to_remove)

    # -------------------------------------------------------------------------
    # Properties
    # -------------------------------------------------------------------------

    @property
    def pending_count(self) -> int:
        """Number of pending observation assemblies."""
        return len(self.pending)
