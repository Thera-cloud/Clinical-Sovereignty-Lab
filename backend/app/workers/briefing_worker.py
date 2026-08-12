"""
SOVEREIGN SWARM — Briefing Worker
Generates pre-session coach briefings 2 hours before every scheduled session.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
from typing import Any, Optional

import structlog

logger = structlog.get_logger(__name__)


class BriefingWorker:
    """Background worker: pre-session briefing generation."""

    def __init__(
        self,
        briefing_generator: Any,
        db_pool: Any = None,
        notifications: Any = None,
        interval: int = 300,  # Check every 5 minutes
        lead_time_hours: float = 2.0,
    ) -> None:
        self.briefing_generator = briefing_generator
        self.db_pool = db_pool
        self.notifications = notifications
        self.interval = interval
        self.lead_time_hours = lead_time_hours
        self._task: asyncio.Task | None = None
        self._running = False
        self._generated: set = set()  # Track session IDs already briefed

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

    async def _run_loop(self) -> None:
        while self._running:
            try:
                await self._check_upcoming_sessions()
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.error("briefing_worker_error", error=str(e))
            await asyncio.sleep(self.interval)

    async def _check_upcoming_sessions(self) -> None:
        """Check for sessions starting within the lead time window.

        Uses coaching_sessions (live Zoom scheduling). No tier filter —
        COACH_ONLY / STANDARD / TOP_TIER all get automatic briefs.
        """
        if not self.db_pool:
            return

        now = datetime.utcnow()
        window_start = now
        window_end = now + timedelta(hours=self.lead_time_hours)

        try:
            async with self.db_pool.acquire() as conn:
                sessions = await conn.fetch(
                    """
                    SELECT session_id AS id,
                           coach_id,
                           client_id AS user_id,
                           COALESCE(scheduled_start, scheduled_at) AS scheduled_at,
                           client_name
                    FROM coaching_sessions
                    WHERE COALESCE(scheduled_start, scheduled_at) BETWEEN $1 AND $2
                      AND LOWER(COALESCE(status, '')) IN ('scheduled', 'confirmed', 'pending')
                    ORDER BY COALESCE(scheduled_start, scheduled_at) ASC
                    """,
                    window_start,
                    window_end,
                )
        except Exception as e:
            logger.warning("Session query failed: %s", e)
            return

        for session in sessions:
            session_id = session["id"]
            if not session_id or session_id in self._generated:
                continue

            try:
                briefing = await self.briefing_generator.generate_briefing(
                    coach_id=session["coach_id"],
                    member_id=session["user_id"],
                    session_datetime=session["scheduled_at"],
                )
                self._generated.add(session_id)

                # Notify coach
                if self.notifications:
                    member_label = (
                        getattr(briefing, "member_name", None)
                        or session.get("client_name")
                        or "client"
                    )
                    await self.notifications.send_notification(
                        user_id=session["coach_id"],
                        notification_type="pre_session_briefing",
                        title="Pre-Session Briefing Ready",
                        body=(
                            f"Briefing for {member_label} is ready. "
                            f"Session at {session['scheduled_at'].strftime('%I:%M %p')}."
                        ),
                        channel="push",
                    )

                logger.info(
                    "briefing_generated",
                    session_id=session_id,
                    coach_id=session["coach_id"],
                    member_id=session["user_id"],
                )
            except Exception as e:
                logger.error(
                    "briefing_generation_failed",
                    session_id=session_id,
                    error=str(e),
                )
