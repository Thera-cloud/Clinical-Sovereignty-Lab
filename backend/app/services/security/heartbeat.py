"""
HIVE DEFENSE PROTOCOL v1.0 — Heartbeat Signal System
Phase 8A: Birth Coherence, Originator Signatures, and Pulse Verification

Every entity in the Sovereign Swarm carries an unforgeable heartbeat — a continuous
cryptographic proof-of-identity that binds:
    1. The exact C_emo coherence state at the moment of birth  (birth_coherence_hash)
    2. An Ed25519 signature from Big Nate's master key          (originator_signature)
    3. An HMAC-SHA256 pulse that evolves with each beat         (pulse_data)

The heartbeat is what the Coherence Gate checks *first* on every internal signal.
No heartbeat → signal goes straight to the Mirror Dimension (absorbed, never reaches
the Real Hive).  Fake heartbeat → contained in Mirror for forensic analysis.

Patent-Pending — Claims 30-31
    Claim 30: "A method for generating a cryptographic heartbeat signal comprising
               a birth coherence hash derived from the system emotional coherence
               state at entity instantiation time."
    Claim 31: "The method of Claim 30, wherein the heartbeat pulse is computed
               using HMAC-SHA256 with the birth coherence hash as key and a
               monotonically increasing counter to prevent replay."

© 2026 Clinical Sovereignty Lab. All rights reserved.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import logging
import struct
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import UUID, uuid4

from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)
from cryptography.hazmat.primitives import serialization
from cryptography.exceptions import InvalidSignature

from app.models.hive_defense import HeartbeatPulse

logger = logging.getLogger("hive.heartbeat")


# =============================================================================
# KEY SERIALIZATION HELPERS
# =============================================================================

def _public_key_to_pem(key: Ed25519PublicKey) -> str:
    """Serialize an Ed25519 public key to PEM string."""
    return key.public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode()


def _public_key_from_pem(pem: str) -> Ed25519PublicKey:
    """Deserialize an Ed25519 public key from PEM string."""
    return serialization.load_pem_public_key(pem.encode())


def _private_key_from_pem(pem: str) -> Ed25519PrivateKey:
    """Deserialize an Ed25519 private key from PEM string."""
    return serialization.load_pem_private_key(pem.encode(), password=None)


# =============================================================================
# HEARTBEAT SIGNAL
# =============================================================================

class HeartbeatSignal:
    """
    Cryptographic heartbeat for a single hive entity.

    The heartbeat is *born* alongside the entity and can never be transferred.
    Each pulse is a deterministic HMAC-SHA256 that incorporates:
        - The immutable birth_coherence_hash (key)
        - The current system state (evolution, counters)
        - A monotonic counter that prevents replay

    Lifecycle:
        1. ``birth()``      — called exactly once when the entity is spawned.
        2. ``pulse()``      — called on each heartbeat cycle (configurable interval).
        3. ``verify_pulse()`` — called by peers / the Coherence Gate to validate.

    Patent Ref: Claims 30-31
    """

    def __init__(self, entity_id: UUID):
        self.entity_id: UUID = entity_id

        # Immutable after birth
        self._birth_coherence_hash: Optional[str] = None
        self._originator_signature: Optional[str] = None
        self._birth_timestamp_ns: Optional[int] = None
        self._identity_chain_root: Optional[str] = None

        # Evolving state
        self._evolution_journal_hash: str = hashlib.sha256(b"genesis").hexdigest()
        self._monotonic_counter: int = 0
        self._last_pulse: Optional[str] = None
        self._last_pulse_time_ns: int = 0

        # Audit trail
        self._pulse_history: List[Dict[str, Any]] = []
        self._born: bool = False

    # ── Birth ────────────────────────────────────────────────────────────────

    def birth(
        self,
        system_c_emo: float,
        master_private_key: Ed25519PrivateKey,
        identity_chain_root: str,
        extra_entropy: bytes = b"",
    ) -> HeartbeatPulse:
        """
        Give this entity its heartbeat.  Must be called exactly once.

        Args:
            system_c_emo:        The system-wide C_emo coherence value at the
                                 exact moment of entity creation.
            master_private_key:  Big Nate's Ed25519 private key for the
                                 originator signature.
            identity_chain_root: Merkle root of the entity's identity chain
                                 (from IdentityChainService).
            extra_entropy:       Optional additional bytes mixed into the
                                 birth hash for uniqueness.

        Returns:
            HeartbeatPulse model with all birth fields populated.

        Raises:
            RuntimeError: If birth() has already been called.

        Patent Ref: Claim 30 — birth coherence hash derivation.
        """
        if self._born:
            raise RuntimeError(
                f"HeartbeatSignal.birth() already called for entity {self.entity_id}"
            )

        now_ns = time.monotonic_ns()

        # ── 1. Birth Coherence Hash ──
        # SHA-256( C_emo as 8-byte double || nanosecond timestamp || entity_id || extra )
        birth_material = (
            struct.pack(">d", system_c_emo)
            + struct.pack(">q", now_ns)
            + self.entity_id.bytes
            + extra_entropy
        )
        self._birth_coherence_hash = hashlib.sha256(birth_material).hexdigest()

        # ── 2. Originator Signature ──
        # Big Nate signs the birth_coherence_hash to prove provenance.
        sig_bytes = master_private_key.sign(self._birth_coherence_hash.encode())
        self._originator_signature = base64.b64encode(sig_bytes).decode()

        # ── 3. Timestamps & Chain Root ──
        self._birth_timestamp_ns = now_ns
        self._identity_chain_root = identity_chain_root

        self._born = True
        logger.info(
            "Entity %s born — birth_hash=%s…",
            self.entity_id,
            self._birth_coherence_hash[:16],
        )

        return self._to_pulse_model()

    # ── Pulse Generation ─────────────────────────────────────────────────────

    def pulse(
        self,
        current_system_state_hash: str = "",
        evolution_journal_hash: Optional[str] = None,
    ) -> HeartbeatPulse:
        """
        Generate the next heartbeat pulse.

        The pulse is ``HMAC-SHA256(key=birth_coherence_hash,
        msg=birth_hash + system_state + journal_hash + counter_bytes)``.

        The monotonic counter increments on every call, preventing replay.

        Args:
            current_system_state_hash: SHA-256 of the current global hive state.
            evolution_journal_hash:    SHA-256 of the entity's evolution journal
                                       (defaults to the last known value).

        Returns:
            Updated HeartbeatPulse model.

        Raises:
            RuntimeError: If birth() has not been called.

        Patent Ref: Claim 31 — HMAC-SHA256 pulse with monotonic counter.
        """
        self._ensure_born()

        if evolution_journal_hash is not None:
            self._evolution_journal_hash = evolution_journal_hash

        # Increment counter
        self._monotonic_counter += 1

        # Build HMAC input
        counter_bytes = struct.pack(">Q", self._monotonic_counter)  # 8 bytes big-endian
        hmac_input = (
            self._birth_coherence_hash.encode()
            + current_system_state_hash.encode()
            + self._evolution_journal_hash.encode()
            + counter_bytes
        )

        # HMAC-SHA256 with birth_coherence_hash as key
        pulse_data = hmac.new(
            key=self._birth_coherence_hash.encode(),
            msg=hmac_input,
            digestmod=hashlib.sha256,
        ).hexdigest()

        self._last_pulse = pulse_data
        self._last_pulse_time_ns = time.monotonic_ns()

        # Record in audit trail (keep last 100)
        self._pulse_history.append({
            "counter": self._monotonic_counter,
            "pulse": pulse_data[:16],
            "time_ns": self._last_pulse_time_ns,
        })
        if len(self._pulse_history) > 100:
            self._pulse_history = self._pulse_history[-100:]

        logger.debug(
            "Entity %s pulse #%d — %s…",
            self.entity_id,
            self._monotonic_counter,
            pulse_data[:16],
        )

        return self._to_pulse_model()

    # ── Peer Pulse Verification ──────────────────────────────────────────────

    @staticmethod
    def verify_pulse(
        claimed_pulse: HeartbeatPulse,
        current_system_state_hash: str = "",
    ) -> bool:
        """
        Verify that a peer's heartbeat pulse is consistent with its claimed identity.

        Recomputes the HMAC-SHA256 from the fields in the HeartbeatPulse and checks
        that the result matches ``pulse_data``.

        Args:
            claimed_pulse:            The HeartbeatPulse received from a peer entity.
            current_system_state_hash: The current global system state hash (must be
                                       the same value used when the pulse was generated).

        Returns:
            True if the recomputed HMAC matches the claimed pulse_data.
        """
        if not claimed_pulse.pulse_data or not claimed_pulse.birth_coherence_hash:
            return False

        counter_bytes = struct.pack(">Q", claimed_pulse.monotonic_counter)
        hmac_input = (
            claimed_pulse.birth_coherence_hash.encode()
            + current_system_state_hash.encode()
            + claimed_pulse.evolution_journal_hash.encode()
            + counter_bytes
        )

        expected = hmac.new(
            key=claimed_pulse.birth_coherence_hash.encode(),
            msg=hmac_input,
            digestmod=hashlib.sha256,
        ).hexdigest()

        return hmac.compare_digest(expected, claimed_pulse.pulse_data)

    # ── Originator Signature Verification ────────────────────────────────────

    @staticmethod
    def verify_originator(
        pulse: HeartbeatPulse,
        master_public_key: Ed25519PublicKey,
    ) -> bool:
        """
        Verify that the originator signature was produced by Big Nate's master key.

        Args:
            pulse:             The HeartbeatPulse whose originator_signature to check.
            master_public_key: Big Nate's Ed25519 public key.

        Returns:
            True if the signature is valid for the birth_coherence_hash.
        """
        if not pulse.originator_signature or not pulse.birth_coherence_hash:
            return False
        try:
            sig_bytes = base64.b64decode(pulse.originator_signature)
            master_public_key.verify(sig_bytes, pulse.birth_coherence_hash.encode())
            return True
        except (InvalidSignature, Exception) as exc:
            logger.debug(
                "Originator verification failed for entity %s: %s",
                pulse.entity_id,
                exc,
            )
            return False

    # ── Accessors ────────────────────────────────────────────────────────────

    @property
    def born(self) -> bool:
        return self._born

    @property
    def birth_coherence_hash(self) -> Optional[str]:
        return self._birth_coherence_hash

    @property
    def originator_signature(self) -> Optional[str]:
        return self._originator_signature

    @property
    def monotonic_counter(self) -> int:
        return self._monotonic_counter

    @property
    def last_pulse(self) -> Optional[str]:
        return self._last_pulse

    @property
    def identity_chain_root(self) -> Optional[str]:
        return self._identity_chain_root

    @property
    def pulse_history(self) -> List[Dict[str, Any]]:
        return list(self._pulse_history)

    # ── Internal Helpers ─────────────────────────────────────────────────────

    def _ensure_born(self) -> None:
        if not self._born:
            raise RuntimeError(
                f"HeartbeatSignal for entity {self.entity_id} has not been born yet"
            )

    def _to_pulse_model(self) -> HeartbeatPulse:
        """Serialize current state to a HeartbeatPulse Pydantic model."""
        return HeartbeatPulse(
            entity_id=self.entity_id,
            birth_coherence_hash=self._birth_coherence_hash or "",
            originator_signature=self._originator_signature or "",
            birth_timestamp_ns=self._birth_timestamp_ns or 0,
            identity_chain_root=self._identity_chain_root or "",
            evolution_journal_hash=self._evolution_journal_hash,
            monotonic_counter=self._monotonic_counter,
            pulse_data=self._last_pulse or "",
        )


# =============================================================================
# HEARTBEAT REGISTRY
# =============================================================================

@dataclass
class _HeartbeatEntry:
    """Internal tracking record for one registered heartbeat."""
    signal: HeartbeatSignal
    last_pulse_model: HeartbeatPulse
    registered_at_ns: int = field(default_factory=time.monotonic_ns)
    last_seen_ns: int = field(default_factory=time.monotonic_ns)
    missed_beats: int = 0
    alive: bool = True


class HeartbeatRegistry:
    """
    Central registry of all active heartbeats in the Sovereign Swarm hive.

    Responsibilities:
        - Register new heartbeats at entity birth.
        - Accept pulse updates and verify continuity (monotonic counter must
          advance, pulse must recompute correctly).
        - Flag entities whose heartbeats go silent or become inconsistent.
        - Provide lookup for the Coherence Gate to validate incoming signals.

    Thread Safety:
        This class is designed for single-threaded asyncio use.  All public
        methods that touch the database are ``async``.

    Patent Ref: Claims 30-31
    """

    def __init__(self, db_pool=None):
        self._db_pool = db_pool
        self._entries: Dict[UUID, _HeartbeatEntry] = {}
        self._master_public_key: Optional[Ed25519PublicKey] = None
        self._master_public_pem: Optional[str] = None

    # ── Configuration ────────────────────────────────────────────────────────

    def set_master_public_key(self, master_public_pem: str) -> None:
        """
        Load Big Nate's master public key so the registry can verify
        originator signatures.

        Args:
            master_public_pem: PEM-encoded Ed25519 public key.
        """
        self._master_public_key = _public_key_from_pem(master_public_pem)
        self._master_public_pem = master_public_pem
        logger.info("HeartbeatRegistry master public key loaded.")

    @property
    def master_public_key(self) -> Optional[Ed25519PublicKey]:
        return self._master_public_key

    # ── Registration ─────────────────────────────────────────────────────────

    def register(self, heartbeat: HeartbeatSignal) -> None:
        """
        Register a newly-born heartbeat in the registry.

        Args:
            heartbeat: A HeartbeatSignal that has already had ``birth()`` called.

        Raises:
            ValueError: If the heartbeat has not been born or is already registered.
        """
        if not heartbeat.born:
            raise ValueError(
                f"Cannot register unborn heartbeat for entity {heartbeat.entity_id}"
            )
        if heartbeat.entity_id in self._entries:
            raise ValueError(
                f"Entity {heartbeat.entity_id} is already registered in the HeartbeatRegistry"
            )

        pulse_model = heartbeat._to_pulse_model()
        self._entries[heartbeat.entity_id] = _HeartbeatEntry(
            signal=heartbeat,
            last_pulse_model=pulse_model,
        )
        logger.info(
            "Registered heartbeat for entity %s (hash=%s…)",
            heartbeat.entity_id,
            heartbeat.birth_coherence_hash[:16] if heartbeat.birth_coherence_hash else "?",
        )

    def unregister(self, entity_id: UUID) -> bool:
        """
        Remove an entity from the heartbeat registry (e.g., on Fibre pruning).

        Returns:
            True if the entity was found and removed.
        """
        removed = entity_id in self._entries
        if removed:
            del self._entries[entity_id]
            logger.info("Unregistered heartbeat for entity %s", entity_id)
        return removed

    # ── Pulse Updates ────────────────────────────────────────────────────────

    def update_pulse(
        self,
        entity_id: UUID,
        pulse: HeartbeatPulse,
        current_system_state_hash: str = "",
    ) -> bool:
        """
        Accept a new pulse from an entity and verify continuity.

        Continuity checks:
            1. Entity must be registered.
            2. Monotonic counter must be strictly greater than the last seen value.
            3. Pulse data must recompute correctly from the claimed fields.

        Args:
            entity_id:                The entity reporting its pulse.
            pulse:                    The new HeartbeatPulse.
            current_system_state_hash: Global system state hash at pulse time.

        Returns:
            True if the pulse is accepted.  False if continuity is broken.
        """
        entry = self._entries.get(entity_id)
        if entry is None:
            logger.warning("Pulse from unknown entity %s — rejected", entity_id)
            return False

        # Counter must advance
        if pulse.monotonic_counter <= entry.last_pulse_model.monotonic_counter:
            logger.warning(
                "Entity %s counter did not advance (%d <= %d) — continuity broken",
                entity_id,
                pulse.monotonic_counter,
                entry.last_pulse_model.monotonic_counter,
            )
            entry.missed_beats += 1
            return False

        # Verify the HMAC pulse itself
        if not HeartbeatSignal.verify_pulse(pulse, current_system_state_hash):
            logger.warning(
                "Entity %s pulse HMAC mismatch at counter %d — continuity broken",
                entity_id,
                pulse.monotonic_counter,
            )
            entry.missed_beats += 1
            return False

        # Accept
        entry.last_pulse_model = pulse
        entry.last_seen_ns = time.monotonic_ns()
        entry.missed_beats = 0
        return True

    # ── Queries ──────────────────────────────────────────────────────────────

    def is_registered(self, entity_id: UUID) -> bool:
        """Check if an entity has a registered heartbeat."""
        return entity_id in self._entries

    def get_pulse(self, entity_id: UUID) -> Optional[HeartbeatPulse]:
        """Return the latest pulse model for an entity, or None."""
        entry = self._entries.get(entity_id)
        return entry.last_pulse_model if entry else None

    def get_birth_hash(self, entity_id: UUID) -> Optional[str]:
        """Return the birth coherence hash for an entity, or None."""
        entry = self._entries.get(entity_id)
        if entry and entry.signal.birth_coherence_hash:
            return entry.signal.birth_coherence_hash
        return None

    def check_continuity(self, entity_id: UUID, max_missed: int = 3) -> bool:
        """
        Check whether an entity's heartbeat is continuous.

        An entity is considered to have broken continuity if it has missed
        more than ``max_missed`` consecutive beats (pulse updates that failed
        verification or were never received).

        Args:
            entity_id:  The entity to check.
            max_missed: The threshold for missed beats before flagging.

        Returns:
            True if continuity is intact, False otherwise.
        """
        entry = self._entries.get(entity_id)
        if entry is None:
            return False
        return entry.missed_beats <= max_missed and entry.alive

    def get_silent_entities(self, silence_threshold_ns: int) -> List[UUID]:
        """
        Return a list of entities that have not pulsed within the given
        nanosecond threshold.

        This is used by the Curiosity Protocol to detect entities that may
        have been compromised or disconnected.

        Args:
            silence_threshold_ns: Max nanoseconds since last pulse before
                                  an entity is considered silent.

        Returns:
            List of entity UUIDs that are silent.
        """
        now = time.monotonic_ns()
        silent = []
        for eid, entry in self._entries.items():
            if entry.alive and (now - entry.last_seen_ns) > silence_threshold_ns:
                silent.append(eid)
        return silent

    def mark_dead(self, entity_id: UUID) -> None:
        """Mark an entity's heartbeat as dead (e.g., after containment)."""
        entry = self._entries.get(entity_id)
        if entry:
            entry.alive = False
            logger.warning("Entity %s heartbeat marked DEAD", entity_id)

    # ── Originator Verification ──────────────────────────────────────────────

    def verify_originator(self, entity_id: UUID) -> bool:
        """
        Verify that an entity's birth was signed by Big Nate's master key.

        Returns:
            True if the originator signature is valid.
            False if the entity is not registered or the signature is invalid.
        """
        if not self._master_public_key:
            logger.error("Cannot verify originator — master public key not loaded")
            return False

        entry = self._entries.get(entity_id)
        if entry is None:
            return False

        return HeartbeatSignal.verify_originator(
            entry.last_pulse_model,
            self._master_public_key,
        )

    # ── Bulk Operations ──────────────────────────────────────────────────────

    @property
    def active_count(self) -> int:
        """Number of alive, registered heartbeats."""
        return sum(1 for e in self._entries.values() if e.alive)

    @property
    def total_count(self) -> int:
        """Total registered heartbeats (alive + dead)."""
        return len(self._entries)

    def all_entity_ids(self) -> List[UUID]:
        """Return all registered entity IDs."""
        return list(self._entries.keys())

    def summary(self) -> Dict[str, Any]:
        """Return a summary dict for admin dashboards."""
        alive = 0
        dead = 0
        broken_continuity = 0
        for entry in self._entries.values():
            if entry.alive:
                alive += 1
            else:
                dead += 1
            if entry.missed_beats > 3:
                broken_continuity += 1

        return {
            "total_registered": len(self._entries),
            "alive": alive,
            "dead": dead,
            "broken_continuity": broken_continuity,
            "master_key_loaded": self._master_public_key is not None,
        }

    # ── Persistence (async) ──────────────────────────────────────────────────

    async def persist_pulse(self, entity_id: UUID) -> None:
        """
        Persist the latest heartbeat pulse for an entity to the database.

        This is called periodically or on significant events (not every single
        pulse, to avoid write amplification).
        """
        if not self._db_pool:
            return

        entry = self._entries.get(entity_id)
        if entry is None:
            return

        pulse = entry.last_pulse_model
        try:
            async with self._db_pool.acquire() as conn:
                await conn.execute(
                    """
                    INSERT INTO hive_heartbeats (
                        entity_id, birth_coherence_hash, originator_signature,
                        birth_timestamp_ns, identity_chain_root,
                        evolution_journal_hash, monotonic_counter, pulse_data,
                        recorded_at
                    ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, NOW())
                    ON CONFLICT (entity_id) DO UPDATE SET
                        evolution_journal_hash = EXCLUDED.evolution_journal_hash,
                        monotonic_counter = EXCLUDED.monotonic_counter,
                        pulse_data = EXCLUDED.pulse_data,
                        recorded_at = NOW()
                    """,
                    pulse.entity_id,
                    pulse.birth_coherence_hash,
                    pulse.originator_signature,
                    pulse.birth_timestamp_ns,
                    pulse.identity_chain_root,
                    pulse.evolution_journal_hash,
                    pulse.monotonic_counter,
                    pulse.pulse_data,
                )
            logger.debug("Persisted pulse for entity %s", entity_id)
        except Exception as exc:
            logger.error("Failed to persist pulse for %s: %s", entity_id, exc)

    async def load_from_db(self) -> int:
        """
        Reload heartbeat records from the database on service restart.

        Note: This restores the *latest known* pulse data but not the full
        HeartbeatSignal (which requires the birth secret).  Entities will
        need to re-pulse after restart to prove liveness.

        Returns:
            Number of records loaded.
        """
        if not self._db_pool:
            return 0

        try:
            async with self._db_pool.acquire() as conn:
                rows = await conn.fetch(
                    """
                    SELECT entity_id, birth_coherence_hash, originator_signature,
                           birth_timestamp_ns, identity_chain_root,
                           evolution_journal_hash, monotonic_counter, pulse_data
                    FROM hive_heartbeats
                    """
                )

            loaded = 0
            for row in rows:
                eid = row["entity_id"]
                # Reconstruct a HeartbeatSignal in "already-born" state
                signal = HeartbeatSignal(entity_id=eid)
                signal._birth_coherence_hash = row["birth_coherence_hash"]
                signal._originator_signature = row["originator_signature"]
                signal._birth_timestamp_ns = row["birth_timestamp_ns"]
                signal._identity_chain_root = row["identity_chain_root"]
                signal._evolution_journal_hash = row["evolution_journal_hash"]
                signal._monotonic_counter = row["monotonic_counter"]
                signal._last_pulse = row["pulse_data"]
                signal._born = True

                pulse_model = signal._to_pulse_model()
                self._entries[eid] = _HeartbeatEntry(
                    signal=signal,
                    last_pulse_model=pulse_model,
                )
                loaded += 1

            logger.info("Loaded %d heartbeat records from database", loaded)
            return loaded
        except Exception as exc:
            logger.error("Failed to load heartbeats from DB: %s", exc)
            return 0
