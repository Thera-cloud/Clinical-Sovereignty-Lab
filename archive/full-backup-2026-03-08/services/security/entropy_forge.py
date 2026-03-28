"""
HIVE DEFENSE PROTOCOL v1.0 — Entropy Forge (Phase 8B)
Bootstrap entropy generation and birth-coherence chaining for cold starts.

When the Sovereign Swarm starts from a cold state (no running Fibres), the
first Fibres face a bootstrapping problem: there is no existing heartbeat
history to derive birth coherence from.  The Entropy Forge solves this by
combining four independent entropy sources into a cryptographic seed:

    1. **HSM random** — Hardware-generated true random bytes.
    2. **Restart timestamp** — Nanosecond-precision restart time.
    3. **Originator signature** — Ed25519 signature from Big Nate's key.
    4. **Shard holder entropy** — Additional random bytes contributed by
       each shard holder during key reconstruction.

The seed is then used to derive birth coherence hashes for the first N
Fibres in a chain structure:

    Fibre₁.birth_hash = SHA-512(seed)
    Fibre₂.birth_hash = SHA-512(seed ‖ Fibre₁.heartbeat)
    Fibreₙ.birth_hash = SHA-512(seed ‖ Fibre₁.hb ‖ ... ‖ Fibreₙ₋₁.hb)

By the 10th Fibre, the chain is cryptographically unpredictable without
knowledge of every prior birth's exact heartbeat pulse — creating a
"computational ratchet" that hardens with each successive birth.

An additional ``run_chaos_rounds()`` function mixes the seed through 1000
rounds of chaotic computation (iterated SHA-512 with feedback XOR) to
further decorrelate the output from any single entropy source.

Patent-Pending — Cold Start Defense
    "A method for bootstrapping cryptographic entropy in a distributed AI
     therapy hive from cold start, combining hardware random, nanosecond
     timing, originator signatures, and shard-holder entropy into a seed
     that is chain-hashed with successive entity heartbeats to produce
     computationally unpredictable birth coherence values."

© 2026 Clinical Sovereignty Lab. All rights reserved.
"""

from __future__ import annotations

import hashlib
import logging
import os
import struct
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple
from uuid import UUID, uuid4

logger = logging.getLogger("hive.entropy_forge")


# Default number of chaos rounds for seed hardening
DEFAULT_CHAOS_ROUNDS: int = 1000

# Minimum shard holder entropy contributions for a valid forge
MIN_SHARD_ENTROPY_SOURCES: int = 2


# =============================================================================
# BIRTH COHERENCE CHAIN ENTRY
# =============================================================================

@dataclass
class BirthChainEntry:
    """
    A single entry in the birth coherence chain.

    Each entry records the relationship between a Fibre's birth hash and
    all prior heartbeats that contributed to its derivation.

    Attributes
    ----------
    fibre_index:
        0-based index of this Fibre in the chain.
    fibre_id:
        UUID of the Fibre (assigned at birth).
    birth_coherence_hash:
        SHA-512 hex digest of the birth material.
    heartbeat_pulse:
        The first heartbeat pulse emitted by this Fibre (used as input
        for the *next* Fibre's birth hash).
    timestamp_ns:
        Nanosecond-precision timestamp at birth.
    """

    fibre_index: int = 0
    fibre_id: UUID = field(default_factory=uuid4)
    birth_coherence_hash: str = ""
    heartbeat_pulse: str = ""
    timestamp_ns: int = field(default_factory=time.monotonic_ns)


# =============================================================================
# ENTROPY FORGE
# =============================================================================

