"""
SOVEREIGN SWARM — Autonomous Coach Recruitment Pipeline (S6)
Orchestrates the recruitment pipeline from awareness through
onboarding, with graduated autonomy levels.

Applied Solution S6: Autonomous Coach Recruitment Pipeline.
"""

import asyncio
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from app.models.solutions import (
    CoachAssessmentResult,
    CoachRecruitmentCampaign,
)

logger = logging.getLogger("coach_recruitment")


class CoachRecruitmentService:
    """
    Manages the autonomous coach recruitment pipeline.
    Uses SkyEye for content distribution and engagement,
    assessment quizzes for qualification, and Golden Ticket
    invitations for approved candidates.
    """

    def __init__(
        self,
        sovereign_mind=None,
        autonomy_manager=None,
        notifications=None,
        db_pool=None,
    ):
        self._sovereign_mind = sovereign_mind
        self._autonomy = autonomy_manager
        self._notifications = notifications
        self._db = db_pool
        self._active_campaigns: Dict[str, CoachRecruitmentCampaign] = {}

    # -------------------------------------------------------------------------
    # CAMPAIGN MANAGEMENT
    # -------------------------------------------------------------------------

    async def create_campaign(
        self,
        target_specialty: str,
        target_platforms: List[str],
        content_pillars: List[str],
        autonomy_level: str = "observation",
    ) -> CoachRecruitmentCampaign:
        """Create a new recruitment campaign."""
        campaign = CoachRecruitmentCampaign(
            target_specialty=target_specialty,
            target_platforms=target_platforms,
            content_pillars=content_pillars,
            autonomy_level=autonomy_level,
        )
        self._active_campaigns[campaign.campaign_id] = campaign
        await self._persist_campaign(campaign)

        logger.info(
            "Recruitment campaign created: specialty=%s platforms=%s",
            target_specialty, target_platforms,
        )
        return campaign

    async def update_campaign_metrics(
        self,
        campaign_id: str,
        impressions: int = 0,
        engagements: int = 0,
        quiz_starts: int = 0,
        quiz_completions: int = 0,
    ) -> Optional[CoachRecruitmentCampaign]:
        """Update campaign engagement metrics."""
        campaign = self._active_campaigns.get(campaign_id)
        if not campaign:
            return None

        campaign.impressions += impressions
        campaign.engagements += engagements
        campaign.quiz_starts += quiz_starts
        campaign.quiz_completions += quiz_completions

        if campaign.quiz_starts > 0:
            campaign.conversion_rate = campaign.quiz_completions / campaign.quiz_starts

        await self._persist_campaign(campaign)
        return campaign

    # -------------------------------------------------------------------------
    # ASSESSMENT QUIZ
    # -------------------------------------------------------------------------

    async def process_assessment(
        self,
        prospect_name: str,
        prospect_email: Optional[str],
        quiz_responses: Dict[str, Any],
    ) -> CoachAssessmentResult:
        """Process a completed coach assessment quiz."""
        result = CoachAssessmentResult(
            prospect_name=prospect_name,
            prospect_email=prospect_email,
        )

        # Score therapeutic orientation
        result.therapeutic_orientation = self._score_orientation(quiz_responses)

        # Score AI comfort
        result.ai_comfort_level = self._score_ai_comfort(quiz_responses)

        # Score relational values
        result.relational_values_score = self._score_relational_values(quiz_responses)

        # Compute platform fit
        eft_alignment = result.therapeutic_orientation.get("EFT", 0.0)
        attachment_alignment = result.therapeutic_orientation.get("attachment_theory", 0.0)

        result.platform_fit_score = (
            eft_alignment * 0.3
            + attachment_alignment * 0.2
            + result.ai_comfort_level * 0.2
            + result.relational_values_score * 0.3
        )

        # Overall match score
        result.match_score = result.platform_fit_score

        # Golden Ticket eligibility: high platform fit + AI comfort
        result.golden_ticket_eligible = (
            result.platform_fit_score > 0.7
            and result.ai_comfort_level > 0.5
        )

        # Recommend Dojo tracks
        if result.golden_ticket_eligible:
            result.recommended_dojos = self._recommend_dojos(result)

        await self._persist_assessment(result)

        logger.info(
            "Assessment processed: %s fit=%.2f golden_ticket=%s",
            prospect_name, result.platform_fit_score, result.golden_ticket_eligible,
        )
        return result

    async def send_golden_ticket(
        self, assessment: CoachAssessmentResult, campaign_id: Optional[str] = None
    ) -> bool:
        """Send a Golden Ticket invitation to an eligible prospect."""
        if not assessment.golden_ticket_eligible:
            return False

        if self._notifications and assessment.prospect_email:
            try:
                await self._notifications.send_email(
                    to=assessment.prospect_email,
                    subject="You've Been Invited to Join the Sovereign Sanctuary",
                    body=(
                        f"Dear {assessment.prospect_name},\n\n"
                        f"Based on your assessment results, we believe you'd be "
                        f"an excellent fit for our platform. Your therapeutic orientation "
                        f"and relational values align beautifully with our mission.\n\n"
                        f"Platform Fit Score: {assessment.platform_fit_score:.0%}\n\n"
                        f"We'd like to invite you to join as a coach. "
                        f"Your recommended Dojo tracks: {', '.join(assessment.recommended_dojos)}\n\n"
                        f"This invitation is valid for 30 days.\n\n"
                        f"— Little Nate"
                    ),
                )
                # Update campaign metrics
                if campaign_id:
                    campaign = self._active_campaigns.get(campaign_id)
                    if campaign:
                        campaign.golden_tickets_sent += 1
                return True
            except Exception as e:
                logger.error("Golden Ticket send failed: %s", e)
        return False

    # -------------------------------------------------------------------------
    # SCORING HELPERS
    # -------------------------------------------------------------------------

    def _score_orientation(self, responses: Dict[str, Any]) -> Dict[str, float]:
        """Score therapeutic orientation from quiz responses."""
        orientations = {
            "EFT": 0.0,
            "attachment_theory": 0.0,
            "narrative": 0.0,
            "somatic": 0.0,
            "cognitive_behavioral": 0.0,
            "psychodynamic": 0.0,
        }
        # Map quiz answers to orientation scores
        training = responses.get("primary_training", "")
        if "emotionally focused" in training.lower() or "eft" in training.lower():
            orientations["EFT"] = 0.9
        if "attachment" in training.lower():
            orientations["attachment_theory"] = 0.8
        if "narrative" in training.lower():
            orientations["narrative"] = 0.7
        if "somatic" in training.lower():
            orientations["somatic"] = 0.7
        if "cbt" in training.lower() or "cognitive" in training.lower():
            orientations["cognitive_behavioral"] = 0.7

        # Secondary training bonus
        for sec in responses.get("secondary_training", []):
            for key in orientations:
                if key.lower() in sec.lower():
                    orientations[key] = max(orientations[key], 0.5)

        return orientations

    def _score_ai_comfort(self, responses: Dict[str, Any]) -> float:
        """Score AI comfort level from quiz responses."""
        comfort_map = {
            "very_comfortable": 0.9,
            "comfortable": 0.7,
            "neutral": 0.5,
            "cautious": 0.3,
            "resistant": 0.1,
        }
        return comfort_map.get(responses.get("ai_comfort", "neutral"), 0.5)

    def _score_relational_values(self, responses: Dict[str, Any]) -> float:
        """Score relational values alignment."""
        score = 0.0
        values_check = [
            ("emotional_safety_priority", 0.25),
            ("collaborative_relationship", 0.25),
            ("cultural_humility", 0.2),
            ("process_over_outcome", 0.15),
            ("attachment_aware", 0.15),
        ]
        for key, weight in values_check:
            if responses.get(key, False):
                score += weight
        return min(score, 1.0)

    def _recommend_dojos(self, result: CoachAssessmentResult) -> List[str]:
        """Recommend Dojo training tracks based on assessment."""
        dojos = ["Platform Orientation"]
        if result.therapeutic_orientation.get("EFT", 0) < 0.5:
            dojos.append("EFT Foundations")
        if result.ai_comfort_level < 0.7:
            dojos.append("AI Collaboration Skills")
        dojos.append("Nevedal Coherence Basics")
        return dojos

    # -------------------------------------------------------------------------
    # PERSISTENCE
    # -------------------------------------------------------------------------

    async def _persist_campaign(self, campaign: CoachRecruitmentCampaign) -> None:
        if not self._db:
            return
        try:
            async with self._db.acquire() as conn:
                await conn.execute(
                    """
                    INSERT INTO coach_recruitment_campaigns (
                        campaign_id, target_specialty, target_platforms,
                        autonomy_level, impressions, engagements,
                        quiz_starts, quiz_completions, golden_tickets_sent
                    ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
                    ON CONFLICT (campaign_id) DO UPDATE SET
                        impressions = EXCLUDED.impressions,
                        engagements = EXCLUDED.engagements,
                        quiz_starts = EXCLUDED.quiz_starts,
                        quiz_completions = EXCLUDED.quiz_completions,
                        golden_tickets_sent = EXCLUDED.golden_tickets_sent
                    """,
                    campaign.campaign_id, campaign.target_specialty,
                    str(campaign.target_platforms), campaign.autonomy_level,
                    campaign.impressions, campaign.engagements,
                    campaign.quiz_starts, campaign.quiz_completions,
                    campaign.golden_tickets_sent,
                )
        except Exception as e:
            logger.error("Campaign persistence failed: %s", e)

    async def _persist_assessment(self, result: CoachAssessmentResult) -> None:
        if not self._db:
            return
        try:
            async with self._db.acquire() as conn:
                await conn.execute(
                    """
                    INSERT INTO coach_assessment_results (
                        quiz_id, prospect_name, prospect_email,
                        therapeutic_orientation, ai_comfort_level,
                        platform_fit_score, match_score, golden_ticket_eligible
                    ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
                    """,
                    result.quiz_id, result.prospect_name, result.prospect_email,
                    str(result.therapeutic_orientation), result.ai_comfort_level,
                    result.platform_fit_score, result.match_score,
                    result.golden_ticket_eligible,
                )
        except Exception as e:
            logger.error("Assessment persistence failed: %s", e)
