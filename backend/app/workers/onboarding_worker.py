"""
SOVEREIGN SWARM — Onboarding Worker
Manages the 72-hour automated onboarding drip sequence:
- Hour 0-4: Post-welcome check-in
- Hour 24: Day-1 engagement prompt
- Hour 48: Day-2 tips and encouragement
- Hour 72: Completion check and coach intro reminder
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
from typing import Any, Optional

import structlog

logger = structlog.get_logger(__name__)


class OnboardingWorker:
    """
    Background worker that monitors active onboarding sequences
    and delivers timed engagement messages.
    """

    def __init__(
        self,
        db_pool: Any,
        notifications: Any = None,
        sovereign_mind: Any = None,
        interval: int = 300,  # Check every 5 minutes
    ) -> None:
        self.db_pool = db_pool
        self.notifications = notifications
        self.sovereign_mind = sovereign_mind
        self.interval = interval
        self._task: asyncio.Task | None = None
        self._running = False

    async def start(self) -> None:
        self._running = True
        self._task = asyncio.create_task(self._run_loop())
        logger.info("worker_started", worker=self.__class__.__name__)

    async def stop(self) -> None:
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("worker_stopped", worker=self.__class__.__name__)

    # -------------------------------------------------------------------------
    # MAIN LOOP
    # -------------------------------------------------------------------------

    async def _run_loop(self) -> None:
        while self._running:
            try:
                await self._process_onboarding_sequences()
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.error("onboarding_worker_error", error=str(e))
            await asyncio.sleep(self.interval)

    async def _process_onboarding_sequences(self) -> None:
        """Check all active onboarding sequences and send due messages."""
        if not self.db_pool:
            return

        try:
            async with self.db_pool.acquire() as conn:
                rows = await conn.fetch(
                    """
                    SELECT initiation_id, user_id, name, started_at,
                           stage, assigned_coach_id, metadata
                    FROM onboarding_initiations
                    WHERE stage != 'complete'
                      AND started_at > NOW() - INTERVAL '7 days'
                    ORDER BY started_at ASC
                    """
                )
        except Exception as e:
            logger.warning("onboarding_query_failed", error=str(e))
            return

        now = datetime.utcnow()
        for row in rows:
            user_id = row["user_id"]
            started = row["started_at"]
            hours_elapsed = (now - started).total_seconds() / 3600

            try:
                if hours_elapsed >= 72:
                    await self._send_completion_check(row)
                elif hours_elapsed >= 48:
                    await self._send_day2_tips(row)
                elif hours_elapsed >= 24:
                    await self._send_day1_engagement(row)
                elif hours_elapsed >= 4:
                    await self._send_post_welcome_checkin(row)
            except Exception as e:
                logger.error(
                    "onboarding_drip_error",
                    user_id=user_id,
                    hours_elapsed=hours_elapsed,
                    error=str(e),
                )

    # -------------------------------------------------------------------------
    # DRIP MESSAGES
    # -------------------------------------------------------------------------

    async def _send_post_welcome_checkin(self, row) -> None:
        """Hour 4: Gentle check-in after welcome conversation."""
        user_id = row["user_id"]
        name = row.get("name", "there")
        message = (
            f"Hey {name} — it's Nate. Just wanted to check in after our chat earlier. "
            f"How are you feeling about everything? No pressure to respond right now. "
            f"I'm here whenever you're ready."
        )
        await self._deliver_message(user_id, "post_welcome_checkin", message)

    async def _send_day1_engagement(self, row) -> None:
        """Hour 24: Day-1 engagement with a gentle prompt."""
        user_id = row["user_id"]
        name = row.get("name", "there")
        coach_id = row.get("assigned_coach_id")

        if coach_id:
            message = (
                f"Good morning, {name}. Your coach is looking forward to connecting with you. "
                f"In the meantime, I've been thinking about what you shared — "
                f"sometimes just naming what's going on can be the first step. "
                f"Want to tell me one small thing that's on your mind today?"
            )
        else:
            message = (
                f"Hey {name} — day one in the Sanctuary. "
                f"I've been thinking about what you shared. "
                f"Would you like to explore coach options together? "
                f"I think I've found some great matches for you."
            )
        await self._deliver_message(user_id, "day1_engagement", message)

    async def _send_day2_tips(self, row) -> None:
        """Hour 48: Day-2 tips and encouragement."""
        user_id = row["user_id"]
        name = row.get("name", "there")
        message = (
            f"{name}, something I want you to know: there's no timeline for this. "
            f"Some people dive right in, others take it slow. Both are perfectly okay. "
            f"One small thing you could try today: take 2 minutes to just notice "
            f"how you're feeling. That's it. No judgment, just noticing."
        )
        await self._deliver_message(user_id, "day2_tips", message)

    async def _send_completion_check(self, row) -> None:
        """Hour 72: Final completion check."""
        user_id = row["user_id"]
        name = row.get("name", "there")
        message = (
            f"Hey {name} — it's been a few days now. How's everything feeling? "
            f"If you haven't scheduled your first session yet, I can help with that. "
            f"And if you have questions about anything, I'm always here. "
            f"You're doing great just by being here."
        )
        await self._deliver_message(user_id, "completion_check", message)

        # Mark as needing follow-up if not complete
        if self.db_pool:
            try:
                async with self.db_pool.acquire() as conn:
                    await conn.execute(
                        """
                        UPDATE onboarding_initiations
                        SET metadata = metadata || '{"needs_followup": true}'::jsonb
                        WHERE user_id = $1 AND stage != 'complete'
                        """,
                        user_id,
                    )
            except Exception:
                pass

    async def _deliver_message(
        self, user_id: str, message_type: str, content: str
    ) -> None:
        """Deliver a drip message through the notifications service."""
        if self.notifications:
            try:
                await self.notifications.send_notification(
                    user_id=user_id,
                    notification_type=f"onboarding_{message_type}",
                    title="Little Nate",
                    body=content,
                    channel="push",
                )
                logger.info(
                    "onboarding_drip_sent",
                    user_id=user_id,
                    message_type=message_type,
                )
            except Exception as e:
                logger.warning(
                    "drip_delivery_failed",
                    user_id=user_id,
                    message_type=message_type,
                    error=str(e),
                )
