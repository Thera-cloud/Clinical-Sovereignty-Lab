"""
ZEFCP — Adaptive Redundancy Tuning
Patent Claim 25.4: Dynamic Reed-Solomon FEC adjustment based on
historical fragment arrival rates at each endpoint environment.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict

from app.services.zefcp.constants import (
    DEFAULT_REDUNDANCY_FACTOR,
    MIN_REDUNDANCY_FACTOR,
    MAX_REDUNDANCY_FACTOR,
)


# =============================================================================
# ARRIVAL STATISTICS
# =============================================================================

@dataclass
class ArrivalStats:
    """Track fragment arrival statistics for a given environment."""
    sample_count: int = 0
    total_expected: int = 0
    total_received: int = 0

    @property
    def arrival_rate(self) -> float:
        """Proportion of expected fragments that actually arrived."""
        if self.total_expected == 0:
            return 1.0
        return self.total_received / self.total_expected


# =============================================================================
# ADAPTIVE REDUNDANCY ENGINE
# =============================================================================

class AdaptiveRedundancy:
    """
    Monitors fragment arrival statistics at each endpoint
    and adjusts redundancy levels for outgoing Fibre observations.

    If a Fibre is operating in an environment where many fragments
    are lost (low Sovereign Swarm endpoint density), it increases
    redundancy. In high-density environments, it reduces redundancy
    to minimize fragment count and assembly time.
    """

    def __init__(self) -> None:
        self.arrival_stats: Dict[str, ArrivalStats] = {}

    def record_arrival(
        self,
        environment_id: str,
        fragments_expected: int,
        fragments_received: int,
    ) -> None:
        """Record a fragment arrival observation for an environment."""
        if environment_id not in self.arrival_stats:
            self.arrival_stats[environment_id] = ArrivalStats()
        stats = self.arrival_stats[environment_id]
        stats.sample_count += 1
        stats.total_expected += fragments_expected
        stats.total_received += min(fragments_received, fragments_expected)

    def compute_optimal_redundancy(self, environment_id: str) -> float:
        """
        Compute optimal redundancy factor based on historical
        fragment arrival rates in this environment.

        Returns value between MIN_REDUNDANCY_FACTOR and MAX_REDUNDANCY_FACTOR.
        """
        stats = self.arrival_stats.get(environment_id)
        if not stats or stats.sample_count < 10:
            return DEFAULT_REDUNDANCY_FACTOR

        loss_rate = 1.0 - stats.arrival_rate

        if loss_rate < 0.05:
            return MIN_REDUNDANCY_FACTOR    # 0.1 — Very reliable
        elif loss_rate < 0.15:
            return 0.2                       # Good
        elif loss_rate < 0.30:
            return DEFAULT_REDUNDANCY_FACTOR  # 0.3 — Moderate
        elif loss_rate < 0.45:
            return 0.4                       # Harsh
        else:
            return MAX_REDUNDANCY_FACTOR     # 0.5 — Very harsh

    def get_stats(self, environment_id: str) -> ArrivalStats:
        """Get arrival stats for an environment, creating if needed."""
        if environment_id not in self.arrival_stats:
            self.arrival_stats[environment_id] = ArrivalStats()
        return self.arrival_stats[environment_id]

    def reset(self, environment_id: str) -> None:
        """Reset statistics for an environment."""
        self.arrival_stats.pop(environment_id, None)
