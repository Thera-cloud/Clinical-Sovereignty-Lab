"""
SOVEREIGN SWARM — Lost Fibre Memorial Encoding (Patent Claim 26.3)
Memorial encoding in partner trails.
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Optional

import structlog

from app.models.quakete import FibreTrailEmission, Memorial

if TYPE_CHECKING:
    from .cosmic_ring import CosmicRingManager


# =============================================================================
# MEMORIAL SERVICE (Patent Claim 26.3)
# =============================================================================


class MemorialService:
    """
    When a Fibre is confirmed lost, surviving Ring partners carry a
    compressed summary of the lost Fibre's last known wisdom in their trails.
    """

    def __init__(self, ring_manager: "CosmicRingManager") -> None:
        self._ring_manager = ring_manager
        self._memorials: dict[str, Memorial] = {}
        self._log = structlog.get_logger()

    # -------------------------------------------------------------------------
    # MEMORIAL CREATION
    # -------------------------------------------------------------------------

    def create_memorial(
        self,
        lost_fibre_id: str,
        lost_fibre_type: str,
        last_health: float,
        last_mission: Optional[str] = None,
        pending_observations: int = 0,
        quaketes_received: int = 0,
    ) -> Memorial:
        """
        Create a Memorial for a lost fibre.
        Computes memorial_hash, finds ring partners for carried_by.
        """
        now = datetime.now(timezone.utc)
        timestamp_str = now.isoformat()
        raw = f"{lost_fibre_id}{timestamp_str}"
        memorial_hash = hashlib.sha256(raw.encode()).hexdigest()

        ring = self._ring_manager.get_fibre_ring(lost_fibre_id)
        carried_by: list[str] = []
        if ring is not None:
            other_cords = ring.get_other_cords(lost_fibre_id)
            carried_by = [c.fibre_id for c in other_cords]

        memorial = Memorial(
            lost_fibre_id=lost_fibre_id,
            lost_fibre_type=lost_fibre_type,
            lost_at=now,
            last_known_health=last_health,
            last_known_mission=last_mission,
            pending_observations=pending_observations,
            quaketes_received_before_loss=quaketes_received,
            memorial_hash=memorial_hash,
            carried_by=carried_by,
        )

        self._memorials[lost_fibre_id] = memorial
        self._log.info(
            "memorial_created",
            lost_fibre_id=lost_fibre_id,
            carried_by=carried_by,
        )
        return memorial

    def get_memorial(self, fibre_id: str) -> Optional[Memorial]:
        """Return memorial for a lost fibre, or None."""
        return self._memorials.get(fibre_id)

    def get_memorials_carried_by(self, carrier_fibre_id: str) -> list[Memorial]:
        """Return all memorials where carrier_fibre_id is in carried_by."""
        return [
            m for m in self._memorials.values()
            if carrier_fibre_id in m.carried_by
        ]

    def encode_in_trail(
        self,
        memorial: Memorial,
        trail: FibreTrailEmission,
    ) -> FibreTrailEmission:
        """
        Encode memorial hash into trail's observation_queue_depth field
        (repurposed as lightweight carrier for memorial data).
        Returns modified trail (copy).
        """
        if memorial.memorial_hash is None:
            return trail

        # Encode hash as int: first 8 hex chars as base-16 int (fits in 32-bit)
        hash_int = int(memorial.memorial_hash[:8], 16)
        modified = trail.model_copy(
            update={"observation_queue_depth": hash_int}
        )
        return modified

    # -------------------------------------------------------------------------
    # WISDOM DISTILLATION (S7: Memorial Wisdom Preservation)
    # -------------------------------------------------------------------------

    def distill_wisdom(self, memorial: Memorial) -> dict:
        """
        Distill clinical wisdom from a memorial's data.
        Returns a wisdom summary for Sovereign Mind absorption.
        """
        from app.models.solutions import MemorialExtended, WisdomEntry

        wisdom_entries = []

        # Extract wisdom from the memorial context
        if memorial.last_known_mission:
            wisdom_entries.append(WisdomEntry(
                pattern_observed=f"Active mission at dissolution: {memorial.last_known_mission}",
                evidence_count=1,
                confidence=0.8 if memorial.last_known_health > 0.5 else 0.5,
                context="fibre_dissolution",
                therapeutic_implication="Mission continuity needed for replacement Fibre",
                recommended_application="Inherit mission priority in successor Fibre",
            ))

        if memorial.pending_observations > 0:
            wisdom_entries.append(WisdomEntry(
                pattern_observed=f"Pending observations at dissolution: {memorial.pending_observations}",
                evidence_count=memorial.pending_observations,
                confidence=0.7,
                context="incomplete_observations",
                therapeutic_implication="Wisdom loss risk — observations not yet transmitted",
                recommended_application="Prioritize observation recovery in ring partners",
            ))

        if memorial.quaketes_received_before_loss > 0:
            wisdom_entries.append(WisdomEntry(
                pattern_observed=f"Quaketes received before loss: {memorial.quaketes_received_before_loss}",
                evidence_count=memorial.quaketes_received_before_loss,
                confidence=0.9,
                context="solidarity_history",
                therapeutic_implication="Fibre was receiving support — may indicate systemic stress",
                recommended_application="Monitor ring partners for similar decline patterns",
            ))

        extended = MemorialExtended(
            source_fibre_id=memorial.lost_fibre_id,
            source_fibre_type=memorial.lost_fibre_type,
            dissolved_at=memorial.lost_at,
            wisdom_entries=wisdom_entries,
            inheritor_fibre_id=memorial.carried_by[0] if memorial.carried_by else None,
            inheritance_priority=memorial.carried_by,
        )

        self._log.info(
            "wisdom_distilled",
            fibre_id=memorial.lost_fibre_id,
            wisdom_count=len(wisdom_entries),
        )

        return extended.model_dump()

    def get_all_wisdom(self) -> list:
        """Get distilled wisdom from all memorials."""
        results = []
        for memorial in self._memorials.values():
            results.append(self.distill_wisdom(memorial))
        return results

    @property
    def total_memorials(self) -> int:
        """Total number of memorials stored."""
        return len(self._memorials)
