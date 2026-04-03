"""
Therapeutic Identity Inference Engine — Phase 2: Linguistic Identity Fingerprint.

Extracts stable linguistic features from transcripts: filler words, sentence length,
vocabulary richness, hedge ratio, question frequency, greeting patterns.
Fast-path greeting signature matches "Hello" / "Hey it's me" / "Hi Nate" patterns
for 4-second identification before full voiceprint completes.
"""

from __future__ import annotations

import logging
import re
import time
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set

logger = logging.getLogger("nate.linguistic_identity")

FILLER_WORDS = {
    "um", "uh", "like", "you know", "i mean", "basically", "literally",
    "actually", "honestly", "right", "so", "well", "kind of", "sort of",
    "whatever", "anyway", "okay so",
}

HEDGE_PHRASES = {
    "i think", "maybe", "i guess", "probably", "sort of", "kind of",
    "i feel like", "it seems", "i suppose", "not sure but",
    "i don't know", "perhaps",
}

GREETING_PATTERNS = [
    re.compile(r"^(hey|hi|hello|yo|good morning|good evening)\b", re.I),
    re.compile(r"^(hey|hi|hello)\s+(nate|little nate)\b", re.I),
    re.compile(r"^it'?s\s+me\b", re.I),
    re.compile(r"^(hey|hi)\s+it'?s\s+\w+", re.I),
]


@dataclass
class LinguisticFingerprint:
    """Stable linguistic identity features extracted from transcripts."""
    user_id: str
    filler_distribution: Dict[str, float] = field(default_factory=dict)
    avg_sentence_length: float = 0.0
    vocabulary_richness: float = 0.0
    hedge_ratio: float = 0.0
    question_frequency: float = 0.0
    contraction_rate: float = 0.0
    first_person_ratio: float = 0.0
    greeting_patterns: List[str] = field(default_factory=list)
    topic_vocabulary: Dict[str, Set[str]] = field(default_factory=dict)
    turn_count: int = 0
    total_words: int = 0
    updated_at: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "user_id": self.user_id,
            "filler_distribution": self.filler_distribution,
            "avg_sentence_length": self.avg_sentence_length,
            "vocabulary_richness": self.vocabulary_richness,
            "hedge_ratio": self.hedge_ratio,
            "question_frequency": self.question_frequency,
            "contraction_rate": self.contraction_rate,
            "first_person_ratio": self.first_person_ratio,
            "greeting_patterns": self.greeting_patterns[-10:],
            "turn_count": self.turn_count,
            "total_words": self.total_words,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "LinguisticFingerprint":
        fp = cls(user_id=d.get("user_id", ""))
        fp.filler_distribution = d.get("filler_distribution", {})
        fp.avg_sentence_length = d.get("avg_sentence_length", 0.0)
        fp.vocabulary_richness = d.get("vocabulary_richness", 0.0)
        fp.hedge_ratio = d.get("hedge_ratio", 0.0)
        fp.question_frequency = d.get("question_frequency", 0.0)
        fp.contraction_rate = d.get("contraction_rate", 0.0)
        fp.first_person_ratio = d.get("first_person_ratio", 0.0)
        fp.greeting_patterns = d.get("greeting_patterns", [])
        fp.turn_count = d.get("turn_count", 0)
        fp.total_words = d.get("total_words", 0)
        fp.updated_at = d.get("updated_at", 0.0)
        return fp


