"""
SOVEREIGN SWARM — Marketing Automation Worker
Autonomous content generation and scheduling pipeline for Little Nate.

Runs on a configurable interval (default: 10 minutes) and:
  1. Checks for active campaigns that need fresh content
  2. Generates posts according to traffic-period cadence rules
  3. Queues content with proper scheduling timestamps
  4. Logs all activity for Big Nate visibility in SkyEye
"""

from __future__ import annotations

import asyncio
import json
import os
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

import structlog

logger = structlog.get_logger(__name__)

# Traffic windows (UTC) — configurable per-campaign but these are defaults
HIGH_TRAFFIC_HOURS = list(range(13, 21))     # 1pm-9pm UTC (8am-4pm EST)
MEDIUM_TRAFFIC_HOURS = list(range(10, 13)) + list(range(21, 24))
LOW_TRAFFIC_HOURS = list(range(0, 10))

DEFAULT_CADENCE = {
    "high": 30,     # minutes between posts during high traffic
    "medium": 60,
    "low": 120,
}

MAX_DAILY_POSTS_PER_PLATFORM = 48
QUEUE_LOOKAHEAD_HOURS = 4
BATCH_SIZE = 6
# Off by default: these drafts never publish (8619 generated, 0 posted).
ENABLE_ENGAGEMENT_DRAFTS = os.getenv(
    "ENABLE_ENGAGEMENT_DRAFTS", "false"
).strip().lower() in ("1", "true", "yes")
ENGAGEMENT_POSTS_PER_DAY = 8

# LinkedIn publish is owned exclusively by LinkedInCampaignScheduler
# (generated_by="linkedin_campaign_v1", published on ET slot windows).
# This worker must never queue LinkedIn content — the session engine's
# _post_phase hard-skips LinkedIn, and the campaign executor only
# publishes its own tagged rows, so anything queued here for LinkedIn
# would never be picked up by any publisher and would pile up forever.
EXCLUDED_PLATFORMS = {"linkedin"}


POST_VERIFY_EVERY_N_TICKS = 36  # 36 × 10 min = 6 hours


