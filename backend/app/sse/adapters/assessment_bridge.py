"""
Assessment Bridge — quiz / assessment outcomes → Thera-World calibration and quest weighting.
"""
from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional, Sequence

logger = logging.getLogger(__name__)

# Map narrative priorities to quest_mission_engine.GOAL_TO_DOMAINS keys (for crystal depth weighting)
PRIORITY_TO_QUEST_GOAL_KEYS: Dict[str, List[str]] = {
    "grounding": ["anxiety"],
    "connection": ["relationship"],
    "shame_resilience": ["confidence", "self-esteem"],
    "activation": ["depression"],
    "general_growth": [],
}


class AssessmentBridge:
    def __init__(self, db_pool):
        self.db = db_pool

    @staticmethod
    def canonical_scores_from_dimensions(dim_averages: Dict[str, Any]) -> Dict[str, float]:
        """
        Normalize arbitrary dimension keys to 0–10 floats for calibration.
        quiz_api stores 0–100; clinical assessments may use 0–10.
        """
        out: Dict[str, float] = {}
        for raw_key, raw_val in (dim_averages or {}).items():
            try:
                v = float(raw_val)
            except (TypeError, ValueError):
                continue
            key = str(raw_key).lower().strip()
            if v > 10:
                v = min(10.0, v / 10.0)
            out[key] = round(v, 2)

        # Aggregate synonyms into canonical buckets (max in group)
        def bucket(keys: Sequence[str]) -> float:
            return max((out.get(k, 0.0) for k in keys), default=0.0)

        canonical = {
            "anxiety": max(
                bucket(["anxiety", "stress", "worry", "panic", "nervous"]),
                out.get("anxiety", 0.0),
            ),
            "attachment": max(
                bucket(["attachment", "connection", "bonding", "trust_relationship"]),
                out.get("attachment", 0.0),
            ),
            "shame": max(
                bucket(["shame", "self_worth", "self-worth", "worthlessness", "guilt"]),
                out.get("shame", 0.0),
            ),
            "depression": max(
                bucket(["depression", "mood", "hopelessness", "fatigue", "motivation"]),
                out.get("depression", 0.0),
            ),
        }
        return {k: round(v, 2) for k, v in canonical.items() if v > 0}

    async def get_assessment_calibration(self, user_id: str) -> Dict[str, Any]:
        """
        Latest assessment results that influence story generation and quest weighting.
        """
        if not self.db or not (user_id or "").strip():
            return {"has_assessments": False}

        assessments = await self._get_recent_assessments(user_id)
        if not assessments:
            return {"has_assessments": False}

        return {
            "has_assessments": True,
            "domain_priorities": self._compute_domain_priorities(assessments),
            "risk_areas": self._identify_risk_areas(assessments),
            "recommended_quest_types": self._recommend_quests(assessments),
            "latest_scores": assessments[0],
        }

    async def _get_recent_assessments(self, user_id: str) -> List[Dict[str, Any]]:
        try:
            async with self.db.acquire() as conn:
                rows = await conn.fetch(
                    """
                    SELECT assessment_type, scores, completed_at, result_summary, status
                    FROM assessment_results
                    WHERE user_id = $1
                      AND status = 'completed'
                    ORDER BY completed_at DESC
                    LIMIT 3
                    """,
                    user_id.strip(),
                )
        except Exception as e:
            logger.debug("AssessmentBridge._get_recent_assessments: %s", e)
            return []

        out: List[Dict[str, Any]] = []
        for r in rows:
            d = dict(r)
            scores = d.get("scores")
            if isinstance(scores, str):
                try:
                    scores = json.loads(scores)
                except Exception:
                    scores = {}
            if not isinstance(scores, dict):
                scores = {}
            d["scores"] = scores
            ts = d.get("completed_at")
            d["completed_at"] = ts.isoformat() if ts and hasattr(ts, "isoformat") else str(ts) if ts else None
            out.append(d)
        return out

    def _canonical_from_row(self, row: Dict[str, Any]) -> Dict[str, float]:
        scores = row.get("scores") or {}
        if isinstance(scores, str):
            try:
                scores = json.loads(scores)
            except Exception:
                scores = {}
        c10 = scores.get("canonical_0_10")
        if isinstance(c10, dict):
            return {str(k): float(v) for k, v in c10.items() if self._safe_float(v) is not None}
        dim = scores.get("dimensions_0_100")
        if isinstance(dim, dict):
            return self.canonical_scores_from_dimensions(dim)
        return self.canonical_scores_from_dimensions(scores)

    @staticmethod
    def _safe_float(v: Any) -> Optional[float]:
        try:
            return float(v)
        except (TypeError, ValueError):
            return None

    def _compute_domain_priorities(self, assessments: List[Dict[str, Any]]) -> List[str]:
        latest = assessments[0]
        scores = self._canonical_from_row(latest)
        priorities: List[str] = []

        if scores.get("anxiety", 0) > 7:
            priorities.append("grounding")
        att = scores.get("attachment")
        if att is None:
            att = 5.0
        if att < 4:
            priorities.append("connection")
        if scores.get("shame", 0) > 6:
            priorities.append("shame_resilience")
        if scores.get("depression", 0) > 7:
            priorities.append("activation")
        if not priorities:
            priorities.append("general_growth")
        return priorities

    def _identify_risk_areas(self, assessments: List[Dict[str, Any]]) -> List[str]:
        risks: List[str] = []
        latest = assessments[0]
        scores = self._canonical_from_row(latest)
        summary = (latest.get("result_summary") or "").lower()

        if scores.get("anxiety", 0) > 8:
            risks.append("acute_anxiety")
        if scores.get("depression", 0) > 8:
            risks.append("severe_low_mood")
        if scores.get("shame", 0) > 8:
            risks.append("acute_shame")
        att = scores.get("attachment")
        if att is None:
            att = 5.0
        if att < 3:
            risks.append("attachment_distress")

        if any(x in summary for x in ("self-harm", "self harm", "suicid", "kill myself", "end it all")):
            risks.append("safety_concern_language")

        return list(dict.fromkeys(risks))

    def _recommend_quests(self, assessments: List[Dict[str, Any]]) -> List[str]:
        """
        Quest / mission emphasis tags aligned with sse quest engine goal keywords.
        """
        priorities = self._compute_domain_priorities(assessments)
        rec: List[str] = []
        for p in priorities:
            rec.extend(PRIORITY_TO_QUEST_GOAL_KEYS.get(p, []))
        if not rec:
            rec = ["relationship"]
        return list(dict.fromkeys(rec))

    def quest_goal_keywords_for_priorities(self, domain_priorities: List[str]) -> List[str]:
        keys: List[str] = []
        for p in domain_priorities or []:
            keys.extend(PRIORITY_TO_QUEST_GOAL_KEYS.get(p, []))
        return list(dict.fromkeys(keys))
