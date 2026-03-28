"""
SOVEREIGN SWARM — Cultural Signal to Member Matching (S5)
Matches external cultural signals to potentially affected members
based on demographics, location, and personal context.

Applied Solution S5: Cultural Sentinel Community Early Warning.
"""

import asyncio
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from app.models.solutions import (
    CulturalSignal,
    MemberImpactAssessment,
)

logger = logging.getLogger("member_matching")


class MemberMatchingService:
    """
    Matches cultural signals detected by SkyEye + Cultural Sentinel
    to individual members who may be affected.
    """

    def __init__(self, db_pool=None, sovereign_mind=None):
        self._db = db_pool
        self._sovereign_mind = sovereign_mind

    async def match_signal_to_members(
        self, signal: CulturalSignal
    ) -> List[MemberImpactAssessment]:
        """
        Given a cultural signal, identify members who may be impacted.
        Uses demographic data, location, and personal context.
        """
        members = await self._load_potentially_affected_members(signal)
        assessments = []

        for member in members:
            assessment = await self._assess_impact(signal, member)
            if assessment and assessment.match_confidence > 0.3:
                assessments.append(assessment)

        # Sort by impact severity
        severity_order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
        assessments.sort(
            key=lambda a: severity_order.get(a.predicted_impact_severity, 4)
        )

        logger.info(
            "Signal %s matched to %d members (type=%s)",
            signal.signal_id, len(assessments), signal.signal_type,
        )
        return assessments

    async def _assess_impact(
        self, signal: CulturalSignal, member: Dict[str, Any]
    ) -> Optional[MemberImpactAssessment]:
        """Assess the impact of a cultural signal on a specific member."""
        member_id = member.get("id", "")
        confidence = 0.0
        reasons = []

        # Demographic match
        member_demographics = member.get("demographics", {})
        for demo in signal.affected_demographics:
            if demo.lower() in str(member_demographics).lower():
                confidence += 0.3
                reasons.append(f"Demographic match: {demo}")

        # Geographic match
        member_location = member.get("location", "")
        if signal.geographic_scope == "local" and member_location:
            confidence += 0.2
            reasons.append("Geographic proximity")

        # Keyword/topic match with member's session themes
        member_themes = member.get("themes", [])
        keyword_matches = sum(
            1 for kw in signal.keywords
            if any(kw.lower() in theme.lower() for theme in member_themes)
        )
        if keyword_matches > 0:
            confidence += min(keyword_matches * 0.15, 0.4)
            reasons.append(f"Topic relevance ({keyword_matches} matches)")

        # Signal confidence and volume boost
        confidence *= signal.confidence

        if confidence < 0.3:
            return None

        # Determine severity
        if confidence > 0.7:
            severity = "high"
        elif confidence > 0.5:
            severity = "medium"
        else:
            severity = "low"

        return MemberImpactAssessment(
            member_id=member_id,
            match_confidence=min(confidence, 1.0),
            match_reason="; ".join(reasons),
            predicted_impact_severity=severity,
            recommended_coach_action=(
                "Proactive check-in recommended" if severity in ("high", "medium")
                else "Monitor during next session"
            ),
        )

    async def _load_potentially_affected_members(
        self, signal: CulturalSignal
    ) -> List[Dict[str, Any]]:
        """Load members who could be affected by a cultural signal."""
        if not self._db:
            return []
        try:
            async with self._db.acquire() as conn:
                rows = await conn.fetch(
                    """
                    SELECT u.id, u.name, u.metadata,
                           COALESCE(
                               (SELECT jsonb_agg(DISTINCT t)
                                FROM sessions s,
                                LATERAL jsonb_array_elements_text(s.themes) AS t
                                WHERE s.client_id = u.id
                                AND s.created_at > NOW() - INTERVAL '90 days'),
                               '[]'::jsonb
                           ) AS themes
                    FROM users u
                    WHERE u.role = 'client' AND u.active = true
                    """
                )
                return [
                    {
                        "id": row["id"],
                        "name": row.get("name", ""),
                        "demographics": row.get("metadata", {}),
                        "themes": row.get("themes", []),
                    }
                    for row in rows
                ]
        except Exception as e:
            logger.error("Member loading failed: %s", e)
            return []
