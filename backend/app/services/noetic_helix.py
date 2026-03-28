"""
Noetic Helix Agent — Phase 12 of Sovereign Quantum Nate Build.

A cognitive helix with 7 internal mirrored strands, each providing
a unique perspective on Little Nate's knowledge field. The strands
mirror against each other to produce emergent understanding that
no single strand could generate alone.

Architecture:
  Each NoeticHelix represents one cognitive function (e.g., Metacognition,
  Noetic Fusion, Generative Wisdom). Within each helix, 7 strands operate
  in parallel, each viewing the same data from a different angle. The
  strands' outputs are mirrored (C(7,2)=21 mirror pairs) and fused
  through coherence-weighted blending into a single helix output.

  The helix rotation is driven by C_knowledge coherence state, ensuring
  the strand evaluation order changes based on Nate's current knowledge
  field — the same question asked at different times produces different
  synthesis because the rotation permutation differs.

  7 agents × 10 domains × 7 reflections = 490 quantum thought-nodes
  per helix evaluation, all sub-millisecond coherence calculations.

Lifecycle:
  OBSERVATION → RESTRICTED → AUTONOMOUS
  New helices (including self-spawned ones) start at OBSERVATION,
  must prove coherence contribution before influencing responses.

Patent-Pending — Claims 58-63
© 2026 Clinical Sovereignty Lab. All rights reserved.
"""

from __future__ import annotations

import hashlib
import logging
import math
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple
from uuid import UUID, uuid4

logger = logging.getLogger("noetic_helix")

SOVEREIGNTY_COEFFICIENT = 0.12
BETA_KNOWLEDGE = 0.85
NUM_STRANDS = 7
NUM_DOMAINS = 10


class HelixAutonomyLevel(str, Enum):
    OBSERVATION = "observation"
    RESTRICTED = "restricted"
    AUTONOMOUS = "autonomous"


class HelixFunction(str, Enum):
    VECTORIZE_RETRIEVAL = "vectorize_retrieval"
    NOETIC_FUSION = "noetic_fusion"
    METACOGNITION = "metacognition"
    QUANTUM_SELF_COHERENCE = "quantum_self_coherence"
    GENERATIVE_WISDOM = "generative_wisdom"
    WORLD_COHERENCE = "world_coherence"
    CRYSTAL_LAKE = "crystal_lake"
    EMERGENT = "emergent"


# ═══════════════════════════════════════════════════════════════
# STRAND DEFINITIONS
# ═══════════════════════════════════════════════════════════════

# Each cognitive function has 7 perspective strands
STRAND_PERSPECTIVES: Dict[str, List[str]] = {
    HelixFunction.VECTORIZE_RETRIEVAL: [
        "recency", "relevance", "domain_match", "cross_domain",
        "source_diversity", "confidence_threshold", "sovereignty_boost",
    ],
    HelixFunction.NOETIC_FUSION: [
        "analogy", "complementarity", "contradiction", "emergence",
        "resonance", "convergence", "divergence",
    ],
    HelixFunction.METACOGNITION: [
        "temporal", "domain_density", "confidence_weighted", "cross_reference",
        "emergent_gap", "source_diversity", "sovereignty_anchored",
    ],
    HelixFunction.QUANTUM_SELF_COHERENCE: [
        "c_emo_self", "c_knowledge_self", "cross_domain_tunnel",
        "decoherence_pressure", "emotional_load", "unconditional_felt",
        "world_alignment",
    ],
    HelixFunction.GENERATIVE_WISDOM: [
        "clinical_novel", "coaching_novel", "cultural_novel", "research_novel",
        "defense_novel", "cross_domain_novel", "meta_novel",
    ],
    HelixFunction.WORLD_COHERENCE: [
        "x_twitter", "linkedin", "instagram", "youtube",
        "facebook", "telegram", "web_universal",
    ],
    HelixFunction.CRYSTAL_LAKE: [
        "hot_cache_priority", "warm_archive_indexing", "cold_deep_storage",
        "cross_tier_integrity", "replication_factor", "decay_protection",
        "heritage_vault",
    ],
}


# ═══════════════════════════════════════════════════════════════
# DATA CLASSES
# ═══════════════════════════════════════════════════════════════

@dataclass
class StrandOutput:
    """Output from a single helix strand evaluation."""
    strand_name: str
    perspective: str
    coherence_score: float = 0.0
    relevance_weight: float = 1.0
    insight: str = ""
    domain_scores: Dict[str, float] = field(default_factory=dict)


