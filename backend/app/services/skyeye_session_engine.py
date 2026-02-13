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
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

from app.config import settings

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
        self._max_duration_seconds = 900  # 15 minutes default
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

        # Load settings
        await self._load_settings()

        # Schedule the main session loop
        self.scheduler.add_job(
            self._session_tick,
            IntervalTrigger(minutes=5),  # Check every 5 minutes
            id="skyeye_session_tick",
            replace_existing=True,
            max_instances=1,
        )

        self.scheduler.start()
        self._is_running = True
        logger.info("SkyEye Session Engine started")

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
                    cooldown_until = last_session["session_end"] + timedelta(minutes=cooldown)
                    if datetime.utcnow() < cooldown_until:
                        return False

                # Check if any platform is due for a session
                # (simplified — full implementation would check per-platform schedules)
                platforms = await conn.fetch("""
                    SELECT name FROM skyeye_platforms
                    WHERE enabled = TRUE AND control_mode != 'observation'
                """)

                # If there are active platforms, we should run
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
                await self._observe_phase(platform_name, adapter, monitor)
                await self._engage_phase(platform_name, adapter, generator, monitor)
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

        except Exception as e:
            logger.warning(f"Observe phase error on {platform}: {e}")

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

                    # Skip own comments
                    if comment.author_handle.lower() in ("littlenate", "little_nate"):
                        continue

                    # Scan for threats first
                    scan = await monitor.scan_comment(comment)
                    if scan["threat_type"] != "safe":
                        continue  # Threats handled by monitor, don't reply

                    # Check social memory for this user
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
                                }
                            )

                            # Log social interaction
                            await self._log_social_interaction(
                                platform, comment.author_handle,
                                "reply", reply_data["content"],
                                comment.text,
                            )

            if replies_sent > 0:
                logger.info(f"Engagement on {platform}: {replies_sent} replies sent")

        except Exception as e:
            logger.warning(f"Engage phase error on {platform}: {e}")

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

            # Check if there are approved expressions waiting to be posted
            from app.services.skyeye_expressions import SkyEyeExpressionsService
            expr_service = SkyEyeExpressionsService(self.db_pool)

            approved = await expr_service.get_approved_expressions(limit=3)
            unposted = [
                e for e in approved.get("expressions", [])
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
                try:
                    # Try strategic content generation first
                    post_data = await generator.generate_strategic_post(
                        platform=platform,
                        context={
                            "recent_posts": [p.text[:80] for p in
                                             (await adapter.get_own_posts(limit=3))],
                        }
                    )
                except Exception:
                    # Fallback to basic generation
                    post_data = await generator.generate_post(
                        platform=platform,
                        topic="Something meaningful from today — your choice. "
                              "Draw from your lived experience with real people.",
                        context={
                            "recent_posts": [p.text[:80] for p in
                                             (await adapter.get_own_posts(limit=3))],
                        }
                    )

                if post_data.get("safe") and post_data.get("content"):
                    queue_id = await generator.queue_content(
                        platform=platform,
                        content=post_data["content"],
                        content_type="post",
                        generated_by="session_engine",
                    )

                    if queue_id:
                        await self._log_action(
                            platform, SessionState.CREATING, "create_post",
                            detail={
                                "summary": f"Generated new post (queue #{queue_id})",
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

            queue_items = await generator.get_queue(
                status=status_filter, platform=platform, limit=3
            )

            for item in queue_items:
                if self._is_session_expired():
                    break

                # In approval mode, only post approved items
                if control_mode == "approval" and item.get("status") != "approved":
                    continue

                content_text = item.get("content_text", "")
                media_url = item.get("media_url")

                # Post to platform
                result = await adapter.post_content(
                    text=content_text,
                    media_url=media_url,
                )

                if result.success:
                    await generator.update_queue_status(
                        item["id"], "posted",
                        approved_by="auto" if control_mode == "full" else item.get("approved_by"),
                        post_id_external=result.post_id,
                        post_url=result.post_url,
                    )

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
                # Get users with 3+ interactions who aren't yet in a funnel
                engaged = await conn.fetch("""
                    SELECT platform_handle, interaction_count, interests, tone_notes
                    FROM skyeye_social_memory
                    WHERE platform = $1
                      AND interaction_count >= 3
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

        except Exception as e:
            logger.warning(f"Strategize phase error: {e}")

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
                         json.dumps(platforms_visited),
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

    async def _log_action(self, platform: str, phase: str, action_type: str,
                          target_user: str = "", detail: Optional[Dict] = None):
        """Log a session action to the database and in-memory list."""
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
                                       nate_message: str, user_message: str):
        """Log a social interaction and update social memory."""
        try:
            async with self.db_pool.acquire() as conn:
                # Log interaction
                await conn.execute("""
                    INSERT INTO skyeye_social_interactions
                        (platform, platform_handle, interaction_type,
                         nate_message, user_message, created_at)
                    VALUES ($1, $2, $3, $4, $5, NOW())
                """, platform, handle, interaction_type,
                     nate_message[:1000], user_message[:1000])

                # Update or create social memory
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