class LinguisticIdentityEngine:
    """
    Builds and compares linguistic fingerprints from voice transcripts.

    Fast-path: greeting pattern matching on the first utterance.
    Full-path: accumulated filler/hedge/vocabulary statistics over time.
    """

    def __init__(self, db_pool=None):
        self._db = db_pool
        self._fingerprints: Dict[str, LinguisticFingerprint] = {}

    async def load_fingerprint(self, user_id: str) -> LinguisticFingerprint:
        if user_id in self._fingerprints:
            return self._fingerprints[user_id]

        fp = LinguisticFingerprint(user_id=user_id)
        if self._db:
            try:
                import json
                row = await self._db.fetchrow(
                    """SELECT filler_distribution, avg_sentence_length,
                              hedge_ratio, greeting_patterns, vocabulary_richness,
                              utterance_count, last_updated
                       FROM linguistic_fingerprints WHERE user_id = $1""",
                    user_id,
                )
                if row:
                    fd = row["filler_distribution"]
                    if fd and isinstance(fd, str):
                        fd = json.loads(fd)
                    fp.filler_distribution = fd if isinstance(fd, dict) else {}
                    fp.avg_sentence_length = row["avg_sentence_length"] or 0.0
                    fp.hedge_ratio = row["hedge_ratio"] or 0.0
                    fp.vocabulary_richness = row["vocabulary_richness"] or 0.0
                    fp.turn_count = row["utterance_count"] or 0
                    gp = row["greeting_patterns"]
                    if gp and isinstance(gp, str):
                        gp = json.loads(gp)
                    fp.greeting_patterns = gp if isinstance(gp, list) else []
            except Exception as e:
                logger.warning("LinguisticIdentity: load failed for %s: %s", user_id, e)

        self._fingerprints[user_id] = fp
        return fp

    def analyze_utterance(self, user_id: str, text: str) -> Dict[str, Any]:
        """Extract linguistic features from a single utterance and update fingerprint."""
        fp = self._fingerprints.get(user_id)
        if not fp:
            fp = LinguisticFingerprint(user_id=user_id)
            self._fingerprints[user_id] = fp

        text_lower = text.lower().strip()
        words = text_lower.split()
        word_count = len(words)
        if word_count == 0:
            return {}

        fillers_found = Counter()
        for filler in FILLER_WORDS:
            count = text_lower.count(filler)
            if count > 0:
                fillers_found[filler] = count

        hedge_count = sum(1 for h in HEDGE_PHRASES if h in text_lower)
        question_count = text.count("?")
        contractions = len(re.findall(r"\w+'(?:t|s|re|ve|ll|d|m)\b", text_lower))
        first_person = sum(1 for w in words if w in ("i", "i'm", "i've", "i'd", "i'll", "my", "me", "mine", "myself"))
        sentences = [s.strip() for s in re.split(r'[.!?]+', text) if s.strip()]

        for filler, count in fillers_found.items():
            old = fp.filler_distribution.get(filler, 0.0)
            fp.filler_distribution[filler] = old * 0.9 + (count / word_count) * 0.1

        alpha = 0.1
        new_sl = sum(len(s.split()) for s in sentences) / max(len(sentences), 1)
        fp.avg_sentence_length = fp.avg_sentence_length * (1 - alpha) + new_sl * alpha
        fp.hedge_ratio = fp.hedge_ratio * (1 - alpha) + (hedge_count / word_count) * alpha
        fp.question_frequency = fp.question_frequency * (1 - alpha) + (question_count / max(len(sentences), 1)) * alpha
        fp.contraction_rate = fp.contraction_rate * (1 - alpha) + (contractions / word_count) * alpha
        fp.first_person_ratio = fp.first_person_ratio * (1 - alpha) + (first_person / word_count) * alpha

        fp.turn_count += 1
        fp.total_words += word_count
        fp.vocabulary_richness = len(set(words)) / word_count if word_count > 10 else fp.vocabulary_richness

        for pat in GREETING_PATTERNS:
            m = pat.match(text)
            if m:
                normalized = m.group(0).lower()
                if normalized not in fp.greeting_patterns:
                    fp.greeting_patterns.append(normalized)

        fp.updated_at = time.time()
        return {
            "fillers": dict(fillers_found),
            "hedge_count": hedge_count,
            "sentence_length": new_sl,
            "question_count": question_count,
        }

    def match_greeting(self, text: str, candidates: List[LinguisticFingerprint]) -> List[Dict[str, Any]]:
        """
        Fast-path: match opening utterance against known greeting patterns.
        Returns ranked candidates.
        """
        text_lower = text.lower().strip()
        matched_pattern = None
        for pat in GREETING_PATTERNS:
            m = pat.match(text_lower)
            if m:
                matched_pattern = m.group(0).lower()
                break

        if not matched_pattern:
            return []

        scores = []
        for fp in candidates:
            if matched_pattern in fp.greeting_patterns:
                scores.append({
                    "user_id": fp.user_id,
                    "confidence": 0.3,
                    "match_type": "greeting_pattern",
                })
        return scores

    def compare_fingerprints(
        self, current: LinguisticFingerprint, stored: LinguisticFingerprint,
    ) -> float:
        """
        Compare two linguistic fingerprints. Returns similarity 0-1.

        Weights: filler distribution 0.25, sentence length 0.15,
        vocabulary richness 0.15, hedge ratio 0.15, contraction rate 0.10,
        first person ratio 0.10, question frequency 0.10.
        """
        if stored.turn_count < 5:
            return 0.0

        scores = []

        all_fillers = set(current.filler_distribution) | set(stored.filler_distribution)
        if all_fillers:
            filler_sim = 1.0 - sum(
                abs(current.filler_distribution.get(f, 0) - stored.filler_distribution.get(f, 0))
                for f in all_fillers
            ) / max(len(all_fillers), 1)
            scores.append(max(0, filler_sim) * 0.25)
        else:
            scores.append(0.25)

        scores.append(_feature_sim(current.avg_sentence_length, stored.avg_sentence_length, 30) * 0.15)
        scores.append(_feature_sim(current.vocabulary_richness, stored.vocabulary_richness, 1.0) * 0.15)
        scores.append(_feature_sim(current.hedge_ratio, stored.hedge_ratio, 0.5) * 0.15)
        scores.append(_feature_sim(current.contraction_rate, stored.contraction_rate, 0.5) * 0.10)
        scores.append(_feature_sim(current.first_person_ratio, stored.first_person_ratio, 0.5) * 0.10)
        scores.append(_feature_sim(current.question_frequency, stored.question_frequency, 1.0) * 0.10)

        return sum(scores)

    async def persist(self, user_id: str) -> None:
        fp = self._fingerprints.get(user_id)
        if not fp or not self._db:
            return
        try:
            import json
            filler_json = json.dumps(fp.filler_distribution)
            greeting_json = json.dumps(fp.greeting_patterns[-10:])
            await self._db.execute(
                """INSERT INTO linguistic_fingerprints
                       (user_id, filler_distribution, avg_sentence_length,
                        hedge_ratio, greeting_patterns, vocabulary_richness,
                        utterance_count, last_updated)
                   VALUES ($1, $2::jsonb, $3, $4, $5::jsonb, $6, $7, NOW())
                   ON CONFLICT (user_id, tenant_id) DO UPDATE SET
                     filler_distribution = EXCLUDED.filler_distribution,
                     avg_sentence_length = EXCLUDED.avg_sentence_length,
                     hedge_ratio = EXCLUDED.hedge_ratio,
                     greeting_patterns = EXCLUDED.greeting_patterns,
                     vocabulary_richness = EXCLUDED.vocabulary_richness,
                     utterance_count = EXCLUDED.utterance_count,
                     last_updated = NOW()""",
                user_id, filler_json, fp.avg_sentence_length,
                fp.hedge_ratio, greeting_json, fp.vocabulary_richness,
                fp.turn_count,
            )
        except Exception as e:
            logger.warning("LinguisticIdentity: persist failed for %s: %s", user_id, e)


def _feature_sim(a: float, b: float, scale: float) -> float:
    return max(0.0, 1.0 - abs(a - b) / max(scale, 1e-6))
