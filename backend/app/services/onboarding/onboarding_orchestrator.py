"""
Onboarding Orchestrator
Coordinates the full onboarding flow: welcome → cold-start → coach match → fibre assignment.
Manages the 72-hour automated onboarding sequence.

Operational Specifications §1 — Onboarding (Master Orchestrator).
"""

import asyncio
import logging
from datetime import datetime, timedelta
from typing import Any, Dict, Optional

from app.models.onboarding import (
    OnboardingInitiation,
    OnboardingStage,
    WelcomeConversationType,
)
from app.services.onboarding.welcome_conversation import WelcomeConversationService
from app.services.onboarding.cold_start_nevedal import ColdStartNevedalService
from app.services.onboarding.coach_matching import OnboardingCoachMatchingService

logger = logging.getLogger("onboarding.orchestrator")


class OnboardingOrchestrator:
    """
    Master orchestrator for the onboarding flow.

    Timeline:
    - Hour 0: Welcome conversation + cold-start calibration
    - Hour 1-4: Coach matching + presentation
    - Hour 4-24: Coach intro session scheduling
    - Hour 24-72: Drip sequence (check-ins, tips, engagement)
    """

    def __init__(
        self,
        welcome_service: Optional[WelcomeConversationService] = None,
        cold_start_service: Optional[ColdStartNevedalService] = None,
        coach_matching_service: Optional[OnboardingCoachMatchingService] = None,
        fibre_manager=None,
        drip_scheduler=None,
        notifications=None,
        db_pool=None,
    ):
        self._welcome = welcome_service or WelcomeConversationService()
        self._cold_start = cold_start_service or ColdStartNevedalService()
        self._coach_matching = coach_matching_service or OnboardingCoachMatchingService()
        self._fibre_manager = fibre_manager
        self._drip_scheduler = drip_scheduler
        self._notifications = notifications
        self._db = db_pool

    async def start_onboarding(
        self,
        user_id: str,
        email: Optional[str] = None,
        name: Optional[str] = None,
        referral_source: Optional[str] = None,
        subscription_tier: str = "threshold",
        conversation_type: WelcomeConversationType = WelcomeConversationType.CASUAL,
    ) -> OnboardingInitiation:
        """
        Initiate the onboarding sequence for a new member.
        Returns the master onboarding record.
        """
        initiation = OnboardingInitiation(
            user_id=user_id,
            email=email,
            name=name,
            referral_source=referral_source,
            subscription_tier=subscription_tier,
        )

        # Start welcome conversation
        conversation = await self._welcome.start_conversation(
            user_id=user_id,
            conversation_type=conversation_type,
        )
        initiation.welcome_conversation_id = conversation.conversation_id

        # Start cold-start calibration
        cold_start = await self._cold_start.initiate_calibration(user_id)

        # Store initial state
        await self._persist_initiation(initiation)

        logger.info(
            "Onboarding started for user %s (tier=%s, referral=%s)",
            user_id, subscription_tier, referral_source,
        )

        return initiation

    async def process_welcome_message(
        self,
        initiation: OnboardingInitiation,
        message: str,
    ) -> Dict[str, Any]:
        """
        Process a message during the welcome conversation phase.
        Also feeds text to cold-start calibration.
        """
        # Retrieve or reconstruct conversation state
        conversation = await self._get_conversation(initiation)
        cold_start = await self._get_cold_start(initiation)

        # Process through welcome service
        nate_response = await self._welcome.process_member_message(
            conversation, message
        )

        # Feed to cold-start calibration
        cold_start = await self._cold_start.process_text_exchange(
            cold_start, message, nate_response
        )

        # Check if safety flag was raised
        if conversation.safety_flag:
            initiation.metadata["safety_flag"] = True
            initiation.metadata["safety_reason"] = conversation.safety_flag_reason
            # Immediate escalation
            if self._notifications:
                await self._notifications.send_safety_alert(
                    user_id=initiation.user_id,
                    reason=conversation.safety_flag_reason,
                )

        # Update Nevedal values
        if cold_start.baseline_established:
            initiation.cold_start_complete = True
            initiation.initial_c_emo = cold_start.cold_start_c_emo
            initiation.initial_gamma_env = cold_start.computed_gamma_env
            initiation.initial_p_ent = cold_start.computed_p_ent

        # Auto-transition to coach match when welcome is sufficient
        member_turns = [t for t in conversation.turns if t.role == "member"]
        if len(member_turns) >= 3 and cold_start.baseline_established:
            await self._transition_to_coach_match(initiation, conversation, cold_start)

        return {
            "nate_response": nate_response,
            "stage": initiation.stage.value,
            "safety_flag": conversation.safety_flag,
            "cold_start_complete": initiation.cold_start_complete,
            "c_emo": cold_start.cold_start_c_emo,
        }

    async def process_coach_selection(
        self,
        initiation: OnboardingInitiation,
        coach_id: str,
    ) -> OnboardingInitiation:
        """Record the member's coach selection and proceed to fibre assignment."""
        initiation.assigned_coach_id = coach_id
        initiation.stage = OnboardingStage.FIBRE_ASSIGNMENT

        # Assign initial Fibres
        if self._fibre_manager:
            try:
                fibres = await self._fibre_manager.assign_initial_fibres(
                    user_id=initiation.user_id,
                    coach_id=coach_id,
                    subscription_tier=initiation.subscription_tier,
                )
                initiation.assigned_fibre_ids = [f.fibre_id for f in fibres]
            except Exception as e:
                logger.error("Fibre assignment failed: %s", e)

        # Schedule the 72-hour drip sequence
        if self._drip_scheduler:
            try:
                await self._drip_scheduler.schedule_onboarding_sequence(
                    user_id=initiation.user_id,
                    coach_id=coach_id,
                )
            except Exception as e:
                logger.error("Drip schedule failed: %s", e)

        # Complete onboarding
        initiation.stage = OnboardingStage.COMPLETE
        initiation.completed_at = datetime.utcnow()
        await self._persist_initiation(initiation)

        logger.info(
            "Onboarding complete for user %s: coach=%s, fibres=%d",
            initiation.user_id,
            coach_id,
            len(initiation.assigned_fibre_ids),
        )

        return initiation

    # -------------------------------------------------------------------------
    # INTERNAL TRANSITIONS
    # -------------------------------------------------------------------------

    async def _transition_to_coach_match(self, initiation, conversation, cold_start):
        """Transition from welcome to coach matching."""
        # Complete the welcome conversation
        await self._welcome.complete_conversation(conversation)
        initiation.stage = OnboardingStage.COACH_MATCH

        # Run coach matching
        try:
            result = await self._coach_matching.find_matches(
                member_id=initiation.user_id,
                welcome=conversation,
                cold_start=cold_start,
            )
            initiation.metadata["coach_match_result"] = {
                "top_matches": [
                    {"coach_id": m.coach_id, "score": m.overall_score, "reasons": m.reasons}
                    for m in result.top_matches
                ],
                "confidence": result.match_confidence,
            }
        except Exception as e:
            logger.error("Coach matching failed: %s", e)

    # -------------------------------------------------------------------------
    # PERSISTENCE (abstract — uses DB when available)
    # -------------------------------------------------------------------------

    async def _persist_initiation(self, initiation: OnboardingInitiation):
        """Persist the onboarding initiation record."""
        if not self._db:
            return
        try:
            async with self._db.acquire() as conn:
                await conn.execute(
                    """
                    INSERT INTO onboarding_initiations (
                        initiation_id, user_id, email, name, subscription_tier,
                        stage, started_at, completed_at, assigned_coach_id, metadata
                    ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
                    ON CONFLICT (initiation_id) DO UPDATE SET
                        stage = EXCLUDED.stage,
                        completed_at = EXCLUDED.completed_at,
                        assigned_coach_id = EXCLUDED.assigned_coach_id,
                        metadata = EXCLUDED.metadata
                    """,
                    initiation.initiation_id,
                    initiation.user_id,
                    initiation.email,
                    initiation.name,
                    initiation.subscription_tier,
                    initiation.stage.value,
                    initiation.started_at,
                    initiation.completed_at,
                    initiation.assigned_coach_id,
                    str(initiation.metadata),
                )
        except Exception as e:
            logger.error("Failed to persist onboarding initiation: %s", e)

    async def _get_conversation(self, initiation):
        """Retrieve the welcome conversation state from DB, or create a new one."""
        from app.models.onboarding import WelcomeConversation
        if self._db:
            try:
                async with self._db.acquire() as conn:
                    row = await conn.fetchrow(
                        """SELECT * FROM welcome_conversations
                        WHERE user_id = $1 ORDER BY started_at DESC LIMIT 1""",
                        initiation.user_id,
                    )
                    if row:
                        return WelcomeConversation(
                            user_id=initiation.user_id,
                            conversation_id=row.get("id", row.get("conversation_id", "")),
                            status=row.get("status", "active"),
                        )
            except Exception:
                pass
        return WelcomeConversation(user_id=initiation.user_id)

    async def _get_cold_start(self, initiation):
        """Retrieve the cold-start calibration state from DB, or create a new one."""
        from app.models.onboarding import NevedalColdStart
        if self._db:
            try:
                async with self._db.acquire() as conn:
                    row = await conn.fetchrow(
                        "SELECT * FROM nevedal_cold_starts WHERE user_id = $1",
                        initiation.user_id,
                    )
                    if row:
                        return NevedalColdStart(
                            user_id=initiation.user_id,
                            computed_p_ent=row.get("computed_p_ent", 0.5),
                            computed_gamma_env=row.get("computed_gamma_env", 0.5),
                            computed_t_tunnel=row.get("computed_t_tunnel", 0.3),
                            cold_start_c_emo=row.get("cold_start_c_emo", 0.0),
                            baseline_established=row.get("baseline_established", False),
                        )
            except Exception:
                pass
        return NevedalColdStart(user_id=initiation.user_id)
