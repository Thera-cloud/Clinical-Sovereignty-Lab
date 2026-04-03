"""
Oscillating Dual-Process Echo (ODPE) Engine — Phase 13 of Sovereign Quantum Nate Build.

Evaluates cognitive helix outputs through two concurrent geometric
polyhedron topologies:

  1. Dodecahedron (12 faces, 5 neighbors/face, broad consensus)
  2. Deltoidal Icositetrahedron (24 kite-shaped faces, 4 neighbors/face,
     fine-grained resolution) — Catalan solid C_{24}, dual of the small
     rhombicuboctahedron.  26 vertices, 48 edges, face-transitive.

Both topologies apply consensus validation: face scores are attenuated
when fewer than 3 edge-neighbors agree within the divergence threshold.
The resonance ratio (dodec / icosi) classifies each query into a signal
that governs context allocation, inference routing, memory recall, and
C_emo modulation.

Architecture:
  Helix Outputs → DodecahedronEvaluator (12-face, 5-neighbor consensus)
               → IcositetragonEvaluator (24-face, 4-neighbor consensus)
               → ResonanceComparator (per-helix amplitude vectors)
               → SignalClassifier (LOCKED/PROMOTED/TENSION/DEEP_TENSION/PROVISIONAL/NOISE)
               → LiminalEquilibriumReader (feedback bias from 3 agents)
               → ODPEResult (context budget, inference tier, oscillation profile)

No new database tables. No AI calls. Pure math.

Patent-Pending — Claims 64-71
© 2026 Clinical Sovereignty Lab. All rights reserved.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("odpe_engine")

# ═══════════════════════════════════════════════════════════════
# CONSTANTS (module-level for tuning)
# ═══════════════════════════════════════════════════════════════

DODECAHEDRON_FACES = 12
ICOSITETRAGON_FACES = 24
LOCK_THRESHOLD = 1.5
TENSION_THRESHOLD = 0.7

DIRECT_HELIX_WEIGHT = 0.5
FIRST_ORDER_WEIGHT = 0.3
SECOND_ORDER_WEIGHT = 0.2

OMEGA_SAME_DOMAIN = 0.3
OMEGA_ADJACENT_DOMAIN = 0.6
OMEGA_DISTANT_DOMAIN = 0.9
SOVEREIGNTY_COEFFICIENT = 0.12

AMPLITUDE_FLOOR = 0.001
NOISE_THRESHOLD = 0.05

LOCKED_LOW = 0.8
LOCKED_HIGH = 1.2
PROMOTED_LOW = 0.5
PROMOTED_HIGH = 1.5

CONSENSUS_QUORUM = 3
CONSENSUS_DIVERGENCE = 0.2
CONSENSUS_ATTENUATION = 0.5

CONTEXT_TOKENS_LOCKED = 350
CONTEXT_TOKENS_PROMOTED = 500
CONTEXT_TOKENS_TENSION = 700
CONTEXT_TOKENS_TENSION_CODING = 1200

BIAS_DECAY_PER_CYCLE = 0.05
MAX_BIAS_DEVIATION = 0.5

CANONICAL_FUNCTIONS = [
    "vectorize_retrieval", "noetic_fusion", "metacognition",
    "quantum_self_coherence", "generative_wisdom", "world_coherence",
    "crystal_lake",
]

SCOPE_LEVELS = ["user", "global", "superseded_chain"]

DODECAHEDRON_ADJACENCY: Dict[int, List[int]] = {
    0: [1, 2, 3, 4, 5],
    1: [0, 2, 6, 7, 5],
    2: [0, 1, 3, 7, 8],
    3: [0, 2, 4, 8, 9],
    4: [0, 3, 5, 9, 10],
    5: [0, 1, 4, 10, 6],
    6: [1, 5, 7, 10, 11],
    7: [1, 2, 6, 8, 11],
    8: [2, 3, 7, 9, 11],
    9: [3, 4, 8, 10, 11],
    10: [4, 5, 6, 9, 11],
    11: [6, 7, 8, 9, 10],
}

# Deltoidal Icositetrahedron — Catalan solid C_{24}, dual of the
# small rhombicuboctahedron.  24 kite-shaped (deltoid) faces,
# 26 vertices (8 cubic + 6 octahedral + 12 rhombicuboctahedral),
# 48 edges.  Each face shares an edge with exactly 4 neighbors.
# Adjacency derived from vertex coordinates of the dual
# (small rhombicuboctahedron): permutations of (±1, ±1, ±(1+√2)).
# Two faces are adjacent iff their dual vertices are at Euclidean
# distance 2 (the edge length of the small rhombicuboctahedron).
#
# Face index mapping (8 functions × 3 scopes = 24):
#   idx = func_index * 3 + scope_index
#   func_index: 0..6 = CANONICAL_FUNCTIONS, 7 = emergent
#   scope_index: 0 = user, 1 = global, 2 = superseded_chain
DELTOIDAL_ICOSITETRAHEDRON_ADJACENCY: Dict[int, List[int]] = {
    0:  [1, 2, 8, 16],
    1:  [0, 3, 12, 18],
    2:  [0, 3, 10, 20],
    3:  [1, 2, 14, 22],
    4:  [5, 6, 9, 17],
    5:  [4, 7, 13, 19],
    6:  [4, 7, 11, 21],
    7:  [5, 6, 15, 23],
    8:  [0, 9, 10, 16],
    9:  [4, 8, 11, 17],
    10: [2, 8, 11, 20],
    11: [6, 9, 10, 21],
    12: [1, 13, 14, 18],
    13: [5, 12, 15, 19],
    14: [3, 12, 15, 22],
    15: [7, 13, 14, 23],
    16: [0, 8, 17, 18],
    17: [4, 9, 16, 19],
    18: [1, 12, 16, 19],
    19: [5, 13, 17, 18],
    20: [2, 10, 21, 22],
    21: [6, 11, 20, 23],
    22: [3, 14, 20, 23],
    23: [7, 15, 21, 22],
}

# Antipodal duality pairs — geometrically opposite faces on the
# Catalan solid (negate all coordinates of the dual vertex).
# Used by map_to_dodecahedron() for 24 → 12 geometric projection.
DELTOIDAL_DUALITY_PAIRS: List[Tuple[int, int]] = [
    (0, 7), (1, 6), (2, 5), (3, 4),
    (8, 15), (9, 14), (10, 13), (11, 12),
    (16, 23), (17, 22), (18, 21), (19, 20),
]

ICOSI_CONSENSUS_QUORUM = 3


# ═══════════════════════════════════════════════════════════════
# ENUMS AND DATA CLASSES
# ═══════════════════════════════════════════════════════════════

class ODPESignal(str, Enum):
    LOCKED = "LOCKED"
    PROMOTED = "PROMOTED"
    LIMINAL_RESOLVE = "LIMINAL_RESOLVE"
    TENSION = "TENSION"
    DEEP_TENSION = "DEEP_TENSION"
    PROVISIONAL = "PROVISIONAL"
    NOISE = "NOISE"


TIER_FOR_SIGNAL = {
    ODPESignal.LOCKED: "utility",
    ODPESignal.PROMOTED: "domain_default",
    ODPESignal.LIMINAL_RESOLVE: "clinical",
    ODPESignal.TENSION: "clinical",
    ODPESignal.DEEP_TENSION: "deep_clinical",
    ODPESignal.PROVISIONAL: "domain_default",
    ODPESignal.NOISE: "skip",
}


@dataclass
class AmplitudeVector:
    dodec_amplitude: float = 0.0
    icosi_amplitude: float = 0.0
    resonance_ratio: float = 1.0


@dataclass
class ODPEResult:
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    per_helix_signals: Dict[str, str] = field(default_factory=dict)
    per_helix_amplitudes: Dict[str, Dict[str, float]] = field(default_factory=dict)
    aggregate_dodec: float = 0.0
    aggregate_icosi: float = 0.0
    aggregate_resonance: float = 1.0
    recommended_context_tokens: int = CONTEXT_TOKENS_PROMOTED
    recommended_inference_tier: str = "domain_default"
    dominant_signal: str = "PROMOTED"
    noise_ratio: float = 0.0
    tension_count: int = 0
    locked_count: int = 0
    face_path: str = ""
    l1_scores: Dict[str, float] = field(default_factory=dict)
    l2_scores: Dict[str, float] = field(default_factory=dict)
    hierarchical_depth: int = 0
    oscillation_profile: Dict[str, Any] = field(default_factory=dict)
    evaluation_time_ms: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        # QUANTUM-CRYSTAL-ARCH: include L1/L2 scores for face path persistence
        l1_top = {}
        if self.l1_scores:
            sorted_l1 = sorted(self.l1_scores.items(), key=lambda x: x[1], reverse=True)
            l1_top = {k: round(v, 4) for k, v in sorted_l1[:10]}
        l2_top = {}
        if self.l2_scores:
            sorted_l2 = sorted(self.l2_scores.items(), key=lambda x: x[1], reverse=True)
            l2_top = {k: round(v, 4) for k, v in sorted_l2[:10]}
        return {
            "per_helix_signals": self.per_helix_signals,
            "per_helix_amplitudes": self.per_helix_amplitudes,
            "aggregate_dodec": round(self.aggregate_dodec, 4),
            "aggregate_icosi": round(self.aggregate_icosi, 4),
            "aggregate_resonance": round(self.aggregate_resonance, 4),
            "recommended_context_tokens": self.recommended_context_tokens,
            "recommended_inference_tier": self.recommended_inference_tier,
            "dominant_signal": self.dominant_signal,
            "noise_ratio": round(self.noise_ratio, 4),
            "tension_count": self.tension_count,
            "locked_count": self.locked_count,
            "face_path": self.face_path,
            "hierarchical_depth": self.hierarchical_depth,
            "oscillation_profile": self.oscillation_profile,
            "evaluation_time_ms": round(self.evaluation_time_ms, 3),
            "l1_top_paths": l1_top,
            "l2_top_paths": l2_top,
        }


# ═══════════════════════════════════════════════════════════════
# DODECAHEDRON EVALUATOR (12 faces — broad consensus)
# ═══════════════════════════════════════════════════════════════

class DodecahedronEvaluator:
    """
    Maps reflection synthesis outputs onto 12 dodecahedron faces.
    Faces 0-6: canonical helices. Faces 7-11: emergent blend faces.
    Consensus requires >= 3 of 5 neighbors to agree.
    """

    def evaluate(
        self,
        helix_outputs: List[Dict[str, Any]],
        synthesis: Optional[Dict[str, Any]] = None,
    ) -> List[float]:
        face_scores = [0.0] * 12

        for i, ho in enumerate(helix_outputs[:7]):
            coherence = ho.get("sovereignty_adjusted", 0.0)
            face_scores[i] = coherence

        if synthesis:
            emergent_pairs = synthesis.get("top_emergent_pairs", [])
            for j, pair in enumerate(emergent_pairs[:5]):
                face_scores[7 + j] = pair.get("emergence", 0.0)

        per_helix = synthesis.get("per_helix_contributions", {}) if synthesis else {}
        fo_weight = FIRST_ORDER_WEIGHT
        so_weight = SECOND_ORDER_WEIGHT

        for i in range(min(7, len(helix_outputs))):
            func = helix_outputs[i].get("function", "")
            contrib = per_helix.get(func, 0.0)
            direct = helix_outputs[i].get("sovereignty_adjusted", 0.0)
            face_scores[i] = (
                DIRECT_HELIX_WEIGHT * direct
                + FIRST_ORDER_WEIGHT * contrib
                + SECOND_ORDER_WEIGHT * face_scores[i]
            )

        validated = self._consensus_validate(face_scores)
        return validated

    def _consensus_validate(self, scores: List[float]) -> List[float]:
        validated = list(scores)
        for face_idx, neighbors in DODECAHEDRON_ADJACENCY.items():
            if face_idx >= len(scores):
                continue
            my_score = scores[face_idx]
            agreeing = sum(
                1 for n in neighbors
                if n < len(scores) and abs(scores[n] - my_score) < CONSENSUS_DIVERGENCE
            )
            if agreeing < CONSENSUS_QUORUM:
                validated[face_idx] = my_score * CONSENSUS_ATTENUATION
        return validated


# ═══════════════════════════════════════════════════════════════
# DELTOIDAL ICOSITETRAHEDRON EVALUATOR (24 faces — fine resolution)
# ═══════════════════════════════════════════════════════════════

class IcositetragonEvaluator:
    """
    Maps quantum cognition outputs onto 24 deltoid (kite-shaped) faces
    of a Deltoidal Icositetrahedron (Catalan solid C_{24}).

    8 HelixFunction types × 3 scope levels = 24 faces.
    Each face has exactly 4 edge-neighbors (vs dodecahedron's 5).
    Consensus validation requires >= 3 of 4 neighbors to agree,
    mirroring the dodecahedron evaluator's geometric rigor.

    The adjacency graph is derived from the dual small
    rhombicuboctahedron's vertex-edge structure (48 edges, 26 vertices).
    """

    def __init__(self) -> None:
        all_functions = list(CANONICAL_FUNCTIONS) + ["emergent"]
        self._face_keys: List[str] = []
        for func in all_functions[:8]:
            for scope in SCOPE_LEVELS:
                self._face_keys.append(f"{func}:{scope}")

    def evaluate(
        self,
        helix_outputs: List[Dict[str, Any]],
        quantum_evaluation: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, float]:
        face_scores: Dict[str, float] = {}
        all_functions = list(CANONICAL_FUNCTIONS) + ["emergent"]

        for func in all_functions[:8]:
            ho = self._find_helix(helix_outputs, func)
            if not ho:
                for scope in SCOPE_LEVELS:
                    face_scores[f"{func}:{scope}"] = 0.0
                continue

            base_coherence = ho.get("sovereignty_adjusted", 0.0)
            strands = ho.get("strand_outputs", [])

            for scope_idx, scope in enumerate(SCOPE_LEVELS):
                scope_score = base_coherence
                if strands:
                    strand_slice = strands[scope_idx * 2: scope_idx * 2 + 3]
                    if strand_slice:
                        strand_avg = sum(
                            s.get("coherence_score", 0.0) for s in strand_slice
                        ) / len(strand_slice)
                        scope_score = strand_avg * 0.6 + base_coherence * 0.4

                scope_score *= (1.0 + SOVEREIGNTY_COEFFICIENT)
                face_scores[f"{func}:{scope}"] = min(1.0, scope_score)

        validated = self._consensus_validate(face_scores)
        return validated

    def _consensus_validate(self, scores: Dict[str, float]) -> Dict[str, float]:
        """Apply Deltoidal Icositetrahedron consensus validation.

        For each of the 24 faces, check whether >= 3 of its 4
        edge-neighbors agree within CONSENSUS_DIVERGENCE.  Faces
        that fail quorum are attenuated by CONSENSUS_ATTENUATION,
        dampening outlier scores that lack geometric support.
        """
        indexed = [scores.get(k, 0.0) for k in self._face_keys]
        validated = list(indexed)

        for face_idx, neighbors in DELTOIDAL_ICOSITETRAHEDRON_ADJACENCY.items():
            if face_idx >= len(indexed):
                continue
            my_score = indexed[face_idx]
            agreeing = sum(
                1 for n in neighbors
                if n < len(indexed) and abs(indexed[n] - my_score) < CONSENSUS_DIVERGENCE
            )
            if agreeing < ICOSI_CONSENSUS_QUORUM:
                validated[face_idx] = my_score * CONSENSUS_ATTENUATION

        return {
            self._face_keys[i]: validated[i]
            for i in range(min(len(self._face_keys), len(validated)))
        }

    def map_to_dodecahedron(self, icosi_scores: List[float]) -> List[float]:
        """Project 24 Deltoidal faces onto 12 dodecahedron faces via
        antipodal duality — each pair consists of geometrically opposite
        faces on the Catalan solid (the dual vertex coordinates are
        negated).  This replaces naive sequential 2:1 averaging with a
        geometrically principled projection.
        """
        dodec_scores: List[float] = []
        for face_a, face_b in DELTOIDAL_DUALITY_PAIRS:
            a = icosi_scores[face_a] if face_a < len(icosi_scores) else 0.0
            b = icosi_scores[face_b] if face_b < len(icosi_scores) else 0.0
            dodec_scores.append((a + b) / 2.0)
        return dodec_scores

    def _find_helix(
        self, helix_outputs: List[Dict[str, Any]], func: str
    ) -> Optional[Dict[str, Any]]:
        for ho in helix_outputs:
            if ho.get("function", "") == func:
                return ho
        return None


# ═══════════════════════════════════════════════════════════════
# RESONANCE COMPARATOR
# ═══════════════════════════════════════════════════════════════

class ResonanceComparator:
    """
    Aligns dodecahedron (12) and icositetragon (24) scores,
    computes per-helix amplitude vectors and resonance ratios.
    """

    def compare(
        self,
        dodec_scores: List[float],
        icosi_scores: Dict[str, float],
        bias: float = 1.0,
        session_context: Optional[Dict[str, Any]] = None,
    ) -> Tuple[Dict[str, AmplitudeVector], Dict[str, ODPESignal]]:
        amplitudes: Dict[str, AmplitudeVector] = {}
        signals: Dict[str, ODPESignal] = {}
        all_functions = list(CANONICAL_FUNCTIONS) + ["emergent"]

        for i, func in enumerate(all_functions[:8]):
            dodec_amp = dodec_scores[i] if i < len(dodec_scores) else 0.0

            func_faces = [
                icosi_scores.get(f"{func}:{scope}", 0.0)
                for scope in SCOPE_LEVELS
            ]
            icosi_amp = max(func_faces) if func_faces else 0.0

            ratio = dodec_amp / max(icosi_amp, AMPLITUDE_FLOOR)

            av = AmplitudeVector(
                dodec_amplitude=dodec_amp,
                icosi_amplitude=icosi_amp,
                resonance_ratio=ratio,
            )
            amplitudes[func] = av
            signals[func] = self._classify(av, bias, session_context)

        return amplitudes, signals

    def _classify(
        self,
        av: AmplitudeVector,
        bias: float,
        session_context: Optional[Dict[str, Any]] = None,
    ) -> ODPESignal:
        if av.dodec_amplitude < NOISE_THRESHOLD and av.icosi_amplitude < NOISE_THRESHOLD:
            return ODPESignal.NOISE

        if av.dodec_amplitude < NOISE_THRESHOLD or av.icosi_amplitude < NOISE_THRESHOLD:
            return ODPESignal.PROVISIONAL

        # --- LIMINAL RESOLVE detection (three OR triggers) ---
        ctx = session_context or {}
        _lr_triggered = False
        # (a) Crystal match exists but resonance in narrow hold-band + low experiential gravity
        if (av.dodec_amplitude > 0.4
                and 0.7 < av.resonance_ratio < 0.85
                and ctx.get("experiential_gravity", 1.0) < 0.30):
            _lr_triggered = True
        # (b) C_emo activation above session baseline + shame-adjacent domain
        if (not _lr_triggered
                and ctx.get("cemo_above_baseline", False)
                and ctx.get("shame_adjacent", False)):
            _lr_triggered = True
        # (c) Recurring LIMINAL theme cycle count >= 3
        if (not _lr_triggered
                and ctx.get("liminal_cycle_count", 0) >= 3):
            _lr_triggered = True

        if _lr_triggered:
            return ODPESignal.LIMINAL_RESOLVE

        r = av.resonance_ratio
        locked_lo = LOCKED_LOW * bias
        locked_hi = LOCKED_HIGH * bias
        promoted_lo = PROMOTED_LOW * bias
        promoted_hi = PROMOTED_HIGH * bias

        if locked_lo <= r <= locked_hi:
            return ODPESignal.LOCKED
        elif promoted_lo <= r < locked_lo or locked_hi < r <= promoted_hi:
            return ODPESignal.PROMOTED
        elif av.icosi_amplitude > 0.8:
            return ODPESignal.DEEP_TENSION
        else:
            return ODPESignal.TENSION


# ═══════════════════════════════════════════════════════════════
# HECTAKIS L1 EVALUATOR (2,400 faces — presenting concern clusters)
# ═══════════════════════════════════════════════════════════════

L1_ADJACENCY_INTRA = 4
L1_ADJACENCY_CROSS = 2
L1_CONSENSUS_QUORUM = 3


class HectakisL1Evaluator:
    """
    Evaluates 2,400 L1 faces (100 per L0 face).
    Only activated L0 faces (score > NOISE_THRESHOLD) have their
    L1 sub-faces evaluated — pruning irrelevant branches.

    Each L1 face has 6 neighbors: 4 within its L0 parent (adjacent
    concern clusters) and 2 cross-L0 neighbors (same concern in
    neighboring L0 faces).
    """

    def __init__(self, taxonomy=None):
        self._taxonomy = taxonomy

    def evaluate(
        self,
        l0_scores: Dict[str, float],
        query_text: str = "",
        helix_outputs: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, float]:
        """Evaluate L1 faces for activated L0 faces.

        Returns dict of face_path -> score for activated L1 faces only.
        face_path format: "l0_key:l1_label" (e.g., "noetic_fusion:user:anxiety_attachment")
        """
        if not self._taxonomy:
            return {}

        l1_scores: Dict[str, float] = {}

        for l0_key, l0_score in l0_scores.items():
            if l0_score < NOISE_THRESHOLD:
                continue

            activations = self._taxonomy.classify(query_text, l0_key)

            for l1_label, activation_score in activations[:20]:
                face_path = f"{l0_key}:{l1_label}"
                l1_scores[face_path] = activation_score * l0_score

        validated = self._consensus_validate_l1(l1_scores)
        return validated

    def _consensus_validate_l1(self, scores: Dict[str, float]) -> Dict[str, float]:
        """L1 consensus: check 4 intra-L0 neighbors + 2 cross-L0 neighbors."""
        if len(scores) < 2:
            return scores

        validated = dict(scores)
        score_list = list(scores.items())

        for i, (face_path, score) in enumerate(score_list):
            neighbors_scores = []
            parts = face_path.rsplit(":", 1)
            if len(parts) < 2:
                continue
            l0_prefix = parts[0]
            l1_label = parts[1]

            for j, (other_path, other_score) in enumerate(score_list):
                if i == j:
                    continue
                if other_path.startswith(l0_prefix + ":"):
                    neighbors_scores.append(other_score)
                elif other_path.endswith(":" + l1_label):
                    neighbors_scores.append(other_score)

            if len(neighbors_scores) < L1_CONSENSUS_QUORUM:
                continue

            agreeing = sum(
                1 for ns in neighbors_scores[:6]
                if abs(ns - score) < CONSENSUS_DIVERGENCE
            )
            if agreeing < L1_CONSENSUS_QUORUM:
                validated[face_path] = score * CONSENSUS_ATTENUATION

        return validated

    def classify_signal(self, l1_scores: Dict[str, float]) -> Tuple[str, str]:
        """Classify aggregate L1 signal and return (dominant_signal, dominant_face_path).

        Uses the same thresholds as L0 but applied to the L1 score distribution.
        """
        if not l1_scores:
            return "PROVISIONAL", ""

        max_path = max(l1_scores, key=l1_scores.get)
        max_score = l1_scores[max_path]

        avg_score = sum(l1_scores.values()) / len(l1_scores)
        score_spread = max_score - avg_score

        if max_score > 0.7 and score_spread > 0.3:
            return "DEEP_TENSION", max_path
        elif max_score > 0.5:
            return "TENSION", max_path
        elif max_score > 0.3 and len(l1_scores) > 3:
            return "LOCKED", max_path
        elif max_score > 0.2:
            return "PROMOTED", max_path
        else:
            return "PROVISIONAL", max_path


# ═══════════════════════════════════════════════════════════════
# HECTAKIS L2 EVALUATOR (24M faces — micro-therapeutic moments)
# ═══════════════════════════════════════════════════════════════

L2_MAX_FACES_PER_L1 = 10000
L2_CLUSTER_SIMILARITY_THRESHOLD = 0.85


class HectakisL2Evaluator:
    """
    Evaluates L2 micro-therapeutic-moment faces.
    Only invoked when L1 signals TENSION or DEEP_TENSION on specific branches.

    L2 faces are emergent — they self-organize from the crystal corpus.
    New L2 faces are created when crystals don't match existing clusters.
    L2 faces pruned after 90 days without new crystals.
    """

    def __init__(self, db_pool=None):
        self._db_pool = db_pool
        self._l2_cache: Dict[str, List[Dict[str, Any]]] = {}

    async def evaluate(
        self,
        l1_tension_faces: Dict[str, float],
        crystals: Optional[List[Dict[str, Any]]] = None,
        query_text: str = "",
    ) -> Dict[str, float]:
        """Evaluate L2 faces for L1 TENSION branches.

        Returns dict of full face_path -> score.
        face_path: "l0:scope:l1_label:l2_moment"
        """
        l2_scores: Dict[str, float] = {}

        for l1_path, l1_score in l1_tension_faces.items():
            if l1_score < 0.3:
                continue

            l2_faces = await self._get_or_create_l2_faces(l1_path, crystals, query_text)

            for l2_face in l2_faces[:50]:
                l2_path = f"{l1_path}:{l2_face['label']}"
                l2_scores[l2_path] = l2_face["score"] * l1_score

        return l2_scores

    async def _get_or_create_l2_faces(
        self,
        l1_path: str,
        crystals: Optional[List[Dict[str, Any]]],
        query_text: str,
    ) -> List[Dict[str, Any]]:
        """Get existing L2 faces for an L1 path, or create from crystal corpus."""
        if l1_path in self._l2_cache:
            cached = self._l2_cache[l1_path]
            scored = self._score_l2_faces(cached, query_text)
            return scored

        if not self._db_pool:
            return self._create_heuristic_l2(l1_path, query_text)

        try:
            async with self._db_pool.acquire() as conn:
                rows = await conn.fetch(
                    """SELECT l2_label, keywords, crystal_count, clinical_weight
                       FROM odpe_l2_faces
                       WHERE l1_face_path = $1
                       ORDER BY crystal_count DESC
                       LIMIT 500""",
                    l1_path,
                )
                if rows:
                    faces = [
                        {
                            "label": r["l2_label"],
                            "keywords": r["keywords"] if isinstance(r["keywords"], list) else [],
                            "crystal_count": r["crystal_count"],
                            "weight": r["clinical_weight"],
                        }
                        for r in rows
                    ]
                    self._l2_cache[l1_path] = faces
                    return self._score_l2_faces(faces, query_text)
        except Exception as e:
            logger.warning("L2 face lookup failed for %s: %s", l1_path, e)

        return self._create_heuristic_l2(l1_path, query_text)

    def _score_l2_faces(
        self, faces: List[Dict[str, Any]], query_text: str
    ) -> List[Dict[str, Any]]:
        text_lower = query_text.lower()
        scored = []
        for face in faces:
            kws = face.get("keywords", [])
            if not kws:
                scored.append({**face, "score": 0.1})
                continue
            hits = sum(1 for kw in kws if kw in text_lower)
            score = min(1.0, (hits / max(len(kws), 1)) * face.get("weight", 1.0))
            scored.append({**face, "score": max(score, 0.05)})
        scored.sort(key=lambda x: x["score"], reverse=True)
        return scored

    def _create_heuristic_l2(
        self, l1_path: str, query_text: str
    ) -> List[Dict[str, Any]]:
        """Create temporary L2 faces from query text analysis when DB is unavailable."""
        words = query_text.lower().split()
        if not words:
            return []

        time_markers = ["morning", "evening", "night", "afternoon", "weekend", "monday", "tuesday",
                        "wednesday", "thursday", "friday", "saturday", "sunday", "work", "home", "school"]
        intensity_markers = ["very", "extremely", "slightly", "always", "never", "sometimes",
                            "overwhelming", "mild", "severe", "constant", "occasional"]

        faces = []
        for marker in time_markers:
            if marker in words:
                faces.append({"label": f"temporal_{marker}", "keywords": [marker], "weight": 1.0, "score": 0.6})

        for marker in intensity_markers:
            if marker in words:
                faces.append({"label": f"intensity_{marker}", "keywords": [marker], "weight": 1.0, "score": 0.5})

        if not faces:
            faces.append({"label": "unspecified_moment", "keywords": [], "weight": 0.5, "score": 0.3})

        return faces[:10]

    def health(self) -> Dict[str, Any]:
        return {
            "status": "healthy",
            "cached_l1_paths": len(self._l2_cache),
            "total_cached_l2_faces": sum(len(v) for v in self._l2_cache.values()),
        }


# ═══════════════════════════════════════════════════════════════
# LIMINAL EQUILIBRIUM READER
# ═══════════════════════════════════════════════════════════════

class LiminalEquilibriumReader:
    """
    Reads signals from the 3 liminal presence agents and adjusts
    the oscillation bias between dodecahedron and icositetragon.
    """

    def __init__(self, db_pool=None):
        self._db_pool = db_pool
        self._current_bias = 1.0
        self._query_count = 0

    async def read_and_adjust(self) -> float:
        self._query_count += 1

        if not self._db_pool:
            return self._current_bias

        try:
            async with self._db_pool.acquire() as conn:
                rows = await conn.fetch("""
                    SELECT DISTINCT ON (agent) agent, signal, score,
                           metadata, created_at
                    FROM liminal_presence_analysis
                    WHERE agent IN ('silence_sentinel', 'language_drift', 'field_response')
                    ORDER BY agent, created_at DESC
                """)

                icosi_bias_delta = 0.0
                dodec_bias_delta = 0.0
                tension_multiplier = 1.0

                for row in rows:
                    agent = row["agent"]
                    signal = (row["signal"] or "").upper()
                    metadata = row["metadata"] if row["metadata"] else {}

                    if isinstance(metadata, str):
                        import json
                        try:
                            metadata = json.loads(metadata)
                        except Exception:
                            metadata = {}

                    if agent == "language_drift":
                        if signal == "RED":
                            icosi_bias_delta += 0.2
                        elif signal == "GREEN":
                            dodec_bias_delta += 0.1

                    elif agent == "silence_sentinel":
                        if signal == "RED":
                            icosi_bias_delta += 0.1

                    elif agent == "field_response":
                        categories = metadata.get("categories", {})
                        if categories.get("authority_transfer", 0) > 0:
                            tension_multiplier = 0.8

                net_delta = dodec_bias_delta - icosi_bias_delta
                self._current_bias += net_delta

                decay = (1.0 - self._current_bias) * BIAS_DECAY_PER_CYCLE
                self._current_bias += decay

                self._current_bias = max(
                    1.0 - MAX_BIAS_DEVIATION,
                    min(1.0 + MAX_BIAS_DEVIATION, self._current_bias),
                )

        except Exception as e:
            logger.warning("LiminalEquilibriumReader: query failed: %s", e)

        return self._current_bias

    def get_status(self) -> Dict[str, Any]:
        return {
            "current_bias": round(self._current_bias, 4),
            "query_count": self._query_count,
        }


# ═══════════════════════════════════════════════════════════════
# ODPE ENGINE (unified entry point)
# ═══════════════════════════════════════════════════════════════

class ODPEEngine:
    """
    Oscillating Dual-Process Echo Engine.

    Runs dodecahedron and icositetragon evaluations concurrently,
    computes amplitude vectors, classifies signals, reads liminal
    feedback, and returns resource-allocation directives.
    """

    def __init__(self, db_pool=None):
        self._db_pool = db_pool
        self._dodec_evaluator = DodecahedronEvaluator()
        self._icosi_evaluator = IcositetragonEvaluator()
        self._comparator = ResonanceComparator()
        self._liminal_reader = LiminalEquilibriumReader(db_pool=db_pool)
        self._l1_evaluator: Optional[HectakisL1Evaluator] = None
        self._l2_evaluator: Optional[HectakisL2Evaluator] = None
        self._evaluation_count = 0
        self._last_result: Optional[ODPEResult] = None

        logger.info(">>> [ODPE] Engine initialized — dual topology ready")

    def set_hierarchical_evaluators(self, l1_evaluator=None, l2_evaluator=None):
        """Wire hierarchical evaluators after taxonomy is loaded."""
        self._l1_evaluator = l1_evaluator
        self._l2_evaluator = l2_evaluator
        logger.info(">>> [ODPE] Hierarchical evaluators set: L1=%s L2=%s",
                     l1_evaluator is not None, l2_evaluator is not None)

    async def evaluate(
        self,
        helix_outputs: List[Dict[str, Any]],
        reflection_synthesis: Optional[Dict[str, Any]] = None,
        quantum_evaluation: Optional[Dict[str, Any]] = None,
        crystals: Optional[List[Dict[str, Any]]] = None,
    ) -> ODPEResult:
        start = time.monotonic()
        self._evaluation_count += 1

        result = ODPEResult()

        bias = await self._liminal_reader.read_and_adjust()

        dodec_scores = self._dodec_evaluator.evaluate(
            helix_outputs, reflection_synthesis
        )

        icosi_scores = self._icosi_evaluator.evaluate(
            helix_outputs, quantum_evaluation
        )

        amplitudes, signals = self._comparator.compare(
            dodec_scores, icosi_scores, bias=bias
        )

        result.per_helix_signals = {k: v.value for k, v in signals.items()}
        result.per_helix_amplitudes = {
            k: {
                "dodec": round(v.dodec_amplitude, 4),
                "icosi": round(v.icosi_amplitude, 4),
                "ratio": round(v.resonance_ratio, 4),
            }
            for k, v in amplitudes.items()
        }

        non_noise = [
            v for v in amplitudes.values()
            if signals.get(
                next(k for k, val in amplitudes.items() if val is v), ODPESignal.NOISE
            ) != ODPESignal.NOISE
        ]

        all_amps = list(amplitudes.values())
        if all_amps:
            result.aggregate_dodec = sum(a.dodec_amplitude for a in all_amps) / len(all_amps)
            result.aggregate_icosi = sum(a.icosi_amplitude for a in all_amps) / len(all_amps)
            result.aggregate_resonance = (
                result.aggregate_dodec / max(result.aggregate_icosi, AMPLITUDE_FLOOR)
            )

        signal_counts: Dict[str, int] = {}
        for sig in signals.values():
            signal_counts[sig.value] = signal_counts.get(sig.value, 0) + 1

        total_signals = len(signals)
        result.noise_ratio = signal_counts.get("NOISE", 0) / max(total_signals, 1)
        result.tension_count = signal_counts.get("TENSION", 0)
        result.locked_count = signal_counts.get("LOCKED", 0)

        if total_signals > 0:
            result.dominant_signal = max(signal_counts, key=signal_counts.get)

        context_budgets = []
        for func, sig in signals.items():
            if sig == ODPESignal.LOCKED:
                context_budgets.append(CONTEXT_TOKENS_LOCKED)
            elif sig == ODPESignal.TENSION:
                context_budgets.append(CONTEXT_TOKENS_TENSION)
            elif sig == ODPESignal.NOISE:
                pass
            else:
                context_budgets.append(CONTEXT_TOKENS_PROMOTED)

        if context_budgets:
            result.recommended_context_tokens = int(
                sum(context_budgets) / len(context_budgets)
            )

        tier_priority = {"clinical": 3, "domain_default": 2, "utility": 1, "skip": 0}
        max_tier = "domain_default"
        max_tier_score = 0
        for sig in signals.values():
            if sig == ODPESignal.NOISE:
                continue
            tier = TIER_FOR_SIGNAL.get(sig, "domain_default")
            score = tier_priority.get(tier, 0)
            if score > max_tier_score:
                max_tier_score = score
                max_tier = tier
        result.recommended_inference_tier = max_tier

        result.oscillation_profile = {
            "bias": round(bias, 4),
            "dominant_topology": (
                "dodecahedron" if result.aggregate_dodec >= result.aggregate_icosi
                else "icositetragon"
            ),
            "signal_distribution": signal_counts,
            "evaluation_count": self._evaluation_count,
        }

        # ── Hierarchical evaluation: L1 (2,400 faces) → L2 (24M faces) ──
        if self._l1_evaluator and icosi_scores:
            try:
                query_text = ""
                if helix_outputs:
                    for ho in helix_outputs:
                        query_text = ho.get("query", ho.get("prompt", ""))
                        if query_text:
                            break

                l1_scores = self._l1_evaluator.evaluate(
                    l0_scores=icosi_scores,
                    query_text=query_text,
                    helix_outputs=helix_outputs,
                )
                result.l1_scores = l1_scores
                result.hierarchical_depth = 1

                if l1_scores:
                    l1_signal, l1_dominant = self._l1_evaluator.classify_signal(l1_scores)
                    result.face_path = l1_dominant

                    if l1_signal in ("TENSION", "DEEP_TENSION") and self._l2_evaluator:
                        tension_faces = {
                            k: v for k, v in l1_scores.items()
                            if v > 0.3
                        }
                        if tension_faces:
                            l2_scores = await self._l2_evaluator.evaluate(
                                l1_tension_faces=tension_faces,
                                crystals=crystals,
                                query_text=query_text,
                            )
                            if l2_scores:
                                result.l2_scores = l2_scores
                                result.hierarchical_depth = 2
                                l2_dominant = max(l2_scores, key=l2_scores.get)
                                result.face_path = l2_dominant

            except Exception as e:
                logger.warning("ODPE hierarchical evaluation failed (non-fatal): %s", e)

        result.evaluation_time_ms = (time.monotonic() - start) * 1000
        self._last_result = result

        # QUANTUM-CRYSTAL-ARCH: persist L0 face activation counts
        if self._db_pool:
            asyncio.ensure_future(self._persist_face_activations(
                dodec_scores, icosi_scores, result.l1_scores,
            ))

        logger.info(
            ">>> [ODPE] Cycle #%d — dominant=%s, context=%d, tier=%s, "
            "bias=%.3f, locked=%d, tension=%d, noise=%.2f, depth=L%d, "
            "face=%s — %.1fms",
            self._evaluation_count,
            result.dominant_signal,
            result.recommended_context_tokens,
            result.recommended_inference_tier,
            bias,
            result.locked_count,
            result.tension_count,
            result.noise_ratio,
            result.hierarchical_depth,
            result.face_path[:60],
            result.evaluation_time_ms,
        )

        return result

    def get_status(self) -> Dict[str, Any]:
        last = self._last_result
        return {
            "status": "healthy",
            "evaluation_count": self._evaluation_count,
            "dual_topology_initialized": True,
            "liminal_reader": self._liminal_reader.get_status(),
            "last_dominant_signal": last.dominant_signal if last else None,
            "last_context_tokens": last.recommended_context_tokens if last else None,
            "last_inference_tier": last.recommended_inference_tier if last else None,
            "l1_evaluator": self._l1_evaluator is not None,
            "l2_evaluator": self._l2_evaluator is not None,
            "last_face_path": last.face_path if last else None,
            "last_hierarchical_depth": last.hierarchical_depth if last else 0,
        }

    async def _persist_face_activations(
        self,
        dodec_scores: List[float],
        icosi_scores: Dict[str, float],
        l1_scores: Dict[str, float],
    ) -> None:
        """QUANTUM-CRYSTAL-ARCH: persist L0 face activation counts to
        odpe_face_activations so dashboards can render per-face heatmaps."""
        if not self._db_pool:
            return
        try:
            async with self._db_pool.acquire() as conn:
                for idx, score in enumerate(dodec_scores):
                    if score > 0.01:
                        await conn.execute(
                            """INSERT INTO odpe_face_activations
                                (topology, face_index, activation_count, cumulative_score, last_score, last_activated)
                               VALUES ('dodec', $1, 1, $2, $2, NOW())
                               ON CONFLICT (topology, face_index) DO UPDATE SET
                                   activation_count = odpe_face_activations.activation_count + 1,
                                   cumulative_score = odpe_face_activations.cumulative_score + $2,
                                   last_score = $2,
                                   last_activated = NOW()""",
                            str(idx), round(float(score), 4),
                        )
                for face_key, score in icosi_scores.items():
                    if score > 0.01:
                        await conn.execute(
                            """INSERT INTO odpe_face_activations
                                (topology, face_index, activation_count, cumulative_score, last_score, last_activated)
                               VALUES ('icosi', $1, 1, $2, $2, NOW())
                               ON CONFLICT (topology, face_index) DO UPDATE SET
                                   activation_count = odpe_face_activations.activation_count + 1,
                                   cumulative_score = odpe_face_activations.cumulative_score + $2,
                                   last_score = $2,
                                   last_activated = NOW()""",
                            str(face_key), round(float(score), 4),
                        )
                for path, score in (l1_scores or {}).items():
                    if score > 0.05:
                        await conn.execute(
                            """INSERT INTO odpe_face_activations
                                (topology, face_index, activation_count, cumulative_score, last_score, last_activated)
                               VALUES ('l1', $1, 1, $2, $2, NOW())
                               ON CONFLICT (topology, face_index) DO UPDATE SET
                                   activation_count = odpe_face_activations.activation_count + 1,
                                   cumulative_score = odpe_face_activations.cumulative_score + $2,
                                   last_score = $2,
                                   last_activated = NOW()""",
                            str(path)[:64], round(float(score), 4),
                        )
        except Exception as e:
            logger.debug("ODPE face activation persist (non-fatal): %s", e)

    async def boost_from_cycle(self, cycle_detection: Dict[str, Any]) -> Optional[str]:
        """
        Accept a cycle detection and boost the corresponding face paths.
        Returns the face_path that was boosted, if applicable.

        Cycle detections come from CycleDetectionEngine and contain:
          domain, period_days, phase, amplitude, confidence
        """
        try:
            taxonomy = getattr(self, '_l1_evaluator', None)
            if not taxonomy or not hasattr(taxonomy, '_taxonomy'):
                return None

            from app.services.odpe_taxonomy import ODPETaxonomy
            tax = taxonomy._taxonomy if hasattr(taxonomy, '_taxonomy') else None
            if not tax:
                return None

            face_path = tax.classify_cycle(cycle_detection)
            if not face_path or face_path == "L0/0":
                return None

            if self._db_pool:
                async with self._db_pool.acquire() as conn:
                    await conn.execute("""
                        INSERT INTO odpe_l2_faces (face_path, activation_count, last_activated)
                        VALUES ($1, 1, NOW())
                        ON CONFLICT (face_path) DO UPDATE SET
                            activation_count = odpe_l2_faces.activation_count + 1,
                            last_activated = NOW()
                    """, face_path)

            logger.info(">>> [ODPE] Cycle boost: face_path=%s domain=%s period=%.1f",
                        face_path, cycle_detection.get("domain"), cycle_detection.get("period_days", 0))
            return face_path
        except Exception as e:
            logger.warning("ODPE cycle boost failed (non-fatal): %s", e)
            return None

    def health(self) -> Dict[str, Any]:
        return {
            "status": "healthy",
            "evaluations": self._evaluation_count,
            "dodecahedron_ready": True,
            "icositetragon_ready": True,
            "liminal_reader_ready": self._db_pool is not None,
            "l1_evaluator_ready": self._l1_evaluator is not None,
            "l2_evaluator_ready": self._l2_evaluator is not None,
            "last_signal_valid": (
                self._last_result is not None
                and self._last_result.dominant_signal in [s.value for s in ODPESignal]
            ) if self._last_result else True,
        }