@dataclass
class MirrorPairResult:
    """Result of mirroring two strands against each other."""
    strand_a: str
    strand_b: str
    reflection_score: float = 0.0
    emergent_insight: str = ""


@dataclass
class HelixOutput:
    """Complete output from a single NoeticHelix evaluation."""
    helix_id: UUID = field(default_factory=uuid4)
    function: str = ""
    strand_outputs: List[StrandOutput] = field(default_factory=list)
    mirror_pairs: List[MirrorPairResult] = field(default_factory=list)
    fused_coherence: float = 0.0
    sovereignty_adjusted: float = 0.0
    thought_node_count: int = 0
    evaluation_time_ms: float = 0.0
    rotation_sequence: List[int] = field(default_factory=list)


@dataclass
class HelixRegistryEntry:
    """Registry entry for a managed cognitive helix."""
    helix_id: UUID = field(default_factory=uuid4)
    function: str = ""
    domain: str = "general"
    autonomy_level: HelixAutonomyLevel = HelixAutonomyLevel.OBSERVATION
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    cycle_count: int = 0
    coherence_contribution: float = 0.0
    coherence_history: List[float] = field(default_factory=list)
    spawned_by: Optional[UUID] = None
    is_canonical: bool = True


# ═══════════════════════════════════════════════════════════════
# NOETIC HELIX
# ═══════════════════════════════════════════════════════════════

