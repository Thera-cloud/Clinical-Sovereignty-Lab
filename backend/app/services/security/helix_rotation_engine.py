"""
HIVE DEFENSE PROTOCOL v3.1 — Helix Rotation Engine (Phase 8D)
Entropy gathering and Fisher-Yates permutation generator for the
Trinity Helix's continuously rotating sub-cord sequence.

The engine combines three independent entropy sources:
    1. **Coherence state hash** — SHA-256 of the current C_emo output
       from the Nevedal engine, tying rotation to the live emotional
       coherence state of the system.
    2. **HSM random** — 32 bytes from ``os.urandom``, providing
       cryptographically secure hardware randomness.
    3. **Nanosecond time** — ``time.monotonic_ns()`` encoded as 8 big-
       endian bytes, ensuring each rotation is temporally unique.

These three are concatenated and hashed with SHA-256 to produce a
single 32-byte digest.  From this digest:
    • Bytes 0-23 seed a Fisher-Yates shuffle of indices 0-8.
    • Bytes 24-27 derive the next rotation interval (50-500ms).

Patent-Pending — Claim 52
    Claim 52: "A rotation engine that combines coherence state hash,
               hardware random bytes, and nanosecond time into a single
               SHA-256 digest for deriving both the permutation and the
               rotation interval of a verification gate sequence."

© 2026 Clinical Sovereignty Lab. All rights reserved.
"""

from __future__ import annotations

import hashlib
import logging
import os
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional

logger = logging.getLogger("hive.helix_rotation_engine")


# =============================================================================
# CONSTANTS
# =============================================================================

NUM_SUB_CORDS: int = 9
MIN_INTERVAL_MS: float = 50.0
MAX_INTERVAL_MS: float = 500.0
ENTROPY_BYTES_COHERENCE: int = 32
ENTROPY_BYTES_HSM: int = 32
ENTROPY_BYTES_TIME: int = 8


# =============================================================================
# ROTATION RECORD
# =============================================================================

@dataclass
class RotationRecord:
    """
    Audit record for a single rotation event.

    Stored in the rotation history ring buffer for forensic inspection
    and entropy-health diagnostics.
    """
    rotation_number: int
    timestamp: datetime = field(default_factory=datetime.utcnow)
    new_sequence: List[int] = field(default_factory=list)
    new_interval_ms: float = 200.0
    entropy_hash_prefix: str = ""  # First 16 hex chars (for audit, not replay)
    coherence_hash_available: bool = True
    hsm_healthy: bool = True


# =============================================================================
# HELIX ROTATION ENGINE
# =============================================================================

