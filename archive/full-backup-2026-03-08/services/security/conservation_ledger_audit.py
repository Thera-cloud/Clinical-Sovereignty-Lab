"""
HIVE DEFENSE PROTOCOL v3.0 — Conservation Ledger Audit (Phase 8C: Third Cord)
Quakete energy conservation enforcement through immutable ledger verification.

The Quakete system operates under a fundamental conservation law: total system
energy is a constant. Any transfer that changes the system total is mathematically
impossible under legitimate operation — therefore, any such transfer is an
immediate, unconditional indicator of compromise.

Design rationale:
    In a closed thermodynamic system, energy cannot be created or destroyed.
    The Quakete energy model mirrors this: every transfer moves energy from
    source to destination with zero-sum accounting.  A running SHA-256 hash
    chain of the ledger state is verified every 60 seconds.  If the total
    deviates from the established constant, the violation is logged to the
    forensic chain and DEFCON is escalated immediately.

    This is one of the few absolute detection mechanisms — there is no
    threshold, no heuristic, no false-positive consideration.  Conservation
    violations are *provably* impossible under legitimate operation.

Patent-Pending — Claims 30-56
© 2026 Clinical Sovereignty Lab. All rights reserved.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable, Coroutine, Deque, Dict, List, Optional, Tuple
from uuid import UUID, uuid4

from app.models.hive_defense import (
    ConservationLedgerEntry,
    DefconLevel,
    ForensicRecord,
    HIVE_EVENT_TOPICS,
)

logger = logging.getLogger("hive.conservation_ledger")


# =============================================================================
# CONSTANTS
# =============================================================================

#: Verification interval in seconds
VERIFICATION_INTERVAL_SEC: float = 60.0

#: Maximum ledger entries kept in memory (older entries remain in DB)
MAX_MEMORY_ENTRIES: int = 10_000

#: Tolerance for floating-point comparison (conservation check)
CONSERVATION_EPSILON: float = 1e-10


# =============================================================================
# TRANSFER RECORD
# =============================================================================

@dataclass
class TransferRecord:
    """
    A single energy transfer between two entities.

    Attributes:
        transfer_id:   Unique identifier for this transfer.
        source_id:     UUID of the energy source entity.
        dest_id:       UUID of the energy destination entity.
        amount:        Amount of energy transferred (positive).
        timestamp:     When the transfer occurred.
        record_hash:   SHA-256 hash of this record (chain link).
        previous_hash: Hash of the preceding record in the chain.
    """
    transfer_id: UUID = field(default_factory=uuid4)
    source_id: UUID = field(default_factory=uuid4)
    dest_id: UUID = field(default_factory=uuid4)
    amount: float = 0.0
    timestamp: datetime = field(default_factory=datetime.utcnow)
    record_hash: str = ""
    previous_hash: str = ""

    def compute_hash(self, previous_hash: str = "") -> str:
        """
        Compute the SHA-256 hash for this record, chaining to the previous.

        Args:
            previous_hash: Hash of the preceding record in the chain.

        Returns:
            Hex-encoded SHA-256 digest.
        """
        data = (
            f"{self.transfer_id}:{self.source_id}:{self.dest_id}:"
            f"{self.amount:.15f}:{self.timestamp.isoformat()}:{previous_hash}"
        )
        self.record_hash = hashlib.sha256(data.encode()).hexdigest()
        self.previous_hash = previous_hash
        return self.record_hash


# =============================================================================
# CONSERVATION LEDGER AUDIT
# =============================================================================

class ConservationLedgerAudit:
    """
    Quakete energy conservation enforcement through immutable ledger verification.

    Total system energy is a constant established at hive initialisation.
    Every energy transfer is logged to an immutable hash-chain ledger.
    A verification loop runs every 60 seconds, recomputing the system total
    and validating the chain. Any deviation triggers DEFCON escalation.

    Integration Points:
        - DefconController  — escalates on conservation violations
        - ForensicLogger    — logs violations to immutable evidence chain
        - QuaketeEngine     — provides energy transfer events
        - Hive event bus    — publishes conservation events

    Usage::

        ledger = ConservationLedgerAudit(
            initial_total_energy=1000.0,
            db_pool=pool,
        )
        await ledger.start_verification_loop()

        # Record a transfer
        await ledger.record_transfer(source_id, dest_id, 50.0)

        # Manual verification
        is_valid = await ledger.verify_conservation()

    Patent-Pending — Claims 30-56
    """

    def __init__(
        self,
        initial_total_energy: float = 0.0,
        db_pool=None,
        event_callback: Optional[Callable[[str, Dict[str, Any]], Coroutine]] = None,
        forensic_logger=None,
        defcon_controller=None,
    ) -> None:
        """
        Initialize the Conservation Ledger Audit.

        Args:
            initial_total_energy: The total system energy constant, established
                                  at hive initialization. All subsequent transfers
                                  must preserve this exact value.
            db_pool:              asyncpg connection pool for persistence.
            event_callback:       Async callback ``(topic, payload) -> None`` for
                                  broadcasting events to the hive event bus.
            forensic_logger:      ForensicLogger instance for immutable evidence.
            defcon_controller:    DefconController for escalation on violations.
        """
        self._db_pool = db_pool
        self._event_callback = event_callback
        self._forensic_logger = forensic_logger
        self._defcon_controller = defcon_controller

        # The conservation constant
        self._total_energy_constant: float = initial_total_energy

        # Per-entity energy balances
        self._balances: Dict[UUID, float] = {}

        # Immutable transfer chain (in-memory ring buffer)
        self._ledger: Deque[TransferRecord] = deque(maxlen=MAX_MEMORY_ENTRIES)
        self._chain_head_hash: str = hashlib.sha256(b"genesis").hexdigest()

        # Verification state
        self._last_verification: Optional[datetime] = None
        self._violations_detected: int = 0
        self._verification_count: int = 0
        self._verification_task: Optional[asyncio.Task] = None

        # Running ledger state hash (verified every 60s)
        self._ledger_state_hash: str = self._chain_head_hash

        logger.info(
            "ConservationLedgerAudit initialized — "
            "total_energy_constant=%.6f, genesis_hash=%s…",
            self._total_energy_constant,
            self._chain_head_hash[:16],
        )

    # =========================================================================
    # ENERGY BALANCE MANAGEMENT
    # =========================================================================

    async def set_initial_balance(self, entity_id: UUID, balance: float) -> None:
        """
        Set the initial energy balance for an entity.

        This should be called during hive initialization to distribute the
        total energy constant across entities.

        Args:
            entity_id: UUID of the entity.
            balance:   Initial energy balance.
        """
        self._balances[entity_id] = balance
        logger.debug(
            "Initial balance set: entity=%s balance=%.6f",
            entity_id, balance,
        )

    def get_entity_balance(self, entity_id: UUID) -> float:
        """
        Return the current energy balance for an entity.

        Args:
            entity_id: UUID of the entity.

        Returns:
            Current energy balance, or 0.0 if entity is unknown.
        """
        return self._balances.get(entity_id, 0.0)

    # =========================================================================
    # TRANSFER RECORDING
    # =========================================================================

    async def record_transfer(
        self,
        source_id: UUID,
        dest_id: UUID,
        amount: float,
    ) -> TransferRecord:
        """
        Record an energy transfer between two entities.

        The transfer is appended to the immutable hash chain and balances
        are updated. If the resulting system total violates conservation,
        the transfer is still recorded (for forensic evidence) but a
        DEFCON escalation is triggered.

        Args:
            source_id: UUID of the source entity (loses energy).
            dest_id:   UUID of the destination entity (gains energy).
            amount:    Amount of energy to transfer (must be positive).

        Returns:
            The TransferRecord appended to the ledger.

        Raises:
            ValueError: If amount is not positive.
        """
        if amount <= 0:
            raise ValueError(
                f"Transfer amount must be positive, got {amount}"
            )

        # Create the transfer record and chain it
        record = TransferRecord(
            source_id=source_id,
            dest_id=dest_id,
            amount=amount,
        )
        record.compute_hash(self._chain_head_hash)
        self._chain_head_hash = record.record_hash

        # Update balances
        self._balances.setdefault(source_id, 0.0)
        self._balances.setdefault(dest_id, 0.0)
        self._balances[source_id] -= amount
        self._balances[dest_id] += amount

        # Append to ledger
        self._ledger.append(record)

        # Update running ledger state hash
        state_data = f"{self._ledger_state_hash}:{record.record_hash}"
        self._ledger_state_hash = hashlib.sha256(state_data.encode()).hexdigest()

        logger.debug(
            "Transfer recorded: %s → %s amount=%.6f chain=%s…",
            source_id, dest_id, amount, record.record_hash[:16],
        )

        # Persist to database
        await self._persist_transfer(record)

        # Check conservation immediately after transfer
        current_total = sum(self._balances.values())
        deviation = abs(current_total - self._total_energy_constant)
        if deviation > CONSERVATION_EPSILON:
            await self._handle_violation(
                current_total=current_total,
                trigger_transfer=record,
            )

        return record

    # =========================================================================
    # CONSERVATION VERIFICATION
    # =========================================================================

    async def verify_conservation(self) -> bool:
        """
        Verify that total system energy matches the conservation constant.

        Recomputes the sum of all entity balances and compares against the
        established constant. Any deviation (beyond floating-point epsilon)
        constitutes a violation.

        Returns:
            True if conservation holds, False if violation detected.
        """
        current_total = sum(self._balances.values())
        deviation = abs(current_total - self._total_energy_constant)

        self._verification_count += 1
        self._last_verification = datetime.utcnow()

        if deviation > CONSERVATION_EPSILON:
            await self._handle_violation(current_total=current_total)
            return False

        logger.debug(
            "Conservation verified OK — total=%.6f expected=%.6f "
            "deviation=%.2e (check #%d)",
            current_total,
            self._total_energy_constant,
            deviation,
            self._verification_count,
        )
        return True

    async def verify_chain_integrity(self) -> bool:
        """
        Verify the integrity of the transfer hash chain.

        Recomputes hashes from the genesis block and compares each record's
        stored hash against the recomputed value.

        Returns:
            True if the chain is intact, False if tampering detected.
        """
        previous_hash = hashlib.sha256(b"genesis").hexdigest()

        for record in self._ledger:
            data = (
                f"{record.transfer_id}:{record.source_id}:{record.dest_id}:"
                f"{record.amount:.15f}:{record.timestamp.isoformat()}:"
                f"{previous_hash}"
            )
            expected_hash = hashlib.sha256(data.encode()).hexdigest()

            if expected_hash != record.record_hash:
                logger.critical(
                    "CHAIN INTEGRITY VIOLATION at transfer %s — "
                    "expected=%s… got=%s…",
                    record.transfer_id,
                    expected_hash[:16],
                    record.record_hash[:16],
                )
                return False

            previous_hash = record.record_hash

        logger.debug(
            "Chain integrity verified — %d records, head=%s…",
            len(self._ledger), self._chain_head_hash[:16],
        )
        return True

    # =========================================================================
    # LEDGER STATE
    # =========================================================================

    async def get_ledger_state(self) -> ConservationLedgerEntry:
        """
        Return the current ledger state as a Pydantic model.

        Returns:
            ConservationLedgerEntry with current total, hash, and violation count.
        """
        current_total = sum(self._balances.values())
        deviation = abs(current_total - self._total_energy_constant)

        return ConservationLedgerEntry(
            total_system_energy=current_total,
            ledger_state_hash=self._ledger_state_hash,
            verified_at=self._last_verification or datetime.utcnow(),
            violations_detected=self._violations_detected,
            is_valid=deviation <= CONSERVATION_EPSILON,
        )

    # =========================================================================
    # VERIFICATION LOOP
    # =========================================================================

    async def start_verification_loop(self) -> None:
        """
        Start the background conservation verification loop.

        Runs every ``VERIFICATION_INTERVAL_SEC`` seconds (default 60).
        Verifies both the energy total and the hash chain integrity.
        """
        if self._verification_task is not None:
            logger.warning("Verification loop already running")
            return

        self._verification_task = asyncio.create_task(
            self._verification_loop()
        )
        logger.info(
            "Conservation verification loop started (interval=%.0fs)",
            VERIFICATION_INTERVAL_SEC,
        )

    async def stop_verification_loop(self) -> None:
        """Stop the background verification loop."""
        if self._verification_task:
            self._verification_task.cancel()
            try:
                await self._verification_task
            except asyncio.CancelledError:
                pass
            self._verification_task = None
            logger.info("Conservation verification loop stopped")

    async def _verification_loop(self) -> None:
        """Internal verification loop coroutine."""
        while True:
            try:
                await asyncio.sleep(VERIFICATION_INTERVAL_SEC)

                # Verify conservation
                conservation_ok = await self.verify_conservation()

                # Verify chain integrity
                chain_ok = await self.verify_chain_integrity()

                if not conservation_ok or not chain_ok:
                    logger.critical(
                        "PERIODIC VERIFICATION FAILED — "
                        "conservation=%s chain=%s",
                        conservation_ok, chain_ok,
                    )

            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.error(
                    "Conservation verification loop error: %s", exc,
                )
                await asyncio.sleep(5.0)

    # =========================================================================
    # VIOLATION HANDLING
    # =========================================================================

    async def _handle_violation(
        self,
        current_total: float,
        trigger_transfer: Optional[TransferRecord] = None,
    ) -> None:
        """
        Handle a conservation law violation.

        This is an absolute indicator of compromise — there are no false
        positives for conservation violations.

        Args:
            current_total:     The observed system total.
            trigger_transfer:  The transfer that triggered detection (if any).
        """
        self._violations_detected += 1
        deviation = current_total - self._total_energy_constant

        logger.critical(
            "⚠ CONSERVATION VIOLATION #%d — "
            "expected=%.6f actual=%.6f deviation=%.6e",
            self._violations_detected,
            self._total_energy_constant,
            current_total,
            deviation,
        )

        # Build forensic evidence
        evidence: Dict[str, Any] = {
            "expected_total": self._total_energy_constant,
            "actual_total": current_total,
            "deviation": deviation,
            "violation_number": self._violations_detected,
            "ledger_size": len(self._ledger),
            "chain_head_hash": self._chain_head_hash,
        }

        if trigger_transfer:
            evidence["trigger_transfer"] = {
                "transfer_id": str(trigger_transfer.transfer_id),
                "source_id": str(trigger_transfer.source_id),
                "dest_id": str(trigger_transfer.dest_id),
                "amount": trigger_transfer.amount,
                "record_hash": trigger_transfer.record_hash,
            }

        # Log to forensic chain
        if self._forensic_logger:
            try:
                await self._forensic_logger.log_event(
                    event_type="conservation_violation",
                    evidence=evidence,
                )
            except Exception as exc:
                logger.error("Forensic log failed: %s", exc)

        # Escalate DEFCON
        if self._defcon_controller:
            try:
                await self._defcon_controller.escalate(
                    DefconLevel.SEVERE,
                    f"Conservation law violated — deviation={deviation:.6e}",
                )
            except Exception as exc:
                logger.error("DEFCON escalation failed: %s", exc)

        # Broadcast event
        await self._broadcast_event(
            "hive.conservation.violation",
            {
                "deviation": deviation,
                "expected_total": self._total_energy_constant,
                "actual_total": current_total,
                "violation_count": self._violations_detected,
                "timestamp": datetime.utcnow().isoformat(),
            },
        )

    # =========================================================================
    # ADMIN
    # =========================================================================

    def summary(self) -> Dict[str, Any]:
        """Return a summary dict for admin dashboards."""
        current_total = sum(self._balances.values())
        return {
            "total_energy_constant": self._total_energy_constant,
            "current_total": current_total,
            "deviation": abs(current_total - self._total_energy_constant),
            "is_conserved": abs(current_total - self._total_energy_constant)
            <= CONSERVATION_EPSILON,
            "ledger_size": len(self._ledger),
            "chain_head_hash": self._chain_head_hash[:16] + "…",
            "verification_count": self._verification_count,
            "violations_detected": self._violations_detected,
            "last_verification": (
                self._last_verification.isoformat()
                if self._last_verification
                else None
            ),
            "entity_count": len(self._balances),
        }

    # =========================================================================
    # PERSISTENCE
    # =========================================================================

    async def _persist_transfer(self, record: TransferRecord) -> None:
        """Persist a transfer record to the database."""
        if not self._db_pool:
            return

        try:
            async with self._db_pool.acquire() as conn:
                await conn.execute(
                    """
                    INSERT INTO conservation_ledger (
                        transfer_id, source_id, dest_id, amount,
                        record_hash, previous_hash, created_at
                    ) VALUES ($1, $2, $3, $4, $5, $6, $7)
                    """,
                    record.transfer_id,
                    record.source_id,
                    record.dest_id,
                    record.amount,
                    record.record_hash,
                    record.previous_hash,
                    record.timestamp,
                )
        except Exception as exc:
            logger.error(
                "Failed to persist transfer %s: %s",
                record.transfer_id, exc,
            )

    async def load_from_db(self) -> int:
        """
        Load the ledger from the database on startup.

        Returns:
            Number of transfer records loaded.
        """
        if not self._db_pool:
            return 0

        try:
            async with self._db_pool.acquire() as conn:
                rows = await conn.fetch(
                    """
                    SELECT transfer_id, source_id, dest_id, amount,
                           record_hash, previous_hash, created_at
                    FROM conservation_ledger
                    ORDER BY created_at ASC
                    """
                )

            loaded = 0
            for row in rows:
                record = TransferRecord(
                    transfer_id=row["transfer_id"],
                    source_id=row["source_id"],
                    dest_id=row["dest_id"],
                    amount=row["amount"],
                    record_hash=row["record_hash"] or "",
                    previous_hash=row["previous_hash"] or "",
                    timestamp=row["created_at"],
                )
                self._ledger.append(record)
                self._chain_head_hash = record.record_hash

                # Rebuild balances
                self._balances.setdefault(record.source_id, 0.0)
                self._balances.setdefault(record.dest_id, 0.0)
                self._balances[record.source_id] -= record.amount
                self._balances[record.dest_id] += record.amount

                loaded += 1

            logger.info(
                "Loaded %d conservation ledger records from database", loaded,
            )
            return loaded

        except Exception as exc:
            logger.error("Failed to load conservation ledger: %s", exc)
            return 0

    # =========================================================================
    # EVENT BUS
    # =========================================================================

    async def _broadcast_event(
        self,
        topic: str,
        payload: Dict[str, Any],
    ) -> None:
        """Broadcast an event via the registered callback."""
        if self._event_callback:
            try:
                await self._event_callback(topic, payload)
            except Exception as exc:
                logger.error(
                    "Event callback failed for topic %s: %s", topic, exc,
                )
