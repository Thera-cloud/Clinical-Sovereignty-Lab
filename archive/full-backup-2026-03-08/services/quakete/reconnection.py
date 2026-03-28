"""
SOVEREIGN SWARM — Magnetic Reconnection Engine (Patent Claim 26.1)
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from app.models.quakete import QuaketeAllocation, ReconnectionPlan

if TYPE_CHECKING:
    from app.services.quakete.resonance import QuaketeResonanceEngine


# =============================================================================
# MAGNETIC RECONNECTION ENGINE
# =============================================================================


class MagneticReconnectionEngine:
    """
    Digital analogue of plasma magnetic reconnection: when field lines break
    and reconnect in a more energetically favorable configuration. In the
    Quakete context, this reconfigures a struggling Fibre's communication
    pathways through donor environments.
    """

    def __init__(self, resonance_engine: "QuaketeResonanceEngine") -> None:
        self.resonance_engine = resonance_engine

    def compute_reconnection_plan(
        self,
        recipient_id: str,
        recipient_deficit: float,
        donors: list[dict],
        recipient_resonance_frequency: float = 0.5,
    ) -> ReconnectionPlan:
        """
        Compute a greedy reconnection plan from donors to cover recipient deficit.
        donors: list of {fibre_id, surplus, resonance_frequency}.
        """
        if recipient_deficit <= 0 or not donors:
            return ReconnectionPlan(
                recipient_id=recipient_id,
                allocations=[],
                total_transfer=0.0,
                deficit_covered=False,
            )

        # For each donor, compute coupling with recipient
        scored: list[tuple[dict, float, float]] = []
        for d in donors:
            donor_freq = d.get("resonance_frequency", 0.0)
            surplus = float(d.get("surplus", 0))
            coupling = self.resonance_engine.compute_coupling_efficiency(
                donor_freq, recipient_resonance_frequency
            )
            score = coupling * surplus
            scored.append((d, coupling, score))

        # Sort donors by coupling * surplus (best first)
        scored.sort(key=lambda x: x[2], reverse=True)

        # Greedily allocate until deficit is covered
        allocations: list[QuaketeAllocation] = []
        total_transfer = 0.0
        remaining = recipient_deficit

        for donor_dict, coupling, _ in scored:
            if remaining <= 0:
                break
            fibre_id = donor_dict.get("fibre_id", "")
            surplus = float(donor_dict.get("surplus", 0))
            amount = min(surplus, remaining)
            if amount <= 0:
                continue
            allocations.append(
                QuaketeAllocation(
                    donor_id=fibre_id,
                    recipient_id=recipient_id,
                    capacity_transfer=amount,
                    resonance=coupling,
                )
            )
            total_transfer += amount
            remaining -= amount

        deficit_covered = remaining <= 0

        return ReconnectionPlan(
            recipient_id=recipient_id,
            allocations=allocations,
            total_transfer=total_transfer,
            deficit_covered=deficit_covered,
        )

    def estimate_recovery_time(
        self, plan: ReconnectionPlan, recipient_deficit: float | None = None
    ) -> float:
        """
        Estimated seconds to recovery based on total transfer amount.
        recovery_time = (recipient_deficit / max(plan.total_transfer, 0.001)) * 60
        Cap at 600 seconds.
        """
        deficit = recipient_deficit if recipient_deficit is not None else plan.total_transfer
        recovery_time = (deficit / max(plan.total_transfer, 0.001)) * 60.0
        return min(recovery_time, 600.0)
