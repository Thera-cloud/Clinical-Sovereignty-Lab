"""
SOVEREIGN SWARM — Silent Fibre Detector (S1)
Monitors the Trail Map for member inactivity, computes risk tiers,
and triggers Quakete Ramp-Up outreach sequences.

Applied Solution S1: Silent Crisis Detector.
"""

import asyncio
import json
import logging
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

from app.models.solutions import (
    MemberHealthView,
    RampUpActivation,
    RiskTier,
    SilentAlert,
    SilentCrisisBriefing,
)

logger = logging.getLogger("silent_fibre_detector")


# =============================================================================
# SILENCE THRESHOLDS (hours)
# =============================================================================

SILENCE_THRESHOLDS = {
    RiskTier.YELLOW: 48,
    RiskTier.ORANGE: 96,
    RiskTier.RED: 168,
    RiskTier.CRITICAL: 336,
}

# C_emo trajectory modifiers
TRAJECTORY_RISK_MULTIPLIER = {
    "declining": 0.7,     # Reach threshold sooner
    "unknown": 1.0,       # Neutral
    "stable": 1.2,        # Slightly slower
    "rising": 1.5,        # Much slower (member was trending well)
}


class SilentFibreDetector:
    """
    Scans all active members for silence patterns and generates
    alerts with appropriate risk tiers and outreach actions.
    """

    def __init__(
        self,
        trail_map=None,
        ramp_up_engine=None,
        sovereign_mind=None,
        notifications=None,
        db_pool=None,
    ):
        self._trail_map = trail_map
        self._ramp_up = ramp_up_engine
        self._sovereign_mind = sovereign_mind
        self._notifications = notifications
        self._db = db_pool

    # -------------------------------------------------------------------------
    # FULL SWEEP
    # -------------------------------------------------------------------------

    async def sweep(self) -> List[SilentAlert]:
        """
        Perform a full sweep of all active members.
        Returns list of generated alerts.
        """
        members = await self._get_all_member_health_views()
        alerts = []

        for member in members:
            risk_tier = self._compute_risk_tier(member)
            if risk_tier != RiskTier.GREEN:
                alert = await self._generate_alert(member, risk_tier)
                alerts.append(alert)

        if alerts:
            logger.info(
                "Silent sweep complete: %d alerts generated (%d critical)",
                len(alerts),
                sum(1 for a in alerts if a.alert_level == RiskTier.CRITICAL),
            )

        return alerts

    # -------------------------------------------------------------------------
    # RISK COMPUTATION
    # -------------------------------------------------------------------------

    def _compute_risk_tier(self, member: MemberHealthView) -> RiskTier:
        """Compute the risk tier for a member based on silence duration and trajectory."""
        hours = member.hours_since_interaction
        if hours <= 0:
            return RiskTier.GREEN

        # Apply trajectory modifier
        trajectory = member.c_emo_trajectory
        modifier = TRAJECTORY_RISK_MULTIPLIER.get(trajectory, 1.0)
        effective_hours = hours / modifier  # Declining trajectory = effectively more hours

        # Also factor in deviation from personal norm
        if member.deviation_from_norm > 2.0:
            effective_hours *= 1.3

        # Determine tier
        for tier in [RiskTier.CRITICAL, RiskTier.RED, RiskTier.ORANGE, RiskTier.YELLOW]:
            if effective_hours >= SILENCE_THRESHOLDS[tier]:
                return tier

        return RiskTier.GREEN

    # -------------------------------------------------------------------------
    # ALERT GENERATION
    # -------------------------------------------------------------------------

    async def _generate_alert(
        self, member: MemberHealthView, risk_tier: RiskTier
    ) -> SilentAlert:
        """Generate a silent alert for a member."""
        # Determine recommended action based on tier
        action_map = {
            RiskTier.YELLOW: "gentle_checkin",
            RiskTier.ORANGE: "personalized_outreach",
            RiskTier.RED: "coach_notification",
            RiskTier.CRITICAL: "immediate_escalation",
        }

        # Get cosmic ring partners
        ring_partners = await self._get_ring_partners(member.member_id)

        alert = SilentAlert(
            member_id=member.member_id,
            alert_level=risk_tier,
            hours_silent=member.hours_since_interaction,
            last_known_c_emo=member.c_emo_at_last_interaction,
            c_emo_trajectory=member.c_emo_trajectory,
            recommended_action=action_map.get(risk_tier, "gentle_checkin"),
            cosmic_ring_partners=ring_partners,
        )

        # Execute the recommended action
        await self._execute_action(alert)

        # Persist alert
        await self._persist_alert(alert)

        logger.info(
            "Silent alert: member=%s tier=%s hours=%.1f action=%s",
            member.member_id, risk_tier.value, member.hours_since_interaction,
            alert.recommended_action,
        )

        return alert

    async def _execute_action(self, alert: SilentAlert) -> None:
        """Execute the recommended action for an alert."""
        if alert.recommended_action == "gentle_checkin":
            await self._send_gentle_checkin(alert)
        elif alert.recommended_action == "personalized_outreach":
            await self._send_personalized_outreach(alert)
        elif alert.recommended_action == "coach_notification":
            await self._notify_coach(alert)
        elif alert.recommended_action == "immediate_escalation":
            await self._immediate_escalation(alert)

    # -------------------------------------------------------------------------
    # OUTREACH ACTIONS
    # -------------------------------------------------------------------------

    async def _send_gentle_checkin(self, alert: SilentAlert) -> None:
        """Yellow tier: gentle AI check-in message."""
        if self._notifications:
            await self._notifications.send_notification(
                user_id=alert.member_id,
                notification_type="silent_checkin",
                title="Little Nate",
                body=(
                    "Hey — I haven't heard from you in a while and wanted to "
                    "check in. How are things going? I'm here whenever you need."
                ),
                channel="push",
            )

    async def _send_personalized_outreach(self, alert: SilentAlert) -> None:
        """Orange tier: personalized outreach using Sovereign Mind."""
        message = (
            "I've been thinking about you. It's been a few days since we "
            "last connected, and I just want you to know — there's no "
            "pressure, but I'm here. Even if it's just to say hi."
        )
        if self._sovereign_mind:
            try:
                context = {
                    "member_id": alert.member_id,
                    "hours_silent": alert.hours_silent,
                    "last_c_emo": alert.last_known_c_emo,
                    "trajectory": alert.c_emo_trajectory,
                }
                personalized = await self._sovereign_mind.generate(
                    prompt="Generate a warm, personalized check-in message for a member who has been silent",
                    context=context,
                )
                if personalized:
                    message = personalized
            except Exception as e:
                logger.warning("Sovereign Mind outreach generation failed: %s", e)

        if self._notifications:
            await self._notifications.send_notification(
                user_id=alert.member_id,
                notification_type="silent_personalized",
                title="Little Nate",
                body=message,
                channel="push",
            )

        # Activate Quakete Ramp-Up if available
        if self._ramp_up and alert.cosmic_ring_partners:
            try:
                activation = RampUpActivation(
                    target_member_id=alert.member_id,
                    trigger="silent_crisis_orange",
                    cosmic_ring_id=None,
                    partner_fibres=alert.cosmic_ring_partners,
                )
                await self._ramp_up.activate(activation)
            except Exception as e:
                logger.warning("Ramp-up activation failed: %s", e)

    async def _notify_coach(self, alert: SilentAlert) -> None:
        """Red tier: notify assigned coach with a briefing."""
        briefing = await self._generate_coach_briefing(alert)
        if self._notifications and briefing:
            await self._notifications.send_notification(
                user_id=briefing.coach_id,
                notification_type="silent_crisis_coach_alert",
                title="Silent Crisis Alert",
                body=(
                    f"{briefing.member_name} has been silent for "
                    f"{briefing.days_silent} days. "
                    f"Last C_emo: {briefing.last_c_emo:.2f}. "
                    f"Recommended: {briefing.recommended_approach}"
                ),
                channel="urgent",
            )

    async def _immediate_escalation(self, alert: SilentAlert) -> None:
        """Critical tier: immediate escalation with full Quakete activation."""
        # Notify coach immediately
        await self._notify_coach(alert)

        # Full Quakete Ramp-Up
        if self._ramp_up and alert.cosmic_ring_partners:
            activation = RampUpActivation(
                target_member_id=alert.member_id,
                trigger="silent_crisis_critical",
                partner_fibres=alert.cosmic_ring_partners,
                actions=[
                    {"type": "full_ramp_up", "priority": "critical"},
                    {"type": "ring_notification", "message": "A member of your ring needs support"},
                ],
            )
            try:
                await self._ramp_up.activate(activation)
            except Exception as e:
                logger.error("Critical ramp-up activation failed: %s", e)

    # -------------------------------------------------------------------------
    # COACH BRIEFING
    # -------------------------------------------------------------------------

    async def _generate_coach_briefing(
        self, alert: SilentAlert
    ) -> Optional[SilentCrisisBriefing]:
        """Generate a coach briefing for a silent crisis alert."""
        if not self._db:
            return None

        try:
            async with self._db.acquire() as conn:
                member_row = await conn.fetchrow(
                    "SELECT name, assigned_coach_id FROM users WHERE id = $1",
                    alert.member_id,
                )
                if not member_row:
                    return None

                return SilentCrisisBriefing(
                    member_id=alert.member_id,
                    member_name=member_row.get("name", "Unknown"),
                    coach_id=member_row.get("assigned_coach_id", ""),
                    days_silent=int(alert.hours_silent / 24),
                    last_c_emo=alert.last_known_c_emo,
                    recommended_approach=(
                        "Direct outreach recommended. Check for wellbeing. "
                        "Consider scheduling an ad-hoc session."
                    ),
                )
        except Exception as e:
            logger.error("Coach briefing generation failed: %s", e)
            return None

    # -------------------------------------------------------------------------
    # DATA ACCESS
    # -------------------------------------------------------------------------

    async def _get_all_member_health_views(self) -> List[MemberHealthView]:
        """Get health views for all active members from Trail Map."""
        if self._trail_map:
            try:
                views = await self._trail_map.get_all_member_health_views()
                return views
            except Exception as e:
                logger.warning("Trail map health views failed: %s", e)

        # Fallback: query database directly
        if not self._db:
            return []

        try:
            async with self._db.acquire() as conn:
                rows = await conn.fetch(
                    """
                    SELECT u.id AS member_id,
                           MAX(s.ended_at) AS last_interaction,
                           EXTRACT(EPOCH FROM NOW() - MAX(s.ended_at)) / 3600 AS hours_since
                    FROM users u
                    LEFT JOIN sessions s ON s.client_id = u.id
                    WHERE u.role = 'client' AND u.active = true
                    GROUP BY u.id
                    """
                )
                views = []
                for row in rows:
                    views.append(MemberHealthView(
                        member_id=row["member_id"],
                        last_interaction=row.get("last_interaction"),
                        hours_since_interaction=float(row.get("hours_since") or 0),
                    ))
                return views
        except Exception as e:
            logger.error("Member health view query failed: %s", e)
            return []

    async def _get_ring_partners(self, member_id: str) -> List[str]:
        """Get cosmic ring partner IDs for a member."""
        if not self._db:
            return []
        try:
            async with self._db.acquire() as conn:
                rows = await conn.fetch(
                    """
                    SELECT member_id FROM cosmic_ring_members
                    WHERE ring_id IN (
                        SELECT ring_id FROM cosmic_ring_members WHERE member_id = $1
                    ) AND member_id != $1
                    """,
                    member_id,
                )
                return [row["member_id"] for row in rows]
        except Exception:
            return []

    async def _persist_alert(self, alert: SilentAlert) -> None:
        """Persist a silent alert to the database."""
        if not self._db:
            return
        try:
            async with self._db.acquire() as conn:
                await conn.execute(
                    """
                    INSERT INTO silent_alerts (
                        alert_id, member_id, alert_level, hours_silent,
                        last_known_c_emo, c_emo_trajectory, recommended_action,
                        cosmic_ring_partners
                    ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
                    """,
                    alert.alert_id, alert.member_id, alert.alert_level.value,
                    alert.hours_silent, alert.last_known_c_emo,
                    alert.c_emo_trajectory, alert.recommended_action,
                    json.dumps(alert.cosmic_ring_partners, default=str),
                )
        except Exception as e:
            logger.error("Alert persistence failed: %s", e)
