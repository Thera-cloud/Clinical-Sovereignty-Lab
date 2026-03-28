"""
Cognitive Rotation Engine — Phase 12 of Sovereign Quantum Nate Build.

Drives the evaluation order of strands within each NoeticHelix by
gathering entropy from C_knowledge coherence state instead of
the defense layer's C_emo hash.

The rotation ensures the same question asked at different times —
with different knowledge states — produces different synthesis
because the strand permutation changes with Nate's evolving field.

Pattern adapted from security/helix_rotation_engine.py, which uses
C_emo state hash for the Trinity Helix defense layer. This engine
uses C_knowledge state hash for cognitive helices.

Patent-Pending — Claims 58-63
© 2026 Clinical Sovereignty Lab. All rights reserved.
"""

from __future__ import annotations

import hashlib
import logging
import os
import struct
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger("cognitive_rotation")

NUM_STRANDS = 7
MIN_INTERVAL_MS = 50.0
MAX_INTERVAL_MS = 500.0
HISTORY_SIZE = 500


@dataclass
class CognitiveRotationRecord:
    """Audit trail of a single cognitive rotation event."""
    rotation_number: int
    timestamp: datetime
    entropy_hash: str
    new_sequence: List[int]
    interval_ms: float
    knowledge_state_hash: str


class CognitiveRotationEngine:
    """
    Entropy-driven rotation engine for cognitive helices.

    Gathers entropy from three sources:
      1. C_knowledge state hash — SHA-256 of Nate's current knowledge
         coherence profile, tying rotation to the live cognitive state.
      2. System randomness — os.urandom(16) for cryptographic entropy.
      3. Nanosecond timing — time.time_ns() for temporal entropy.

    The combined entropy drives a Fisher-Yates shuffle to produce
    a strand evaluation permutation, and an interval derivation
    for adaptive rotation timing.
    """

    def __init__(
        self,
        knowledge_engine=None,
        history_size: int = HISTORY_SIZE,
    ) -> None:
        self._knowledge_engine = knowledge_engine
        self._history_max = history_size
        self._rotation_count = 0
        self._history: List[CognitiveRotationRecord] = []
        self._last_entropy_hash = ""
        self._last_sequence: List[int] = list(range(NUM_STRANDS))

        logger.info(
            ">>> [COG_ROTATION] Initialized — history_size=%d",
            history_size,
        )

    @property
    def rotation_count(self) -> int:
        return self._rotation_count

    @property
    def last_sequence(self) -> List[int]:
        return list(self._last_sequence)

    @property
    def last_entropy_hash(self) -> str:
        return self._last_entropy_hash

    # ─── Core Rotation ───────────────────────────────────────────

    async def rotate(self) -> Dict[str, Any]:
        """
        Perform a single rotation: gather entropy from C_knowledge state,
        generate a new strand permutation, and derive the next rotation interval.
        """
        combined, health = await self._gather_entropy()

        digest = hashlib.sha256(combined).digest()
        digest_hex = digest.hex()

        new_sequence = self._generate_permutation(digest)
        new_interval_ms = self._derive_interval(digest)

        self._rotation_count += 1
        self._last_entropy_hash = digest_hex[:16]
        self._last_sequence = new_sequence

        record = CognitiveRotationRecord(
            rotation_number=self._rotation_count,
            timestamp=datetime.now(timezone.utc),
            entropy_hash=digest_hex[:16],
            new_sequence=new_sequence,
            interval_ms=new_interval_ms,
            knowledge_state_hash=health.get("knowledge_hash", ""),
        )
        self._history.append(record)
        if len(self._history) > self._history_max:
            self._history = self._history[-self._history_max:]

        logger.debug(
            ">>> [COG_ROTATION] Rotation #%d — seq=%s interval=%.1fms",
            self._rotation_count, new_sequence, new_interval_ms,
        )

        return {
            "new_sequence": new_sequence,
            "new_interval_ms": new_interval_ms,
            "entropy_healthy": health.get("all_sources", False),
            "rotation_number": self._rotation_count,
        }

    # ─── Entropy Gathering ────────────────────────────────────────

    async def _gather_entropy(self) -> tuple:
        """
        Combine three entropy sources:
          1. C_knowledge state hash (cognitive field state)
          2. System random bytes
          3. Nanosecond timestamp
        """
        health: Dict[str, Any] = {
            "knowledge_hash": "",
            "system_random": True,
            "time_ns": True,
            "all_sources": True,
        }

        # Source 1: Knowledge coherence state
        knowledge_bytes = b"\x00" * 32
        if self._knowledge_engine:
            try:
                status = self._knowledge_engine.get_status()
                state_str = str(sorted(status.items()))
                knowledge_bytes = hashlib.sha256(state_str.encode()).digest()
                health["knowledge_hash"] = knowledge_bytes.hex()[:16]
            except Exception as e:
                logger.warning("COG_ROTATION: knowledge entropy failed: %s", e)
                health["all_sources"] = False
        else:
            health["all_sources"] = False

        # Source 2: System randomness
        try:
            system_bytes = os.urandom(16)
        except Exception:
            system_bytes = hashlib.sha256(str(time.time()).encode()).digest()[:16]
            health["system_random"] = False
            health["all_sources"] = False

        # Source 3: Nanosecond timestamp
        time_bytes = struct.pack(">Q", time.time_ns())

        combined = knowledge_bytes + system_bytes + time_bytes
        return combined, health

    # ─── Permutation ──────────────────────────────────────────────

    def _generate_permutation(self, digest: bytes) -> List[int]:
        """
        Fisher-Yates shuffle driven by entropy digest bytes.
        Produces a permutation of [0..NUM_STRANDS-1].
        """
        sequence = list(range(NUM_STRANDS))
        for i in range(NUM_STRANDS - 1, 0, -1):
            byte_idx = i % len(digest)
            j = digest[byte_idx] % (i + 1)
            sequence[i], sequence[j] = sequence[j], sequence[i]
        return sequence

    # ─── Interval Derivation ──────────────────────────────────────

    def _derive_interval(self, digest: bytes) -> float:
        """
        Derive the next rotation interval from entropy digest.
        Maps to range [MIN_INTERVAL_MS, MAX_INTERVAL_MS].
        """
        raw = struct.unpack(">H", digest[28:30])[0]
        ratio = raw / 65535.0
        return MIN_INTERVAL_MS + ratio * (MAX_INTERVAL_MS - MIN_INTERVAL_MS)

    # ─── Status ──────────────────────────────────────────────────

    def get_status(self) -> Dict[str, Any]:
        return {
            "rotation_count": self._rotation_count,
            "last_sequence": self._last_sequence,
            "last_entropy_hash": self._last_entropy_hash,
            "history_size": len(self._history),
        }
