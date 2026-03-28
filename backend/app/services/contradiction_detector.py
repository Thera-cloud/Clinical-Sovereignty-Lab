"""
Hallucination Defense Layer 6 — Contradiction Detector

Detects contradictions between new crystal candidates and existing crystals
in the same domain. Runs BEFORE crystal storage to prevent conflicting
knowledge from entering the memory field.

Uses semantic similarity and assertion extraction to find:
- Direct negation (crystal A says X, crystal B says NOT X)
- Numeric contradiction (crystal A says "15%", crystal B says "45%")
- Temporal impossibility (crystal A says "before X", crystal B says "after X")
"""

import hashlib
import logging
import re
from dataclasses import dataclass
from typing import List, Optional, Tuple

logger = logging.getLogger("hallucination.contradiction_detector")


@dataclass
class ContradictionResult:
    has_contradiction: bool
    confidence: float
    contradicting_crystal_id: Optional[str] = None
    explanation: str = ""
    contradiction_type: str = ""


NUMERIC_PATTERN = re.compile(r'(\d+(?:\.\d+)?)\s*(%|percent|times|x|hours?|minutes?|days?|sessions?)')
NEGATION_MARKERS = re.compile(
    r'\b(never|not|no longer|stopped|ceased|doesn\'t|don\'t|cannot|'
    r'isn\'t|aren\'t|wasn\'t|weren\'t|won\'t|wouldn\'t|shouldn\'t|'
    r'unable|impossible|false|incorrect|wrong|invalid)\b',
    re.IGNORECASE,
)
TEMPORAL_ORDER = re.compile(
    r'\b(before|after|prior to|following|preceded by|subsequently|'
    r'earlier than|later than|first|last|initially|finally)\b',
    re.IGNORECASE,
)


