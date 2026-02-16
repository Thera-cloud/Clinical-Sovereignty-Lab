"""
SOVEREIGN SWARM — Quakete Ion Pool
Patent Claim 26: Collisionless energy transfer ion storage.
"""

from __future__ import annotations

from typing import List

from app.models.quakete import QuaketeIon


# =============================================================================
# QUAKETE ION POOL
# =============================================================================


class QuaketeIonPool:
    """
    Pool for storing QuaketeIon units generated during ring circulation.
    Ions can be consumed by the Lorentz Force Accelerator for fragment boosts.
    """

    def __init__(self) -> None:
        self._ions: List[QuaketeIon] = []

    def deposit(self, ions: list[QuaketeIon]) -> None:
        """Add ions to the pool."""
        self._ions.extend(ions)

    def withdraw_for_recipient(self, recipient_id: str) -> list[QuaketeIon]:
        """Remove and return ions targeted at the given recipient."""
        matched = [i for i in self._ions if i.recipient_fibre_id == recipient_id]
        for i in matched:
            self._ions.remove(i)
        return matched

    def total_ions(self) -> int:
        """Total number of ions in the pool."""
        return len(self._ions)

    def clear(self) -> None:
        """Remove all ions from the pool."""
        self._ions.clear()
