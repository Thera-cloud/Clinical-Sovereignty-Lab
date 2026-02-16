"""
HIVE DEFENSE PROTOCOL v3.0 — Conservation Audit Worker (Phase 8C)
Continuous verification of Quakete energy conservation invariant.

Runs every 60 seconds and verifies that total system energy is conserved
according to the Quakete ledger.  In the Quakete framework, emotional
energy is neither created nor destroyed — it is transformed and transferred.
Any discrepancy between the expected total and the actual ledger state
indicates either a bug or a manipulation attempt.

When a conservation violation is detected:
    - Fire ``hive.conservation.violation`` event
    - Log full forensic record of the discrepancy
    - Flag the ledger entries involved for manual review

Patent-Pending — Claims 30-56
© 2026 Clinical Sovereignty Lab. All rights reserved.
"""

from __future__ import annotations

import asyncio
import hashlib
import math
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from uuid import UUID, uuid4

import structlog

from app.models.hive_defense import ConservationLedgerEntry

logger = structlog.get_logger("hive.conservation_audit")


# =============================================================================
# CONSTANTS
# =============================================================================

# Default audit interval (seconds)
DEFAULT_INTERVAL: float = 60.0

# DEFCON → interval mapping
DEFCON_INTERVAL_MAP: Dict[int, float] = {
    5: 60.0,    # PEACE — every minute
    4: 45.0,    # ELEVATED — tighter
    3: 30.0,    # SUBSTANTIAL — aggressive
    2: 15.0,    # SEVERE — near real-time
    1: 5.0,     # CRITICAL — maximum vigilance
}

# Tolerance for floating-point energy comparison
ENERGY_TOLERANCE: float = 1e-6

# Maximum acceptable drift from initial energy constant
MAX_ENERGY_DRIFT_PERCENT: float = 0.001  # 0.001%


# =============================================================================
# CONSERVATION AUDIT WORKER
# =============================================================================