class ContradictionDetector:
    """Pre-storage contradiction check for intelligence crystals."""

    def __init__(self, db_pool=None):
        self.db_pool = db_pool

    async def check(
        self,
        candidate_text: str,
        candidate_domain: str,
        existing_crystals: Optional[List[dict]] = None,
    ) -> ContradictionResult:
        """
        Check a candidate crystal against existing crystals in the same domain.

        If existing_crystals is None and db_pool is available, queries the
        database for active crystals in the same domain.
        """
        if existing_crystals is None:
            existing_crystals = await self._fetch_domain_crystals(candidate_domain)

        if not existing_crystals:
            return ContradictionResult(has_contradiction=False, confidence=0.0)

        candidate_assertions = self._extract_assertions(candidate_text)
        if not candidate_assertions:
            return ContradictionResult(has_contradiction=False, confidence=0.0)

        best_match = ContradictionResult(has_contradiction=False, confidence=0.0)

        for crystal in existing_crystals:
            crystal_text = crystal.get("crystal_text", "")
            crystal_id = crystal.get("id", "unknown")

            result = self._compare_assertions(
                candidate_assertions,
                self._extract_assertions(crystal_text),
                crystal_id,
            )
            if result.confidence > best_match.confidence:
                best_match = result

        return best_match

    def _extract_assertions(self, text: str) -> List[dict]:
        """Extract structured assertions from text for comparison."""
        assertions = []
        sentences = re.split(r'[.!?]\s+', text)

        for sent in sentences:
            sent = sent.strip()
            if len(sent) < 10:
                continue

            assertion = {
                "text": sent,
                "has_negation": bool(NEGATION_MARKERS.search(sent)),
                "numerics": NUMERIC_PATTERN.findall(sent),
                "temporal": TEMPORAL_ORDER.findall(sent),
                "key_phrases": self._extract_key_phrases(sent),
            }
            assertions.append(assertion)

        return assertions

    def _extract_key_phrases(self, text: str) -> List[str]:
        """Extract noun-phrase-like key phrases for topic matching."""
        words = re.findall(r'\b[a-zA-Z]{3,}\b', text.lower())
        stop_words = {
            "the", "and", "for", "are", "but", "not", "you", "all",
            "can", "has", "her", "was", "one", "our", "out", "had",
            "this", "that", "with", "have", "from", "they", "been",
            "said", "each", "which", "their", "will", "other", "about",
            "many", "then", "them", "these", "some", "would", "make",
            "like", "into", "could", "more", "very", "when", "what",
        }
        return [w for w in words if w not in stop_words]

    def _compare_assertions(
        self,
        candidate_assertions: List[dict],
        existing_assertions: List[dict],
        crystal_id: str,
    ) -> ContradictionResult:
        """Compare two sets of assertions for contradictions."""
        for ca in candidate_assertions:
            for ea in existing_assertions:
                topic_overlap = self._topic_overlap(ca["key_phrases"], ea["key_phrases"])
                if topic_overlap < 0.3:
                    continue

                # Direct negation: same topic, opposite polarity
                if ca["has_negation"] != ea["has_negation"] and topic_overlap > 0.5:
                    return ContradictionResult(
                        has_contradiction=True,
                        confidence=min(0.95, topic_overlap + 0.3),
                        contradicting_crystal_id=crystal_id,
                        explanation=f"Negation conflict: '{ca['text'][:80]}' vs '{ea['text'][:80]}'",
                        contradiction_type="negation",
                    )

                # Numeric contradiction: same topic, different numbers
                if ca["numerics"] and ea["numerics"]:
                    for c_num, c_unit in ca["numerics"]:
                        for e_num, e_unit in ea["numerics"]:
                            if c_unit == e_unit and c_num != e_num:
                                diff_ratio = abs(float(c_num) - float(e_num)) / max(float(c_num), float(e_num), 0.001)
                                if diff_ratio > 0.2:
                                    return ContradictionResult(
                                        has_contradiction=True,
                                        confidence=min(0.9, topic_overlap + diff_ratio * 0.3),
                                        contradicting_crystal_id=crystal_id,
                                        explanation=f"Numeric conflict: {c_num}{c_unit} vs {e_num}{e_unit}",
                                        contradiction_type="numeric",
                                    )

                # Temporal impossibility
                if ca["temporal"] and ea["temporal"]:
                    ca_temporal = set(t.lower() for t in ca["temporal"])
                    ea_temporal = set(t.lower() for t in ea["temporal"])
                    if ("before" in ca_temporal and "after" in ea_temporal) or \
                       ("after" in ca_temporal and "before" in ea_temporal):
                        if topic_overlap > 0.4:
                            return ContradictionResult(
                                has_contradiction=True,
                                confidence=min(0.85, topic_overlap + 0.25),
                                contradicting_crystal_id=crystal_id,
                                explanation=f"Temporal conflict on overlapping topic",
                                contradiction_type="temporal",
                            )

        return ContradictionResult(has_contradiction=False, confidence=0.0)

    @staticmethod
    def _topic_overlap(phrases_a: List[str], phrases_b: List[str]) -> float:
        """Jaccard similarity between key phrase sets."""
        if not phrases_a or not phrases_b:
            return 0.0
        set_a, set_b = set(phrases_a), set(phrases_b)
        intersection = set_a & set_b
        union = set_a | set_b
        return len(intersection) / len(union) if union else 0.0

    async def _fetch_domain_crystals(self, domain: str, limit: int = 50) -> List[dict]:
        """Fetch active crystals in the same domain for comparison."""
        if not self.db_pool:
            return []
        try:
            async with self.db_pool.acquire() as conn:
                rows = await conn.fetch(
                    """SELECT id::text, crystal_text, domain, confidence
                       FROM nate_intelligence_crystals
                       WHERE domain = $1
                         AND scope != 'archived'
                         AND superseded_by IS NULL
                       ORDER BY confidence DESC
                       LIMIT $2""",
                    domain, limit,
                )
                return [dict(r) for r in rows]
        except Exception as e:
            logger.warning("ContradictionDetector: DB fetch failed: %s", e)
            return []
