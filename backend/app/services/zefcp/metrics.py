"""
ZEFCP Metrics — Transport performance monitoring.
Patent Claim 25: Zero-Energy BLE Communication — Track detection,
assembly, and forwarding metrics for The Eye dashboard.
"""

from __future__ import annotations

import time
from collections import defaultdict
from datetime import datetime
from typing import Any, Dict, List, Optional

from app.models.zefcp import TransportMetrics


# =============================================================================
# ZEFCP METRICS
# =============================================================================


class ZEFCPMetrics:
    """
    Transport performance monitoring for ZEFCP endpoints.
    Patent Claim 25: Records detection, assembly, and forwarding events;
    aggregates into TransportMetrics for reporting.
    """

    def __init__(self, endpoint_id: str) -> None:
        """
        Initialize metrics for an endpoint.

        Args:
            endpoint_id: Spider Web endpoint identifier.
        """
        self._endpoint_id = endpoint_id
        self._counters: Dict[str, int] = defaultdict(int)
        self._assembly_times: List[float] = []
        self._assembly_fragment_counts: List[int] = []
        self._assembly_loss_rates: List[float] = []
        # Counter-intelligence: device-aware tracking
        self._device_false_positives: Dict[str, int] = defaultdict(int)
        self._device_failure_history: List[Dict[str, Any]] = []

    def record_pdu_scanned(self) -> None:
        """Record one BLE PDU scanned."""
        self._counters["total_ble_pdus_scanned"] += 1

    def record_signature_match(self) -> None:
        """Record one signature match (candidate fragment)."""
        self._counters["signature_matches"] += 1

    def record_crc_valid(self) -> None:
        """Record one CRC-validated fragment."""
        self._counters["crc_validated"] += 1

    def record_false_positive(
        self, source_device: Optional[str] = None,
    ) -> None:
        """Record one false positive discarded, optionally with source device."""
        self._counters["false_positives_discarded"] += 1
        if source_device:
            self._device_false_positives[source_device] = (
                self._device_false_positives.get(source_device, 0) + 1
            )

    def record_detection_failure(
        self,
        failure_type: str,
        source_device: Optional[str] = None,
        signature_guess: Optional[int] = None,
    ) -> None:
        """Record a detection failure with full device context."""
        self._counters["detection_failures"] += 1
        if source_device:
            key = f"{source_device}:{failure_type}"
            self._device_failure_history.append({
                "device": source_device,
                "type": failure_type,
                "signature_guess": signature_guess,
                "timestamp": time.time(),
            })
            # Trim to last 1000 entries
            if len(self._device_failure_history) > 1000:
                self._device_failure_history = self._device_failure_history[-500:]

    def record_fragment_detected(self) -> None:
        """Record one valid fragment detected."""
        self._counters["valid_fragments_detected"] += 1

    def record_observation_complete(
        self,
        assembly_time: float,
        fragment_count: int,
        loss_rate: float,
    ) -> None:
        """
        Record one completed observation assembly.

        Args:
            assembly_time: Assembly duration in seconds.
            fragment_count: Total fragments in the observation.
            loss_rate: Fraction of fragments lost (0.0–1.0).
        """
        self._counters["observations_completed"] += 1
        self._assembly_times.append(assembly_time)
        self._assembly_fragment_counts.append(fragment_count)
        self._assembly_loss_rates.append(loss_rate)

    def record_observation_expired(self) -> None:
        """Record one observation that expired without completion."""
        self._counters["observations_expired"] += 1

    def get_metrics(
        self,
        period_start: datetime,
        period_end: datetime,
    ) -> TransportMetrics:
        """
        Return TransportMetrics populated from counters within the period.
        Patent Claim 25.
        """
        # For simplicity we use all recorded data; time filtering would require
        # storing timestamps per event — deferred for full implementation
        n_completed = self._counters["observations_completed"]
        avg_assembly = (
            sum(self._assembly_times) / n_completed
            if n_completed > 0
            else 0.0
        )
        avg_fragments = (
            sum(self._assembly_fragment_counts) / n_completed
            if n_completed > 0
            else 0.0
        )
        avg_loss = (
            sum(self._assembly_loss_rates) / n_completed
            if n_completed > 0
            else 0.0
        )

        return TransportMetrics(
            endpoint_id=self._endpoint_id,
            period_start=period_start,
            period_end=period_end,
            total_ble_pdus_scanned=self._counters["total_ble_pdus_scanned"],
            signature_matches=self._counters["signature_matches"],
            crc_validated=self._counters["crc_validated"],
            false_positives_discarded=self._counters["false_positives_discarded"],
            valid_fragments_detected=self._counters["valid_fragments_detected"],
            observations_completed=self._counters["observations_completed"],
            observations_expired=self._counters["observations_expired"],
            avg_assembly_time_seconds=avg_assembly,
            avg_fragments_per_observation=avg_fragments,
            avg_fragment_loss_rate=avg_loss,
        )

    def reset(self) -> None:
        """Reset all counters and assembly data."""
        self._counters.clear()
        self._assembly_times.clear()
        self._assembly_fragment_counts.clear()
        self._assembly_loss_rates.clear()