class ConservationAuditWorker:
    """Background worker: continuous Quakete energy conservation verification.

    Responsibilities
    ----------------
    * Query the Quakete ledger for total system energy.
    * Compare against the expected conservation constant.
    * Detect any creation or destruction of energy.
    * Compute a cryptographic hash of the ledger state.
    * Fire ``hive.conservation.violation`` on any discrepancy.
    * Persist audit records for compliance and forensics.

    Parameters
    ----------
    db_pool : Any, optional
        asyncpg connection pool for ledger queries and audit persistence.
    event_callback : callable, optional
        Async callback ``(topic: str, payload: dict) -> None``.
    defcon_provider : callable, optional
        Async callable returning the current DEFCON level (int 1-5).
    base_interval : float
        Default audit interval in seconds.
    initial_energy_constant : float, optional
        The total system energy constant established at genesis.
        If None, derived from the first audit.
    """

    def __init__(
        self,
        db_pool: Any = None,
        event_callback: Optional[Any] = None,
        defcon_provider: Optional[Any] = None,
        base_interval: float = DEFAULT_INTERVAL,
        initial_energy_constant: Optional[float] = None,
    ) -> None:
        self.db_pool = db_pool
        self.event_callback = event_callback
        self.defcon_provider = defcon_provider
        self.base_interval = base_interval

        # The immutable energy constant (set at genesis or first audit)
        self._energy_constant: Optional[float] = initial_energy_constant

        self._task: Optional[asyncio.Task] = None
        self._running: bool = False

        # Cumulative metrics
        self._total_audits: int = 0
        self._total_violations: int = 0
        self._total_valid: int = 0
        self._last_audit_at: Optional[datetime] = None
        self._last_energy_reading: Optional[float] = None
        self._last_ledger_hash: Optional[str] = None

        # Consecutive violation tracking
        self._consecutive_violations: int = 0

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Start the conservation audit loop."""
        self._running = True
        self._task = asyncio.create_task(self._run_loop())
        logger.info(
            "worker_started",
            worker="ConservationAuditWorker",
            energy_constant=self._energy_constant,
        )

    async def stop(self) -> None:
        """Gracefully stop the audit loop."""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info(
            "worker_stopped",
            worker="ConservationAuditWorker",
            total_audits=self._total_audits,
            total_violations=self._total_violations,
        )

    # ------------------------------------------------------------------
    # Main Loop
    # ------------------------------------------------------------------

    async def _run_loop(self) -> None:
        """Primary loop: audit conservation at DEFCON-adjusted intervals."""
        while self._running:
            cycle_start = time.monotonic()
            try:
                await self._audit_conservation()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.error(
                    "conservation_audit_error",
                    error=str(exc),
                    exc_info=True,
                )

            interval = await self._current_interval()
            elapsed = time.monotonic() - cycle_start
            sleep_time = max(0.0, interval - elapsed)
            await asyncio.sleep(sleep_time)

    # ------------------------------------------------------------------
    # Audit Logic
    # ------------------------------------------------------------------

    async def _audit_conservation(self) -> None:
        """Execute one conservation audit cycle.

        Steps:
        1. Query total system energy from Quakete ledger.
        2. Compute ledger state hash for integrity chain.
        3. Compare against the energy constant.
        4. Fire violation event if discrepancy found.
        5. Persist audit record.
        """
        self._total_audits += 1
        self._last_audit_at = datetime.now(timezone.utc)

        # Step 1: Query total energy
        energy_data = await self._query_total_energy()
        if energy_data is None:
            logger.debug("conservation_audit_skipped reason=no_energy_data")
            return

        total_energy = energy_data["total_energy"]
        ledger_entries = energy_data.get("entry_count", 0)
        self._last_energy_reading = total_energy

        # Step 2: Compute ledger hash
        ledger_hash = self._compute_ledger_hash(energy_data)
        self._last_ledger_hash = ledger_hash

        # Step 3: Establish or compare constant
        if self._energy_constant is None:
            # First audit — establish the constant
            self._energy_constant = total_energy
            logger.info(
                "conservation_constant_established",
                energy_constant=self._energy_constant,
                ledger_entries=ledger_entries,
            )

        # Step 4: Compare
        is_valid = self._is_energy_conserved(total_energy)
        violations_found = 0

        if is_valid:
            self._total_valid += 1
            self._consecutive_violations = 0
        else:
            violations_found = 1
            self._total_violations += 1
            self._consecutive_violations += 1

            drift = abs(total_energy - self._energy_constant)
            drift_pct = (drift / abs(self._energy_constant)) * 100 if self._energy_constant else 0

            logger.critical(
                "CONSERVATION_VIOLATION",
                expected=self._energy_constant,
                actual=total_energy,
                drift=drift,
                drift_pct=round(drift_pct, 6),
                consecutive=self._consecutive_violations,
            )

            # Fire violation event
            await self._fire_violation_event(
                total_energy=total_energy,
                expected=self._energy_constant,
                drift=drift,
                drift_pct=drift_pct,
                ledger_hash=ledger_hash,
            )

        # Step 5: Persist audit record
        entry = ConservationLedgerEntry(
            total_system_energy=total_energy,
            ledger_state_hash=ledger_hash,
            violations_detected=violations_found,
            is_valid=is_valid,
        )
        await self._persist_audit_record(entry)

        # Periodic status log
        if self._total_audits % 60 == 0:  # Every ~1 hour at 60s interval
            logger.info(
                "conservation_audit_status",
                audit_number=self._total_audits,
                energy_constant=self._energy_constant,
                current_energy=total_energy,
                total_violations=self._total_violations,
                ledger_hash=ledger_hash[:16],
            )

    # ------------------------------------------------------------------
    # Energy Queries
    # ------------------------------------------------------------------

    async def _query_total_energy(self) -> Optional[Dict[str, Any]]:
        """Query the Quakete ledger for total system energy.

        Returns
        -------
        dict or None
            ``total_energy`` (float), ``entry_count`` (int),
            ``ledger_data`` (list) for hash computation.
        """
        if not self.db_pool:
            return None

        try:
            async with self.db_pool.acquire() as conn:
                # Sum all energy across the Quakete system
                row = await conn.fetchrow(
                    """
                    SELECT
                        COALESCE(SUM(energy_amount), 0.0) as total_energy,
                        COUNT(*) as entry_count
                    FROM quakete_energy_ledger
                    WHERE active = true
                    """
                )

                if not row:
                    return None

                # Also fetch recent entries for hash computation
                recent = await conn.fetch(
                    """
                    SELECT ledger_id, entity_id, energy_amount,
                           transaction_type, created_at
                    FROM quakete_energy_ledger
                    WHERE active = true
                    ORDER BY created_at DESC
                    LIMIT 1000
                    """
                )

                return {
                    "total_energy": float(row["total_energy"]),
                    "entry_count": int(row["entry_count"]),
                    "ledger_data": [dict(r) for r in recent],
                }

        except Exception as exc:
            logger.warning("energy_query_failed", error=str(exc))
            return None

    # ------------------------------------------------------------------
    # Conservation Check
    # ------------------------------------------------------------------

    def _is_energy_conserved(self, total_energy: float) -> bool:
        """
        Check if total energy matches the conservation constant.

        Uses both absolute tolerance (for near-zero values) and
        relative tolerance (for large values) to account for
        floating-point precision.

        Parameters
        ----------
        total_energy : float
            Current total system energy.

        Returns
        -------
        bool
            True if energy is conserved within tolerance.
        """
        if self._energy_constant is None:
            return True

        # Absolute check
        if abs(total_energy - self._energy_constant) <= ENERGY_TOLERANCE:
            return True

        # Relative check
        if self._energy_constant != 0:
            drift_pct = abs(
                (total_energy - self._energy_constant) / self._energy_constant
            ) * 100
            return drift_pct <= MAX_ENERGY_DRIFT_PERCENT

        return math.isclose(
            total_energy,
            self._energy_constant,
            rel_tol=1e-9,
            abs_tol=ENERGY_TOLERANCE,
        )

    # ------------------------------------------------------------------
    # Ledger Hash
    # ------------------------------------------------------------------

    @staticmethod
    def _compute_ledger_hash(energy_data: Dict[str, Any]) -> str:
        """
        Compute a SHA-256 hash of the current ledger state.

        This creates an immutable fingerprint of the ledger that
        can be compared across audit cycles to detect tampering.
        """
        ledger_entries = energy_data.get("ledger_data", [])
        hash_input = ""
        for entry in ledger_entries:
            hash_input += (
                f"{entry.get('ledger_id', '')}:"
                f"{entry.get('entity_id', '')}:"
                f"{entry.get('energy_amount', 0)}:"
                f"{entry.get('transaction_type', '')}:"
                f"{entry.get('created_at', '')}|"
            )
        hash_input += f"total:{energy_data.get('total_energy', 0)}"
        return hashlib.sha256(hash_input.encode()).hexdigest()

    # ------------------------------------------------------------------
    # Violation Events
    # ------------------------------------------------------------------

    async def _fire_violation_event(
        self,
        total_energy: float,
        expected: float,
        drift: float,
        drift_pct: float,
        ledger_hash: str,
    ) -> None:
        """Fire a hive.conservation.violation event."""
        payload = {
            "total_energy": total_energy,
            "expected_constant": expected,
            "drift": drift,
            "drift_pct": round(drift_pct, 6),
            "ledger_hash": ledger_hash,
            "consecutive_violations": self._consecutive_violations,
            "audit_number": self._total_audits,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

        logger.critical(
            "CONSERVATION_VIOLATION_EVENT",
            drift=drift,
            drift_pct=round(drift_pct, 6),
            consecutive=self._consecutive_violations,
        )

        if self.event_callback:
            try:
                await self.event_callback("hive.conservation.violation", payload)
            except Exception as exc:
                logger.error("conservation_event_failed", error=str(exc))

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    async def _persist_audit_record(self, entry: ConservationLedgerEntry) -> None:
        """Persist an audit record to the database."""
        if not self.db_pool:
            return

        try:
            async with self.db_pool.acquire() as conn:
                await conn.execute(
                    """
                    INSERT INTO hive_conservation_audits (
                        entry_id, total_system_energy, ledger_state_hash,
                        violations_detected, is_valid, verified_at
                    ) VALUES ($1, $2, $3, $4, $5, $6)
                    """,
                    entry.entry_id,
                    entry.total_system_energy,
                    entry.ledger_state_hash,
                    entry.violations_detected,
                    entry.is_valid,
                    entry.verified_at,
                )
        except Exception as exc:
            logger.debug("conservation_audit_persist_failed", error=str(exc))

    # ------------------------------------------------------------------
    # DEFCON-aware interval
    # ------------------------------------------------------------------

    async def _current_interval(self) -> float:
        """Return the audit interval adjusted for DEFCON level."""
        if self.defcon_provider:
            try:
                level = await self.defcon_provider()
                level_int = int(level.value) if hasattr(level, "value") else int(level)
                return DEFCON_INTERVAL_MAP.get(level_int, self.base_interval)
            except Exception:
                pass
        return self.base_interval

    # ------------------------------------------------------------------
    # Diagnostics
    # ------------------------------------------------------------------

    @property
    def stats(self) -> Dict[str, Any]:
        """Diagnostic statistics."""
        return {
            "running": self._running,
            "total_audits": self._total_audits,
            "total_violations": self._total_violations,
            "total_valid": self._total_valid,
            "consecutive_violations": self._consecutive_violations,
            "energy_constant": self._energy_constant,
            "last_energy_reading": self._last_energy_reading,
            "last_ledger_hash": (
                self._last_ledger_hash[:16] if self._last_ledger_hash else None
            ),
            "last_audit_at": (
                self._last_audit_at.isoformat() if self._last_audit_at else None
            ),
        }

    def __repr__(self) -> str:
        return (
            f"<ConservationAuditWorker "
            f"audits={self._total_audits} "
            f"violations={self._total_violations} "
            f"energy={self._last_energy_reading}>"
        )