class HelixRotationEngine:
    """
    Entropy-driven rotation engine for the Trinity Helix.

    Responsible for gathering entropy, producing Fisher-Yates
    permutations, deriving rotation intervals, and maintaining an
    audit trail of rotation events.

    Parameters
    ----------
    coherence_engine : object, optional
        Service that provides the current coherence state hash via
        ``get_state_hash() -> str``.  If *None*, a zero-fill hash is
        used (reduces entropy quality but permits standalone operation).
    history_size : int
        Maximum number of ``RotationRecord`` entries to retain in
        the ring buffer.

    Usage
    -----
    ::

        engine = HelixRotationEngine(coherence_engine=nevedal)
        result = await engine.rotate()
        # result = {
        #     "new_sequence": [3, 7, 0, ...],
        #     "new_interval_ms": 142.0,
        #     "entropy_healthy": True,
        # }

    Patent Ref: Claim 52.
    """

    def __init__(
        self,
        coherence_engine=None,
        history_size: int = 1000,
    ) -> None:
        self._coherence_engine = coherence_engine
        self._history_max: int = history_size

        # State
        self._rotation_count: int = 0
        self._history: List[RotationRecord] = []
        self._last_entropy_hash: str = ""

        logger.info(
            ">>> [ROTATION_ENGINE] Initialized — history_size=%d",
            history_size,
        )

    # ─── Properties ──────────────────────────────────────────────────────

    @property
    def rotation_count(self) -> int:
        """Total number of rotations performed since initialization."""
        return self._rotation_count

    @property
    def history(self) -> List[RotationRecord]:
        """Read-only access to the rotation history ring buffer."""
        return list(self._history)

    @property
    def last_entropy_hash(self) -> str:
        """First 16 hex chars of the last entropy digest (audit only)."""
        return self._last_entropy_hash

    # ─── Core Rotation ───────────────────────────────────────────────────

    async def rotate(self) -> Dict[str, Any]:
        """
        Perform a single rotation: gather entropy, generate new
        permutation and interval.

        Returns
        -------
        dict
            ``new_sequence`` : list[int]  — new sub-cord permutation
            ``new_interval_ms`` : float   — next rotation interval
            ``entropy_healthy`` : bool    — all sources contributed
            ``rotation_number`` : int     — monotonic counter
        """
        # 1. Gather combined entropy
        combined, health = await self.gather_entropy()

        # 2. Hash to produce the 32-byte digest
        digest = hashlib.sha256(combined).digest()
        digest_hex = digest.hex()

        # 3. Generate permutation
        new_sequence = self.generate_permutation(digest)

        # 4. Derive interval
        new_interval_ms = self.derive_interval(digest)

        # 5. Record
        self._rotation_count += 1
        self._last_entropy_hash = digest_hex[:16]

        record = RotationRecord(
            rotation_number=self._rotation_count,
            new_sequence=list(new_sequence),
            new_interval_ms=new_interval_ms,
            entropy_hash_prefix=digest_hex[:16],
            coherence_hash_available=health["coherence_available"],
            hsm_healthy=health["hsm_healthy"],
        )
        self._history.append(record)
        if len(self._history) > self._history_max:
            self._history = self._history[-self._history_max:]

        logger.debug(
            ">>> [ROTATION_ENGINE] Rotation #%d — seq=%s interval=%.0fms "
            "entropy=%s",
            self._rotation_count,
            new_sequence,
            new_interval_ms,
            digest_hex[:16],
        )

        return {
            "new_sequence": new_sequence,
            "new_interval_ms": new_interval_ms,
            "entropy_healthy": (
                health["coherence_available"] and health["hsm_healthy"]
            ),
            "rotation_number": self._rotation_count,
        }

    # ─── Entropy Gathering ───────────────────────────────────────────────

    async def gather_entropy(self) -> tuple[bytes, Dict[str, bool]]:
        """
        Gather combined entropy from all three sources.

        Returns
        -------
        tuple[bytes, dict]
            Combined entropy bytes and a health dict indicating which
            sources contributed.
        """
        health: Dict[str, bool] = {
            "coherence_available": False,
            "hsm_healthy": True,
        }

        # Source 1: Coherence state hash
        coherence_bytes = b"\x00" * ENTROPY_BYTES_COHERENCE
        if self._coherence_engine:
            try:
                state_hash = await self._get_coherence_hash()
                if state_hash:
                    coherence_bytes = bytes.fromhex(state_hash[:64].ljust(64, "0"))
                    health["coherence_available"] = True
            except Exception as exc:
                logger.warning(
                    ">>> [ROTATION_ENGINE] Coherence hash unavailable: %s",
                    exc,
                )
        else:
            # No coherence engine — use urandom as substitute
            coherence_bytes = os.urandom(ENTROPY_BYTES_COHERENCE)
            health["coherence_available"] = False

        # Source 2: HSM random (os.urandom)
        try:
            hsm_bytes = os.urandom(ENTROPY_BYTES_HSM)
        except Exception as exc:
            logger.error(
                ">>> [ROTATION_ENGINE] os.urandom failed: %s — "
                "falling back to time-based entropy",
                exc,
            )
            hsm_bytes = time.monotonic_ns().to_bytes(32, "big")
            health["hsm_healthy"] = False

        # Source 3: Nanosecond time
        time_bytes = time.monotonic_ns().to_bytes(ENTROPY_BYTES_TIME, "big")

        combined = coherence_bytes + hsm_bytes + time_bytes
        return combined, health

    async def _get_coherence_hash(self) -> Optional[str]:
        """
        Retrieve the current coherence state hash from the engine.

        Supports both sync and async ``get_state_hash()`` methods.
        """
        if not self._coherence_engine:
            return None

        getter = getattr(self._coherence_engine, "get_state_hash", None)
        if getter is None:
            return None

        import asyncio
        if asyncio.iscoroutinefunction(getter):
            return await getter()
        return getter()

    # ─── Permutation Generation ──────────────────────────────────────────

    @staticmethod
    def generate_permutation(combined_entropy: bytes) -> List[int]:
        """
        Generate a permutation of 0-8 using Fisher-Yates shuffle with
        entropy-derived random bytes.

        The Fisher-Yates (Knuth) shuffle is unbiased when the random
        source is uniform.  We use successive bytes of the SHA-256
        digest to select swap indices.

        Parameters
        ----------
        combined_entropy : bytes
            At least 32 bytes; typically the SHA-256 digest of combined
            entropy sources.

        Returns
        -------
        list[int]
            A permutation of [0, 1, 2, ..., 8].
        """
        # Ensure we have a full 32-byte digest
        if len(combined_entropy) < 32:
            combined_entropy = hashlib.sha256(combined_entropy).digest()

        perm = list(range(NUM_SUB_CORDS))

        for i in range(NUM_SUB_CORDS - 1, 0, -1):
            # Use two bytes for better uniformity over small ranges
            byte_idx = (NUM_SUB_CORDS - 1 - i) * 2
            if byte_idx + 1 < len(combined_entropy):
                rand_val = (
                    combined_entropy[byte_idx] << 8
                    | combined_entropy[byte_idx + 1]
                )
            else:
                rand_val = combined_entropy[byte_idx % len(combined_entropy)]

            j = rand_val % (i + 1)
            perm[i], perm[j] = perm[j], perm[i]

        return perm

    # ─── Interval Derivation ─────────────────────────────────────────────

    @staticmethod
    def derive_interval(combined_entropy: bytes) -> float:
        """
        Derive the next rotation interval from entropy bytes 24-28.

        The interval is uniformly distributed across the range
        [MIN_INTERVAL_MS, MAX_INTERVAL_MS] (50-500ms).

        Parameters
        ----------
        combined_entropy : bytes
            At least 28 bytes (typically a 32-byte SHA-256 digest).

        Returns
        -------
        float
            Rotation interval in milliseconds.
        """
        if len(combined_entropy) < 28:
            combined_entropy = hashlib.sha256(combined_entropy).digest()

        raw = int.from_bytes(combined_entropy[24:28], "big")
        span = int(MAX_INTERVAL_MS - MIN_INTERVAL_MS) + 1
        interval = MIN_INTERVAL_MS + (raw % span)
        return float(interval)

    # ─── Diagnostics ─────────────────────────────────────────────────────

    def summary(self) -> Dict[str, Any]:
        """
        Return diagnostic summary for the admin dashboard.
        """
        recent = self._history[-10:] if self._history else []
        return {
            "rotation_count": self._rotation_count,
            "last_entropy_hash": self._last_entropy_hash,
            "history_size": len(self._history),
            "recent_rotations": [
                {
                    "number": r.rotation_number,
                    "timestamp": r.timestamp.isoformat(),
                    "interval_ms": r.new_interval_ms,
                    "coherence_available": r.coherence_hash_available,
                    "hsm_healthy": r.hsm_healthy,
                    "entropy_prefix": r.entropy_hash_prefix,
                }
                for r in recent
            ],
        }

    def __repr__(self) -> str:
        return (
            f"<HelixRotationEngine rotations={self._rotation_count} "
            f"history={len(self._history)} "
            f"last_entropy={self._last_entropy_hash}>"
        )
