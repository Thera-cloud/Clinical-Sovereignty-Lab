"""
SOVEREIGN SWARM — Predictive Coach Briefing Generator (S3)
Assembles pre-session briefings 2 hours before every scheduled session.
Includes current state, trajectory, prediction, and recommended focus.

Applied Solution S3: Predictive Coach Preparation Engine.
"""

import asyncio
import logging
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from app.models.solutions import (
    CurrentStateSection,
    PredictionSection,
    PredictiveCoachBriefing,
    RecommendedFocusSection,
    RiskSection,
    SessionContextSection,
    TrajectorySection,
)

logger = logging.getLogger("briefing_generator")


class BriefingGenerator:
    """
    Generates comprehensive pre-session briefings for coaches.
    Pulls data from coherence engine, session history, foresight engine,
    and pattern engine to assemble a complete picture.
    """

    def __init__(
        self,
        coherence_engine=None,
        nevedal_engine=None,
        foresight_engine=None,
        pattern_engine=None,
        sovereign_mind=None,
        db_pool=None,
    ):
        self._coherence = coherence_engine
        self._nevedal = nevedal_engine
        self._foresight = foresight_engine
        self._pattern = pattern_engine
        self._sovereign_mind = sovereign_mind
        self._db = db_pool

    async def generate_briefing(
        self,
        coach_id: str,
        member_id: str,
        session_datetime: datetime,
    ) -> PredictiveCoachBriefing:
        """Generate a complete pre-session briefing."""
        briefing = PredictiveCoachBriefing(
            coach_id=coach_id,
            member_id=member_id,
            session_datetime=session_datetime,
        )

        # Gather all sections concurrently
        results = await asyncio.gather(
            self._build_current_state(member_id),
            self._build_trajectory(member_id),
            self._build_prediction(member_id),
            self._build_session_context(member_id, coach_id),
            self._build_risk_assessment(member_id),
            return_exceptions=True,
        )

        # Assign results (handling any individual failures gracefully)
        if not isinstance(results[0], Exception):
            briefing.current_state = results[0]
        if not isinstance(results[1], Exception):
            briefing.trajectory = results[1]
        if not isinstance(results[2], Exception):
            briefing.prediction = results[2]
        if not isinstance(results[3], Exception):
            briefing.session_context = results[3]
        if not isinstance(results[4], Exception):
            briefing.risk_assessment = results[4]

        # Generate recommended focus using Sovereign Mind
        briefing.recommended_focus = await self._build_recommended_focus(briefing)

        # Load member name
        briefing.member_name = await self._get_member_name(member_id)

        # Persist briefing
        await self._persist_briefing(briefing)

        logger.info(
            "Briefing generated: coach=%s member=%s session=%s",
            coach_id, member_id, session_datetime,
        )
        return briefing

    # -------------------------------------------------------------------------
    # SECTION BUILDERS
    # -------------------------------------------------------------------------

    async def _build_current_state(self, member_id: str) -> CurrentStateSection:
        """Build the current state section."""
        section = CurrentStateSection()

        if self._coherence:
            try:
                metrics = await self._coherence.get_member_metrics(member_id)
                if metrics:
                    section.c_emo_current = metrics.get("c_emo", 0.0)
                    section.c_emo_7day_average = metrics.get("c_emo_7d_avg", 0.0)
            except Exception as e:
                logger.warning("Coherence data unavailable: %s", e)

        if self._db:
            try:
                async with self._db.acquire() as conn:
                    # Last session themes
                    row = await conn.fetchrow(
                        """
                        SELECT themes, unresolved_topics, homework_status
                        FROM session_summaries
                        WHERE client_id = $1
                        ORDER BY created_at DESC LIMIT 1
                        """,
                        member_id,
                    )
                    if row:
                        section.active_themes = row.get("themes", [])
                        section.unresolved_from_last_session = row.get("unresolved_topics", [])
                        section.homework_completion = row.get("homework_status", "unknown")
            except Exception as e:
                logger.warning("Session history unavailable: %s", e)

        return section

    async def _build_trajectory(self, member_id: str) -> TrajectorySection:
        """Build the trajectory section."""
        section = TrajectorySection()

        if self._coherence:
            try:
                history = await self._coherence.get_coherence_history(member_id, days=30)
                if history and len(history) >= 2:
                    recent = history[-7:]
                    direction = recent[-1] - recent[0]
                    velocity = direction / max(len(recent), 1)

                    section.c_emo_velocity = velocity
                    if direction > 0.05:
                        section.c_emo_direction = "improving"
                    elif direction < -0.05:
                        section.c_emo_direction = "declining"
                    else:
                        section.c_emo_direction = "stable"
            except Exception as e:
                logger.warning("Trajectory data unavailable: %s", e)

        return section

    async def _build_prediction(self, member_id: str) -> PredictionSection:
        """Build the prediction section using foresight engine."""
        section = PredictionSection()

        if self._foresight:
            try:
                prediction = await self._foresight.predict_session(member_id)
                if prediction:
                    section.predicted_theme = prediction.get("predicted_theme")
                    section.confidence = prediction.get("confidence", 0.0)
                    section.predicted_emotional_state = prediction.get("emotional_state")
                    section.cee_opportunity = prediction.get("cee_opportunity")
                    section.risk_if_missed = prediction.get("risk_if_missed")
            except Exception as e:
                logger.warning("Foresight prediction unavailable: %s", e)

        return section

    async def _build_session_context(
        self, member_id: str, coach_id: str
    ) -> SessionContextSection:
        """Build the session context section."""
        section = SessionContextSection()

        if self._db:
            try:
                async with self._db.acquire() as conn:
                    # Total sessions
                    count = await conn.fetchval(
                        "SELECT COUNT(*) FROM sessions WHERE client_id = $1 AND coach_id = $2",
                        member_id, coach_id,
                    )
                    section.total_sessions = count or 0

                    # Presenting problem
                    row = await conn.fetchrow(
                        """
                        SELECT presenting_concern, treatment_goals
                        FROM onboarding_initiations
                        WHERE user_id = $1
                        ORDER BY started_at DESC LIMIT 1
                        """,
                        member_id,
                    )
                    if row:
                        section.presenting_problem_original = row.get("presenting_concern")
            except Exception as e:
                logger.warning("Session context unavailable: %s", e)

        return section

    async def _build_risk_assessment(self, member_id: str) -> RiskSection:
        """Build the risk assessment section."""
        section = RiskSection()

        if self._db:
            try:
                async with self._db.acquire() as conn:
                    # Check crisis watchlist
                    watch = await conn.fetchrow(
                        "SELECT * FROM crisis_watchlist WHERE user_id = $1 AND resolved_at IS NULL",
                        member_id,
                    )
                    if watch:
                        section.current_risk_level = "elevated"
                        section.safety_plan_active = True

                    # Check safety plans
                    plan = await conn.fetchrow(
                        """
                        SELECT * FROM clinical_records
                        WHERE user_id = $1 AND record_type = 'safety_plan'
                        ORDER BY created_at DESC LIMIT 1
                        """,
                        member_id,
                    )
                    if plan:
                        section.safety_plan_active = True
                        section.last_safety_assessment_date = plan.get("created_at")
            except Exception as e:
                logger.warning("Risk assessment data unavailable: %s", e)

        return section

    async def _build_recommended_focus(
        self, briefing: PredictiveCoachBriefing
    ) -> RecommendedFocusSection:
        """Generate recommended focus using AI synthesis."""
        section = RecommendedFocusSection()

        if self._sovereign_mind:
            try:
                context = {
                    "current_c_emo": briefing.current_state.c_emo_current,
                    "trajectory": briefing.trajectory.c_emo_direction,
                    "predicted_theme": briefing.prediction.predicted_theme,
                    "risk_level": briefing.risk_assessment.current_risk_level,
                    "total_sessions": briefing.session_context.total_sessions,
                    "active_themes": briefing.current_state.active_themes,
                    "unresolved": briefing.current_state.unresolved_from_last_session,
                }
                response = await self._sovereign_mind.generate(
                    prompt="Generate a recommended focus for the upcoming therapy session",
                    context=context,
                )
                if response:
                    section.primary_recommendation = response
            except Exception as e:
                logger.warning("AI focus generation unavailable: %s", e)

        # Fallback defaults
        if not section.primary_recommendation:
            if briefing.prediction.predicted_theme:
                section.primary_recommendation = (
                    f"Focus on predicted theme: {briefing.prediction.predicted_theme}"
                )
            elif briefing.current_state.unresolved_from_last_session:
                section.primary_recommendation = (
                    f"Address unresolved: {', '.join(briefing.current_state.unresolved_from_last_session[:2])}"
                )
            else:
                section.primary_recommendation = "Open-ended check-in and reflection"

        section.therapeutic_frame = "EFT"
        return section

    # -------------------------------------------------------------------------
    # DATA ACCESS
    # -------------------------------------------------------------------------

    async def _get_member_name(self, member_id: str) -> str:
        """Get the member's display name."""
        if not self._db:
            return ""
        try:
            async with self._db.acquire() as conn:
                name = await conn.fetchval(
                    "SELECT name FROM users WHERE id = $1", member_id
                )
                return name or ""
        except Exception:
            return ""

    async def _persist_briefing(self, briefing: PredictiveCoachBriefing) -> None:
        """Persist the briefing to the database."""
        if not self._db:
            return
        try:
            async with self._db.acquire() as conn:
                await conn.execute(
                    """
                    INSERT INTO coach_briefings (
                        briefing_id, coach_id, member_id, member_name,
                        session_datetime, briefing_data
                    ) VALUES ($1, $2, $3, $4, $5, $6)
                    """,
                    briefing.briefing_id, briefing.coach_id,
                    briefing.member_id, briefing.member_name,
                    briefing.session_datetime,
                    briefing.model_dump_json(),
                )
        except Exception as e:
            logger.error("Briefing persistence failed: %s", e)
