"""
ZEFCP Environment Inference — BLE density classification.
Patent Claim 25: Zero-Energy BLE Communication — Infer environment type
from transport metadata (handshakes per minute) for adaptive scheduling
and redundancy tuning.
"""

from __future__ import annotations

from collections import deque
from typing import Dict, List

from app.services.zefcp.constants import (
    DENSITY_CLINIC,
    DENSITY_RURAL,
    DENSITY_SUBURBAN,
    DENSITY_URBAN_DENSE,
    DENSITY_URBAN_STANDARD,
)


# =============================================================================
# ENVIRONMENT INFERENCE
# =============================================================================

# Rolling window size for density averaging
DENSITY_HISTORY_SIZE = 30


class EnvironmentInference:
    """
    Infers environment classification from BLE handshake density.
    Patent Claim 25: Uses transport metadata (handshakes/minute) to classify
    urban_dense, urban_standard, suburban, clinic, rural, or unknown.
    """

    def __init__(self) -> None:
        """Initialize with empty density history per endpoint."""
        self._density_history: Dict[str, deque[float]] = {}

    def record_density(self, endpoint_id: str, handshakes_per_minute: float) -> None:
        """
        Record a density observation for an endpoint.

        Args:
            endpoint_id: Spider Web endpoint identifier.
            handshakes_per_minute: BLE handshakes per minute from transport metadata.
        """
        if endpoint_id not in self._density_history:
            self._density_history[endpoint_id] = deque(maxlen=DENSITY_HISTORY_SIZE)
        self._density_history[endpoint_id].append(handshakes_per_minute)

    def classify_environment(self, endpoint_id: str) -> str:
        """
        Classify environment based on average density over recent history.
        Patent Claim 25. Uses thresholds from constants.py.

        Returns:
            One of: "urban_dense", "urban_standard", "suburban", "clinic",
            "rural", or "unknown".
        """
        avg = self.get_avg_density(endpoint_id)
        if avg < 0:
            return "unknown"

        if avg >= DENSITY_URBAN_DENSE:
            return "urban_dense"
        if avg >= DENSITY_URBAN_STANDARD:
            return "urban_standard"
        if avg >= DENSITY_SUBURBAN:
            return "suburban"
        if avg >= DENSITY_CLINIC:
            return "clinic"
        if avg >= DENSITY_RURAL:
            return "rural"

        return "rural"

    def get_avg_density(self, endpoint_id: str) -> float:
        """
        Get average handshakes/minute over recent history for an endpoint.

        Returns:
            Average density, or -1.0 if no data.
        """
        history = self._density_history.get(endpoint_id)
        if not history:
            return -1.0
        return sum(history) / len(history)
