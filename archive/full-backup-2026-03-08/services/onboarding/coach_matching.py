"""
Onboarding Coach Matching Service
Extends the core CoachMatcher with onboarding-specific logic:
cold-start compatibility, availability filtering, and member choice.

Operational Specifications §1.3 — Coach Matching.
"""

import asyncio
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from app.models.onboarding import (
    CoachMatchResult,
    CoachProfile,
    MatchCriteria,
    MatchScore,
    NevedalColdStart,
    WelcomeConversation,
)

logger = logging.getLogger("onboarding.coach_matching")


# =============================================================================
# MATCHING WEIGHTS
# =============================================================================

MATCH_WEIGHTS = {
    MatchCriteria.ORIENTATION_FIT: 0.25,
    MatchCriteria.ATTACHMENT_COMPATIBILITY: 0.20,
    MatchCriteria.SPECIALTY_RELEVANCE: 0.20,
    MatchCriteria.AI_COMFORT: 0.10,
    MatchCriteria.AVAILABILITY: 0.15,
    MatchCriteria.CULTURAL_MATCH: 0.10,
}


class OnboardingCoachMatchingService:
    """
    Matches a newly onboarded member with the best-fit coach using
    data from the welcome conversation and cold-start calibration.
    """

    def __init__(self, db_pool=None, coach_matcher=None):
        self._db = db_pool
        self._coach_matcher = coach_matcher

    async def find_matches(
        self,
        member_id: str,
        welcome: WelcomeConversation,
        cold_start: NevedalColdStart,
        available_coaches: Optional[List[CoachProfile]] = None,
        top_n: int = 3,
    ) -> CoachMatchResult:
        """
        Generate top-N coach matches for a new member.
        Uses welcome conversation themes + cold-start Nevedal data.
        """
        if not available_coaches:
            available_coaches = await self._load_available_coaches()

        if not available_coaches:
            logger.warning("No coaches available for matching (member %s)", member_id)
            return CoachMatchResult(member_id=member_id, match_confidence=0.0)

        scores = []
        for coach in available_coaches:
            score = await self._score_match(coach, welcome, cold_start)
            scores.append(score)

        # Sort by overall score descending
        scores.sort(key=lambda s: s.overall_score, reverse=True)
        top_matches = scores[:top_n]

        result = CoachMatchResult(
            member_id=member_id,
            top_matches=top_matches,
            match_confidence=top_matches[0].overall_score if top_matches else 0.0,
        )

        logger.info(
            "Coach matching for member %s: %d candidates, top score=%.3f",
            member_id,
            len(scores),
            result.match_confidence,
        )
        return result

    async def select_coach(
        self,
        result: CoachMatchResult,
        coach_id: str,
        method: str = "member_choice",
    ) -> CoachMatchResult:
        """Record the final coach selection."""
        result.selected_coach_id = coach_id
        result.selection_method = method
        result.match_timestamp = datetime.utcnow()
        logger.info(
            "Coach %s selected for member %s (method=%s)",
            coach_id, result.member_id, method,
        )
        return result

    # -------------------------------------------------------------------------
    # SCORING
    # -------------------------------------------------------------------------

    async def _score_match(
        self,
        coach: CoachProfile,
        welcome: WelcomeConversation,
        cold_start: NevedalColdStart,
    ) -> MatchScore:
        """Compute a composite match score between member and coach."""
        member_id = cold_start.user_id

        # 1. Orientation fit: EFT alignment
        orientation_fit = self._score_orientation_fit(
            coach, welcome
        )

        # 2. Attachment compatibility
        attachment_compat = self._score_attachment_compatibility(
            coach, cold_start
        )

        # 3. Specialty relevance
        specialty_relevance = self._score_specialty_relevance(
            coach, welcome
        )

        # 4. AI comfort match
        ai_comfort = coach.ai_comfort_level

        # 5. Availability
        availability = self._score_availability(coach)

        # 6. Cultural match
        cultural = self._score_cultural_match(coach, welcome)

        # Weighted composite
        overall = (
            orientation_fit * MATCH_WEIGHTS[MatchCriteria.ORIENTATION_FIT]
            + attachment_compat * MATCH_WEIGHTS[MatchCriteria.ATTACHMENT_COMPATIBILITY]
            + specialty_relevance * MATCH_WEIGHTS[MatchCriteria.SPECIALTY_RELEVANCE]
            + ai_comfort * MATCH_WEIGHTS[MatchCriteria.AI_COMFORT]
            + availability * MATCH_WEIGHTS[MatchCriteria.AVAILABILITY]
            + cultural * MATCH_WEIGHTS[MatchCriteria.CULTURAL_MATCH]
        )

        # Caseload penalty: reduce score if coach is near capacity
        caseload_factor = max(
            0.5,
            1.0 - (coach.current_caseload / max(coach.max_caseload, 1)) * 0.5,
        )
        overall *= caseload_factor

        reasons = []
        if orientation_fit > 0.7:
            reasons.append("Strong therapeutic orientation match")
        if specialty_relevance > 0.7:
            reasons.append("Specialty aligns with presenting concern")
        if attachment_compat > 0.7:
            reasons.append("Attachment style expertise match")

        return MatchScore(
            coach_id=coach.coach_id,
            member_id=member_id,
            overall_score=min(overall, 1.0),
            orientation_fit=orientation_fit,
            attachment_compatibility=attachment_compat,
            specialty_relevance=specialty_relevance,
            ai_comfort_match=ai_comfort,
            availability_overlap=availability,
            cultural_match=cultural,
            caseload_factor=caseload_factor,
            reasons=reasons,
        )

    def _score_orientation_fit(
        self, coach: CoachProfile, welcome: WelcomeConversation
    ) -> float:
        """Score how well the coach's orientation fits the member's needs."""
        # EFT alignment is primary
        eft_score = coach.therapeutic_orientation.get("EFT", 0.0)
        attachment_score = coach.therapeutic_orientation.get("attachment_theory", 0.0)
        # Bonus for relationship/family themes
        themes = set()
        for turn in welcome.turns:
            themes.update(turn.detected_themes)
        relationship_bonus = 0.1 if "relationship" in themes or "family" in themes else 0.0
        return min(eft_score * 0.6 + attachment_score * 0.3 + relationship_bonus, 1.0)

    def _score_attachment_compatibility(
        self, coach: CoachProfile, cold_start: NevedalColdStart
    ) -> float:
        """
        Score attachment style compatibility.
        Higher gamma_env suggests more avoidant attachment → need coach
        with avoidant expertise.
        """
        gamma = cold_start.computed_gamma_env
        if gamma > 0.6:
            # Higher decoherence → likely avoidant/dismissive
            return 0.8 if "avoidant" in coach.attachment_style_expertise else 0.4
        elif gamma < 0.3:
            # Lower decoherence → likely anxious/preoccupied
            return 0.8 if "anxious" in coach.attachment_style_expertise else 0.4
        return 0.6  # Moderate gamma → flexible

    def _score_specialty_relevance(
        self, coach: CoachProfile, welcome: WelcomeConversation
    ) -> float:
        """Score how relevant the coach's specialties are to the member's concerns."""
        if not welcome.presenting_concern:
            return 0.5
        concern_lower = welcome.presenting_concern.lower()
        matches = sum(
            1 for s in coach.specialties
            if s.lower() in concern_lower or concern_lower in s.lower()
        )
        return min(matches * 0.3 + 0.3, 1.0) if matches else 0.3

    def _score_availability(self, coach: CoachProfile) -> float:
        """Score coach availability (caseload headroom)."""
        if coach.max_caseload <= 0:
            return 0.0
        utilization = coach.current_caseload / coach.max_caseload
        return max(0.0, 1.0 - utilization)

    def _score_cultural_match(
        self, coach: CoachProfile, welcome: WelcomeConversation
    ) -> float:
        """Score cultural competency match."""
        # Base score for having any cultural competencies
        if not coach.cultural_competencies:
            return 0.3
        return min(len(coach.cultural_competencies) * 0.15, 1.0)

    # -------------------------------------------------------------------------
    # DATA LOADING
    # -------------------------------------------------------------------------

    async def _load_available_coaches(self) -> List[CoachProfile]:
        """Load available coaches from the database."""
        if not self._db:
            logger.warning("No database pool available for coach loading")
            return []
        try:
            async with self._db.acquire() as conn:
                rows = await conn.fetch(
                    """
                    SELECT id, name, specialties, therapeutic_orientation,
                           ai_comfort_level, current_caseload, max_caseload
                    FROM coaches
                    WHERE active = true AND current_caseload < max_caseload
                    ORDER BY current_caseload ASC
                    """
                )
                coaches = []
                for row in rows:
                    coaches.append(CoachProfile(
                        coach_id=str(row["id"]),
                        name=row.get("name", ""),
                        specialties=row.get("specialties", []),
                        therapeutic_orientation=row.get("therapeutic_orientation", {}),
                        ai_comfort_level=row.get("ai_comfort_level", 0.5),
                        current_caseload=row.get("current_caseload", 0),
                        max_caseload=row.get("max_caseload", 30),
                    ))
                return coaches
        except Exception as e:
            logger.error("Failed to load coaches: %s", e)
            return []
