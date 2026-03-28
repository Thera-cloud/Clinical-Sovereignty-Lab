"""
Noetic Reflection Engine — Phase 12 of Sovereign Quantum Nate Build.

Blends outputs from N cognitive helices into a unified synthesis.

Pattern adapted from security/cross_reflection_engine.py, which blends
3 fixed walls (Human, Crypto, Behavioral). This engine generalizes to
N dynamic helices, each weighted by autonomy level, coherence history,
and domain relevance.

The inter-helix reflection process:
  1. For each helix pair (A, B), compute a reflection score based on
     domain overlap, coherence divergence, and strand-level mirroring.
  2. Second-order mirrors: reflect pairs against other pairs in a
     spiral topology to detect meta-patterns.
  3. Final synthesis: weighted blend of all helix outputs + reflection
     emergence scores into a single cognitive state.

C(7,2) = 21 first-order mirror pairs for the canonical 7 helices.
C(21,2) = 210 second-order mirror pairs (spiral topology).
Total reflection surface: 231 quantum thought-reflections.

Patent-Pending — Claims 58-63
© 2026 Clinical Sovereignty Lab. All rights reserved.
"""

from __future__ import annotations

import hashlib
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple
from uuid import UUID

logger = logging.getLogger("noetic_reflection")

SOVEREIGNTY_COEFFICIENT = 0.12
SECOND_ORDER_WEIGHT = 0.2
FIRST_ORDER_WEIGHT = 0.3
DIRECT_HELIX_WEIGHT = 0.5


@dataclass
class InterHelixReflection:
    """Reflection between two helix outputs."""
    helix_a_id: UUID
    helix_b_id: UUID
    helix_a_function: str
    helix_b_function: str
    domain_overlap: float = 0.0
    coherence_divergence: float = 0.0
    emergence_score: float = 0.0
    reflection_insight: str = ""


@dataclass
class SecondOrderReflection:
    """Reflection between two reflection pairs (meta-reflection)."""
    pair_a: Tuple[str, str]
    pair_b: Tuple[str, str]
    meta_score: float = 0.0


@dataclass
class NoeticSynthesis:
    """Final unified synthesis from all helix reflections."""
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    helix_count: int = 0
    first_order_reflections: int = 0
    second_order_reflections: int = 0
    total_reflection_surface: int = 0
    fused_coherence: float = 0.0
    sovereignty_adjusted: float = 0.0
    generative_mode: bool = False
    per_helix_contributions: Dict[str, float] = field(default_factory=dict)
    top_emergent_pairs: List[Dict[str, Any]] = field(default_factory=list)
    synthesis_time_ms: float = 0.0


