"""
LinkedIn campaign publish scheduler — Eastern-time slot windows (3pm / 8pm ET).

Runs every 5 minutes; publishes at most one approved slot per tick.
Windowed slots (first 15 minutes of 3pm / 8pm ET) take priority; overdue
missed slots catch up on later ticks. Session engine never owns LinkedIn publish.
"""
from __future__ import annotations

import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

logger = logging.getLogger(__name__)


class LinkedInCampaignScheduler:
    """Background tick for linkedin_campaign_v1 auto-publish."""

    def __init__(self, db_pool):
        self.db_pool = db_pool
        self.scheduler = AsyncIOScheduler()

    def start(self):
        self.scheduler.add_job(
            self._tick,
            IntervalTrigger(minutes=5),
            id="linkedin_campaign_publish",
            name="LinkedIn campaign ET slot publish",
            replace_existing=True,
            max_instances=1,
        )
        self.scheduler.start()
        logger.info("LinkedIn campaign scheduler started (5min tick)")

    def stop(self):
        if self.scheduler.running:
            self.scheduler.shutdown(wait=False)

    async def _tick(self):
        try:
            from app.services.linkedin_campaign_executor import LinkedInCampaignExecutor

            msg = await LinkedInCampaignExecutor(self.db_pool).publish_scheduled_slots()
            if msg:
                logger.info("LinkedIn campaign publish: %s", msg)
        except Exception as e:
            logger.warning("LinkedIn campaign scheduler tick failed: %s", e)
