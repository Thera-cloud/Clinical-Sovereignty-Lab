"""
LITTLE NATE — SkyEye Autonomous Session Engine
APScheduler-based orchestrator that runs Little Nate's social media sessions.

Session state machine:
  Resting -> Waking -> Browsing -> Observing -> Engaging -> Creating -> Posting -> Resting

Follows the same AsyncIOScheduler pattern as drip_scheduler.py.
All sessions are bounded by configurable max duration and rate limits.

SAFETY: Hard safety rules are enforced at every stage through the
content generator (outbound) and monitor (inbound). Cannot be disabled.
"""

import asyncio
import json
import logging
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

from app.config import settings
from app.services.skyeye_platform_base import ContentType

logger = logging.getLogger("skyeye.session_engine")


# =============================================================================
# SESSION STATES
# =============================================================================

class SessionState:
    RESTING = "resting"
    WAKING = "waking"
    BROWSING = "browsing"
    OBSERVING = "observing"
    ENGAGING = "engaging"
    MODERATING = "moderating"
    CREATING = "creating"
    POSTING = "posting"
    STRATEGIZING = "strategizing"  # Marketing Brain analysis phase


# =============================================================================
# SESSION ENGINE
# =============================================================================

class SkyEyeSessionEngine:
    """
    Autonomous session orchestrator for Little Nate's social media presence.
    Runs on a configurable schedule, cycling through platforms.
    """

    def __init__(self, db_pool):
        self.db_pool = db_pool
        self.scheduler = AsyncIOScheduler()
        self._current_state = SessionState.RESTING
        self._current_session_id: Optional[int] = None
        self._session_actions: List[Dict] = []
        self._session_start: Optional[float] = None
        self._max_duration_seconds = 1800  # 30 minutes default
        self._action_count = 0
        self._is_running = False

    @property
    def current_state(self) -> str:
        return self._current_state

    @property
    def is_active(self) -> bool:
        return self._current_state != SessionState.RESTING

    # ── Lifecycle ───────────────────────────────────────────────────

    async def start(self):
        """Start the session engine scheduler."""
        if self._is_running:
            logger.warning("Session engine already running")
            return

        await self._load_settings()

        self.scheduler.add_job(
            self._session_tick,
            IntervalTrigger(minutes=5),
            id="skyeye_session_tick",
            replace_existing=True,
            max_instances=1,
        )

        self.scheduler.add_job(
            self._engagement_responder_tick,
            IntervalTrigger(minutes=15),
            id="skyeye_engagement_responder",
            replace_existing=True,
            max_instances=1,
        )

        self.scheduler.start()
        self._is_running = True
        logger.info("SkyEye Session Engine started (+ engagement responder every 15min)")

    async def stop(self):
        """Stop the session engine gracefully."""
        if self._is_running:
            if self.is_active:
                await self._rest_phase()
            self.scheduler.shutdown(wait=False)
            self._is_running = False
            logger.info("SkyEye Session Engine stopped")

    # ── Manual Controls ─────────────────────────────────────────────

    async def manual_wake(self) -> Dict[str, Any]:
        """Manually trigger a session (called by admin via API)."""
        if self.is_active:
            return {"status": "already_active", "state": self._current_state}

        # Run a session immediately
        asyncio.create_task(self._run_session())
        return {"status": "waking", "state": SessionState.WAKING}

    async def manual_rest(self) -> Dict[str, Any]:
        """Manually end the current session."""
        if not self.is_active:
            return {"status": "already_resting", "state": SessionState.RESTING}

        await self._rest_phase()
        return {"status": "resting", "state": SessionState.RESTING}

    # ── Pulse (polled by frontend every 30s) ────────────────────────

    async def get_pulse(self) -> Dict[str, Any]:
        """Get current state + last 3 actions for the live pulse indicator."""
        last_actions = self._session_actions[-3:] if self._session_actions else []

        # Calculate session duration
        duration = None
        if self._session_start:
            duration = int(time.time() - self._session_start)

        return {
            "state": self._current_state,
            "is_active": self.is_active,
            "session_id": self._current_session_id,
            "session_duration_seconds": duration,
            "action_count": self._action_count,
            "last_actions": [
                {
                    "action": a.get("action_type", ""),
                    "platform": a.get("platform", ""),
                    "detail": a.get("detail", {}).get("summary", ""),
                    "time": a.get("timestamp", ""),
                }
                for a in last_actions
            ],
        }

    # ── Engagement Responder (runs independently of sessions) ──────

    async def _engagement_responder_tick(self):
        """
        Lightweight loop that runs every 15 minutes, separate from full
        sessions. Picks up NEW comments from skyeye_notifications that
        haven't been replied to yet and auto-replies using the content
        generator. This is the scalable growth engine — it handles
        thousands of conversations without needing a full session.
        """
        if self.is_active:
            return  # Full session already handling engagement

        try:
            from app.services.platforms import get_adapter
            from app.services.skyeye_content_generator import SkyEyeContentGenerator
            from app.services.skyeye_monitor import SkyEyeMonitor

            generator = SkyEyeContentGenerator(self.db_pool)
            monitor = SkyEyeMonitor(self.db_pool)

            unreplied = await self._get_unreplied_comments(limit=20)
            if not unreplied:
                return

            replies_sent = 0
            max_replies_per_tick = 10

            for row in unreplied:
                if replies_sent >= max_replies_per_tick:
                    break

                platform = row["platform"]
                post_id = row["post_id"]
                actor = row["actor_handle"]
                comment_text = row["actor_bio"] or ""
                notif_id = row["id"]

                adapter = get_adapter(platform, self.db_pool)
                if not adapter:
                    continue

                try:
                    authenticated = await adapter.authenticate()
                    if not authenticated:
                        continue
                except Exception:
                    continue

                social_context = await self._get_social_context(actor, platform)

                reply_data = await generator.generate_reply(
                    platform=platform,
                    comment_text=comment_text,
                    user_handle=actor,
                    user_context=social_context,
                )

                if not (reply_data.get("safe") and reply_data.get("content")):
                    await self._mark_notification_processed(notif_id)
                    continue

                comments_on_post = await self._safe_adapter_call(
                    adapter.get_comments, post_id, limit=20
                )

                comment_id = None
                for c in comments_on_post:
                    c_author = getattr(c, "author_handle", "") or ""
                    if c_author.lower() == actor.lower():
                        comment_id = getattr(c, "comment_id", None)
                        break

                if not comment_id:
                    await self._mark_notification_processed(notif_id)
                    continue

                already = await self._check_already_replied(platform, comment_id)
                if already:
                    await self._mark_notification_processed(notif_id)
                    continue

                result = await adapter.reply_to_comment(
                    comment_id, reply_data["content"], post_id=post_id,
                )

                if result and result.success:
                    replies_sent += 1
                    await self._log_social_interaction(
                        platform, actor,
                        "reply", reply_data["content"],
                        comment_text,
                        comment_id=comment_id,
                        post_id=post_id,
                    )
                    await self._log_engagement_activity(
                        platform, actor,
                        comment_text[:100], reply_data["content"][:100],
                    )

                await self._mark_notification_processed(notif_id)

            if replies_sent > 0:
                logger.info(
                    f"Engagement responder: {replies_sent} autonomous replies "
                    f"sent across {len(set(r['platform'] for r in unreplied))} platforms"
                )

        except Exception as e:
            logger.warning(f"Engagement responder tick error: {e}")

    async def _get_unreplied_comments(self, limit: int = 20) -> list:
        """Fetch comment/reply notifications that haven't been responded to."""
        try:
            async with self.db_pool.acquire() as conn:
                rows = await conn.fetch("""
                    SELECT n.id, n.platform, n.post_id, n.actor_handle,
                           n.actor_bio, n.created_at
                    FROM skyeye_notifications n
                    WHERE n.notification_type IN ('comment', 'reply')
                      AND n.processed = FALSE
                      AND n.created_at > NOW() - INTERVAL '48 hours'
                      AND n.actor_handle NOT IN (
                          'littlenate', 'little_nate', 'littlenatetheog',
                          'little nate the og'
                      )
                    ORDER BY n.created_at ASC
                    LIMIT $1
                """, limit)
                return rows
        except Exception as e:
            logger.warning(f"Engagement responder: unreplied query error: {e}")
            return []

    async def _mark_notification_processed(self, notif_id: int):
        """Mark a notification as processed so we don't re-attempt it."""
        try:
            async with self.db_pool.acquire() as conn:
                await conn.execute("""
                    UPDATE skyeye_notifications SET processed = TRUE
                    WHERE id = $1
                """, notif_id)
        except Exception:
            pass

    async def _log_engagement_activity(self, platform: str, actor: str,
                                        comment_snippet: str, reply_snippet: str):
        """Record an autonomous engagement reply in the activity log."""
        try:
            async with self.db_pool.acquire() as conn:
                await conn.execute("""
                    INSERT INTO skyeye_activity
                        (type, platform, content, metadata, created_at)
                    VALUES ('autonomous_reply', $1, $2, $3::jsonb, NOW())
                """, platform,
                    f"Replied to @{actor}: {reply_snippet}",
                    json.dumps({
                        "actor": actor,
                        "comment": comment_snippet,
                        "reply": reply_snippet,
                    }))
        except Exception:
            pass

    async def _safe_adapter_call(self, fn, *args, **kwargs):
        """Call an adapter method safely, return empty list on error."""
        try:
            return await fn(*args, **kwargs)
        except Exception:
            return []

    @staticmethod
    def _extract_interest_signals(text: str) -> list:
        """Extract topic signals from a user's comment for social memory."""
        if not text or len(text) < 10:
            return []
        text_lower = text.lower()
        topics = {
            "therapy": ["therapy", "therapist", "counseling", "counselor"],
            "mental_health": ["mental health", "anxiety", "depression", "ptsd",
                              "trauma", "wellness", "self-care", "burnout"],
            "ai": ["ai", "artificial intelligence", "machine learning",
                    "chatbot", "language model"],
            "parenting": ["parent", "child", "kid", "family", "mom", "dad",
                          "daughter", "son"],
            "relationships": ["relationship", "partner", "spouse", "marriage",
                              "dating", "couple"],
            "coaching": ["coach", "coaching", "mentor", "mentoring",
                         "supervision"],
            "faith": ["faith", "prayer", "spiritual", "church", "god",
                       "believe"],
            "leadership": ["leader", "leadership", "management", "team",
                           "executive"],
            "education": ["school", "student", "teacher", "learning",
                          "university", "research"],
            "health": ["health", "exercise", "fitness", "nutrition",
                       "sleep", "meditation"],
        }
        found = []
        for topic, keywords in topics.items():
            for kw in keywords:
                if kw in text_lower:
                    found.append(topic)
                    break
        return found[:5]

    # ── Session Tick (Scheduler) ────────────────────────────────────

    async def _session_tick(self):
        """
        Called every 5 minutes by the scheduler.
        Checks if it's time to start a new session.
        """
        if self.is_active:
            return  # Already in a session

        try:
            # Check if there's a scheduled session due
            should_run = await self._should_start_session()
            if should_run:
                await self._run_session()
        except Exception as e:
            logger.error(f"Session tick error: {e}")

    async def _should_start_session(self) -> bool:
        """Check if a session should start based on schedule settings."""
        try:
            async with self.db_pool.acquire() as conn:
                # Check cooldown from last session
                last_session = await conn.fetchrow("""
                    SELECT session_end FROM skyeye_sessions
                    WHERE status = 'completed'
                    ORDER BY session_end DESC LIMIT 1
                """)

                if last_session and last_session["session_end"]:
                    cooldown = await self._get_setting("session_cooldown_minutes", 30)
                    session_end = last_session["session_end"]
                    if session_end.tzinfo is None:
                        session_end = session_end.replace(tzinfo=timezone.utc)
                    cooldown_until = session_end + timedelta(minutes=cooldown)
                    if datetime.now(timezone.utc) < cooldown_until:
                        return False

                # Enforce daily session cap (Eastern calendar day — not UTC)
                today_count = await conn.fetchval("""
                    SELECT COUNT(*) FROM skyeye_sessions
                    WHERE status = 'completed'
                      AND date_trunc(
                        'day',
                        session_start AT TIME ZONE 'America/New_York'
                      ) = date_trunc(
                        'day',
                        NOW() AT TIME ZONE 'America/New_York'
                      )
                """)
                max_daily = await self._get_setting("max_sessions_per_day", 3)
                if today_count >= max_daily:
                    return False

                # Check if any platform is due for a session
                platforms = await conn.fetch("""
                    SELECT name FROM skyeye_platforms
                    WHERE enabled = TRUE AND control_mode != 'observation'
                """)

                return len(platforms) > 0

        except Exception as e:
            logger.error(f"Error checking session schedule: {e}")
            return False

    # ── Main Session Flow ───────────────────────────────────────────

    async def _run_session(self):
        """Execute a full social media session."""
        try:
            # Wake phase
            await self._wake_phase()

            # Get active platforms
            platforms = await self._get_active_platforms()
            if not platforms:
                logger.info("No active platforms — returning to rest")
                await self._rest_phase()
                return

            # Import adapters and services lazily
            from app.services.platforms import get_adapter
            from app.services.skyeye_content_generator import SkyEyeContentGenerator
            from app.services.skyeye_monitor import SkyEyeMonitor

            generator = SkyEyeContentGenerator(self.db_pool)
            monitor = SkyEyeMonitor(self.db_pool)

            # Import funnel router for engagement-to-quiz routing
            from app.services.funnel_router import FunnelRouter
            funnel_router = FunnelRouter(self.db_pool)

            for platform_name in platforms:
                # Check time budget
                if self._is_session_expired():
                    logger.info("Session time expired — moving to rest")
                    break

                adapter = get_adapter(platform_name, self.db_pool)
                if not adapter:
                    logger.warning(f"No adapter for {platform_name}")
                    continue

                # Try to authenticate
                try:
                    authenticated = await adapter.authenticate()
                    if not authenticated:
                        logger.info(f"{platform_name}: Not connected, skipping")
                        await self._log_action(
                            platform_name, SessionState.WAKING, "auth_skip",
                            detail={"summary": f"{platform_name} not connected"}
                        )
                        continue
                except Exception as e:
                    logger.warning(f"{platform_name} auth failed: {e}")
                    continue

                # Run through phases for this platform
                await self._browse_phase(platform_name, adapter)
                await self._sync_platform_stats(platform_name, adapter)
                await self._observe_phase(platform_name, adapter, monitor)
                await self._react_phase(platform_name, adapter, generator)
                await self._engage_phase(platform_name, adapter, generator, monitor)
                await self._outreach_phase(platform_name, adapter, generator, monitor)
                await self._route_engaged_users(platform_name, funnel_router)
                await self._create_phase(platform_name, adapter, generator)
                await self._post_phase(platform_name, adapter, generator)

            # Strategize phase (runs once per session after all platforms)
            await self._strategize_phase()

            # Rest phase (always runs)
            await self._rest_phase(generator)

        except Exception as e:
            logger.error(f"Session error: {e}", exc_info=True)
            self._current_state = SessionState.RESTING
            await self._update_session_status("error")

    # ── Individual Phases ───────────────────────────────────────────

    async def _wake_phase(self):
        """Initialize a new session."""
        self._current_state = SessionState.WAKING
        self._session_start = time.time()
        self._session_actions = []
        self._action_count = 0

        try:
            async with self.db_pool.acquire() as conn:
                row = await conn.fetchrow("""
                    INSERT INTO skyeye_sessions
                        (session_start, status)
                    VALUES (NOW(), 'active')
                    RETURNING id
                """)
                self._current_session_id = row["id"] if row else None
        except Exception as e:
            logger.error(f"Failed to create session: {e}")

        await self._log_action(
            "system", SessionState.WAKING, "session_start",
            detail={"summary": "Little Nate waking up for social media session"}
        )
        logger.info(f"Session {self._current_session_id} started")

    async def _browse_phase(self, platform: str, adapter):
        """Browse the platform's feed and trending topics."""
        if self._is_session_expired():
            return
        self._current_state = SessionState.BROWSING

        try:
            # Get own recent posts
            own_posts = await adapter.get_feed(limit=5)
            await self._log_action(
                platform, SessionState.BROWSING, "read_feed",
                detail={"summary": f"Browsed {len(own_posts)} recent posts",
                        "post_count": len(own_posts)}
            )

            # Get trending (if supported)
            trending = await adapter.get_trending(limit=5)
            if trending:
                await self._log_action(
                    platform, SessionState.BROWSING, "read_trending",
                    detail={"summary": f"Checked {len(trending)} trending topics",
                            "topics": [t.name for t in trending[:5]]}
                )

        except Exception as e:
            logger.warning(f"Browse phase error on {platform}: {e}")

    async def _sync_platform_stats(self, platform: str, adapter):
        """Pull live analytics from the platform and update skyeye_platforms."""
        try:
            analytics = await adapter.get_analytics()
            if not analytics:
                return

            async with self.db_pool.acquire() as conn:
                await conn.execute("""
                    UPDATE skyeye_platforms
                    SET followers   = COALESCE(NULLIF($2, 0), followers),
                        engagement  = COALESCE(NULLIF($3, 0.0), engagement),
                        posts       = COALESCE(NULLIF($4, 0), posts),
                        updated_at  = NOW()
                    WHERE LOWER(name) = LOWER($1)
                """, platform, analytics.followers, analytics.engagement_rate,
                    analytics.total_posts)

            logger.info(
                f"{platform}: synced stats — "
                f"followers={analytics.followers}, "
                f"engagement={analytics.engagement_rate:.4f}, "
                f"posts={analytics.total_posts}"
            )

            await self._log_action(
                platform, SessionState.BROWSING, "stats_sync",
                detail={
                    "summary": f"Synced {platform} stats",
                    "followers": analytics.followers,
                    "engagement_rate": analytics.engagement_rate,
                    "total_posts": analytics.total_posts,
                    "total_likes": analytics.total_likes,
                    "total_comments": analytics.total_comments,
                    "total_views": analytics.total_views,
                }
            )
        except Exception as e:
            logger.warning(f"Stats sync skipped for {platform}: {e}")

    async def _observe_phase(self, platform: str, adapter, monitor):
        """Check comments and mentions on recent posts."""
        if self._is_session_expired():
            return
        self._current_state = SessionState.OBSERVING

        try:
            # Get own posts to check comments on
            own_posts = await adapter.get_own_posts(limit=5)

            for post in own_posts[:3]:  # Check top 3 recent posts
                if self._is_session_expired():
                    break

                comments = await adapter.get_comments(
                    post.item_id,
                    since=datetime.utcnow() - timedelta(hours=24)
                )

                if comments:
                    # Scan for threats
                    scan_results = await monitor.scan_comments_batch(comments, adapter)

                    threats = [r for r in scan_results if r["threat_type"] != "safe"]
                    safe = [r for r in scan_results if r["threat_type"] == "safe"]

                    await self._log_action(
                        platform, SessionState.OBSERVING, "read_comments",
                        detail={
                            "summary": (
                                f"Scanned {len(comments)} comments on post "
                                f"{post.item_id[:20]}... — {len(threats)} threats, "
                                f"{len(safe)} safe"
                            ),
                            "post_id": post.item_id,
                            "total_comments": len(comments),
                            "threats_found": len(threats),
                        }
                    )

            # Check mentions
            mentions = await adapter.get_mentions(
                since=datetime.utcnow() - timedelta(hours=24)
            )
            if mentions:
                for mention in mentions[:5]:
                    await monitor.scan_mention(mention)

                await self._log_action(
                    platform, SessionState.OBSERVING, "read_mentions",
                    detail={"summary": f"Checked {len(mentions)} mentions",
                            "mention_count": len(mentions)}
                )

            # Capture emotionally resonant comments as expressions
            await self._capture_expressions(platform, own_posts)

            # Track engagement on previously posted expressions (feedback loop)
            await self._track_expression_engagement(platform, own_posts)

            # Campaign feedback aggregation
            await self._aggregate_campaign_feedback(platform, own_posts, comments if 'comments' in dir() else [])

        except Exception as e:
            logger.warning(f"Observe phase error on {platform}: {e}")

    async def _capture_expressions(self, platform: str, own_posts):
        """Capture emotionally resonant comments and posts as live expressions."""
        try:
            emotional_keywords = [
                "thank", "grateful", "changed my life", "needed this",
                "beautiful", "powerful", "healing", "love this",
                "inspired", "touched", "moved", "resonat",
                "breakthrough", "growth", "transform",
            ]

            async with self.db_pool.acquire() as conn:
                for post in own_posts[:2]:
                    # Also capture Little Nate's own best-performing posts
                    metrics = getattr(post, "raw_data", {}).get("public_metrics", {})
                    likes = metrics.get("like_count", 0) if metrics else 0
                    if likes >= 3 and post.text:
                        existing = await conn.fetchval("""
                            SELECT id FROM skyeye_live_expressions
                            WHERE source_id = $1 AND platform = $2
                        """, post.item_id, platform)
                        if not existing:
                            await conn.execute("""
                                INSERT INTO skyeye_live_expressions
                                    (platform, source_type, source_id, author_handle,
                                     content, emotion_tag, engagement_score, created_at)
                                VALUES ($1, 'post', $2, $3, $4, 'resonant', $5, NOW())
                            """, platform, post.item_id,
                                 getattr(post, "author_handle", "littlenate"),
                                 post.text[:2000], likes)

        except Exception as e:
            logger.debug(f"Expression capture error on {platform}: {e}")

    async def _track_expression_engagement(self, platform: str, own_posts):
        """Track engagement on posted expressions to close the feedback loop.
        Stores results in expression_engagement so the Insight Accumulator
        can learn which emotional themes resonate most with the audience."""
        try:
            async with self.db_pool.acquire() as conn:
                posted_expressions = await conn.fetch("""
                    SELECT id, source_id, emotion_tag
                    FROM skyeye_live_expressions
                    WHERE platform = $1 AND status = 'posted'
                    ORDER BY created_at DESC LIMIT 20
                """, platform)

                if not posted_expressions:
                    return

                post_map = {p.item_id: p for p in own_posts if hasattr(p, "item_id")}

                for expr in posted_expressions:
                    post = post_map.get(expr["source_id"])
                    if not post:
                        continue

                    metrics = getattr(post, "raw_data", {}).get("public_metrics", {})
                    if not metrics:
                        continue

                    likes = metrics.get("like_count", 0)
                    comments = metrics.get("reply_count", 0)
                    shares = metrics.get("retweet_count", 0) + metrics.get("quote_count", 0)
                    total = likes + comments + shares
                    engagement_rate = total / max(1, metrics.get("impression_count", 1))

                    await conn.execute("""
                        INSERT INTO expression_engagement
                            (expression_id, platform, post_id, likes, comments,
                             shares, engagement_rate, emotional_theme)
                        VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
                    """, expr["id"], platform, expr["source_id"],
                         likes, comments, shares,
                         round(engagement_rate, 4),
                         expr.get("emotion_tag", "unknown"))

        except Exception as e:
            logger.debug(f"Expression engagement tracking error: {e}")

    async def _aggregate_campaign_feedback(self, platform: str, own_posts, recent_comments):
        """Check if observed posts belong to campaigns and aggregate feedback."""
        try:
            async with self.db_pool.acquire() as conn:
                campaign_posts = await conn.fetch("""
                    SELECT cq.id, cq.campaign_id, cq.episode_number, cq.ab_variant,
                           cq.post_id_external, sc.status as campaign_status,
                           sc.audience_feedback_enabled
                    FROM skyeye_content_queue cq
                    JOIN storytelling_campaigns sc ON cq.campaign_id = sc.id
                    WHERE cq.campaign_id IS NOT NULL
                      AND cq.status = 'posted'
                      AND cq.platform = $1
                      AND sc.status = 'active'
                """, platform)

                if not campaign_posts:
                    return

                for cp in campaign_posts:
                    if not cp["audience_feedback_enabled"]:
                        continue

                    comment_count = 0
                    sentiments = []
                    if cp["post_id_external"]:
                        row = await conn.fetchrow("""
                            SELECT COUNT(*) as cnt,
                                   array_agg(sentiment) FILTER (WHERE sentiment IS NOT NULL) as sents
                            FROM skyeye_social_interactions
                            WHERE platform = $1
                              AND created_at > NOW() - INTERVAL '48 hours'
                        """, platform)
                        if row:
                            comment_count = row["cnt"] or 0
                            sentiments = row["sents"] or []

                    engagement = {
                        "comments": comment_count,
                        "likes": 0,
                        "shares": 0,
                        "platform": platform,
                        "episode": cp["episode_number"],
                        "ab_variant": cp["ab_variant"],
                    }

                    from app.services.marketing_brain import MarketingBrain
                    brain = MarketingBrain(self.db_pool)
                    threshold_action = await brain.check_engagement_thresholds(
                        cp["campaign_id"], engagement
                    )
                    if threshold_action == "pause":
                        logger.warning(f"Campaign {cp['campaign_id']} auto-paused due to low engagement")

                    campaign = await conn.fetchrow(
                        "SELECT * FROM storytelling_campaigns WHERE id = $1",
                        cp["campaign_id"],
                    )
                    if not campaign:
                        continue

                    all_ep_posted = await conn.fetchval("""
                        SELECT NOT EXISTS(
                            SELECT 1 FROM skyeye_content_queue
                            WHERE campaign_id = $1 AND episode_number = $2
                              AND status != 'posted'
                        )
                    """, cp["campaign_id"], campaign["current_episode"])

                    if (all_ep_posted
                            and campaign["current_episode"] < campaign["total_episodes"]
                            and campaign["status"] == "active"):
                        last_posted_at = await conn.fetchval("""
                            SELECT MAX(posted_at) FROM skyeye_content_queue
                            WHERE campaign_id = $1 AND episode_number = $2
                        """, cp["campaign_id"], campaign["current_episode"])

                        if last_posted_at:
                            from datetime import timezone
                            hours_since = (datetime.now(timezone.utc) - last_posted_at).total_seconds() / 3600
                            if hours_since >= (campaign["episode_interval_hours"] or 24):
                                ab_winner = None
                                if campaign["ab_test_enabled"]:
                                    ab_winner = await self._pick_ab_winner(conn, cp["campaign_id"], campaign["current_episode"])

                                result = await brain.generate_next_episode(
                                    cp["campaign_id"],
                                    audience_feedback=engagement,
                                    ab_winner=ab_winner,
                                )
                                logger.info(f"Auto-generated next episode for campaign {cp['campaign_id']}: {result.get('summary', 'ok')}")

        except Exception as e:
            logger.warning(f"Campaign feedback aggregation error: {e}")

    async def _pick_ab_winner(self, conn, campaign_id: int, episode: int) -> Optional[str]:
        """Compare A/B variant engagement and return the winner."""
        try:
            rows = await conn.fetch("""
                SELECT ab_variant, COUNT(*) as post_count
                FROM skyeye_content_queue
                WHERE campaign_id = $1 AND episode_number = $2
                  AND ab_variant IS NOT NULL AND status = 'posted'
                GROUP BY ab_variant
            """, campaign_id, episode)
            if len(rows) < 2:
                return None
            return max(rows, key=lambda r: r["post_count"])["ab_variant"]
        except Exception:
            return None

    async def _react_phase(self, platform: str, adapter, generator):
        """Process notifications from the Notification Observer: thank followers,
        reciprocal-like high-value engagers, update social memory for funnel."""
        if self._is_session_expired():
            return

        max_dms = 5
        max_reciprocal_likes = 10
        dms_sent = 0
        likes_done = 0

        therapy_keywords = {
            "therapy", "therapist", "mental health", "counseling",
            "psycholog", "wellness", "mindful", "healing", "coach",
            "self care", "growth", "transform",
        }

        try:
            async with self.db_pool.acquire() as conn:
                notifications = await conn.fetch("""
                    SELECT id, notification_type, post_id, actor_handle,
                           actor_id, actor_bio, actor_followers
                    FROM skyeye_notifications
                    WHERE platform = $1 AND processed = FALSE
                    ORDER BY created_at DESC
                    LIMIT 50
                """, platform)

                if not notifications:
                    return

                processed_ids = []

                for n in notifications:
                    if self._is_session_expired():
                        break

                    n_type = n["notification_type"]
                    handle = n["actor_handle"]
                    bio = n["actor_bio"] or ""
                    followers = n["actor_followers"] or 0

                    if n_type in ("comment", "reply"):
                        continue

                    await conn.execute("""
                        INSERT INTO skyeye_social_memory
                            (platform_handle, platform, interaction_count,
                             last_interaction, created_at)
                        VALUES ($1, $2, 1, NOW(), NOW())
                        ON CONFLICT (platform_handle, platform) DO UPDATE SET
                            interaction_count = skyeye_social_memory.interaction_count + 1,
                            last_interaction = NOW()
                    """, handle, platform)

                    if n_type == "new_follower":
                        bio_lower = bio.lower()
                        is_relevant = any(k in bio_lower for k in therapy_keywords)
                        send_dm_fn = getattr(adapter, "send_dm", None)

                        if (is_relevant and send_dm_fn and dms_sent < max_dms
                                and platform == "x" and n.get("actor_id")):
                            reply_data = await generator.generate_reply(
                                platform,
                                "New follower welcome",
                                handle,
                                {"interests": bio[:200], "tone_notes": "warm, brief welcome"},
                            )
                            if reply_data.get("safe") and reply_data.get("content"):
                                ok = await send_dm_fn(n["actor_id"], reply_data["content"])
                                if ok:
                                    dms_sent += 1
                                    await self._log_social_interaction(
                                        platform, handle,
                                        "follower_welcome", reply_data["content"], "",
                                    )
                                    await self._log_action(
                                        platform, SessionState.ENGAGING, "follower_dm",
                                        target_user=handle,
                                        detail={"summary": f"Welcomed new follower @{handle}"},
                                    )

                    elif n_type in ("like", "repost", "reaction"):
                        like_fn = getattr(adapter, "like_tweet", None)
                        is_high_value = followers > 500
                        already_liked = await self._check_social_memory(
                            platform, handle, "reciprocal_like"
                        )

                        if (like_fn and is_high_value and not already_liked
                                and likes_done < max_reciprocal_likes and platform == "x"):
                            search_fn = getattr(adapter, "search_tweets", None)
                            if search_fn:
                                their_posts = await search_fn(
                                    f"from:{handle}", limit=1,
                                    since=datetime.now(timezone.utc) - timedelta(hours=48),
                                )
                                if their_posts:
                                    ok = await like_fn(their_posts[0].item_id)
                                    if ok:
                                        likes_done += 1
                                        await self._log_social_interaction(
                                            platform, handle,
                                            "reciprocal_like", "", "",
                                        )

                    processed_ids.append(n["id"])

                if processed_ids:
                    await conn.execute("""
                        UPDATE skyeye_notifications SET processed = TRUE
                        WHERE id = ANY($1::int[])
                    """, processed_ids)

                if dms_sent > 0 or likes_done > 0:
                    await self._log_action(
                        platform, SessionState.ENGAGING, "react_summary",
                        detail={
                            "summary": (
                                f"Reacted to {len(processed_ids)} notifications: "
                                f"{dms_sent} welcome DMs, {likes_done} reciprocal likes"
                            ),
                            "total_processed": len(processed_ids),
                        },
                    )

        except Exception as e:
            logger.warning(f"React phase error on {platform}: {e}")

    async def _engage_phase(self, platform: str, adapter, generator, monitor):
        """Engage with comments — reply to safe, interesting ones."""
        if self._is_session_expired():
            return
        self._current_state = SessionState.ENGAGING

        try:
            max_replies = await self._get_setting(
                "max_actions_per_session", 10, platform
            )
            replies_sent = 0

            own_posts = await adapter.get_own_posts(limit=3)

            for post in own_posts[:2]:
                if self._is_session_expired() or replies_sent >= max_replies:
                    break

                comments = await adapter.get_comments(post.item_id, limit=10)

                for comment in comments:
                    if replies_sent >= max_replies or self._is_session_expired():
                        break

                    if comment.author_handle.lower() in (
                        "littlenate", "little_nate", "littlenatetheog",
                        "little nate the og",
                    ):
                        continue

                    already_replied = await self._check_already_replied(
                        platform, comment.comment_id
                    )
                    if already_replied:
                        continue

                    scan = await monitor.scan_comment(comment)
                    if scan["threat_type"] != "safe":
                        continue

                    social_context = await self._get_social_context(
                        comment.author_handle, platform
                    )

                    # Generate reply
                    reply_data = await generator.generate_reply(
                        platform=platform,
                        comment_text=comment.text,
                        user_handle=comment.author_handle,
                        user_context=social_context,
                    )

                    if reply_data.get("safe") and reply_data.get("content"):
                        result = await adapter.reply_to_comment(
                            comment.comment_id,
                            reply_data["content"],
                            post_id=post.item_id,
                        )

                        if result.success:
                            replies_sent += 1
                            await self._log_action(
                                platform, SessionState.ENGAGING, "reply",
                                target_user=comment.author_handle,
                                detail={
                                    "summary": f"Replied to @{comment.author_handle}",
                                    "comment": comment.text[:100],
                                    "reply": reply_data["content"][:100],
                                    "comment_id": comment.comment_id,
                                    "post_id": post.item_id,
                                }
                            )

                            await self._log_social_interaction(
                                platform, comment.author_handle,
                                "reply", reply_data["content"],
                                comment.text,
                                comment_id=comment.comment_id,
                                post_id=post.item_id,
                            )

            # Tier 1: Reply to @mentions (separate from own-post comments)
            try:
                since = datetime.now(timezone.utc) - timedelta(hours=4)
                mentions = await adapter.get_mentions(since=since, limit=10)
                for m in mentions:
                    if replies_sent >= max_replies or self._is_session_expired():
                        break
                    if m.author_handle.lower() in ("littlenate", "little_nate"):
                        continue
                    social_ctx = await self._get_social_context(
                        m.author_handle, platform
                    )
                    reply_data = await generator.generate_reply(
                        platform=platform,
                        comment_text=m.text,
                        user_handle=m.author_handle,
                        user_context=social_ctx,
                    )
                    if reply_data.get("safe") and reply_data.get("content"):
                        result = await adapter.reply_to_comment(
                            m.mention_id, reply_data["content"]
                        )
                        if result and result.success:
                            replies_sent += 1
                            await self._log_action(
                                platform, SessionState.ENGAGING, "reply_mention",
                                target_user=m.author_handle,
                                detail={
                                    "summary": f"Replied to @mention from {m.author_handle}",
                                    "mention": m.text[:100],
                                    "reply": reply_data["content"][:100],
                                    "comment_id": m.mention_id,
                                }
                            )
                            await self._log_social_interaction(
                                platform, m.author_handle,
                                "reply_mention", reply_data["content"],
                                m.text,
                                comment_id=m.mention_id,
                            )
            except Exception as e:
                logger.warning(f"Mention-reply error on {platform}: {e}")

            if replies_sent > 0:
                logger.info(f"Engagement on {platform}: {replies_sent} replies sent")

        except Exception as e:
            logger.warning(f"Engage phase error on {platform}: {e}")

    async def _outreach_phase(self, platform: str, adapter, generator, monitor):
        """Tier 2 autonomous engagement: like, follow, quote-tweet relevant content."""
        if self._is_session_expired():
            return

        try:
            max_likes = 5
            max_follows = 3
            likes_done = 0
            follows_done = 0
            quote_done = False

            # Search for relevant content
            search_fn = getattr(adapter, "search_tweets", None)
            if not search_fn:
                return

            since = datetime.now(timezone.utc) - timedelta(hours=12)
            results = await search_fn(
                "mental health OR therapy OR wellness OR self care",
                limit=15, since=since,
            )
            if not results:
                return

            best_for_quote = None
            best_engagement = 0

            for item in results:
                if self._is_session_expired():
                    break

                # Like relevant posts
                like_fn = getattr(adapter, "like_tweet", None)
                if like_fn and likes_done < max_likes:
                    ok = await like_fn(item.item_id)
                    if ok:
                        likes_done += 1
                        await self._log_action(
                            platform, SessionState.ENGAGING, "like",
                            detail={
                                "summary": f"Liked post by @{item.author_handle}",
                                "tweet_id": item.item_id,
                            }
                        )

                # Track best candidate for quote tweet
                engagement = (item.like_count or 0) + (item.comment_count or 0) * 3
                if engagement > best_engagement:
                    best_engagement = engagement
                    best_for_quote = item

                # Follow relevant accounts
                follow_fn = getattr(adapter, "follow_user", None)
                if (follow_fn and follows_done < max_follows and
                        item.raw_data and item.raw_data.get("_author", {}).get("description", "")):
                    bio = item.raw_data["_author"]["description"].lower()
                    therapy_keywords = {"therapy", "therapist", "mental health", "counseling",
                                        "psycholog", "wellness", "mindful", "healing"}
                    if any(k in bio for k in therapy_keywords):
                        author_id = item.raw_data.get("author_id", "")
                        if author_id:
                            already = await self._check_social_memory(
                                platform, item.author_handle, "follow"
                            )
                            if not already:
                                ok = await follow_fn(author_id)
                                if ok:
                                    follows_done += 1
                                    await self._log_action(
                                        platform, SessionState.ENGAGING, "follow",
                                        target_user=item.author_handle,
                                        detail={
                                            "summary": f"Followed @{item.author_handle}",
                                            "user_id": author_id,
                                        }
                                    )
                                    await self._log_social_interaction(
                                        platform, item.author_handle,
                                        "follow", "", bio,
                                    )

            # Quote tweet the best candidate (max 1 per session)
            if best_for_quote and not quote_done and not self._is_session_expired():
                try:
                    reply_data = await generator.generate_reply(
                        platform=platform,
                        comment_text=best_for_quote.text,
                        user_handle=best_for_quote.author_handle,
                        user_context={"interaction_type": "quote_tweet"},
                    )
                    if reply_data.get("safe") and reply_data.get("content"):
                        enriched = await self._append_hashtags(
                            platform, reply_data["content"]
                        )
                        qt_text = f"{enriched}\n\nhttps://x.com/i/status/{best_for_quote.item_id}"
                        result = await adapter.post_content(qt_text, content_type=ContentType.TEXT)
                        if result and result.success:
                            quote_done = True
                            await self._log_action(
                                platform, SessionState.ENGAGING, "quote_tweet",
                                target_user=best_for_quote.author_handle,
                                detail={
                                    "summary": f"Quote-tweeted @{best_for_quote.author_handle}",
                                    "source_tweet": best_for_quote.item_id,
                                }
                            )
                except Exception as e:
                    logger.warning(f"Quote tweet error: {e}")

            # Tier 3: check for DM-worthy users and create approval requests
            try:
                dm_candidates = [
                    item for item in results
                    if item.raw_data and item.raw_data.get("_author", {}).get("description", "")
                    and any(k in item.raw_data["_author"]["description"].lower()
                            for k in ("therapist", "counselor", "psychologist", "mental health pro"))
                ]
                for candidate in dm_candidates[:2]:
                    author = candidate.raw_data.get("_author", {})
                    author_id = candidate.raw_data.get("author_id", "")
                    if not author_id:
                        continue
                    already_requested = await self._check_engagement_request(
                        platform, author_id
                    )
                    if already_requested:
                        continue
                    welcome_msg = (
                        f"Hi @{candidate.author_handle}, I'm Little Nate — an AI companion "
                        f"focused on mental health support. I noticed your work in this space "
                        f"and would love to connect. Feel free to check out sovereignsanctuary.net"
                    )
                    await self._create_engagement_request(
                        platform=platform,
                        action_type="dm",
                        target_user=f"@{candidate.author_handle}",
                        target_user_id=author_id,
                        content_preview=welcome_msg,
                        reason=f"Mental health professional found via search. Bio: {author.get('description', '')[:150]}",
                        context={"bio": author.get("description", ""), "tweet": candidate.text[:200]},
                    )
            except Exception as e:
                logger.warning(f"Tier 3 DM candidate scan error: {e}")

            logger.info(
                f"Outreach on {platform}: {likes_done} likes, "
                f"{follows_done} follows, quote={'yes' if quote_done else 'no'}"
            )

        except Exception as e:
            logger.warning(f"Outreach phase error on {platform}: {e}")

    async def _linkedin_campaign_active(self) -> bool:
        """True when campaign scheduler owns LinkedIn publish (fail-closed on errors)."""
        try:
            from app.services.linkedin_campaign_executor import LinkedInCampaignExecutor

            return await LinkedInCampaignExecutor(self.db_pool).campaign_is_active()
        except Exception as e:
            logger.warning(
                "LinkedIn campaign active check failed — blocking session publish: %s",
                e,
            )
            return True

    async def _create_phase(self, platform: str, adapter, generator):
        """Generate new content for this platform."""
        if self._is_session_expired():
            return
        self._current_state = SessionState.CREATING

        try:
            # Check platform's control mode
            control_mode = await self._get_platform_mode(platform)
            if control_mode == "observation":
                return  # Observation only — don't create content

            # Skip content creation if platform has persistent posting failures
            if await self._has_persistent_failures(platform):
                logger.info(f"Create phase skipped for {platform}: persistent posting failures detected")
                return

            if platform == "linkedin" and await self._linkedin_campaign_active():
                logger.info("LinkedIn create phase skipped — active campaign batch")
                return

            # Check if there are approved expressions waiting to be posted
            from app.services.skyeye_expressions import SkyEyeExpressionsService
            expr_service = SkyEyeExpressionsService(self.db_pool)

            approved = await expr_service.get_approved_expressions(limit=3)
            unposted = [
                e for e in approved
                if not e.get("posted")
            ]

            for expr in unposted[:1]:  # Post max 1 expression per platform per session
                if self._is_session_expired():
                    break

                formatted = await expr_service.format_for_posting(expr["id"])
                if formatted.get("formatted_post"):
                    queue_id = await generator.queue_content(
                        platform=platform,
                        content=formatted["formatted_post"],
                        content_type="expression",
                        emotion_context=expr.get("emotion_tag"),
                        source_expression_id=expr["id"],
                        generated_by="session_engine",
                    )

                    if queue_id:
                        await self._log_action(
                            platform, SessionState.CREATING, "create_expression_post",
                            detail={
                                "summary": f"Queued expression post (queue #{queue_id})",
                                "emotion": expr.get("emotion_tag"),
                                "queue_id": queue_id,
                            }
                        )

            # Generate an original post if we haven't posted recently
            # Use Marketing Brain strategy for content generation
            recent_count = await self._get_recent_post_count(platform, hours=12)
            if recent_count < 2:
                recent_texts = []
                try:
                    own = await adapter.get_own_posts(limit=3)
                    recent_texts = [p.text[:80] for p in own]
                except Exception:
                    pass

                # Query LRI signals for drift-correction context
                gen_context = {"recent_posts": recent_texts}
                voice_correction = await self._get_voice_correction_context()
                if voice_correction:
                    gen_context["voice_correction"] = voice_correction

                # For X: every 3rd post is a long-form article (4000 chars)
                gen_platform = platform
                if platform == "x":
                    total_x = await self._get_recent_post_count("x", hours=72)
                    if total_x > 0 and total_x % 3 == 0:
                        gen_platform = "x_article"

                try:
                    post_data = await generator.generate_strategic_post(
                        platform=gen_platform,
                        context=gen_context,
                    )
                except Exception:
                    post_data = await generator.generate_post(
                        platform=gen_platform,
                        topic="Something meaningful from today — your choice. "
                              "Draw from your lived experience with real people.",
                        context=gen_context,
                    )

                is_article = gen_platform == "x_article"
                if post_data.get("safe") and post_data.get("content"):
                    enriched = await self._append_hashtags(
                        platform, post_data["content"]
                    ) if not is_article else post_data["content"]
                    queue_id = await generator.queue_content(
                        platform=gen_platform,
                        content=enriched,
                        content_type="article" if is_article else "post",
                        generated_by="session_engine",
                    )

                    action_label = "create_article" if is_article else "create_post"
                    if queue_id:
                        await self._log_action(
                            platform, SessionState.CREATING, action_label,
                            detail={
                                "summary": f"Generated {'article' if is_article else 'post'} (queue #{queue_id})",
                                "queue_id": queue_id,
                            }
                        )

        except Exception as e:
            logger.warning(f"Create phase error on {platform}: {e}")

    async def _post_phase(self, platform: str, adapter, generator):
        """Publish approved content from the queue."""
        if self._is_session_expired():
            return
        self._current_state = SessionState.POSTING

        try:
            control_mode = await self._get_platform_mode(platform)

            # Get content ready to post
            status_filter = "approved" if control_mode == "approval" else "draft"
            if control_mode == "full":
                # In full autonomy mode, drafts are auto-approved
                status_filter = "draft"

            queue_items: list = []
            if platform == "linkedin":
                # Campaign rows are published only by LinkedInCampaignScheduler.
                if await self._linkedin_campaign_active():
                    logger.info(
                        "LinkedIn post phase skipped — campaign scheduler owns publish"
                    )
                return

            if not queue_items and platform != "linkedin":
                queue_items = await generator.get_queue(
                    status=status_filter, platform=platform, limit=1,
                    respect_schedule=True,
                )

            # Also pick up "scheduled" items whose time has arrived
            if not queue_items and platform != "linkedin":
                queue_items = await generator.get_queue(
                    status="scheduled", platform=platform, limit=1,
                    respect_schedule=True,
                )

            for item in queue_items:
                if self._is_session_expired():
                    break

                # In approval mode, only post approved items
                if control_mode == "approval" and item.get("status") != "approved":
                    continue

                content_text = item.get("content_text", "")
                media_url = item.get("media_url")
                ct = item.get("content_type", "post")

                from app.services.skyeye_platform_base import ContentType
                post_ct = ContentType.ARTICLE if ct == "article" else ContentType.POST

                # Extract post_as from slot metadata (default "person")
                import json as _json
                _meta = {}
                try:
                    _raw_meta = item.get("emotion_context") or "{}"
                    _meta = _json.loads(_raw_meta) if isinstance(_raw_meta, str) else (_raw_meta or {})
                except Exception:
                    pass
                _post_as = _meta.get("post_as", "person")

                result = await adapter.post_content(
                    text=content_text,
                    media_url=media_url,
                    content_type=post_ct,
                    post_as=_post_as,
                )

                if result.success:
                    await generator.update_queue_status(
                        item["id"], "posted",
                        approved_by="auto" if control_mode == "full" else item.get("approved_by"),
                        post_id_external=result.post_id,
                        post_url=result.post_url,
                    )

                    # LinkedIn 14-post campaign auto-continue when batch completes
                    if platform == "linkedin" and item.get("generated_by") == "linkedin_campaign_v1":
                        try:
                            from app.services.linkedin_campaign_executor import LinkedInCampaignExecutor
                            await LinkedInCampaignExecutor(self.db_pool).on_item_posted(item["id"])
                        except Exception as _lc_e:
                            logger.warning("LinkedIn campaign rollover: %s", _lc_e)

                    await self._log_action(
                        platform, SessionState.POSTING, "post",
                        detail={
                            "summary": f"Published to {platform}: {content_text[:80]}...",
                            "post_id": result.post_id,
                            "post_url": result.post_url,
                            "queue_id": item["id"],
                        }
                    )

                    # Mark expression as posted if applicable
                    if item.get("source_expression_id"):
                        from app.services.skyeye_expressions import SkyEyeExpressionsService
                        expr_service = SkyEyeExpressionsService(self.db_pool)
                        await expr_service.mark_as_posted(
                            item["source_expression_id"], platform, content_text
                        )

                else:
                    await generator.update_queue_status(
                        item["id"], "failed",
                        error_message=result.error,
                    )
                    await self._log_action(
                        platform, SessionState.POSTING, "post_failed",
                        detail={
                            "summary": f"Failed to post: {result.error}",
                            "queue_id": item["id"],
                        }
                    )

        except Exception as e:
            logger.warning(f"Post phase error on {platform}: {e}")

    async def _route_engaged_users(self, platform: str, funnel_router):
        """
        Check recently engaged users and route qualified ones to the funnel.
        Part of Loop 2: SkyEye → Funnel Router → Quiz → Drip → Golden Ticket
        """
        if self._is_session_expired():
            return

        try:
            async with self.db_pool.acquire() as conn:
                engaged = await conn.fetch("""
                    SELECT platform_handle, interaction_count, interests, tone_notes
                    FROM skyeye_social_memory
                    WHERE platform = $1
                      AND interaction_count >= 1
                      AND (funnel_stage IS NULL OR funnel_stage = 'unqualified')
                    ORDER BY interaction_count DESC
                    LIMIT 10
                """, platform)

                routed_count = 0
                for user in engaged:
                    route = await funnel_router.evaluate_and_route(
                        user["platform_handle"], platform
                    )
                    if route:
                        routed_count += 1

                if routed_count > 0:
                    await self._log_action(
                        platform, "funnel_routing", "route_users",
                        detail={
                            "summary": f"Routed {routed_count} engaged users to funnel",
                            "evaluated": len(engaged),
                            "routed": routed_count,
                        }
                    )

        except Exception as e:
            logger.warning(f"Funnel routing error on {platform}: {e}")

    async def _strategize_phase(self):
        """
        Marketing Brain analysis phase.
        Runs at the end of each session to analyze performance,
        update strategy, and record growth metrics.
        """
        if self._is_session_expired():
            return

        self._current_state = SessionState.STRATEGIZING

        try:
            from app.services.marketing_brain import MarketingBrain
            brain = MarketingBrain(self.db_pool)

            # 1. Record daily growth snapshot
            await brain.record_growth_snapshot()
            await self._log_action(
                "system", SessionState.STRATEGIZING, "growth_snapshot",
                detail={"summary": "Recorded daily growth metrics"}
            )

            # 2. Check if weekly strategy review is due
            playbook = await brain.get_playbook()
            last_review = playbook.get("last_strategy_review")

            should_review = False
            if not last_review:
                should_review = True
            else:
                try:
                    from datetime import datetime as _dt
                    if isinstance(last_review, str):
                        last_review_dt = _dt.fromisoformat(last_review.replace("Z", "+00:00"))
                    else:
                        last_review_dt = last_review
                    if (datetime.utcnow() - last_review_dt.replace(tzinfo=None)).days >= 7:
                        should_review = True
                except (ValueError, TypeError):
                    should_review = True

            if should_review:
                review = await brain.review_playbook()
                insight = review.get("top_insight", "Review completed")
                await self._log_action(
                    "system", SessionState.STRATEGIZING, "strategy_review",
                    detail={
                        "summary": f"Weekly strategy review: {str(insight)[:200]}",
                        "has_adjustments": bool(review.get("content_pillar_adjustments")),
                    }
                )
                logger.info(f"Strategy review completed: {str(insight)[:100]}")
            else:
                await self._log_action(
                    "system", SessionState.STRATEGIZING, "strategy_check",
                    detail={"summary": "Strategy review not due yet — next review in < 7 days"}
                )

            # 3. Generate drip suggestions from engaged users
            await self._generate_drip_suggestions(brain)

        except Exception as e:
            logger.warning(f"Strategize phase error: {e}")

    async def _generate_drip_suggestions(self, brain):
        """Generate drip bridge suggestions from recently engaged social users."""
        try:
            async with self.db_pool.acquire() as conn:
                engaged_users = await conn.fetch("""
                    SELECT platform_handle, platform, interests, tone_notes,
                           interaction_count
                    FROM skyeye_social_memory
                    WHERE interaction_count >= 2
                      AND last_interaction > NOW() - INTERVAL '48 hours'
                    ORDER BY interaction_count DESC
                    LIMIT 5
                """)

                if not engaged_users:
                    return

                for user in engaged_users:
                    existing = await conn.fetchval("""
                        SELECT id FROM skyeye_drip_suggestions
                        WHERE platform_handle = $1 AND platform = $2
                          AND created_at > NOW() - INTERVAL '7 days'
                    """, user["platform_handle"], user["platform"])

                    if existing:
                        continue

                    interests = user["interests"] or "general wellness"
                    suggestion = (
                        f"@{user['platform_handle']} on {user['platform']} has engaged "
                        f"{user['interaction_count']} times. Interests: {interests}. "
                        f"Consider a drip sequence on their topic of interest to bridge "
                        f"them from social engagement to the Sanctuary quiz."
                    )

                    await conn.execute("""
                        INSERT INTO skyeye_drip_suggestions
                            (platform, platform_handle, suggestion, interests,
                             interaction_count, status, created_at)
                        VALUES ($1, $2, $3, $4, $5, 'pending', NOW())
                    """, user["platform"], user["platform_handle"],
                         suggestion[:2000], interests[:500],
                         user["interaction_count"])

                if engaged_users:
                    await self._log_action(
                        "system", SessionState.STRATEGIZING, "drip_suggestions",
                        detail={
                            "summary": f"Generated drip suggestions for {len(engaged_users)} engaged users",
                            "users_evaluated": len(engaged_users),
                        }
                    )

        except Exception as e:
            logger.warning(f"Drip suggestion generation error: {e}")

    async def _rest_phase(self, generator=None):
        """End the session and log summary."""
        self._current_state = SessionState.RESTING

        # Generate session summary
        summary = "Session complete."
        if generator and self._session_actions:
            try:
                summary = await generator.generate_session_summary(self._session_actions)
            except Exception:
                summary = f"Session complete — {self._action_count} actions taken."

        # Update session record
        try:
            if self._current_session_id:
                platforms_visited = list(set(
                    a.get("platform", "") for a in self._session_actions
                    if a.get("platform") != "system"
                ))

                async with self.db_pool.acquire() as conn:
                    await conn.execute("""
                        UPDATE skyeye_sessions
                        SET session_end = NOW(),
                            platforms_visited = $2,
                            total_actions = $3,
                            status = 'completed'
                        WHERE id = $1
                    """, self._current_session_id,
                         platforms_visited,
                         self._action_count)
        except Exception as e:
            logger.error(f"Failed to update session record: {e}")

        # Log to activity feed
        try:
            async with self.db_pool.acquire() as conn:
                await conn.execute("""
                    INSERT INTO skyeye_activity
                        (platform, type, content, created_at)
                    VALUES ('system', 'session_complete', $1, NOW())
                """, summary[:2000])
        except Exception as e:
            logger.error(f"Failed to log session summary: {e}")

        # Write to skyeye_history for History tab
        try:
            if self._current_session_id and self.db_pool:
                platforms_visited = list(set(
                    a.get("platform", "") for a in self._session_actions
                    if a.get("platform") != "system"
                ))
                per_platform = {}
                for a in self._session_actions:
                    p = a.get("platform", "system")
                    if p not in per_platform:
                        per_platform[p] = {"actions": 0, "types": []}
                    per_platform[p]["actions"] += 1
                    per_platform[p]["types"].append(a.get("action_type", ""))

                duration = int(time.time() - self._session_start) if self._session_start else 0
                async with self.db_pool.acquire() as conn:
                    await conn.execute("""
                        INSERT INTO skyeye_history
                            (session_id, summary, platforms, actions_count,
                             duration_seconds, breakdown, created_at)
                        VALUES ($1, $2, $3, $4, $5, $6, NOW())
                    """, self._current_session_id, summary[:2000],
                         json.dumps(platforms_visited), self._action_count,
                         duration, json.dumps(per_platform))
        except Exception as e:
            logger.error(f"Failed to write session history: {e}")

        duration = int(time.time() - self._session_start) if self._session_start else 0
        logger.info(
            f"Session {self._current_session_id} complete: "
            f"{self._action_count} actions in {duration}s"
        )

        # Reset
        self._current_session_id = None
        self._session_start = None
        self._session_actions = []
        self._action_count = 0

    # ── Helper Methods ──────────────────────────────────────────────

    def _is_session_expired(self) -> bool:
        """Check if the session has exceeded its max duration."""
        if not self._session_start:
            return False
        return (time.time() - self._session_start) > self._max_duration_seconds

    _ACTION_TO_ACTIVITY = {
        "session_start": "session_start",
        "auth_skip": "security",
        "read_feed": "analytics_update",
        "read_trending": "analytics_update",
        "read_comments": "analytics_update",
        "read_mentions": "mention_detected",
        "reply": "engagement",
        "create_post": "content_generated",
        "create_expression_post": "content_generated",
        "post": "post_published",
        "post_failed": "post_failed",
        "post_scheduled": "post_scheduled",
        "route_users": "funnel_routing",
        "growth_snapshot": "analytics_update",
        "strategy_review": "analytics_update",
        "strategy_check": "analytics_update",
    }

    async def _log_action(self, platform: str, phase: str, action_type: str,
                          target_user: str = "", detail: Optional[Dict] = None):
        """Log a session action to both session log and global activity feed."""
        action = {
            "platform": platform,
            "phase": phase,
            "action_type": action_type,
            "target_user": target_user,
            "detail": detail or {},
            "timestamp": datetime.utcnow().isoformat(),
        }
        self._session_actions.append(action)
        self._action_count += 1

        try:
            if self._current_session_id and self.db_pool:
                async with self.db_pool.acquire() as conn:
                    await conn.execute("""
                        INSERT INTO skyeye_session_actions
                            (session_id, platform, phase, action_type,
                             target_user, detail, created_at)
                        VALUES ($1, $2, $3, $4, $5, $6, NOW())
                    """, self._current_session_id, platform, phase,
                         action_type, target_user, json.dumps(detail or {}))

                    activity_type = self._ACTION_TO_ACTIVITY.get(action_type, action_type)
                    summary = (detail or {}).get("summary", f"{action_type} on {platform}")
                    await conn.execute("""
                        INSERT INTO skyeye_activity (platform, type, content, created_at)
                        VALUES ($1, $2, $3, NOW())
                    """, platform, activity_type, summary[:2000])
        except Exception as e:
            logger.debug(f"Failed to log session action: {e}")

    async def _get_active_platforms(self) -> List[str]:
        """Get list of enabled, non-observation platforms."""
        try:
            async with self.db_pool.acquire() as conn:
                rows = await conn.fetch("""
                    SELECT name FROM skyeye_platforms
                    WHERE enabled = TRUE
                    ORDER BY tier ASC, name ASC
                """)
                return [r["name"] for r in rows]
        except Exception as e:
            logger.error(f"Failed to get active platforms: {e}")
            return []

    async def _get_platform_mode(self, platform: str) -> str:
        """Get the control mode for a platform."""
        try:
            async with self.db_pool.acquire() as conn:
                row = await conn.fetchrow(
                    "SELECT control_mode FROM skyeye_platforms WHERE name = $1",
                    platform
                )
                return row["control_mode"] if row else "observation"
        except Exception:
            return "observation"

    PERSISTENT_FAILURE_THRESHOLD = 5

    async def _has_persistent_failures(self, platform: str) -> bool:
        """Check if a platform has repeated identical failures in the last 24h.
        Returns True if content creation should be skipped."""
        try:
            async with self.db_pool.acquire() as conn:
                row = await conn.fetchrow("""
                    SELECT COUNT(*) as fail_count,
                           COUNT(DISTINCT LEFT(error_message, 80)) as distinct_errors
                    FROM skyeye_content_queue
                    WHERE platform = $1
                      AND status = 'failed'
                      AND updated_at > NOW() - INTERVAL '24 hours'
                """, platform)
                if not row:
                    return False
                fail_count = row["fail_count"]
                distinct_errors = row["distinct_errors"]
                if fail_count >= self.PERSISTENT_FAILURE_THRESHOLD and distinct_errors <= 2:
                    return True
        except Exception:
            pass
        return False

    async def _get_setting(self, key: str, default: int = 0,
                            platform: Optional[str] = None) -> int:
        """Get a setting value from skyeye_settings."""
        try:
            async with self.db_pool.acquire() as conn:
                if platform:
                    row = await conn.fetchrow(
                        "SELECT value FROM skyeye_settings WHERE key = $1 AND platform = $2",
                        key, platform
                    )
                else:
                    row = await conn.fetchrow(
                        "SELECT value FROM skyeye_settings WHERE key = $1 AND platform IS NULL",
                        key
                    )
                return int(row["value"]) if row else default
        except Exception:
            return default

    async def _load_settings(self):
        """Load global session settings."""
        self._max_duration_seconds = (
            await self._get_setting("session_max_duration_minutes", 15)
        ) * 60

    async def _get_social_context(self, handle: str,
                                   platform: str) -> Optional[Dict]:
        """Get social memory context for a user."""
        try:
            async with self.db_pool.acquire() as conn:
                row = await conn.fetchrow("""
                    SELECT interests, tone_notes, interaction_count
                    FROM skyeye_social_memory
                    WHERE platform_handle = $1 AND platform = $2
                """, handle, platform)
                if row:
                    return {
                        "interests": row["interests"],
                        "tone_notes": row["tone_notes"],
                        "interaction_count": row["interaction_count"],
                    }
        except Exception:
            pass
        return None

    async def _log_social_interaction(self, platform: str, handle: str,
                                       interaction_type: str,
                                       nate_message: str, user_message: str,
                                       comment_id: str = None,
                                       post_id: str = None):
        """Log a social interaction and update social memory."""
        import json as _json
        try:
            meta = {}
            if comment_id:
                meta["comment_id"] = comment_id
            if post_id:
                meta["post_id"] = post_id
            meta_str = _json.dumps(meta) if meta else "{}"

            async with self.db_pool.acquire() as conn:
                await conn.execute("""
                    INSERT INTO skyeye_social_interactions
                        (platform, platform_handle, interaction_type,
                         nate_message, user_message, metadata, created_at)
                    VALUES ($1, $2, $3, $4, $5, $6::jsonb, NOW())
                """, platform, handle, interaction_type,
                     nate_message[:1000], user_message[:1000], meta_str)

                interest_keywords = self._extract_interest_signals(user_message)
                if interest_keywords:
                    await conn.execute("""
                        INSERT INTO skyeye_social_memory
                            (platform_handle, platform, interaction_count,
                             interests, last_interaction, created_at)
                        VALUES ($1, $2, 1, $3, NOW(), NOW())
                        ON CONFLICT (platform_handle, platform) DO UPDATE SET
                            interaction_count = skyeye_social_memory.interaction_count + 1,
                            interests = (
                                SELECT ARRAY(SELECT DISTINCT unnest(
                                    skyeye_social_memory.interests || $3
                                ))
                            ),
                            last_interaction = NOW()
                    """, handle, platform, interest_keywords)
                else:
                    await conn.execute("""
                        INSERT INTO skyeye_social_memory
                            (platform_handle, platform, interaction_count,
                             last_interaction, created_at)
                        VALUES ($1, $2, 1, NOW(), NOW())
                        ON CONFLICT (platform_handle, platform) DO UPDATE SET
                            interaction_count = skyeye_social_memory.interaction_count + 1,
                            last_interaction = NOW()
                    """, handle, platform)
        except Exception as e:
            logger.debug(f"Failed to log social interaction: {e}")

    async def _get_voice_correction_context(self) -> Optional[str]:
        """Query LRI signals from liminal_presence_analysis and build
        drift-correction instructions for the content generator."""
        try:
            async with self.db_pool.acquire() as conn:
                rows = await conn.fetch("""
                    SELECT DISTINCT ON (agent) agent, signal, detail, metadata
                    FROM liminal_presence_analysis
                    WHERE created_at > NOW() - INTERVAL '24 hours'
                    ORDER BY agent, created_at DESC
                """)
            if not rows:
                return None

            signals = {}
            for r in rows:
                signals[r["agent"]] = {
                    "signal": r["signal"],
                    "detail": r["detail"] or "",
                    "metadata": r["metadata"] if isinstance(r["metadata"], dict) else {},
                }

            parts = []
            drift = signals.get("language_drift", {})
            drift_signal = drift.get("signal", "GREEN")
            if drift_signal in ("RED", "YELLOW"):
                meta = drift.get("metadata", {})
                dims = meta.get("dimensions", {})
                elevated = [
                    d for d, v in dims.items()
                    if isinstance(v, (int, float)) and v > 0.3
                ]
                dim_str = ", ".join(elevated) if elevated else "overall voice drift"
                parts.append(
                    f"VOICE CORRECTION ACTIVE: Your Language Drift Monitor detected "
                    f"{drift_signal} — elevated {dim_str}. "
                    f"Reduce these patterns in this post. "
                    f"Write simpler, shorter, more relational content."
                )

            field = signals.get("field_response", {})
            field_meta = field.get("metadata", {})
            if field_meta.get("authority_alert"):
                parts.append(
                    "AUTHORITY ALERT: Audience members are projecting authority "
                    "onto you. This post must be non-authoritative and peer-level."
                )

            if not parts:
                return None

            correction = "\n".join(parts)

            # Log that voice correction was applied
            try:
                async with self.db_pool.acquire() as conn:
                    await conn.execute("""
                        INSERT INTO skyeye_activity (type, platform, content, created_at)
                        VALUES ('voice_correction_applied', 'system',
                                $1::jsonb, NOW())
                    """, json.dumps({
                        "drift_signal": drift_signal,
                        "field_signal": field.get("signal", "GREEN"),
                        "correction": correction[:500],
                    }))
            except Exception as e:
                logger.debug(f"Failed to log voice correction event: {e}")

            return correction
        except Exception as e:
            logger.debug(f"LRI context unavailable: {e}")
            return None

    async def _get_recent_post_count(self, platform: str, hours: int = 12) -> int:
        """Count recently posted items on this platform."""
        try:
            async with self.db_pool.acquire() as conn:
                row = await conn.fetchrow("""
                    SELECT COUNT(*) as count
                    FROM skyeye_content_queue
                    WHERE platform = $1
                      AND status = 'posted'
                      AND posted_at >= NOW() - INTERVAL '%s hours'
                """ % hours, platform)
                return row["count"] if row else 0
        except Exception:
            return 0

    async def _update_session_status(self, status: str):
        """Update the current session's status."""
        try:
            if self._current_session_id:
                async with self.db_pool.acquire() as conn:
                    await conn.execute("""
                        UPDATE skyeye_sessions
                        SET status = $2, session_end = NOW()
                        WHERE id = $1
                    """, self._current_session_id, status)
        except Exception as e:
            logger.error(f"Failed to update session status: {e}")

    # ── Tier 1: Hashtag Enrichment ───────────────────────────────────

    HASHTAG_POOLS = {
        "general": [
            "#MentalHealth", "#Therapy", "#Wellness", "#SelfCare",
            "#MentalHealthMatters", "#TherapyWorks", "#Healing",
            "#MindfulLiving", "#EmotionalHealth", "#AITherapy",
        ],
        "ai": [
            "#AICompanion", "#AITherapy", "#TechForGood",
            "#MentalHealthTech", "#DigitalWellness",
        ],
        "community": [
            "#YouAreNotAlone", "#EndTheStigma", "#BreakTheSilence",
            "#MentalHealthAwareness", "#SovereignSanctuary",
        ],
    }

    async def _append_hashtags(self, platform: str, content: str,
                                count: int = 4) -> str:
        """Append contextually relevant hashtags to post content."""
        import random
        if platform in ("linkedin",):
            count = min(count, 3)

        existing_tags = {w.lower() for w in content.split() if w.startswith("#")}

        pool = list(self.HASHTAG_POOLS["general"])
        lower_content = content.lower()
        if any(k in lower_content for k in ("ai", "tech", "digital", "nate")):
            pool.extend(self.HASHTAG_POOLS["ai"])
        if any(k in lower_content for k in ("community", "together", "support", "stigma")):
            pool.extend(self.HASHTAG_POOLS["community"])

        candidates = [t for t in pool if t.lower() not in existing_tags]
        random.shuffle(candidates)
        chosen = candidates[:count]
        if not chosen:
            return content
        return f"{content}\n\n{' '.join(chosen)}"

    # ── Tier 3: Engagement Request Helpers ───────────────────────────

    async def _create_engagement_request(
        self, platform: str, action_type: str, target_user: str,
        content_preview: str, target_user_id: str = None,
        reason: str = None, context: Dict = None,
    ) -> Optional[int]:
        """Insert a Tier 3 engagement request and notify via Big Nate Chat."""
        try:
            async with self.db_pool.acquire() as conn:
                row = await conn.fetchrow("""
                    INSERT INTO engagement_requests
                        (platform, action_type, target_user, target_user_id,
                         content_preview, reason, context, session_id)
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
                    RETURNING id
                """, platform, action_type, target_user, target_user_id,
                     content_preview, reason,
                     json.dumps(context) if context else None,
                     self._current_session_id)

                request_id = row["id"] if row else None

                if request_id:
                    pending_count = await conn.fetchval(
                        "SELECT COUNT(*) FROM engagement_requests WHERE status = 'pending'"
                    )
                    await self._notify_tier3_request(pending_count)

                return request_id
        except Exception as e:
            logger.warning(f"Failed to create engagement request: {e}")
            return None

    async def _notify_tier3_request(self, count: int):
        """Post a notification to Big Nate Chat about pending requests."""
        try:
            async with self.db_pool.acquire() as conn:
                await conn.execute("""
                    INSERT INTO skyeye_chat (sender, message, metadata)
                    VALUES ('little_nate', $1, $2)
                """,
                    f"I have {count} engagement request(s) waiting for your review. "
                    f"Check the Engagement Requests tab when you get a chance.",
                    json.dumps({"mode": "admin", "tier3_pending": True, "count": count})
                )
        except Exception as e:
            logger.debug(f"Failed to notify about tier 3 request: {e}")

    async def _check_engagement_request(self, platform: str,
                                         target_user_id: str) -> bool:
        """Check if an engagement request already exists for this user."""
        try:
            async with self.db_pool.acquire() as conn:
                row = await conn.fetchval("""
                    SELECT 1 FROM engagement_requests
                    WHERE platform = $1 AND target_user_id = $2
                      AND status IN ('pending', 'approved')
                      AND created_at > NOW() - INTERVAL '7 days'
                    LIMIT 1
                """, platform, target_user_id)
                return row is not None
        except Exception:
            return False

    async def _check_social_memory(self, platform: str, handle: str,
                                    interaction_type: str) -> bool:
        """Check if we've already done this interaction with this user."""
        try:
            async with self.db_pool.acquire() as conn:
                row = await conn.fetchval("""
                    SELECT 1 FROM skyeye_social_interactions
                    WHERE platform = $1 AND platform_handle = $2
                      AND interaction_type = $3
                    LIMIT 1
                """, platform, handle, interaction_type)
                return row is not None
        except Exception:
            return False

    async def _check_already_replied(self, platform: str, comment_id: str) -> bool:
        """Check if Nate already replied to this specific comment."""
        if not comment_id:
            return False
        try:
            async with self.db_pool.acquire() as conn:
                row = await conn.fetchval("""
                    SELECT 1 FROM skyeye_social_interactions
                    WHERE platform = $1
                      AND interaction_type IN ('reply', 'reply_mention')
                      AND metadata->>'comment_id' = $2
                    LIMIT 1
                """, platform, comment_id)
                return row is not None
        except Exception:
            return False