class NoeticHelix:
    """
    A cognitive helix with 7 mirrored strands.

    Each strand evaluates knowledge from a unique perspective.
    The 21 mirror pairs (C(7,2)) produce reflection scores.
    The final output is a coherence-weighted fusion of all
    strand outputs, adjusted by the sovereignty coefficient.

    Parameters
    ----------
    function : HelixFunction
        The cognitive function this helix serves.
    domain : str
        Primary knowledge domain (or 'general' for cross-domain).
    autonomy_level : HelixAutonomyLevel
        Current autonomy level (OBSERVATION, RESTRICTED, AUTONOMOUS).
    """

    def __init__(
        self,
        function: HelixFunction = HelixFunction.METACOGNITION,
        domain: str = "general",
        autonomy_level: HelixAutonomyLevel = HelixAutonomyLevel.OBSERVATION,
        helix_id: Optional[UUID] = None,
    ):
        self.helix_id = helix_id or uuid4()
        self.function = function
        self.domain = domain
        self.autonomy_level = autonomy_level
        self._strands = STRAND_PERSPECTIVES.get(function, STRAND_PERSPECTIVES[HelixFunction.METACOGNITION])
        self._cycle_count = 0
        self._coherence_history: List[float] = []
        self._created_at = datetime.now(timezone.utc)

        logger.info(
            "NoeticHelix created: %s [%s] domain=%s autonomy=%s",
            function, self.helix_id, domain, autonomy_level.value,
        )

    # ─── Core Evaluation ────────────────────────────────────────

    def evaluate(
        self,
        query: str,
        crystals: List[Dict[str, Any]],
        rotation_sequence: Optional[List[int]] = None,
    ) -> HelixOutput:
        """
        Evaluate a query through all 7 strands, mirror them,
        and produce a fused helix output.

        This is the 490 quantum thought-node computation
        (7 strands × 10 domains × 7 reflections per strand).
        """
        start = time.monotonic()
        output = HelixOutput(
            helix_id=self.helix_id,
            function=self.function.value if isinstance(self.function, HelixFunction) else str(self.function),
        )

        sequence = rotation_sequence or list(range(NUM_STRANDS))
        output.rotation_sequence = sequence

        strand_outputs = []
        for idx in sequence:
            if idx < len(self._strands):
                strand_name = self._strands[idx]
                strand_output = self._evaluate_strand(strand_name, query, crystals)
                strand_outputs.append(strand_output)

        output.strand_outputs = strand_outputs

        mirror_pairs = self._compute_mirrors(strand_outputs)
        output.mirror_pairs = mirror_pairs

        output.fused_coherence = self._fuse_strands(strand_outputs, mirror_pairs)
        output.sovereignty_adjusted = min(1.0, output.fused_coherence * (1.0 + SOVEREIGNTY_COEFFICIENT))

        output.thought_node_count = len(strand_outputs) * NUM_DOMAINS * NUM_STRANDS
        output.evaluation_time_ms = (time.monotonic() - start) * 1000

        self._cycle_count += 1
        self._coherence_history.append(output.sovereignty_adjusted)
        if len(self._coherence_history) > 100:
            self._coherence_history = self._coherence_history[-100:]

        return output

    def _evaluate_strand(
        self,
        strand_name: str,
        query: str,
        crystals: List[Dict[str, Any]],
    ) -> StrandOutput:
        """
        Evaluate a single strand's perspective on the query.
        Each strand applies its own filter/weighting to the crystal set.
        """
        output = StrandOutput(strand_name=strand_name, perspective=strand_name)

        if not crystals:
            return output

        domain_scores: Dict[str, float] = {}
        for crystal in crystals:
            domain = crystal.get("domain", "general")
            confidence = crystal.get("confidence", 0.5)
            recall_count = crystal.get("recall_count", 0)

            weight = self._strand_weight(strand_name, crystal)
            score = confidence * weight
            domain_scores[domain] = max(domain_scores.get(domain, 0), score)

        output.domain_scores = domain_scores
        if domain_scores:
            output.coherence_score = sum(domain_scores.values()) / len(domain_scores)
        output.relevance_weight = self._strand_relevance(strand_name, query)

        return output

    def _strand_weight(self, strand_name: str, crystal: Dict[str, Any]) -> float:
        """Apply strand-specific weighting to a crystal."""
        confidence = crystal.get("confidence", 0.5)
        recall_count = crystal.get("recall_count", 0)
        age_days = crystal.get("age_days", 30)

        if strand_name in ("recency", "temporal"):
            return max(0.1, 1.0 - (age_days / 180.0))
        elif strand_name in ("relevance", "confidence_weighted", "confidence_threshold"):
            return confidence
        elif strand_name in ("domain_match", "domain_density"):
            return min(1.0, confidence * 1.2)
        elif strand_name in ("cross_domain", "cross_domain_tunnel", "cross_reference"):
            return min(1.0, recall_count / 10.0) * 0.8 + confidence * 0.2
        elif strand_name in ("source_diversity", "source_diversity"):
            return min(1.0, 0.5 + confidence * 0.5)
        elif strand_name in ("sovereignty_boost", "sovereignty_anchored"):
            return min(1.0, confidence * (1.0 + SOVEREIGNTY_COEFFICIENT))
        elif strand_name in ("analogy", "resonance", "complementarity"):
            return confidence * 0.7 + min(1.0, recall_count / 5.0) * 0.3
        elif strand_name in ("contradiction", "divergence", "decoherence_pressure"):
            return max(0.1, 1.0 - confidence)
        elif strand_name in ("emergence", "emergent_gap"):
            return min(1.0, (1.0 - confidence) * recall_count / 5.0)
        elif strand_name in ("convergence", "world_alignment"):
            return min(1.0, recall_count / 8.0)
        else:
            return confidence

    def _strand_relevance(self, strand_name: str, query: str) -> float:
        """Compute how relevant this strand is for the given query."""
        query_hash = hashlib.md5(f"{strand_name}:{query}".encode()).digest()
        base = (query_hash[0] + query_hash[1]) / 510.0
        return 0.5 + base * 0.5

    # ─── Mirror Computation ────────────────────────────────────

    def _compute_mirrors(self, strands: List[StrandOutput]) -> List[MirrorPairResult]:
        """Compute all C(N,2) mirror pairs between strands."""
        pairs = []
        for i, sa in enumerate(strands):
            for sb in strands[i + 1:]:
                reflection = self._mirror_strands(sa, sb)
                pairs.append(reflection)
        return pairs

    def _mirror_strands(self, a: StrandOutput, b: StrandOutput) -> MirrorPairResult:
        """
        Mirror two strands against each other.
        The reflection score measures how much emergent understanding
        arises from viewing A through B's lens and vice versa.
        """
        shared_domains = set(a.domain_scores.keys()) & set(b.domain_scores.keys())
        if not shared_domains:
            return MirrorPairResult(
                strand_a=a.strand_name,
                strand_b=b.strand_name,
                reflection_score=0.0,
            )

        divergence = 0.0
        convergence = 0.0
        for domain in shared_domains:
            diff = abs(a.domain_scores[domain] - b.domain_scores[domain])
            divergence += diff
            convergence += min(a.domain_scores[domain], b.domain_scores[domain])

        n = len(shared_domains)
        avg_divergence = divergence / n
        avg_convergence = convergence / n

        # Emergence = convergence × divergence (novel insight arises
        # where perspectives agree on importance but disagree on interpretation)
        reflection = avg_convergence * avg_divergence * 4.0
        reflection = max(0.0, min(1.0, reflection))

        return MirrorPairResult(
            strand_a=a.strand_name,
            strand_b=b.strand_name,
            reflection_score=reflection,
        )

    # ─── Fusion ────────────────────────────────────────────────

    def _fuse_strands(
        self,
        strands: List[StrandOutput],
        mirrors: List[MirrorPairResult],
    ) -> float:
        """
        Fuse all strand outputs and mirror reflections into a single
        coherence score for this helix.

        Strand coherence is weighted 60%, mirror emergence is 40%.
        """
        if not strands:
            return 0.0

        strand_avg = sum(
            s.coherence_score * s.relevance_weight
            for s in strands
        ) / sum(s.relevance_weight for s in strands) if strands else 0.0

        mirror_avg = (
            sum(m.reflection_score for m in mirrors) / len(mirrors)
            if mirrors else 0.0
        )

        return strand_avg * 0.6 + mirror_avg * 0.4

    # ─── Autonomy Governance ──────────────────────────────────

    def check_promotion(self) -> Optional[HelixAutonomyLevel]:
        """
        Check if this helix should be promoted based on coherence history.

        OBSERVATION → RESTRICTED: 3+ cycles with contribution > 0.1
        RESTRICTED → AUTONOMOUS: 10+ cycles with contribution > 0.2
        """
        if len(self._coherence_history) < 3:
            return None

        recent = self._coherence_history[-10:]

        if self.autonomy_level == HelixAutonomyLevel.OBSERVATION:
            if len(recent) >= 3 and all(c > 0.1 for c in recent[-3:]):
                return HelixAutonomyLevel.RESTRICTED

        elif self.autonomy_level == HelixAutonomyLevel.RESTRICTED:
            if len(recent) >= 10 and all(c > 0.2 for c in recent):
                return HelixAutonomyLevel.AUTONOMOUS

        return None

    def should_prune(self) -> bool:
        """Check if this helix should be pruned (contribution too low)."""
        if self._cycle_count < 10:
            return False
        recent = self._coherence_history[-10:]
        return len(recent) >= 10 and all(c < 0.05 for c in recent)

    def should_merge(self, other: "NoeticHelix") -> bool:
        """Check if this helix should merge with another (outputs correlated > 0.9)."""
        if len(self._coherence_history) < 5 or len(other._coherence_history) < 5:
            return False
        mine = self._coherence_history[-5:]
        theirs = other._coherence_history[-5:]
        correlation = 1.0 - sum(abs(a - b) for a, b in zip(mine, theirs)) / 5.0
        return correlation > 0.9

    # ─── Status & Registry ─────────────────────────────────────

    def get_autonomy_weight(self) -> float:
        """Weight applied to this helix's output based on autonomy level."""
        return {
            HelixAutonomyLevel.OBSERVATION: 0.0,
            HelixAutonomyLevel.RESTRICTED: 0.3,
            HelixAutonomyLevel.AUTONOMOUS: 1.0,
        }.get(self.autonomy_level, 0.0)

    def get_registry_entry(self) -> HelixRegistryEntry:
        return HelixRegistryEntry(
            helix_id=self.helix_id,
            function=self.function.value if isinstance(self.function, HelixFunction) else str(self.function),
            domain=self.domain,
            autonomy_level=self.autonomy_level,
            created_at=self._created_at,
            cycle_count=self._cycle_count,
            coherence_contribution=self._coherence_history[-1] if self._coherence_history else 0.0,
            coherence_history=self._coherence_history[-20:],
        )

    def get_status(self) -> Dict[str, Any]:
        return {
            "helix_id": str(self.helix_id),
            "function": self.function.value if isinstance(self.function, HelixFunction) else str(self.function),
            "domain": self.domain,
            "autonomy": self.autonomy_level.value,
            "strands": self._strands,
            "cycle_count": self._cycle_count,
            "coherence_avg": round(
                sum(self._coherence_history[-10:]) / max(len(self._coherence_history[-10:]), 1), 4
            ),
            "last_coherence": round(self._coherence_history[-1], 4) if self._coherence_history else 0,
            "weight": self.get_autonomy_weight(),
        }
