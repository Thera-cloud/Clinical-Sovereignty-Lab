"""
SOVEREIGN SWARM — Optimal Triangle Detection for Ring Formation
Patent Claim 26.6d: Optimal triangle detection.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import structlog

from app.models.quakete import CosmicRelationalRing

from .constants import RING_MIN_COUPLING

if TYPE_CHECKING:
    from .cosmic_ring import CosmicRingManager
    from .resonance import QuaketeResonanceEngine


# =============================================================================
# RING FORMATION SERVICE (Patent Claim 26.6d)
# =============================================================================


class RingFormationService:
    """
    Finds optimal three-cord triangles from fibre coupling matrices.
    Uses 3-clique detection with greedy assignment.
    """

    def __init__(
        self,
        resonance_engine: QuaketeResonanceEngine,
        ring_manager: CosmicRingManager,
    ) -> None:
        self._resonance_engine = resonance_engine
        self._ring_manager = ring_manager
        self._log = structlog.get_logger()

    # -------------------------------------------------------------------------
    # OPTIMAL RING DETECTION
    # -------------------------------------------------------------------------

    def find_optimal_rings(self, fibres: list[dict]) -> list[tuple[str, str, str]]:
        """
        fibres = list of {fibre_id, fibre_type, resonance_frequency}
        Compute all pairwise couplings using resonance_engine.
        Find all valid triangles (3-cliques where all pairwise > RING_MIN_COUPLING).
        Sort by sum of couplings (best first). Greedily assign.
        Return list of (id_a, id_b, id_c) tuples.
        """
        if len(fibres) < 3:
            return []

        freq_by_id: dict[str, float] = {}
        for f in fibres:
            fid = f.get("fibre_id")
            if fid is None:
                continue
            freq_by_id[fid] = float(f.get("resonance_frequency", 0.0))

        # Compute pairwise couplings
        ids = list(freq_by_id.keys())
        coupling: dict[tuple[str, str], float] = {}
        for i, a in enumerate(ids):
            for b in ids[i + 1 :]:
                eta = self._resonance_engine.compute_coupling_efficiency(
                    freq_by_id[a], freq_by_id[b]
                )
                coupling[(a, b)] = eta
                coupling[(b, a)] = eta

        # Find all valid triangles (3-cliques)
        triangles: list[tuple[tuple[str, str, str], float]] = []
        for i, a in enumerate(ids):
            for j, b in enumerate(ids):
                if j <= i:
                    continue
                for k, c in enumerate(ids):
                    if k <= j:
                        continue
                    eta_ab = coupling.get((a, b), 0.0)
                    eta_ac = coupling.get((a, c), 0.0)
                    eta_bc = coupling.get((b, c), 0.0)
                    if (
                        eta_ab > RING_MIN_COUPLING
                        and eta_ac > RING_MIN_COUPLING
                        and eta_bc > RING_MIN_COUPLING
                    ):
                        total = eta_ab + eta_ac + eta_bc
                        triangles.append(((a, b, c), total))

        # Sort by sum of couplings (best first)
        triangles.sort(key=lambda t: t[1], reverse=True)

        # Greedily assign: once a fibre is in a ring, remove from candidates
        assigned: set[str] = set()
        result: list[tuple[str, str, str]] = []
        for (a, b, c), _ in triangles:
            if a in assigned or b in assigned or c in assigned:
                continue
            result.append((a, b, c))
            assigned.add(a)
            assigned.add(b)
            assigned.add(c)

        return result

    # -------------------------------------------------------------------------
    # RING CREATION
    # -------------------------------------------------------------------------

    def form_rings(self, fibres: list[dict]) -> list[CosmicRelationalRing]:
        """
        Calls find_optimal_rings, then ring_manager.create_ring for each triangle.
        Returns created rings.
        """
        fibre_by_id: dict[str, dict] = {f.get("fibre_id", ""): f for f in fibres if f.get("fibre_id")}
        triangles = self.find_optimal_rings(fibres)
        created: list[CosmicRelationalRing] = []

        for (a, b, c) in triangles:
            fa = fibre_by_id.get(a, {})
            fb = fibre_by_id.get(b, {})
            fc = fibre_by_id.get(c, {})
            ring = self._ring_manager.create_ring(
                cord1_id=a,
                cord1_type=str(fa.get("fibre_type", "unknown")),
                cord2_id=b,
                cord2_type=str(fb.get("fibre_type", "unknown")),
                cord3_id=c,
                cord3_type=str(fc.get("fibre_type", "unknown")),
            )
            created.append(ring)

        self._log.info(
            "rings_formed",
            triangle_count=len(triangles),
            ring_ids=[r.ring_id for r in created],
        )
        return created

    # -------------------------------------------------------------------------
    # RING REFORMATION
    # -------------------------------------------------------------------------

    def reform_broken_ring(
        self,
        broken_ring: CosmicRelationalRing,
        replacement_fibre: dict,
    ) -> CosmicRelationalRing:
        """
        Replace the lost cord with the replacement.
        Dissolve old ring, create new ring.
        """
        cords = broken_ring.all_cords()
        if len(cords) < 3:
            self._log.warning(
                "reform_broken_ring_invalid",
                ring_id=broken_ring.ring_id,
            )
            return broken_ring

        # Identify surviving cords (assume we replace the "lost" one - typically
        # the one with SILENT mode or worst health)
        lost_cord = min(cords, key=lambda c: (c.current_health, c.current_mode.value))
        survivors = [c for c in cords if c.fibre_id != lost_cord.fibre_id]
        if len(survivors) != 2:
            self._log.warning(
                "reform_broken_ring_unexpected_survivors",
                ring_id=broken_ring.ring_id,
            )
            return broken_ring

        repl_id = str(replacement_fibre.get("fibre_id", ""))
        repl_type = str(replacement_fibre.get("fibre_type", "unknown"))

        self._ring_manager.dissolve_ring(broken_ring.ring_id)

        new_ring = self._ring_manager.create_ring(
            cord1_id=survivors[0].fibre_id,
            cord1_type=survivors[0].fibre_type,
            cord2_id=survivors[1].fibre_id,
            cord2_type=survivors[1].fibre_type,
            cord3_id=repl_id,
            cord3_type=repl_type,
        )

        self._log.info(
            "ring_reformed",
            old_ring_id=broken_ring.ring_id,
            new_ring_id=new_ring.ring_id,
            replaced=lost_cord.fibre_id,
            replacement=repl_id,
        )
        return new_ring
