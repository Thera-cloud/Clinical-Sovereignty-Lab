"""
Coach-Client Matching Engine
AI-powered matching of clients to coaches using Night School learned history,
coherence (C_emo), GAP, and Quantum scores.
"""

import json
import logging
import os
from pathlib import Path
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, asdict

logger = logging.getLogger(__name__)


@dataclass
class MatchResult:
    coach_id: str
    coach_name: str
    score: float          # 0.0 - 1.0
    reasoning: str
    specialty_score: float
    coherence_score: float
    performance_score: float
    wisdom_score: float


def _load_json(path, default=None):
    try:
        with open(path, "r") as f:
            return json.load(f)
    except Exception as e:
        logger.debug("_load_json helper: %s", e)
        return default if default is not None else {}


class CoachMatcher:
    """
    Matches clients to coaches based on:
    1. Specialty alignment (0.30 weight)
    2. Coherence compatibility (0.25 weight)
    3. Coach performance history (0.20 weight)
    4. Night School learned observations (0.25 weight)
    """

    WEIGHT_SPECIALTY = 0.30
    WEIGHT_COHERENCE = 0.25
    WEIGHT_PERFORMANCE = 0.20
    WEIGHT_WISDOM = 0.25

    def __init__(self, data_dir: Path, vault_root: Path):
        self.data_dir = Path(data_dir)
        self.vault_root = Path(vault_root)
        self.registry_file = self.data_dir / "user_registry.json"
        self.learning_queue_file = self.data_dir / "coach_learning_queue.json"
        self.learning_archive_file = self.data_dir / "coach_learning_archive.json"
        self.wisdom_file = self.vault_root / "Admin" / "night_school" / "wisdom.json"

    def _load_registry(self) -> Dict:
        return _load_json(self.registry_file, {})

    def _get_client_profile(self, client_id: str) -> Optional[Dict]:
        registry = self._load_registry()
        for k, v in registry.items():
            p = v.get("profile", {})
            if p.get("hardware_id") == client_id:
                return p
        return None

    def _get_coach_profiles(self) -> List[Dict]:
        registry = self._load_registry()
        coaches = []
        for k, v in registry.items():
            p = v.get("profile", {})
            if p.get("role") == "COACH" and p.get("subscription_status") != "SUSPENDED":
                coaches.append(p)
        return coaches

    def _get_client_metrics(self, client_id: str) -> Dict:
        metrics_file = self.vault_root / "Clients" / client_id / "metrics.json"
        return _load_json(metrics_file, {})

    def _get_client_story(self, client_id: str) -> Dict:
        story_file = self.vault_root / "Clients" / client_id / "story.json"
        return _load_json(story_file, {})

    def _get_coach_learnings(self, coach_id: str) -> List[Dict]:
        """Get all Night School learnings associated with a coach."""
        learnings = []
        queue = _load_json(self.learning_queue_file, [])
        archive = _load_json(self.learning_archive_file, [])
        if not isinstance(queue, list):
            queue = []
        if not isinstance(archive, list):
            archive = []
        for item in queue + archive:
            if not isinstance(item, dict):
                continue
            source = (item.get("source") or "").upper()
            coach_hw = (item.get("coach_id") or "").strip()
            if coach_hw == coach_id or coach_id.upper() in source:
                if item.get("status") == "APPROVED":
                    learnings.append(item)
        return learnings

    def _get_wisdom_entries(self) -> List[Dict]:
        data = _load_json(self.wisdom_file, {})
        if isinstance(data, dict):
            return data.get("entries", [])
        if isinstance(data, list):
            return data
        return []

    def _compute_specialty_score(self, client_profile: Dict, client_story: Dict,
                                  coach_profile: Dict, wisdom_entries: List[Dict]) -> float:
        """Compare client's presenting issues with coach's specialty."""
        score = 0.5  # Base score

        coach_specialty = (coach_profile.get("specialty") or
                          coach_profile.get("specializations") or "").lower()

        # Extract client needs from story
        wounds = client_story.get("wounds", {})
        core_wounds = wounds.get("core_wounds", [])
        patterns = client_story.get("patterns", {})
        unfinished = client_story.get("unfinished_business", [])

        # Keywords from client needs
        client_keywords = set()
        for w in core_wounds:
            if isinstance(w, str):
                client_keywords.update(w.lower().split())
            elif isinstance(w, dict):
                client_keywords.update((w.get("description", "") or "").lower().split())
        for u in unfinished:
            if isinstance(u, str):
                client_keywords.update(u.lower().split())

        # Match keywords against coach specialty
        if coach_specialty:
            specialty_words = set(coach_specialty.split())
            overlap = client_keywords & specialty_words
            if overlap:
                score += min(0.3, len(overlap) * 0.1)

        # Check wisdom entries tagged to this coach's specialty areas
        therapy_keywords = {"anxiety", "depression", "trauma", "attachment", "grief",
                           "relationship", "cbt", "eft", "ifs", "aedp", "polyvagal",
                           "somatic", "mindfulness", "crisis", "boundary"}
        client_therapy_needs = client_keywords & therapy_keywords
        if client_therapy_needs and any(kw in coach_specialty for kw in client_therapy_needs):
            score += 0.2

        return min(1.0, max(0.0, score))

    def _compute_coherence_score(self, client_metrics: Dict, coach_profile: Dict,
                                  coach_learnings: List[Dict]) -> float:
        """Match client coherence needs with coach capabilities."""
        score = 0.5
        ns = client_metrics.get("nevedal_state", client_metrics)

        c_emo = float(ns.get("C_emo", 0.5))
        gap = float(ns.get("GAP", 0.3))
        quantum = float(ns.get("Quantum", 0.5))

        # Low coherence clients need coaches skilled in emotional regulation
        if c_emo < 0.3:
            regulation_learnings = sum(1 for l in coach_learnings
                                      if "regulation" in (l.get("content", "") or "").lower()
                                      or "grounding" in (l.get("content", "") or "").lower())
            score += min(0.25, regulation_learnings * 0.05)

        # High GAP clients need attachment-skilled coaches
        if gap > 0.5:
            attachment_learnings = sum(1 for l in coach_learnings
                                      if "attachment" in (l.get("content", "") or "").lower()
                                      or "connection" in (l.get("content", "") or "").lower())
            score += min(0.25, attachment_learnings * 0.05)

        # Low quantum clients need comprehensive support
        if quantum < 0.3:
            total_learnings = len(coach_learnings)
            score += min(0.2, total_learnings * 0.02)

        return min(1.0, max(0.0, score))

    def _compute_performance_score(self, coach_profile: Dict) -> float:
        """Score based on coach's track record."""
        score = 0.5

        retention = float(coach_profile.get("retention_rate", 50)) / 100.0
        satisfaction = float(coach_profile.get("satisfaction", 3.0)) / 5.0
        breakthroughs = int(coach_profile.get("breakthroughs", 0))
        total_sessions = int(coach_profile.get("total_sessions_conducted",
                            coach_profile.get("total_sessions", 0)))

        # Retention rate (0-100 -> 0-1)
        score = 0.3 * retention + 0.3 * satisfaction
        if breakthroughs > 0 and total_sessions > 0:
            score += 0.2 * min(1.0, breakthroughs / max(total_sessions, 1) * 10)
        if total_sessions > 20:
            score += 0.2  # Experience bonus

        return min(1.0, max(0.0, score))

    def _compute_wisdom_score(self, client_story: Dict, coach_learnings: List[Dict],
                               wisdom_entries: List[Dict], coach_id: str) -> float:
        """Score based on Night School learned observations."""
        score = 0.5

        # Count approved wisdom entries related to this coach
        coach_wisdom = [w for w in wisdom_entries
                       if isinstance(w, dict) and coach_id.lower() in (w.get("source_file", "") or "").lower()]
        score += min(0.2, len(coach_wisdom) * 0.02)

        # Count coaching learnings quality
        approved_learnings = [l for l in coach_learnings if l.get("status") == "APPROVED"]
        score += min(0.15, len(approved_learnings) * 0.01)

        # Check for dojo training completion
        dojo_learnings = [l for l in approved_learnings if l.get("category") == "coach_dojo_training"]
        score += min(0.15, len(dojo_learnings) * 0.03)

        return min(1.0, max(0.0, score))

    def compute_match_score(self, client_id: str, coach_id: str) -> Optional[MatchResult]:
        """Compute match score between a client and coach."""
        client_profile = self._get_client_profile(client_id)
        if not client_profile:
            return None

        coaches = self._get_coach_profiles()
        coach_profile = None
        for c in coaches:
            if c.get("hardware_id") == coach_id:
                coach_profile = c
                break
        if not coach_profile:
            return None

        client_metrics = self._get_client_metrics(client_id)
        client_story = self._get_client_story(client_id)
        coach_learnings = self._get_coach_learnings(coach_id)
        wisdom_entries = self._get_wisdom_entries()

        specialty = self._compute_specialty_score(client_profile, client_story, coach_profile, wisdom_entries)
        coherence = self._compute_coherence_score(client_metrics, coach_profile, coach_learnings)
        performance = self._compute_performance_score(coach_profile)
        wisdom = self._compute_wisdom_score(client_story, coach_learnings, wisdom_entries, coach_id)

        total = (self.WEIGHT_SPECIALTY * specialty +
                self.WEIGHT_COHERENCE * coherence +
                self.WEIGHT_PERFORMANCE * performance +
                self.WEIGHT_WISDOM * wisdom)

        # Build reasoning
        reasons = []
        if specialty > 0.6:
            reasons.append("Strong specialty alignment")
        if coherence > 0.6:
            reasons.append("Good coherence compatibility")
        if performance > 0.7:
            reasons.append("High performance track record")
        if wisdom > 0.6:
            reasons.append("Rich Night School learnings")
        if not reasons:
            reasons.append("General compatibility")

        return MatchResult(
            coach_id=coach_id,
            coach_name=coach_profile.get("name", "Unknown"),
            score=round(total, 3),
            reasoning="; ".join(reasons),
            specialty_score=round(specialty, 3),
            coherence_score=round(coherence, 3),
            performance_score=round(performance, 3),
            wisdom_score=round(wisdom, 3),
        )

    def calculate_compatibility(self, client_id: str, coach_id: str) -> Optional[int]:
        """
        Matchmaker Protocol alias: returns a 0-100 integer compatibility score.
        Wraps compute_match_score() and scales from 0.0-1.0 to 0-100.
        """
        result = self.compute_match_score(client_id, coach_id)
        if result is None:
            return None
        return round(result.score * 100)

    async def get_top_matches(self, client_id: str, n: int = 3) -> List[Dict]:
        """Get top N coach matches for a client."""
        coaches = self._get_coach_profiles()
        results = []

        for coach in coaches:
            coach_id = coach.get("hardware_id", "")
            if not coach_id:
                continue
            result = self.compute_match_score(client_id, coach_id)
            if result:
                results.append(asdict(result))

        # Sort by score descending
        results.sort(key=lambda x: x.get("score", 0), reverse=True)
        return results[:n]
