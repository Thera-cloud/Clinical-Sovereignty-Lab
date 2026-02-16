"""
SOVEREIGN SWARM — Convergence Engine

Standalone convergence detection for independent Fibre observations.
When multiple Fibres arrive at correlated conclusions from different vantage points,
generates ConvergenceAlert for Sovereign Mind escalation.
"""

from __future__ import annotations

import math
from collections import defaultdict
from typing import Any, Dict, List

import structlog

from app.models.swarm import ConvergenceAlert

logger = structlog.get_logger(__name__)


def _tokenize(text: str) -> List[str]:
    """Extract lowercase word tokens from text."""
    if not text:
        return []
    return [w.lower() for w in text.replace(",", " ").replace(".", " ").split() if w.strip()]


def _keyword_vector(obs: dict) -> Dict[str, float]:
    """
    Build keyword frequency vector from an observation.

    Uses domain_tags, content, theme, insight, and similar text fields.
    """
    vec: Dict[str, float] = defaultdict(float)
    for field in ("domain_tags", "content", "theme", "insight", "shared_insight", "domains"):
        val = obs.get(field)
        if isinstance(val, str):
            for t in _tokenize(val):
                vec[t] += 1.0
        elif isinstance(val, list):
            for item in val:
                if isinstance(item, str):
                    for t in _tokenize(item):
                        vec[t] += 1.0
    return dict(vec)


class ConvergenceEngine:
    """
    Detects when independent Fibres converge on similar conclusions.

    Groups observations by theme/domain, computes similarity within groups,
    and emits ConvergenceAlert when threshold is exceeded.
    """

    def __init__(
        self,
        threshold: float = 0.7,
        min_fibres: int = 3,
    ) -> None:
        """
        Initialize ConvergenceEngine.

        Args:
            threshold: Minimum convergence score (0.0–1.0) to generate alert.
            min_fibres: Minimum number of observations in a group to consider.
        """
        self.threshold = max(0.0, min(1.0, threshold))
        self.min_fibres = max(2, min_fibres)

    def compute_similarity(self, obs_a: Dict[str, Any], obs_b: Dict[str, Any]) -> float:
        """
        Compute cosine similarity between two observations based on keyword vectors.

        Args:
            obs_a: First observation dict.
            obs_b: Second observation dict.

        Returns:
            Similarity score 0.0–1.0.
        """
        va = _keyword_vector(obs_a)
        vb = _keyword_vector(obs_b)
        if not va or not vb:
            return 0.0

        all_keys = set(va) | set(vb)
        dot = sum(va.get(k, 0) * vb.get(k, 0) for k in all_keys)
        norm_a = math.sqrt(sum(v * v for v in va.values()))
        norm_b = math.sqrt(sum(v * v for v in vb.values()))
        if norm_a == 0 or norm_b == 0:
            return 0.0
        sim = dot / (norm_a * norm_b)
        return max(0.0, min(1.0, sim))

    def extract_themes(self, observations: List[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
        """
        Group observations by extracted themes.

        Theme extraction uses domain_tags, content keywords, and theme/insight fields.
        Observations with overlapping keywords are grouped.

        Returns:
            Dict mapping theme key -> list of observations.
        """
        groups: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
        seen: set[int] = set()

        for i, obs in enumerate(observations):
            if i in seen:
                continue
            domain_tags = obs.get("domain_tags") or obs.get("domains") or []
            if isinstance(domain_tags, str):
                domain_tags = [domain_tags]
            themes = set()
            for t in domain_tags:
                if t:
                    themes.add(str(t).lower().strip())
            content = obs.get("content") or obs.get("insight") or obs.get("theme") or ""
            for tok in _tokenize(str(content)):
                if len(tok) > 3:
                    themes.add(tok)

            theme_key = "|".join(sorted(themes)[:5]) if themes else "unknown"
            groups[theme_key].append(obs)
            seen.add(i)

        # Merge single-obs "unknown" groups into a catch-all
        unknown_obs = []
        for k in list(groups.keys()):
            if k == "unknown" or len(groups[k]) == 1:
                unknown_obs.extend(groups.pop(k, []))
        if unknown_obs:
            groups["unknown"] = unknown_obs

        return dict(groups)

    def detect_convergence(self, observations: List[Dict[str, Any]]) -> List[ConvergenceAlert]:
        """
        Detect convergence across observations and return alerts.

        Groups by theme, computes pairwise similarity within groups,
        and creates ConvergenceAlert when score >= threshold and group size >= min_fibres.

        Args:
            observations: List of observation dicts from Fibres.

        Returns:
            List of ConvergenceAlert instances.
        """
        alerts: List[ConvergenceAlert] = []
        theme_groups = self.extract_themes(observations)

        for theme_key, group in theme_groups.items():
            if len(group) < self.min_fibres:
                continue

            # Compute mean pairwise similarity (convergence score)
            n = len(group)
            total_sim = 0.0
            count = 0
            for i in range(n):
                for j in range(i + 1, n):
                    sim = self.compute_similarity(group[i], group[j])
                    total_sim += sim
                    count += 1
            if count == 0:
                continue
            convergence_score = total_sim / count

            if convergence_score >= self.threshold:
                fibre_ids = [
                    str(o.get("fibre_id", ""))
                    for o in group
                    if o.get("fibre_id")
                ]
                fibre_types = [
                    str(o.get("fibre_type", ""))
                    for o in group
                    if o.get("fibre_type")
                ]
                shared_theme = theme_key.replace("|", ", ")
                shared_insight = self._synthesize_insight(group)

                alert = ConvergenceAlert(
                    contributing_fibre_ids=fibre_ids or ["unknown"],
                    contributing_fibre_types=fibre_types or ["unknown"],
                    convergence_score=round(convergence_score, 4),
                    shared_theme=shared_theme[:200],
                    shared_insight=shared_insight[:500],
                    individual_observations=group[:20],
                    domains=list({
                    str(d) for o in group
                    for d in (o.get("domain_tags") or o.get("domains") or [])
                    if d
                }),
                    confidence=min(1.0, convergence_score * 1.2),
                )
                alerts.append(alert)
                logger.info(
                    "convergence_detected",
                    theme=shared_theme,
                    score=convergence_score,
                    fibres=len(fibre_ids),
                )

        return alerts

    def _synthesize_insight(self, group: List[Dict[str, Any]]) -> str:
        """Synthesize a shared insight from observations."""
        insights = []
        for o in group:
            ins = o.get("insight") or o.get("content") or o.get("theme")
            if ins:
                insights.append(str(ins)[:200])
        if not insights:
            return "Multiple Fibres converged on correlated observations."
        return " | ".join(insights[:5])
