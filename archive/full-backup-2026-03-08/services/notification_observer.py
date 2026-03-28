"""
LITTLE NATE — Notification Observer Agent
Polls social media platforms every 30 minutes to detect engagement signals
that the session engine can't see: likes on own posts, reposts, new followers,
and reactions. Stores discoveries in skyeye_notifications for the session
engine's React phase to process.

Also captures per-post analytics snapshots and resolves unresolved user IDs.

Stagger delay: 260s. Loop interval: 30 minutes.
"""

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger("nate.notification_observer")

POLL_INTERVAL_SECONDS = 1800  # 30 minutes
STAGGER_DELAY = 260
MAX_POSTS_TO_CHECK = 10
POST_LOOKBACK_HOURS = 48


class NotificationObserver:
    def __init__(self, db_pool, app_state=None, notification_system=None):
        self.db_pool = db_pool
        self._app_state = app_state
        self.notifications = notification_system
        self._task: Optional[asyncio.Task] = None
        self._running = False

    async def start(self):
        if self._task and not self._task.done():
            return
        self._running = True
        self._task = asyncio.create_task(self._run_loop())
        logger.info("NotificationObserver started (every 30min, stagger 260s)")

    async def stop(self):
        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("NotificationObserver stopped")

    async def _run_loop(self):
        await asyncio.sleep(STAGGER_DELAY)
        while self._running:
            try:
                await self._poll_all_platforms()
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.error("NotificationObserver tick failed: %s", e, exc_info=True)
            await asyncio.sleep(POLL_INTERVAL_SECONDS)

    async def _poll_all_platforms(self):
        """Run notification polling across all connected platforms."""
        from app.services.platforms import get_adapter

        platforms = await self._get_connected_platforms()
        if not platforms:
            logger.warning("NotificationObserver: no connected platforms found — skipping poll cycle")
            return

        total_new = 0
        platforms_polled = []

        for platform_name in platforms:
            try:
                adapter = get_adapter(platform_name, self.db_pool)
                if not adapter:
                    continue

                connected = await adapter.authenticate()
                if not connected:
                    continue

                new_count = 0

                if platform_name == "x":
                    new_count += await self._poll_x(adapter)
                elif platform_name == "linkedin":
                    new_count += await self._poll_linkedin(adapter)
                elif platform_name == "instagram":
                    new_count += await self._poll_instagram(adapter)
                elif platform_name == "facebook":
                    new_count += await self._poll_facebook(adapter)
                elif platform_name == "youtube":
                    new_count += await self._poll_youtube(adapter)

                await self._capture_post_analytics(platform_name, adapter)

                total_new += new_count
                platforms_polled.append(platform_name)

            except Exception as e:
                logger.warning(f"NotificationObserver: {platform_name} error: {e}")

        if total_new > 0:
            logger.info(f"NotificationObserver: {total_new} new notifications detected")

        await self._log_cycle_activity(platforms_polled, total_new)

    # ── X/Twitter Polling ────────────────────────────────────────────

    async def _poll_x(self, adapter) -> int:
        new_count = 0

        own_posts = await adapter.get_own_posts(limit=MAX_POSTS_TO_CHECK)

        for post in own_posts:
            if not post.item_id:
                continue

            likers = await self._safe_call(adapter.get_liking_users, post.item_id)
            for user in likers:
                inserted = await self._store_notification(
                    "x", "like", post.item_id, user.handle,
                    actor_id=user.user_id, actor_bio=user.bio,
                    actor_followers=user.follower_count,
                )
                if inserted:
                    new_count += 1

            retweeters = await self._safe_call(adapter.get_retweeted_by, post.item_id)
            for user in retweeters:
                inserted = await self._store_notification(
                    "x", "repost", post.item_id, user.handle,
                    actor_id=user.user_id, actor_bio=user.bio,
                    actor_followers=user.follower_count,
                )
                if inserted:
                    new_count += 1

        for post in own_posts:
            if not post.item_id:
                continue
            comments = await self._safe_call(adapter.get_comments, post.item_id)
            for c in comments:
                author = getattr(c, "author_handle", "") or "unknown"
                comment_text = getattr(c, "text", "") or ""
                if author.lower() in ("littlenate", "little_nate", "littlenatetheog"):
                    continue
                inserted = await self._store_notification(
                    "x", "reply", post.item_id, author,
                    actor_bio=comment_text[:500],
                )
                if inserted:
                    new_count += 1

        followers = await self._safe_call(adapter.get_new_followers, limit=100)
        known_followers = await self._get_known_actors("x", "new_follower")
        for user in followers:
            if user.handle not in known_followers:
                inserted = await self._store_notification(
                    "x", "new_follower", None, user.handle,
                    actor_id=user.user_id, actor_bio=user.bio,
                    actor_followers=user.follower_count,
                )
                if inserted:
                    new_count += 1

        get_analytics_fn = getattr(adapter, "get_analytics", None)
        if get_analytics_fn:
            analytics = await self._safe_call(get_analytics_fn)
            if analytics and analytics.followers and analytics.followers > 0:
                await self._record_follower_snapshot("x", analytics.followers)

        await self._resolve_unresolved_handles("x", adapter)

        return new_count

    # ── LinkedIn Polling ─────────────────────────────────────────────

    async def _poll_linkedin(self, adapter) -> int:
        new_count = 0

        # Use stored post URNs from skyeye_session_actions instead of
        # adapter.get_own_posts() — the LinkedIn Posts API returns 403
        # without r_member_social scope, but we have all our published
        # URNs stored locally from the Post phase.
        post_urns = await self._get_linkedin_post_urns()

        for post_urn in post_urns:
            if not post_urn:
                continue

            get_reactions_fn = getattr(adapter, "get_post_reactions", None)
            if get_reactions_fn:
                reactions = await self._safe_call(get_reactions_fn, post_urn)
                for rxn in reactions:
                    actor_urn = rxn.get("actor", "")
                    if actor_urn:
                        inserted = await self._store_notification(
                            "linkedin", "reaction", post_urn, actor_urn,
                        )
                        if inserted:
                            new_count += 1

            comments = await self._safe_call(adapter.get_comments, post_urn)
            for c in comments:
                author = getattr(c, "author_handle", "") or "unknown"
                comment_text = getattr(c, "text", "") or ""
                comment_urn = getattr(c, "comment_id", "") or ""
                inserted = await self._store_notification(
                    "linkedin", "comment", post_urn, author,
                    actor_bio=comment_text[:500],
                )
                if inserted:
                    new_count += 1

        get_follower_fn = getattr(adapter, "get_follower_count", None)
        if get_follower_fn:
            current_count = await self._safe_call(get_follower_fn)
            if current_count and current_count > 0:
                await self._record_follower_snapshot("linkedin", current_count)

        return new_count

    async def _get_linkedin_post_urns(self) -> list:
        """Get recently published LinkedIn post URNs from the local DB.

        Checks both skyeye_session_actions (from session engine posts)
        and skyeye_content_queue (from queued content) to find share URNs
        that Little Nate published.  This bypasses the 403-blocked
        LinkedIn Posts API read endpoint.
        """
        urns = []
        try:
            async with self.db_pool.acquire() as conn:
                # Session actions — detail->>'post_id' has share URNs
                rows = await conn.fetch("""
                    SELECT DISTINCT detail->>'post_id' as post_urn
                    FROM skyeye_session_actions
                    WHERE platform = 'linkedin'
                      AND action_type = 'post'
                      AND detail->>'post_id' IS NOT NULL
                      AND detail->>'post_id' != ''
                      AND created_at > NOW() - INTERVAL '30 days'
                    ORDER BY post_urn
                """)
                urns.extend(r["post_urn"] for r in rows if r["post_urn"])

                # Content queue — post_id_external has the external ID
                cq_rows = await conn.fetch("""
                    SELECT DISTINCT post_id_external
                    FROM skyeye_content_queue
                    WHERE platform = 'linkedin'
                      AND status = 'posted'
                      AND post_id_external IS NOT NULL
                      AND post_id_external != ''
                      AND created_at > NOW() - INTERVAL '30 days'
                """)
                for r in cq_rows:
                    if r["post_id_external"] and r["post_id_external"] not in urns:
                        urns.append(r["post_id_external"])

        except Exception as e:
            logger.warning("NotificationObserver: LinkedIn URN lookup failed: %s", e)

        if urns:
            logger.info("NotificationObserver: found %d LinkedIn post URNs from DB", len(urns))
        return urns[:MAX_POSTS_TO_CHECK]

    # ── Instagram Polling ───────────────────────────────────────────

    async def _poll_instagram(self, adapter) -> int:
        new_count = 0

        get_follower_fn = getattr(adapter, "get_follower_count", None)
        if get_follower_fn:
            current = await self._safe_call(get_follower_fn)
            if current and current > 0:
                await self._record_follower_snapshot("instagram", current)

        own_posts = await adapter.get_own_posts(limit=MAX_POSTS_TO_CHECK)
        for post in own_posts:
            if not post.item_id:
                continue
            comments = await self._safe_call(adapter.get_comments, post.item_id)
            for c in comments:
                author = getattr(c, "author_handle", "") or getattr(c, "author_name", "unknown")
                inserted = await self._store_notification(
                    "instagram", "comment", post.item_id, author,
                )
                if inserted:
                    new_count += 1

        return new_count

    # ── Facebook Polling ──────────────────────────────────────────

    async def _poll_facebook(self, adapter) -> int:
        new_count = 0

        get_follower_fn = getattr(adapter, "get_follower_count", None)
        if get_follower_fn:
            current = await self._safe_call(get_follower_fn)
            if current and current > 0:
                await self._record_follower_snapshot("facebook", current)

        own_posts = await adapter.get_own_posts(limit=MAX_POSTS_TO_CHECK)
        for post in own_posts:
            if not post.item_id:
                continue
            get_reactions_fn = getattr(adapter, "get_post_reactions", None)
            if get_reactions_fn:
                reactions = await self._safe_call(get_reactions_fn, post.item_id)
                for rxn in reactions:
                    actor = rxn.get("actor", "") or rxn.get("actor_id", "")
                    if actor:
                        inserted = await self._store_notification(
                            "facebook", "reaction", post.item_id, actor,
                        )
                        if inserted:
                            new_count += 1

            comments = await self._safe_call(adapter.get_comments, post.item_id)
            for c in comments:
                author = getattr(c, "author_handle", "") or getattr(c, "author_name", "unknown")
                comment_text = getattr(c, "text", "") or ""
                inserted = await self._store_notification(
                    "facebook", "comment", post.item_id, author,
                    actor_bio=comment_text[:500],
                )
                if inserted:
                    new_count += 1

        return new_count

    # ── YouTube Polling ───────────────────────────────────────────

    async def _poll_youtube(self, adapter) -> int:
        new_count = 0

        get_follower_fn = getattr(adapter, "get_follower_count", None)
        if get_follower_fn:
            current = await self._safe_call(get_follower_fn)
            if current and current > 0:
                await self._record_follower_snapshot("youtube", current)

        own_posts = await adapter.get_own_posts(limit=MAX_POSTS_TO_CHECK)
        for post in own_posts:
            if not post.item_id:
                continue
            comments = await self._safe_call(adapter.get_comments, post.item_id)
            for c in comments:
                author = getattr(c, "author_handle", "") or getattr(c, "author_name", "unknown")
                inserted = await self._store_notification(
                    "youtube", "comment", post.item_id, author,
                )
                if inserted:
                    new_count += 1

        return new_count

    # ── Cycle Activity Logging ────────────────────────────────────

    async def _log_cycle_activity(self, platforms_polled: List[str], total_new: int):
        """Record each poll cycle in skyeye_activity for auditor visibility."""
        try:
            async with self.db_pool.acquire() as conn:
                await conn.execute("""
                    INSERT INTO skyeye_activity (type, platform, content, created_at)
                    VALUES ($1, $2, $3, NOW())
                """, "notification_observer_cycle",
                    ",".join(platforms_polled) if platforms_polled else "none",
                    f"polled {len(platforms_polled)} platforms, {total_new} new notifications")
        except Exception as e:
            logger.warning("NotificationObserver: cycle activity log error: %s", e)

    # ── Post Analytics Capture ───────────────────────────────────────

    async def _capture_post_analytics(self, platform: str, adapter):
        """Snapshot per-post metrics for trend tracking.

        For LinkedIn, uses DB-stored URNs since the Posts API read endpoint
        returns 403 without r_member_social scope.
        """
        try:
            if platform == "linkedin":
                # LinkedIn: use stored URNs, skip get_own_posts which returns 403
                post_urns = await self._get_linkedin_post_urns()
                if not post_urns:
                    return
                async with self.db_pool.acquire() as conn:
                    for post_urn in post_urns:
                        comments = await self._safe_call(adapter.get_comments, post_urn, limit=5)
                        comment_count = len(comments) if isinstance(comments, list) else 0
                        reactions = []
                        get_reactions_fn = getattr(adapter, "get_post_reactions", None)
                        if get_reactions_fn:
                            reactions = await self._safe_call(get_reactions_fn, post_urn)
                        like_count = len(reactions) if isinstance(reactions, list) else 0

                        await conn.execute("""
                            INSERT INTO skyeye_post_analytics
                                (platform, post_id, likes, comments,
                                 captured_at, captured_date)
                            VALUES ($1, $2, $3, $4, NOW(), CURRENT_DATE)
                            ON CONFLICT (platform, post_id, captured_date)
                            DO UPDATE SET
                                likes = EXCLUDED.likes,
                                comments = EXCLUDED.comments
                        """, "linkedin", post_urn, like_count, comment_count)
                await self._sync_platform_post_stats("linkedin")
                return

            own_posts = await adapter.get_own_posts(limit=MAX_POSTS_TO_CHECK)
            if not own_posts:
                return

            async with self.db_pool.acquire() as conn:
                for post in own_posts:
                    if not post.item_id:
                        continue
                    metrics = getattr(post, "raw_data", {}).get("public_metrics", {})
                    likes = metrics.get("like_count", 0) or getattr(post, "like_count", 0) or 0
                    reposts = metrics.get("retweet_count", 0) or getattr(post, "share_count", 0) or 0
                    comments = metrics.get("reply_count", 0) or getattr(post, "comment_count", 0) or 0
                    impressions = metrics.get("impression_count", 0) or getattr(post, "view_count", 0) or 0

                    await conn.execute("""
                        INSERT INTO skyeye_post_analytics
                            (platform, post_id, post_url, post_text,
                             likes, reposts, comments, impressions,
                             captured_at, captured_date)
                        VALUES ($1, $2, $3, $4, $5, $6, $7, $8, NOW(), CURRENT_DATE)
                        ON CONFLICT (platform, post_id, captured_date)
                        DO UPDATE SET
                            likes = EXCLUDED.likes,
                            reposts = EXCLUDED.reposts,
                            comments = EXCLUDED.comments,
                            impressions = EXCLUDED.impressions
                    """, platform, post.item_id,
                        getattr(post, "url", None),
                        (getattr(post, "text", "") or "")[:500],
                        likes, reposts, comments, impressions)
            await self._sync_platform_post_stats(platform)
        except Exception as e:
            logger.warning("NotificationObserver: post analytics capture error for %s: %s", platform, e)

    async def _sync_platform_post_stats(self, platform: str):
        """Roll up post analytics into skyeye_platforms for the Platform Grid."""
        try:
            async with self.db_pool.acquire() as conn:
                stats = await conn.fetchrow("""
                    SELECT
                        COUNT(DISTINCT post_id) as total_posts,
                        CASE WHEN SUM(impressions) > 0
                            THEN ROUND((SUM(likes) + SUM(comments) + SUM(reposts))::numeric
                                       / NULLIF(SUM(impressions), 0) * 100, 2)
                            ELSE 0
                        END as engagement_rate
                    FROM skyeye_post_analytics
                    WHERE LOWER(platform) = LOWER($1)
                      AND captured_at > NOW() - INTERVAL '30 days'
                """, platform)
                if stats:
                    await conn.execute("""
                        UPDATE skyeye_platforms
                        SET posts = COALESCE($2, posts),
                            engagement = COALESCE(NULLIF($3, 0), engagement),
                            updated_at = NOW()
                        WHERE LOWER(name) = LOWER($1)
                    """, platform, stats["total_posts"], float(stats["engagement_rate"]))
        except Exception as e:
            logger.warning("NotificationObserver: platform stats sync error for %s: %s", platform, e)

    # ── Helpers ──────────────────────────────────────────────────────

    async def _store_notification(self, platform: str, notification_type: str,
                                  post_id: Optional[str], actor_handle: str,
                                  actor_id: str = "", actor_bio: str = "",
                                  actor_followers: int = 0) -> bool:
        """Insert a notification, returns True if new (not a duplicate)."""
        try:
            async with self.db_pool.acquire() as conn:
                result = await conn.execute("""
                    INSERT INTO skyeye_notifications
                        (platform, notification_type, post_id, actor_handle,
                         actor_id, actor_bio, actor_followers, created_at)
                    VALUES ($1, $2, $3, $4, $5, $6, $7, NOW())
                    ON CONFLICT (platform, notification_type, COALESCE(post_id, ''), actor_handle)
                    DO NOTHING
                """, platform, notification_type, post_id or "",
                    actor_handle, actor_id, (actor_bio or "")[:500],
                    actor_followers)
                return "INSERT" in result
        except Exception as e:
            logger.warning("NotificationObserver: notification store error: %s", e)
            return False

    async def _get_known_actors(self, platform: str, notification_type: str) -> set:
        """Get set of already-recorded actor handles for deduplication."""
        try:
            async with self.db_pool.acquire() as conn:
                rows = await conn.fetch("""
                    SELECT DISTINCT actor_handle FROM skyeye_notifications
                    WHERE platform = $1 AND notification_type = $2
                """, platform, notification_type)
                return {r["actor_handle"] for r in rows}
        except Exception:
            return set()

    async def _record_follower_snapshot(self, platform: str, count: int):
        """Store a follower count snapshot for delta detection."""
        try:
            async with self.db_pool.acquire() as conn:
                last = await conn.fetchval("""
                    SELECT follower_count FROM skyeye_follower_snapshots
                    WHERE platform = $1
                    ORDER BY captured_at DESC LIMIT 1
                """, platform)

                await conn.execute("""
                    INSERT INTO skyeye_follower_snapshots (platform, follower_count, captured_at)
                    VALUES ($1, $2, NOW())
                """, platform, count)

                await conn.execute("""
                    UPDATE skyeye_platforms
                    SET followers = $2, updated_at = NOW()
                    WHERE LOWER(name) = LOWER($1)
                """, platform, count)

                if last is not None and count > last:
                    delta = count - last
                    logger.info(
                        f"NotificationObserver: {platform} gained {delta} "
                        f"followers ({last} -> {count})"
                    )
        except Exception as e:
            logger.warning("NotificationObserver: follower snapshot error for %s: %s", platform, e)

    async def _resolve_unresolved_handles(self, platform: str, adapter):
        """Fix skyeye_social_memory entries with numeric IDs instead of @usernames."""
        if platform != "x":
            return
        resolve_fn = getattr(adapter, "resolve_user_id", None)
        if not resolve_fn:
            return

        try:
            async with self.db_pool.acquire() as conn:
                rows = await conn.fetch("""
                    SELECT platform_handle FROM skyeye_social_memory
                    WHERE platform = 'x'
                      AND platform_handle ~ '^[0-9]+$'
                    LIMIT 10
                """)
                for row in rows:
                    numeric_id = row["platform_handle"]
                    user_info = await resolve_fn(numeric_id)
                    if user_info and user_info.handle:
                        await conn.execute("""
                            UPDATE skyeye_social_memory
                            SET platform_handle = $1
                            WHERE platform = 'x' AND platform_handle = $2
                        """, user_info.handle, numeric_id)
                        logger.debug(f"Resolved X user {numeric_id} -> @{user_info.handle}")
        except Exception as e:
            logger.warning("NotificationObserver: handle resolution error: %s", e)

    async def _get_connected_platforms(self) -> List[str]:
        """Get platforms that have valid tokens in skyeye_platform_tokens.
        Uses the token table (not skyeye_platforms) because that's where
        OAuth credentials and expiry are actually stored."""
        try:
            async with self.db_pool.acquire() as conn:
                rows = await conn.fetch("""
                    SELECT platform FROM skyeye_platform_tokens
                    WHERE access_token IS NOT NULL
                      AND access_token != ''
                      AND (token_expiry IS NULL OR token_expiry > NOW())
                      AND (error_message IS NULL OR error_message = '')
                """)
                return [r["platform"] for r in rows]
        except Exception as e:
            logger.warning("NotificationObserver: failed to query connected platforms: %s", e)
            return []

    async def _safe_call(self, fn, *args, **kwargs):
        """Call an adapter method, swallow errors, return empty result."""
        try:
            return await fn(*args, **kwargs)
        except Exception as e:
            logger.debug(f"Safe call to {fn.__name__} failed: {e}")
            return [] if "get_" in fn.__name__ else 0