class MarketingAutomationWorker:
    """Background worker: autonomous marketing content pipeline."""

    def __init__(self, db_pool: Any, interval: int = 600) -> None:
        self.db_pool = db_pool
        self.interval = interval
        self._task: asyncio.Task | None = None
        self._running = False
        self._tick_count = 0

    async def start(self) -> None:
        self._running = True
        self._task = asyncio.create_task(self._run_loop())
        logger.info("worker_started", worker="MarketingAutomationWorker")

    async def stop(self) -> None:
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("worker_stopped", worker="MarketingAutomationWorker")

    async def _run_loop(self) -> None:
        await asyncio.sleep(30)
        while self._running:
            try:
                await self._tick()
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.error("marketing_automation_error", error=str(e))
            await asyncio.sleep(self.interval)

    async def _tick(self) -> None:
        """Main automation tick — runs every interval."""
        self._tick_count += 1

        if self._tick_count % POST_VERIFY_EVERY_N_TICKS == 0:
            await self._verify_recent_posts()

        active_campaigns = await self._get_active_campaigns()
        active_platforms = await self._get_active_platforms()

        if not active_platforms:
            return

        for platform in active_platforms:
            if platform in EXCLUDED_PLATFORMS:
                continue

            cadence = await self._get_platform_cadence(platform)
            if not cadence:
                continue

            queued_count = await self._count_pending_posts(platform)
            if queued_count >= MAX_DAILY_POSTS_PER_PLATFORM:
                logger.debug("queue_full", platform=platform, count=queued_count)
                continue

            needs_content = await self._needs_content(platform, cadence)
            if needs_content:
                generated = await self._generate_cadence_batch(
                    platform, cadence, active_campaigns,
                )
                if generated > 0:
                    logger.info("content_generated",
                                platform=platform, posts=generated)

        if not ENABLE_ENGAGEMENT_DRAFTS:
            return

        # Strategic engagement posts (unused unless ENABLE_ENGAGEMENT_DRAFTS=true)
        for platform in active_platforms:
            if platform in EXCLUDED_PLATFORMS:
                continue

            engagement_count = await self._count_todays_engagement(platform)
            if engagement_count < ENGAGEMENT_POSTS_PER_DAY:
                await self._generate_engagement_post(platform)

    async def _get_active_campaigns(self) -> List[Dict]:
        """Get campaigns with status='active'."""
        try:
            async with self.db_pool.acquire() as conn:
                rows = await conn.fetch("""
                    SELECT id, title, narrative_premise, platforms,
                           total_episodes, current_episode,
                           episode_interval_hours
                    FROM storytelling_campaigns
                    WHERE status = 'active'
                    ORDER BY created_at DESC
                """)
                return [dict(r) for r in rows]
        except Exception as e:
            logger.debug("campaigns_fetch_error", error=str(e))
            return []

    async def _get_active_platforms(self) -> List[str]:
        """Get platforms with control_mode != 'observation'."""
        try:
            async with self.db_pool.acquire() as conn:
                rows = await conn.fetch("""
                    SELECT name FROM skyeye_platforms
                    WHERE enabled = TRUE AND control_mode != 'observation'
                    ORDER BY tier ASC, name ASC
                """)
                return [r["name"] for r in rows]
        except Exception as e:
            logger.error("platforms_fetch_error", error=str(e))
            return []

    async def _get_platform_cadence(self, platform: str) -> Optional[Dict]:
        """Get cadence rules. Returns None if platform should not auto-post."""
        try:
            async with self.db_pool.acquire() as conn:
                row = await conn.fetchrow(
                    "SELECT control_mode FROM skyeye_platforms WHERE name = $1",
                    platform,
                )
                if not row or row["control_mode"] == "observation":
                    return None
                return DEFAULT_CADENCE.copy()
        except Exception:
            return None

    async def _count_pending_posts(self, platform: str) -> int:
        """Count scheduled/draft posts for today."""
        try:
            async with self.db_pool.acquire() as conn:
                row = await conn.fetchrow("""
                    SELECT COUNT(*) as cnt FROM skyeye_content_queue
                    WHERE platform = $1
                      AND status IN ('draft', 'scheduled', 'approved')
                      AND created_at > NOW() - INTERVAL '24 hours'
                """, platform)
                return row["cnt"] if row else 0
        except Exception:
            return 0

    async def _needs_content(self, platform: str, cadence: Dict) -> bool:
        """Check if the platform's queue needs replenishment."""
        try:
            async with self.db_pool.acquire() as conn:
                row = await conn.fetchrow("""
                    SELECT COUNT(*) as cnt FROM skyeye_content_queue
                    WHERE platform = $1
                      AND status IN ('draft', 'scheduled', 'approved')
                      AND (scheduled_for IS NULL
                           OR scheduled_for <= NOW() + INTERVAL '%s hours')
                """ % QUEUE_LOOKAHEAD_HOURS, platform)
                pending = row["cnt"] if row else 0
                return pending < BATCH_SIZE
        except Exception:
            return True

    async def _generate_cadence_batch(self, platform: str, cadence: Dict,
                                       campaigns: List[Dict]) -> int:
        """Generate a batch of posts following cadence rules."""
        try:
            from app.services.skyeye_content_generator import SkyEyeContentGenerator
            gen = SkyEyeContentGenerator(self.db_pool)

            campaign_context = ""
            platform_campaigns = [
                c for c in campaigns
                if platform in (c.get("platforms") or [])
            ]
            if platform_campaigns:
                c = platform_campaigns[0]
                campaign_context = (
                    f"Active campaign: {c['title']}. "
                    f"Narrative: {c.get('narrative_premise', '')}. "
                    f"Episode {c.get('current_episode', 1)} of {c.get('total_episodes', 5)}."
                )

            now = datetime.now(timezone.utc)
            generated = 0

            for i in range(BATCH_SIZE):
                slot_time = now + timedelta(minutes=i * cadence.get("medium", 60))
                hour = slot_time.hour

                if hour in HIGH_TRAFFIC_HOURS:
                    interval = cadence["high"]
                elif hour in MEDIUM_TRAFFIC_HOURS:
                    interval = cadence["medium"]
                else:
                    interval = cadence["low"]

                slot_time = now + timedelta(minutes=interval * i)

                topic = campaign_context if campaign_context else (
                    "Emotional coherence, presence, threshold moments. "
                    "Liminal Intelligence voice — unfinished, warm, no CTA."
                )

                result = await gen.generate_post(platform, topic, context={
                    "batch_position": i + 1,
                    "traffic_period": (
                        "high" if hour in HIGH_TRAFFIC_HOURS
                        else "medium" if hour in MEDIUM_TRAFFIC_HOURS
                        else "low"
                    ),
                    "tone": "liminal, presence-first, no CTA, unfinished thoughts",
                })

                if result.get("safe") or result.get("content"):
                    await gen.queue_content(
                        platform=platform,
                        content=result["content"],
                        content_type=result.get("content_type", "post"),
                        emotion_context=result.get("emotion_context"),
                        scheduled_for=slot_time,
                        generated_by="marketing_automation",
                    )
                    generated += 1

            return generated
        except Exception as e:
            logger.error("cadence_batch_error", platform=platform, error=str(e))
            return 0

    async def _count_todays_engagement(self, platform: str) -> int:
        """Count engagement-type posts generated today."""
        try:
            async with self.db_pool.acquire() as conn:
                row = await conn.fetchrow("""
                    SELECT COUNT(*) as cnt FROM skyeye_content_queue
                    WHERE platform = $1
                      AND generated_by = 'marketing_engagement'
                      AND created_at > NOW() - INTERVAL '24 hours'
                """, platform)
                return row["cnt"] if row else 0
        except Exception:
            return 0

    async def _generate_engagement_post(self, platform: str) -> None:
        """Generate a strategic engagement/reply-style post."""
        try:
            from app.services.skyeye_content_generator import SkyEyeContentGenerator
            gen = SkyEyeContentGenerator(self.db_pool)

            result = await gen.generate_post(platform,
                "Strategic engagement: respond to trending emotional wellness, "
                "mental health, AI companionship, or therapy discourse. "
                "Mirror the tone of someone who has been in the room, not above it. "
                "Reflect without resolving. Leave the thought alive.",
                context={
                    "content_type": "engagement_reply",
                    "tone": "warm, unresolved, present — not performative",
                },
            )

            if result.get("safe") or result.get("content"):
                now = datetime.now(timezone.utc)
                offset = asyncio.get_event_loop().time() % 120
                scheduled = now + timedelta(minutes=offset)

                await gen.queue_content(
                    platform=platform,
                    content=result["content"],
                    content_type="engagement",
                    emotion_context=result.get("emotion_context"),
                    scheduled_for=scheduled,
                    generated_by="marketing_engagement",
                )
                logger.info("engagement_post_queued", platform=platform)
        except Exception as e:
            logger.error("engagement_post_error", platform=platform, error=str(e))

    async def _verify_recent_posts(self) -> None:
        """
        Periodic verification: check that recently posted content is still
        reachable via HTTP HEAD on the post_url. Runs every 6 hours.
        Logs failures to skyeye_activity for dashboard visibility.
        """
        import httpx

        try:
            async with self.db_pool.acquire() as conn:
                posts = await conn.fetch("""
                    SELECT id, platform, post_url, post_id_external
                    FROM skyeye_content_queue
                    WHERE status = 'posted'
                      AND posted_at > NOW() - INTERVAL '24 hours'
                      AND post_url IS NOT NULL
                    ORDER BY posted_at DESC
                    LIMIT 30
                """)

            if not posts:
                return

            verified = 0
            failed = 0

            async with httpx.AsyncClient(timeout=10, follow_redirects=True) as client:
                for post in posts:
                    try:
                        resp = await client.head(post["post_url"])
                        if resp.status_code < 400:
                            verified += 1
                        else:
                            failed += 1
                            async with self.db_pool.acquire() as conn:
                                await conn.execute(
                                    """INSERT INTO skyeye_activity (type, platform, content)
                                       VALUES ('post_verification_failed', $1, $2)""",
                                    post["platform"],
                                    f"Post {post['id']} returned HTTP {resp.status_code} — may be deleted"
                                )
                    except Exception:
                        failed += 1

            logger.info("post_verification_complete",
                        verified=verified, failed=failed, total=len(posts))

        except Exception as e:
            logger.error("post_verification_error", error=str(e))