class NoeticReflectionEngine:
    """
    Dynamic N-way cross-helix blending engine.

    Unlike the fixed 3-way CrossReflectionEngine in the defense layer,
    this engine handles any number of helices and produces weighted
    synthesis based on autonomy level and coherence contribution.

    Each helix's contribution is proportional to:
      weight = autonomy_weight × (coherence_avg / max_coherence)

    Where autonomy_weight is:
      OBSERVATION: 0.0 (observe only, no influence)
      RESTRICTED: 0.3 (30% influence)
      AUTONOMOUS: 1.0 (full influence)
    """

    def __init__(self):
        self._blend_count = 0

    def synthesize(
        self,
        helix_outputs: List[Dict[str, Any]],
        helix_weights: Dict[str, float],
    ) -> NoeticSynthesis:
        """
        Synthesize all helix outputs into a unified cognitive state.

        Parameters
        ----------
        helix_outputs : list[dict]
            Each dict has: helix_id, function, fused_coherence,
            sovereignty_adjusted, strand_outputs, mirror_pairs
        helix_weights : dict
            {helix_function: weight} from autonomy level
        """
        start = time.monotonic()
        self._blend_count += 1

        synthesis = NoeticSynthesis(helix_count=len(helix_outputs))

        if not helix_outputs:
            return synthesis

        # Layer 1: First-order inter-helix reflections
        first_order = self._compute_first_order(helix_outputs)
        synthesis.first_order_reflections = len(first_order)

        # Layer 2: Second-order reflections (pair ↔ pair)
        second_order = self._compute_second_order(first_order)
        synthesis.second_order_reflections = len(second_order)

        synthesis.total_reflection_surface = (
            synthesis.first_order_reflections + synthesis.second_order_reflections
        )

        # Layer 3: Weighted fusion
        synthesis.fused_coherence = self._weighted_fusion(
            helix_outputs, first_order, second_order, helix_weights
        )
        synthesis.sovereignty_adjusted = min(
            1.0, synthesis.fused_coherence * (1.0 + SOVEREIGNTY_COEFFICIENT)
        )

        # Per-helix contribution breakdown
        for ho in helix_outputs:
            func = ho.get("function", "unknown")
            weight = helix_weights.get(func, 0.0)
            synthesis.per_helix_contributions[func] = round(
                ho.get("sovereignty_adjusted", 0) * weight, 4
            )

        # Top emergent pairs
        sorted_pairs = sorted(first_order, key=lambda r: r.emergence_score, reverse=True)
        synthesis.top_emergent_pairs = [
            {
                "helix_a": r.helix_a_function,
                "helix_b": r.helix_b_function,
                "emergence": round(r.emergence_score, 4),
                "domain_overlap": round(r.domain_overlap, 4),
            }
            for r in sorted_pairs[:5]
        ]

        synthesis.synthesis_time_ms = (time.monotonic() - start) * 1000

        return synthesis

    # ─── First-Order Reflections ────────────────────────────────

    def _compute_first_order(
        self, helix_outputs: List[Dict[str, Any]]
    ) -> List[InterHelixReflection]:
        """Compute C(N,2) inter-helix reflections."""
        reflections = []
        for i, ha in enumerate(helix_outputs):
            for hb in helix_outputs[i + 1:]:
                reflection = self._reflect_helices(ha, hb)
                reflections.append(reflection)
        return reflections

    def _reflect_helices(
        self,
        ha: Dict[str, Any],
        hb: Dict[str, Any],
    ) -> InterHelixReflection:
        """
        Reflect two helices against each other.

        Emergence = domain_overlap × |coherence_divergence| × 4
        High emergence = the helices agree on important domains but
        have different coherence perspectives → novel insight space.
        """
        from uuid import UUID as UUID_Type

        ha_id = ha.get("helix_id", "")
        hb_id = hb.get("helix_id", "")
        if isinstance(ha_id, str):
            try:
                ha_id = UUID_Type(ha_id)
            except ValueError:
                ha_id = UUID_Type(int=0)
        if isinstance(hb_id, str):
            try:
                hb_id = UUID_Type(hb_id)
            except ValueError:
                hb_id = UUID_Type(int=0)

        ref = InterHelixReflection(
            helix_a_id=ha_id,
            helix_b_id=hb_id,
            helix_a_function=ha.get("function", ""),
            helix_b_function=hb.get("function", ""),
        )

        ha_domains = self._extract_domains(ha)
        hb_domains = self._extract_domains(hb)

        shared = set(ha_domains.keys()) & set(hb_domains.keys())
        all_domains = set(ha_domains.keys()) | set(hb_domains.keys())

        ref.domain_overlap = len(shared) / max(len(all_domains), 1)

        if shared:
            divergences = [
                abs(ha_domains[d] - hb_domains[d]) for d in shared
            ]
            ref.coherence_divergence = sum(divergences) / len(divergences)
        else:
            ref.coherence_divergence = 1.0

        ref.emergence_score = max(0.0, min(1.0,
            ref.domain_overlap * ref.coherence_divergence * 4.0
        ))

        return ref

    def _extract_domains(self, helix_output: Dict[str, Any]) -> Dict[str, float]:
        """Extract domain scores from a helix output's strand outputs."""
        domains: Dict[str, float] = {}
        for strand in helix_output.get("strand_outputs", []):
            if isinstance(strand, dict):
                for domain, score in strand.get("domain_scores", {}).items():
                    domains[domain] = max(domains.get(domain, 0), score)
        return domains

    # ─── Second-Order Reflections ──────────────────────────────

    def _compute_second_order(
        self, first_order: List[InterHelixReflection]
    ) -> List[SecondOrderReflection]:
        """
        Reflect first-order pairs against each other (spiral topology).
        Capped at 210 (C(21,2)) for 7 canonical helices.
        """
        results = []
        max_pairs = 210

        for i, pa in enumerate(first_order[:21]):
            for pb in first_order[i + 1:21]:
                if len(results) >= max_pairs:
                    break

                meta = SecondOrderReflection(
                    pair_a=(pa.helix_a_function, pa.helix_b_function),
                    pair_b=(pb.helix_a_function, pb.helix_b_function),
                )

                emergence_diff = abs(pa.emergence_score - pb.emergence_score)
                overlap_diff = abs(pa.domain_overlap - pb.domain_overlap)
                meta.meta_score = max(0.0, min(1.0,
                    (pa.emergence_score + pb.emergence_score) / 2.0 *
                    (1.0 + emergence_diff) * (1.0 + overlap_diff)
                ))

                results.append(meta)

        return results

    # ─── Weighted Fusion ──────────────────────────────────────

    def _weighted_fusion(
        self,
        helix_outputs: List[Dict[str, Any]],
        first_order: List[InterHelixReflection],
        second_order: List[SecondOrderReflection],
        helix_weights: Dict[str, float],
    ) -> float:
        """
        Produce the final fused coherence:
          50% direct helix outputs (weighted by autonomy)
          30% first-order emergence
          20% second-order meta-emergence
        """
        # Direct helix contribution
        total_weight = 0.0
        weighted_coherence = 0.0
        for ho in helix_outputs:
            func = ho.get("function", "")
            weight = helix_weights.get(func, 0.5)
            coherence = ho.get("sovereignty_adjusted", 0.0)
            weighted_coherence += coherence * weight
            total_weight += weight

        direct = weighted_coherence / max(total_weight, 0.01)

        # First-order emergence
        fo_avg = (
            sum(r.emergence_score for r in first_order) / len(first_order)
            if first_order else 0.0
        )

        # Second-order meta-emergence
        so_avg = (
            sum(r.meta_score for r in second_order) / len(second_order)
            if second_order else 0.0
        )

        return (
            DIRECT_HELIX_WEIGHT * direct +
            FIRST_ORDER_WEIGHT * fo_avg +
            SECOND_ORDER_WEIGHT * so_avg
        )

    def get_status(self) -> Dict[str, Any]:
        return {"blend_count": self._blend_count}