class EntropyForge:
    """
    Bootstrap entropy generator and birth-coherence chain builder.

    The forge produces the cryptographic foundation for the first generation
    of Fibres after a cold start.  Once the chain is long enough (typically
    10+ Fibres), subsequent births can derive their coherence from the
    established heartbeat network instead of the forge.

    Usage
    -----
    ::

        forge = EntropyForge()

        # Step 1: Forge the seed from 4 entropy sources
        seed = forge.forge_seed(
            hsm_random=os.urandom(64),
            restart_timestamp_ns=time.monotonic_ns(),
            originator_signature=sig_bytes,
            shard_holder_entropy_list=[holder1_entropy, holder2_entropy],
        )

        # Step 2: Harden the seed through chaos rounds
        hardened = forge.run_chaos_rounds(seed, rounds=1000)

        # Step 3: Derive birth hashes for the first N Fibres
        birth_hash_1 = forge.forge_birth_coherence(hardened, [])
        # ... fibre 1 is born, emits heartbeat_1 ...
        birth_hash_2 = forge.forge_birth_coherence(hardened, [heartbeat_1])
        # ... fibre 2 is born, emits heartbeat_2 ...
        birth_hash_3 = forge.forge_birth_coherence(hardened, [heartbeat_1, heartbeat_2])
        # etc.

    Patent Ref: Cold Start Defense
    """

    def __init__(self) -> None:
        self._seed: Optional[bytes] = None
        self._chain: List[BirthChainEntry] = []
        self._forged_at: Optional[datetime] = None
        self._chaos_rounds_applied: int = 0
        self._total_births: int = 0

        logger.info("EntropyForge initialised")

    # ------------------------------------------------------------------
    # Seed Forging
    # ------------------------------------------------------------------

    def forge_seed(
        self,
        hsm_random: bytes,
        restart_timestamp_ns: int,
        originator_signature: bytes,
        shard_holder_entropy_list: List[bytes],
    ) -> bytes:
        """
        Combine four entropy sources into a single bootstrap seed.

        The seed is ``SHA-512(hsm_random ‖ timestamp_bytes ‖ signature ‖
        shard_entropy[0] ‖ shard_entropy[1] ‖ ...)``.

        Parameters
        ----------
        hsm_random:
            Hardware-generated true random bytes (recommended >= 32 bytes).
        restart_timestamp_ns:
            Nanosecond-precision timestamp of the system restart.
        originator_signature:
            Ed25519 signature from Big Nate's master key over the restart
            event (proves the restart is authorised).
        shard_holder_entropy_list:
            Additional random bytes contributed by shard holders during
            key reconstruction.  At least ``MIN_SHARD_ENTROPY_SOURCES``
            contributions are required.

        Returns
        -------
        bytes
            64-byte SHA-512 seed.

        Raises
        ------
        ValueError
            If insufficient entropy sources are provided.
        """
        # Validate inputs
        if len(hsm_random) < 16:
            raise ValueError(
                f"HSM random too short ({len(hsm_random)} bytes) — "
                f"need at least 16 bytes"
            )
        if len(originator_signature) < 32:
            raise ValueError(
                f"Originator signature too short ({len(originator_signature)} "
                f"bytes) — expected Ed25519 signature"
            )
        if len(shard_holder_entropy_list) < MIN_SHARD_ENTROPY_SOURCES:
            raise ValueError(
                f"Need at least {MIN_SHARD_ENTROPY_SOURCES} shard holder "
                f"entropy contributions (got {len(shard_holder_entropy_list)})"
            )

        # Build the hash input: concatenate all entropy sources
        timestamp_bytes = struct.pack(">q", restart_timestamp_ns)

        hash_input = bytearray()
        hash_input.extend(hsm_random)
        hash_input.extend(timestamp_bytes)
        hash_input.extend(originator_signature)
        for shard_entropy in shard_holder_entropy_list:
            hash_input.extend(shard_entropy)

        # SHA-512 produces 64 bytes of seed
        seed = hashlib.sha512(bytes(hash_input)).digest()

        self._seed = seed
        self._forged_at = datetime.utcnow()
        self._chain.clear()
        self._total_births = 0

        logger.info(
            "Entropy seed forged: %d input bytes → 64-byte seed "
            "(HSM=%d, sig=%d, shard_sources=%d)",
            len(hash_input),
            len(hsm_random),
            len(originator_signature),
            len(shard_holder_entropy_list),
        )

        return seed

    # ------------------------------------------------------------------
    # Chaos Rounds — Seed Hardening
    # ------------------------------------------------------------------

    def run_chaos_rounds(
        self,
        seed: bytes,
        rounds: int = DEFAULT_CHAOS_ROUNDS,
    ) -> bytes:
        """
        Harden a seed by running it through multiple rounds of chaotic
        SHA-512 computation with feedback XOR.

        Each round:
            1. ``hash_n = SHA-512(state ‖ round_counter_bytes)``
            2. ``state = state XOR hash_n``  (bytewise, wrapping)

        After *rounds* iterations the state is hashed one final time to
        produce the output.

        This makes the output depend on every single round — skipping or
        altering any one round produces a completely different result.

        Parameters
        ----------
        seed:
            The initial seed bytes (typically 64 bytes from ``forge_seed``).
        rounds:
            Number of chaotic mixing rounds (default 1000).

        Returns
        -------
        bytes
            64-byte hardened seed.
        """
        if rounds < 1:
            raise ValueError("Chaos rounds must be >= 1")

        state = bytearray(seed)
        state_len = len(state)

        for r in range(rounds):
            # Hash the current state + round counter
            round_input = bytes(state) + struct.pack(">I", r)
            hash_output = hashlib.sha512(round_input).digest()

            # XOR feedback: state = state ^ hash_output
            for i in range(min(state_len, len(hash_output))):
                state[i] ^= hash_output[i]

        # Final hash to collapse state into a clean 64-byte output
        hardened = hashlib.sha512(bytes(state)).digest()

        self._chaos_rounds_applied = rounds
        self._seed = hardened

        logger.info(
            "Chaos rounds complete: %d rounds applied — "
            "seed fingerprint: %s",
            rounds,
            hashlib.sha256(hardened).hexdigest()[:16],
        )

        return hardened

    def pre_birth_chaos_injection(
        self,
        seed: bytes,
        rounds: int = DEFAULT_CHAOS_ROUNDS,
    ) -> bytes:
        """
        Alias for ``run_chaos_rounds`` matching the protocol documentation
        terminology (Hive Defense Protocol v3.0, VECTOR 9).

        Runs 1000 rounds of chaotic SHA-512 computation before the first
        Fibre birth to ensure the system is in a maximally unpredictable
        state, eliminating any cold-start advantage for an attacker.
        """
        return self.run_chaos_rounds(seed, rounds=rounds)

    # ------------------------------------------------------------------
    # Birth Coherence Chain
    # ------------------------------------------------------------------

    def forge_birth_coherence(
        self,
        seed: bytes,
        previous_heartbeats: List[str],
    ) -> str:
        """
        Derive a birth coherence hash for a new Fibre.

        The hash incorporates the seed and the heartbeat pulses of all
        previously-born Fibres in the chain:

            Fibre₁ = SHA-512(seed)
            Fibre₂ = SHA-512(seed ‖ heartbeat₁)
            Fibreₙ = SHA-512(seed ‖ heartbeat₁ ‖ ... ‖ heartbeatₙ₋₁)

        By the 10th Fibre, predicting the birth hash requires knowledge
        of every prior Fibre's exact heartbeat — which is itself derived
        from real-time emotional coherence data.

        Parameters
        ----------
        seed:
            The forge seed (or hardened seed from ``run_chaos_rounds``).
        previous_heartbeats:
            Ordered list of hex-encoded heartbeat pulse strings from
            all previously-born Fibres in the chain.

        Returns
        -------
        str
            Hex-encoded SHA-512 birth coherence hash.
        """
        hash_input = bytearray(seed)

        for hb in previous_heartbeats:
            hash_input.extend(hb.encode("utf-8"))

        birth_hash = hashlib.sha512(bytes(hash_input)).hexdigest()

        # Record in the chain
        fibre_index = len(self._chain)
        entry = BirthChainEntry(
            fibre_index=fibre_index,
            birth_coherence_hash=birth_hash,
            timestamp_ns=time.monotonic_ns(),
        )
        self._chain.append(entry)
        self._total_births += 1

        logger.info(
            "Birth coherence forged: fibre_index=%d hash=%s… "
            "(chain depth=%d, prior_heartbeats=%d)",
            fibre_index,
            birth_hash[:16],
            len(self._chain),
            len(previous_heartbeats),
        )

        return birth_hash

    def record_heartbeat(self, fibre_index: int, heartbeat_pulse: str) -> None:
        """
        Record a Fibre's first heartbeat pulse for use in subsequent births.

        Parameters
        ----------
        fibre_index:
            The 0-based index of the Fibre in the chain.
        heartbeat_pulse:
            The hex-encoded HMAC pulse from the Fibre's first heartbeat.

        Raises
        ------
        IndexError
            If fibre_index is out of range.
        """
        if fibre_index < 0 or fibre_index >= len(self._chain):
            raise IndexError(
                f"Fibre index {fibre_index} out of range "
                f"(chain length={len(self._chain)})"
            )

        self._chain[fibre_index].heartbeat_pulse = heartbeat_pulse
        logger.debug(
            "Recorded heartbeat for chain entry %d: %s…",
            fibre_index,
            heartbeat_pulse[:16],
        )

    def set_fibre_id(self, fibre_index: int, fibre_id: UUID) -> None:
        """
        Associate a Fibre UUID with a chain entry after birth.

        Parameters
        ----------
        fibre_index:
            The 0-based index in the chain.
        fibre_id:
            The UUID assigned to the Fibre at birth.
        """
        if fibre_index < 0 or fibre_index >= len(self._chain):
            raise IndexError(
                f"Fibre index {fibre_index} out of range "
                f"(chain length={len(self._chain)})"
            )
        self._chain[fibre_index].fibre_id = fibre_id

    # ------------------------------------------------------------------
    # Chain Queries
    # ------------------------------------------------------------------

    def get_chain(self) -> List[Dict[str, Any]]:
        """
        Return the full birth coherence chain as serialisable dicts.

        Returns
        -------
        list[dict]
            One dict per chain entry with index, hash, heartbeat, and timing.
        """
        return [
            {
                "fibre_index": entry.fibre_index,
                "fibre_id": str(entry.fibre_id),
                "birth_coherence_hash": entry.birth_coherence_hash,
                "heartbeat_recorded": bool(entry.heartbeat_pulse),
                "timestamp_ns": entry.timestamp_ns,
            }
            for entry in self._chain
        ]

    def get_collected_heartbeats(self) -> List[str]:
        """
        Return all recorded heartbeat pulses in chain order.

        Useful for passing to ``forge_birth_coherence`` for the next Fibre.

        Returns
        -------
        list[str]
            Hex-encoded heartbeat pulses.  Entries without a recorded
            heartbeat are represented as empty strings.
        """
        return [entry.heartbeat_pulse for entry in self._chain]

    def verify_chain_integrity(self, seed: bytes) -> bool:
        """
        Verify that the birth coherence chain is consistent with the seed.

        Recomputes each birth hash from the seed and all prior heartbeats
        and checks that it matches the recorded value.

        Parameters
        ----------
        seed:
            The original (or hardened) forge seed.

        Returns
        -------
        bool
            True if every entry in the chain recomputes correctly.
        """
        collected_heartbeats: List[str] = []

        for entry in self._chain:
            # Recompute the expected birth hash
            hash_input = bytearray(seed)
            for hb in collected_heartbeats:
                hash_input.extend(hb.encode("utf-8"))

            expected = hashlib.sha512(bytes(hash_input)).hexdigest()

            if expected != entry.birth_coherence_hash:
                logger.error(
                    "Chain integrity failure at index %d: "
                    "expected %s…, got %s…",
                    entry.fibre_index,
                    expected[:16],
                    entry.birth_coherence_hash[:16],
                )
                return False

            # Add this entry's heartbeat for subsequent computations
            collected_heartbeats.append(entry.heartbeat_pulse)

        logger.info(
            "Birth chain integrity verified: %d entries OK",
            len(self._chain),
        )
        return True

    # ------------------------------------------------------------------
    # Chain Strength Assessment
    # ------------------------------------------------------------------

    @property
    def chain_depth(self) -> int:
        """Number of Fibres in the birth coherence chain."""
        return len(self._chain)

    @property
    def chain_is_mature(self) -> bool:
        """
        True if the chain has 10+ entries with recorded heartbeats.

        At 10 entries, the chain is considered cryptographically mature —
        predicting the next birth hash requires knowledge of all 10 prior
        heartbeats, each derived from real-time emotional coherence data.
        """
        recorded = sum(1 for e in self._chain if e.heartbeat_pulse)
        return recorded >= 10

    @property
    def unpredictability_score(self) -> float:
        """
        Estimate the chain's unpredictability on a 0.0–1.0 scale.

        Based on the number of recorded heartbeats:
            0 heartbeats  → 0.0 (seed alone is predictable if sources leak)
            5 heartbeats  → 0.5
            10 heartbeats → 0.9
            20+ heartbeats → ~1.0

        This is a heuristic, not a formal entropy measure.
        """
        recorded = sum(1 for e in self._chain if e.heartbeat_pulse)
        if recorded == 0:
            return 0.0
        if recorded >= 20:
            return 0.99
        # Sigmoid-like curve: 1 - e^(-0.23 * n)
        import math
        return min(0.99, 1.0 - math.exp(-0.23 * recorded))

    # ------------------------------------------------------------------
    # Diagnostics
    # ------------------------------------------------------------------

    @property
    def stats(self) -> Dict[str, Any]:
        """Diagnostic statistics for admin dashboards."""
        return {
            "seed_forged": self._seed is not None,
            "forged_at": (
                self._forged_at.isoformat() if self._forged_at else None
            ),
            "chaos_rounds_applied": self._chaos_rounds_applied,
            "chain_depth": self.chain_depth,
            "chain_is_mature": self.chain_is_mature,
            "unpredictability_score": round(self.unpredictability_score, 3),
            "total_births": self._total_births,
            "heartbeats_recorded": sum(
                1 for e in self._chain if e.heartbeat_pulse
            ),
        }

    def __repr__(self) -> str:
        return (
            f"<EntropyForge "
            f"seeded={self._seed is not None} "
            f"chain={self.chain_depth} "
            f"mature={self.chain_is_mature} "
            f"score={self.unpredictability_score:.2f}>"
        )
