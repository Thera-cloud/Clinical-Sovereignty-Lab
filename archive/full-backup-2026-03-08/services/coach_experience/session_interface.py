"""
SOVEREIGN SWARM — Live Session Notification Interface
Manages real-time notifications to coaches during sessions:
whisper, nudge, alert, and crisis tiers.

Operational Specifications §2 — Coach Experience.
"""

import asyncio
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from app.models.solutions import LiveSessionNotification, NotificationTier

logger = logging.getLogger("coach_experience.session_interface")


# =============================================================================
# NOTIFICATION RULES
# =============================================================================

TIER_CONFIG = {
    NotificationTier.WHISPER: {
        "auto_dismiss_seconds": 10,
        "suppressible": True,
        "channel": "in_session",
        "sound": None,
        "visual": "subtle_badge",
    },
    NotificationTier.NUDGE: {
        "auto_dismiss_seconds": 30,
        "suppressible": True,
        "channel": "in_session",
        "sound": "soft_chime",
        "visual": "sidebar_panel",
    },
    NotificationTier.ALERT: {
        "auto_dismiss_seconds": None,
        "suppressible": False,
        "channel": "in_session",
        "sound": "attention",
        "visual": "overlay",
    },
    NotificationTier.CRISIS: {
        "auto_dismiss_seconds": None,
        "suppressible": False,
        "channel": "urgent",
        "sound": "urgent",
        "visual": "full_screen_overlay",
    },
}


class SessionInterface:
    """
    Manages the coach's notification stream during a live session.
    Respects tier hierarchy and suppression rules.
    """

    def __init__(self, ws_bridge=None):
        self._ws_bridge = ws_bridge
        self._active_sessions: Dict[str, Dict[str, Any]] = {}
        self._suppressed: Dict[str, set] = {}

    async def start_session(self, session_id: str, coach_id: str) -> None:
        """Register a new live session for notification management."""
        self._active_sessions[session_id] = {
            "coach_id": coach_id,
            "started_at": datetime.utcnow(),
            "notification_count": 0,
            "notifications": [],
        }
        self._suppressed[session_id] = set()
        logger.info("Session interface started: session=%s coach=%s", session_id, coach_id)

    async def end_session(self, session_id: str) -> None:
        """End a live session's notification management."""
        self._active_sessions.pop(session_id, None)
        self._suppressed.pop(session_id, None)
        logger.info("Session interface ended: session=%s", session_id)

    async def send_notification(
        self,
        session_id: str,
        tier: NotificationTier,
        message: str,
        member_id: Optional[str] = None,
    ) -> Optional[LiveSessionNotification]:
        """Send a notification to the coach during a live session."""
        session = self._active_sessions.get(session_id)
        if not session:
            logger.warning("Notification to unknown session: %s", session_id)
            return None

        config = TIER_CONFIG.get(tier, TIER_CONFIG[NotificationTier.WHISPER])

        # Check suppression (only for whisper/nudge)
        if config["suppressible"] and tier.value in self._suppressed.get(session_id, set()):
            return None

        notification = LiveSessionNotification(
            tier=tier,
            message=message,
            target_coach_id=session["coach_id"],
            session_id=session_id,
            member_id=member_id,
            suppressible=config["suppressible"],
            auto_dismiss_seconds=config["auto_dismiss_seconds"],
        )

        # Deliver via WebSocket
        await self._deliver_notification(notification, config)

        # Track
        session["notification_count"] += 1
        session["notifications"].append({
            "id": notification.notification_id,
            "tier": tier.value,
            "message": message,
            "timestamp": notification.created_at.isoformat(),
        })

        return notification

    async def suppress_tier(self, session_id: str, tier: NotificationTier) -> None:
        """Suppress a notification tier for the rest of the session."""
        if tier.value in ("alert", "crisis"):
            return  # Cannot suppress alert/crisis
        suppressed = self._suppressed.get(session_id, set())
        suppressed.add(tier.value)
        self._suppressed[session_id] = suppressed
        logger.info("Tier suppressed: session=%s tier=%s", session_id, tier.value)

    # -------------------------------------------------------------------------
    # CEE WINDOW NOTIFICATION
    # -------------------------------------------------------------------------

    async def notify_cee_window(
        self,
        session_id: str,
        member_name: str,
        emotional_state: str,
        recommended_action: str,
        estimated_duration: int = 60,
    ) -> Optional[LiveSessionNotification]:
        """Send a CEE window notification to the coach."""
        message = (
            f"CEE WINDOW OPEN — {member_name} is showing {emotional_state}. "
            f"Recommended: {recommended_action}. "
            f"Estimated window: ~{estimated_duration}s."
        )
        return await self.send_notification(
            session_id=session_id,
            tier=NotificationTier.ALERT,
            message=message,
        )

    # -------------------------------------------------------------------------
    # WEATHER UPDATE NOTIFICATION
    # -------------------------------------------------------------------------

    async def notify_weather_change(
        self,
        session_id: str,
        change_type: str,
        details: str,
    ) -> Optional[LiveSessionNotification]:
        """Send a weather change notification based on severity."""
        if change_type == "escalation":
            return await self.send_notification(
                session_id=session_id,
                tier=NotificationTier.ALERT,
                message=f"Escalation detected: {details}",
            )
        elif change_type == "bridge_opportunity":
            return await self.send_notification(
                session_id=session_id,
                tier=NotificationTier.NUDGE,
                message=f"Bridge opportunity: {details}",
            )
        else:
            return await self.send_notification(
                session_id=session_id,
                tier=NotificationTier.WHISPER,
                message=details,
            )

    # -------------------------------------------------------------------------
    # DELIVERY
    # -------------------------------------------------------------------------

    async def _deliver_notification(
        self, notification: LiveSessionNotification, config: Dict[str, Any]
    ) -> None:
        """Deliver notification via WebSocket to the coach."""
        if self._ws_bridge:
            try:
                payload = {
                    "type": "session_notification",
                    "notification_id": notification.notification_id,
                    "tier": notification.tier.value,
                    "message": notification.message,
                    "suppressible": notification.suppressible,
                    "auto_dismiss": notification.auto_dismiss_seconds,
                    "visual": config.get("visual"),
                    "sound": config.get("sound"),
                    "timestamp": notification.created_at.isoformat(),
                }
                await self._ws_bridge.send_to_user(
                    notification.target_coach_id, payload
                )
            except Exception as e:
                logger.warning("Notification delivery failed: %s", e)
