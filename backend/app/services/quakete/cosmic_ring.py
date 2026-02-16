"""
SOVEREIGN SWARM — Cosmic Relational Ring Data Structure Operations
Patent Claim 26.1h: CosmicRelationalRing data structure operations.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Optional

import structlog

from app.models.quakete import (
    CosmicRelationalRing,
    QuaketeMode,
    RingCord,
    RingState,
)

if TYPE_CHECKING:
    from .resonance import QuaketeResonanceEngine


# =============================================================================
# COSMIC RING MANAGER (Patent Claim 26.1h)
# =============================================================================


class CosmicRingManager:
    """
    Manages CosmicRelationalRing data structures.
    Creates, updates, and dissolves three-cord solidarity rings.
    """

    def __init__(self, resonance_engine: QuaketeResonanceEngine) -> None:
        self._resonance_engine = resonance_engine
        self._rings: dict[str, CosmicRelationalRing] = {}
        self._fibre_to_ring: dict[str, str] = {}
        self._log = structlog.get_logger()

    # -------------------------------------------------------------------------
    # RING CREATION & RETRIEVAL
    # -------------------------------------------------------------------------

    def create_ring(
        self,
        cord1_id: str,
        cord1_type: str,
        cord2_id: str,
        cord2_type: str,
        cord3_id: str,
        cord3_type: str,
    ) -> CosmicRelationalRing:
        """
        Creates RingCord for each fibre, assembles ring, stores in _rings.
        Returns the created ring.
        """
        cord1 = RingCord(fibre_id=cord1_id, fibre_type=cord1_type)
        cord2 = RingCord(fibre_id=cord2_id, fibre_type=cord2_type)
        cord3 = RingCord(fibre_id=cord3_id, fibre_type=cord3_type)

        ring = CosmicRelationalRing(
            cord_1=cord1,
            cord_2=cord2,
            cord_3=cord3,
        )
        ring.ring_coherence = self._compute_ring_coherence(ring)
        ring.ring_state = self._compute_ring_state(ring)

        self._rings[ring.ring_id] = ring
        for fid in (cord1_id, cord2_id, cord3_id):
            self._fibre_to_ring[fid] = ring.ring_id

        self._log.info(
            "cosmic_ring_created",
            ring_id=ring.ring_id,
            cords=[cord1_id, cord2_id, cord3_id],
            coherence=ring.ring_coherence,
            state=ring.ring_state.value,
        )
        return ring

    def get_ring(self, ring_id: str) -> Optional[CosmicRelationalRing]:
        """Return the ring by ring_id, or None if not found."""
        return self._rings.get(ring_id)

    def get_fibre_ring(self, fibre_id: str) -> Optional[CosmicRelationalRing]:
        """Return the ring containing the given fibre_id, or None."""
        ring_id = self._fibre_to_ring.get(fibre_id)
        if ring_id is None:
            return None
        return self._rings.get(ring_id)

    # -------------------------------------------------------------------------
    # CORD HEALTH UPDATES
    # -------------------------------------------------------------------------

    def update_cord_health(
        self,
        fibre_id: str,
        health: float,
        mode: QuaketeMode,
        trail_at: datetime | None = None,
    ) -> None:
        """
        Updates the cord in its ring. Recalculates ring_state and ring_coherence.
        """
        ring = self.get_fibre_ring(fibre_id)
        if ring is None:
            self._log.warning("update_cord_health_unknown_fibre", fibre_id=fibre_id)
            return

        for cord in ring.all_cords():
            if cord.fibre_id == fibre_id:
                cord.current_health = max(0.0, min(1.0, health))
                cord.current_mode = mode
                cord.last_trail_at = trail_at
                break

        ring.ring_coherence = self._compute_ring_coherence(ring)
        ring.ring_state = self._compute_ring_state(ring)

    # -------------------------------------------------------------------------
    # RING STATE & COHERENCE
    # -------------------------------------------------------------------------

    def _compute_ring_state(self, ring: CosmicRelationalRing) -> RingState:
        """
        Compute ring operational state from cord modes and health.
        - All NOMINAL/SURPLUS → HEALTHY
        - One REQUESTING → SUPPORTING
        - Two degraded → STRAINED
        - All degraded → DISTRESSED
        - Any SILENT → RESCUE
        - Any cord missing → BROKEN
        """
        cords = ring.all_cords()
        if len(cords) < 3:
            return RingState.BROKEN

        modes = [c.current_mode for c in cords]
        degraded = [
            QuaketeMode.REQUESTING,
            QuaketeMode.CRITICAL,
        ]
        degraded_count = sum(1 for m in modes if m in degraded)

        if QuaketeMode.SILENT in modes:
            return RingState.RESCUE
        if degraded_count == 0:
            return RingState.HEALTHY
        if degraded_count == 1:
            return RingState.SUPPORTING
        if degraded_count == 2:
            return RingState.STRAINED
        return RingState.DISTRESSED

    def _compute_ring_coherence(self, ring: CosmicRelationalRing) -> float:
        """Average of all three cord healths."""
        cords = ring.all_cords()
        if len(cords) == 0:
            return 0.0
        total = sum(c.current_health for c in cords)
        return max(0.0, min(1.0, total / len(cords)))

    # -------------------------------------------------------------------------
    # RING DISSOLUTION
    # -------------------------------------------------------------------------

    def dissolve_ring(self, ring_id: str) -> Optional[CosmicRelationalRing]:
        """Remove ring from storage, clear fibre mappings. Return dissolved ring or None."""
        ring = self._rings.pop(ring_id, None)
        if ring is None:
            return None

        for cord in ring.all_cords():
            self._fibre_to_ring.pop(cord.fibre_id, None)

        self._log.info("cosmic_ring_dissolved", ring_id=ring_id)
        return ring

    # -------------------------------------------------------------------------
    # PROPERTIES
    # -------------------------------------------------------------------------

    @property
    def all_rings(self) -> list[CosmicRelationalRing]:
        """List of all managed rings."""
        return list(self._rings.values())

    @property
    def ring_count(self) -> int:
        """Number of managed rings."""
        return len(self._rings)
