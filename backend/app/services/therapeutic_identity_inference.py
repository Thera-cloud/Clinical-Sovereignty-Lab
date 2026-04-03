"""
Therapeutic Identity Inference Engine — Phase 4: Core Inference.

The "Blindfolded Therapist" model: fuses Voice (acoustic), Linguistic (text),
and Narrative (therapeutic) layers with dynamic weighting and an Arbiter
for confidence thresholding and sibling conflict resolution.

Environment-specific weight matrices adjust for schools, prisons, clinics.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("nate.identity_inference")

CONFIDENCE_THRESHOLD_HIGH = 0.75
CONFIDENCE_THRESHOLD_MEDIUM = 0.50
CONFIDENCE_THRESHOLD_LOW = 0.30

ENVIRONMENT_WEIGHTS = {
    "default": {"voice": 0.45, "linguistic": 0.30, "narrative": 0.25},
    "clinic": {"voice": 0.45, "linguistic": 0.30, "narrative": 0.25},
    "school": {"voice": 0.30, "linguistic": 0.35, "narrative": 0.35},
    "prison": {"voice": 0.25, "linguistic": 0.40, "narrative": 0.35},
    "family": {"voice": 0.35, "linguistic": 0.25, "narrative": 0.40},
    "group": {"voice": 0.40, "linguistic": 0.25, "narrative": 0.35},
}


@dataclass
class IdentityCandidate:
    """A candidate identity match with per-layer scores."""
    user_id: str
    voice_score: float = 0.0
    linguistic_score: float = 0.0
    narrative_score: float = 0.0
    greeting_score: float = 0.0
    fused_score: float = 0.0
    confidence_tier: str = "NONE"
    match_type: str = "full"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "user_id": self.user_id,
            "voice_score": round(self.voice_score, 3),
            "linguistic_score": round(self.linguistic_score, 3),
            "narrative_score": round(self.narrative_score, 3),
            "greeting_score": round(self.greeting_score, 3),
            "fused_score": round(self.fused_score, 3),
            "confidence_tier": self.confidence_tier,
            "match_type": self.match_type,
        }


@dataclass
class IdentityResult:
    """Result of the identity inference process."""
    identified_user: Optional[str] = None
    confidence: float = 0.0
    confidence_tier: str = "NONE"
    candidates: List[IdentityCandidate] = field(default_factory=list)
    requires_investigation: bool = False
    investigation_reason: Optional[str] = None
    environment: str = "default"
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "identified_user": self.identified_user,
            "confidence": round(self.confidence, 3),
            "confidence_tier": self.confidence_tier,
            "candidates": [c.to_dict() for c in self.candidates[:5]],
            "requires_investigation": self.requires_investigation,
            "investigation_reason": self.investigation_reason,
            "environment": self.environment,
        }


class TherapeuticIdentityInference:
    """
    Core identity inference engine with multi-layer fusion.

    Combines voice biometrics, linguistic fingerprints, and narrative profiles
    using environment-specific weight matrices. Includes an Arbiter for
    confidence thresholding and sibling conflict resolution.
    """

    def __init__(self, environment: str = "default"):
        self._environment = environment
        self._weights = ENVIRONMENT_WEIGHTS.get(environment, ENVIRONMENT_WEIGHTS["default"])
        self._history: List[IdentityResult] = []

    @property
    def environment(self) -> str:
        return self._environment

    def set_environment(self, env: str) -> None:
        self._environment = env
        self._weights = ENVIRONMENT_WEIGHTS.get(env, ENVIRONMENT_WEIGHTS["default"])

    def fuse_scores(
        self,
        candidates: List[IdentityCandidate],
        qos_degraded: bool = False,
        adolescent_flag: bool = False,
    ) -> IdentityResult:
        """
        Fuse per-layer scores into final ranked candidates with arbitration.

        When QoS is degraded (prison calls, poor connection), voice weight
        is reduced and linguistic/narrative weights increase.
        For adolescents, voice weight is reduced due to vocal maturation.
        """
        weights = dict(self._weights)

        if qos_degraded:
            voice_reduction = weights["voice"] * 0.4
            weights["voice"] -= voice_reduction
            weights["linguistic"] += voice_reduction * 0.6
            weights["narrative"] += voice_reduction * 0.4

        if adolescent_flag:
            voice_reduction = weights["voice"] * 0.3
            weights["voice"] -= voice_reduction
            weights["linguistic"] += voice_reduction * 0.5
            weights["narrative"] += voice_reduction * 0.5

        for c in candidates:
            c.fused_score = (
                c.voice_score * weights["voice"]
                + c.linguistic_score * weights["linguistic"]
                + c.narrative_score * weights["narrative"]
            )

            if c.greeting_score > 0:
                c.fused_score = max(c.fused_score, c.greeting_score * 0.4)

            if c.fused_score >= CONFIDENCE_THRESHOLD_HIGH:
                c.confidence_tier = "HIGH"
            elif c.fused_score >= CONFIDENCE_THRESHOLD_MEDIUM:
                c.confidence_tier = "MEDIUM"
            elif c.fused_score >= CONFIDENCE_THRESHOLD_LOW:
                c.confidence_tier = "LOW"
            else:
                c.confidence_tier = "NONE"

        candidates.sort(key=lambda x: x.fused_score, reverse=True)
        result = IdentityResult(environment=self._environment)
        result.candidates = candidates

        result = self._arbitrate(result)
        self._history.append(result)
        if len(self._history) > 50:
            self._history = self._history[-50:]

        return result

    def _arbitrate(self, result: IdentityResult) -> IdentityResult:
        """
        Arbiter: resolve ambiguity, detect sibling conflicts,
        and determine if gentle investigation is needed.
        """
        if not result.candidates:
            result.requires_investigation = True
            result.investigation_reason = "no_candidates"
            return result

        top = result.candidates[0]
        runner_up = result.candidates[1] if len(result.candidates) > 1 else None

        if top.confidence_tier == "HIGH":
            if runner_up and runner_up.fused_score > CONFIDENCE_THRESHOLD_MEDIUM:
                margin = top.fused_score - runner_up.fused_score
                if margin < 0.10:
                    result.requires_investigation = True
                    result.investigation_reason = "sibling_conflict"
                    result.confidence_tier = "MEDIUM"
                    result.confidence = top.fused_score
                    return result

            result.identified_user = top.user_id
            result.confidence = top.fused_score
            result.confidence_tier = "HIGH"
            return result

        if top.confidence_tier == "MEDIUM":
            if runner_up and runner_up.fused_score > CONFIDENCE_THRESHOLD_LOW:
                margin = top.fused_score - runner_up.fused_score
                if margin < 0.15:
                    result.requires_investigation = True
                    result.investigation_reason = "ambiguous_medium"
                    result.confidence = top.fused_score
                    result.confidence_tier = "LOW"
                    return result

            result.identified_user = top.user_id
            result.confidence = top.fused_score
            result.confidence_tier = "MEDIUM"
            result.requires_investigation = True
            result.investigation_reason = "medium_confidence"
            return result

        result.requires_investigation = True
        result.investigation_reason = "low_confidence"
        result.confidence = top.fused_score
        result.confidence_tier = top.confidence_tier
        return result

    def resolve_sibling_conflict(
        self, candidates: List[IdentityCandidate],
    ) -> Optional[IdentityCandidate]:
        """
        When voice scores are close (siblings/twins), use narrative
        divergence as the tiebreaker.
        """
        if len(candidates) < 2:
            return candidates[0] if candidates else None

        top_two = sorted(candidates, key=lambda x: x.fused_score, reverse=True)[:2]
        voice_gap = abs(top_two[0].voice_score - top_two[1].voice_score)

        if voice_gap < 0.10:
            narrative_gap = abs(top_two[0].narrative_score - top_two[1].narrative_score)
            if narrative_gap > 0.15:
                winner = max(top_two, key=lambda x: x.narrative_score)
                logger.info(
                    "SiblingConflict: voice gap %.3f, narrative gap %.3f → %s",
                    voice_gap, narrative_gap, winner.user_id,
                )
                return winner
            return None

        return top_two[0]


class IdentityArbiter:
    """
    Tracks identity inference results over time and manages the
    transition from uncertain to confident identification.
    """

    def __init__(self):
        self._session_results: List[IdentityResult] = []
        self._consensus_user: Optional[str] = None
        self._consensus_confidence: float = 0.0

    def add_result(self, result: IdentityResult) -> None:
        self._session_results.append(result)
        if len(self._session_results) > 20:
            self._session_results = self._session_results[-20:]
        self._update_consensus()

    def _update_consensus(self) -> None:
        if not self._session_results:
            return

        user_scores: Dict[str, List[float]] = {}
        for r in self._session_results[-10:]:
            for c in r.candidates:
                user_scores.setdefault(c.user_id, []).append(c.fused_score)

        if not user_scores:
            return

        best_user = None
        best_avg = 0.0
        for uid, scores in user_scores.items():
            avg = sum(scores) / len(scores)
            if avg > best_avg:
                best_avg = avg
                best_user = uid

        self._consensus_user = best_user
        self._consensus_confidence = best_avg

    @property
    def consensus(self) -> Tuple[Optional[str], float]:
        return self._consensus_user, self._consensus_confidence
