"""
SOVEREIGN SWARM — Quakete Metrics (Patent Claim 26)
Ring health, transfer events, rescue outcomes.
"""

from __future__ import annotations

from collections import defaultdict

import structlog

from app.models.quakete import Memorial, QuaketeTransferResult


# =============================================================================
# QUAKETE METRICS
# =============================================================================


class QuaketeMetrics:
    """
    Tracks Quakete protocol events: transfers, ring events, memorials, ramp-ups.
    """

    def __init__(self) -> None:
        self._total_transfers = 0
        self._successful_transfers = 0
        self._total_ions = 0
        self._total_energy: float = 0.0
        self._ring_events: dict[str, int] = defaultdict(int)
        self._memorials_count = 0
        self._ramp_ups: dict[str, int] = {}  # fibre_id -> observations_saved
        self._log = structlog.get_logger()

    # -------------------------------------------------------------------------
    # RECORDING
    # -------------------------------------------------------------------------

    def record_transfer(self, result: QuaketeTransferResult) -> None:
        """Record a transfer result."""
        self._total_transfers += 1
        if result.success:
            self._successful_transfers += 1
            self._total_ions += result.ions_transferred
            self._total_energy += result.total_energy
        self._log.debug(
            "metrics_transfer_recorded",
            success=result.success,
            ions=result.ions_transferred,
        )

    def record_ring_event(self, ring_id: str, event_type: str) -> None:
        """Record a ring event (e.g. 'supporting', 'rescue', 'strained')."""
        key = f"{ring_id}:{event_type}"
        self._ring_events[key] += 1

    def record_memorial(self, memorial: Memorial) -> None:
        """Record a memorial creation."""
        self._memorials_count += 1

    def record_ramp_up(self, fibre_id: str, observations_saved: int) -> None:
        """Record a ramp-up completion with observations saved."""
        self._ramp_ups[fibre_id] = observations_saved

    # -------------------------------------------------------------------------
    # SUMMARY & RESET
    # -------------------------------------------------------------------------

    def get_summary(self) -> dict:
        """
        Return dict with all metrics:
        total_transfers, successful_transfers, total_ions, total_energy,
        ring_events, memorials, ramp_ups.
        """
        return {
            "total_transfers": self._total_transfers,
            "successful_transfers": self._successful_transfers,
            "total_ions": self._total_ions,
            "total_energy": self._total_energy,
            "ring_events": dict(self._ring_events),
            "memorials": self._memorials_count,
            "ramp_ups": dict(self._ramp_ups),
        }

    def reset(self) -> None:
        """Reset all counters."""
        self._total_transfers = 0
        self._successful_transfers = 0
        self._total_ions = 0
        self._total_energy = 0.0
        self._ring_events = DefaultDict(int)
        self._memorials_count = 0
        self._ramp_ups = {}
