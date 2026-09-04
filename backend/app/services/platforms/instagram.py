"""
LITTLE NATE — Instagram Platform Adapter
Uses Meta Graph API (Instagram Graph API).
Tier 1 platform. Primary for visual storytelling + reels.

API Reference: https://developers.facebook.com/docs/instagram-api/
Auth: OAuth 2.0 via Facebook Login (shared with Facebook adapter)
"""

import logging
from datetime import datetime, timedelta, timezone
from typing import Dict, Any, List, Optional

import httpx
from app.config import settings
from app.services.skyeye_platform_base import (
    SocialPlatformAdapter, PostResult, Comment, Mention, UserInfo,
    FeedItem, PlatformAnalytics, ReplyResult, ModerateResult,
    ContentType, ActionResult,
    PlatformNotConnectedError, PlatformAuthError, PlatformAPIError,
    PlatformRateLimitError, retry_on_failure,
)

logger = logging.getLogger("skyeye.platforms.instagram")

META_API_VERSION = "v21.0"
META_AUTH_URL = f"https://www.facebook.com/{META_API_VERSION}/dialog/oauth"
META_TOKEN_URL = f"https://graph.facebook.com/{META_API_VERSION}/oauth/access_token"
GRAPH_API_BASE = f"https://graph.facebook.com/{META_API_VERSION}"


class InstagramAdapter(SocialPlatformAdapter):
    """Instagram platform adapter via Meta Graph API."""

    def __init__(self, db_pool, rate_limit_seconds: float = 10.0):
        super().__init__("instagram", db_pool, rate_limit_seconds)
        self.app_id = getattr(settings, "INSTAGRAM_APP_ID", "") or getattr(settings, "FACEBOOK_APP_ID", "")
        self.app_secret = getattr(settings, "INSTAGRAM_APP_SECRET", "") or getattr(settings, "FACEBOOK_APP_SECRET", "")
        self._access_token: Optional[str] = None
        self._ig_user_id: Optional[str] = None

    @property
    def _has_credentials(self) -> bool:
        return bool(self.app_id and self.app_secret)

    # ── Authentication ──────────────────────────────────────────────

    async def authenticate(self) -> bool:
        """Load stored tokens and verify against Instagram Graph API."""
        if not self._has_credentials:
            logger.info("Instagram: No app credentials configured")
            self._connected = False
            return False

        tokens = await self._load_tokens()
        if not tokens or not tokens.get("access_token"):
            logger.info("Instagram: No stored tokens found")
            self._connected = False
            return False

        self._access_token = tokens["access_token"]
        self._ig_user_id = tokens.get("account_id")

        # Verify token
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.get(
                    f"{GRAPH_API_BASE}/me",
                    params={
                        "fields": "id,name",
                        "access_token": self._access_token,
                    }
                )
                if resp.status_code == 200:
                    self._connected = True
                    await self._update_token_status("connected")
                    await self._heal_past_token_expiry()
                    logger.info("Instagram: Authenticated successfully")
                    return True
                elif resp.status_code == 401:
                    return await self.refresh_token()
                else:
                    self._last_error = f"Verify failed: {resp.status_code}"
                    self._connected = False
                    await self._update_token_status("error", self._last_error)
                    return False
        except Exception as e:
            self._last_error = str(e)
            self._connected = False
            logger.error(f"Instagram auth verification failed: {e}")
            return False

    async def refresh_token(self) -> bool:
        """Refresh the long-lived Instagram token via fb_exchange_token.
        This requires the CURRENT token to still be valid; if it's already
        dead the exchange is futile and we skip straight to re-auth required."""
        if not self._access_token:
            tokens = await self._load_tokens()
            if tokens:
                self._access_token = tokens.get("access_token")

        if not self._access_token:
            self._connected = False
            await self._update_token_status("expired", "No token to refresh")
            return False

        # fb_exchange_token requires a valid token — verify first
        try:
            async with httpx.AsyncClient(timeout=10.0) as probe:
                check = await probe.get(
                    f"{GRAPH_API_BASE}/me",
                    params={"fields": "id", "access_token": self._access_token},
                )
                if check.status_code in (400, 401, 403):
                    self._last_error = "Token invalid — full re-authorization required"
                    self._connected = False
                    await self._update_token_status("expired", self._last_error)
                    logger.warning("Instagram: Token is dead, fb_exchange_token would fail — skipping")
                    return False
        except Exception:
            pass  # network hiccup — still attempt the exchange

        try:
            async with httpx.AsyncClient() as client:
                resp = await client.get(
                    f"{GRAPH_API_BASE}/oauth/access_token",
                    params={
                        "grant_type": "fb_exchange_token",
                        "client_id": self.app_id,
                        "client_secret": self.app_secret,
                        "fb_exchange_token": self._access_token,
                    }
                )
                data = resp.json()

                if resp.status_code == 200 and "access_token" in data:
                    self._access_token = data["access_token"]
                    expiry = datetime.now(timezone.utc) + timedelta(
                        seconds=data.get("expires_in", 5184000)  # ~60 days
                    )
                    await self._save_tokens(
                        access_token=data["access_token"],
                        token_expiry=expiry,
                    )
                    self._connected = True
                    logger.info("Instagram: Token refreshed successfully")
                    return True
                else:
                    error = data.get("error", {}).get("message", "Unknown error")
                    self._last_error = f"Refresh failed: {error}"
                    self._connected = False
                    await self._update_token_status("expired", self._last_error)
                    return False
        except Exception as e:
            self._last_error = str(e)
            self._connected = False
            logger.error(f"Instagram token refresh failed: {e}")
            return False

    async def get_oauth_url(self, redirect_uri: str) -> str:
        """Generate Meta OAuth URL for Instagram access via Facebook Login for Business."""
        import urllib.parse
        params = {
            "client_id": self.app_id,
            "redirect_uri": redirect_uri,
            "config_id": "1458216979214040",
            "response_type": "code",
            "state": "skyeye_instagram",
            "override_default_response_type": "true",
        }
        return f"{META_AUTH_URL}?{urllib.parse.urlencode(params)}"

    async def handle_oauth_callback(self, code: str, redirect_uri: str) -> bool:
        """Exchange code for tokens, then get IG user ID."""
        try:
            async with httpx.AsyncClient() as client:
                # Exchange code for short-lived token
                resp = await client.get(META_TOKEN_URL, params={
                    "client_id": self.app_id,
                    "client_secret": self.app_secret,
                    "redirect_uri": redirect_uri,
                    "code": code,
                })
                data = resp.json()

                if "access_token" not in data:
                    self._last_error = data.get("error", {}).get("message", "Token exchange failed")
                    return False

                short_token = data["access_token"]

                # Exchange for long-lived token
                ll_resp = await client.get(
                    f"{GRAPH_API_BASE}/oauth/access_token",
                    params={
                        "grant_type": "fb_exchange_token",
                        "client_id": self.app_id,
                        "client_secret": self.app_secret,
                        "fb_exchange_token": short_token,
                    }
                )
                ll_data = ll_resp.json()
                access_token = ll_data.get("access_token", short_token)

                # Get Instagram Business Account ID
                pages_resp = await client.get(
                    f"{GRAPH_API_BASE}/me/accounts",
                    params={"access_token": access_token}
                )
                pages = pages_resp.json().get("data", [])

                ig_user_id = None
                page_token = access_token
                for page in pages:
                    page_id = page.get("id")
                    page_token = page.get("access_token", access_token)
                    ig_resp = await client.get(
                        f"{GRAPH_API_BASE}/{page_id}",
                        params={
                            "fields": "instagram_business_account",
                            "access_token": page_token,
                        }
                    )
                    ig_data = ig_resp.json()
                    ig_biz = ig_data.get("instagram_business_account")
                    if ig_biz:
                        ig_user_id = ig_biz.get("id")
                        break

                expiry = datetime.now(timezone.utc) + timedelta(
                    seconds=ll_data.get("expires_in", 5184000)
                )
                await self._save_tokens(
                    access_token=page_token,
                    token_expiry=expiry,
                    account_id=ig_user_id,
                    account_name="Instagram Business",
                )
                self._access_token = page_token
                self._ig_user_id = ig_user_id
                self._connected = True
                logger.info(f"Instagram: OAuth complete, IG user ID: {ig_user_id}")
                return True

        except Exception as e:
            self._last_error = str(e)
            logger.error(f"Instagram OAuth callback error: {e}")
            return False

    # ── Content Publishing ──────────────────────────────────────────

    @retry_on_failure(max_retries=2)
    async def post_content(self, text: str, media_url: Optional[str] = None,
                           content_type: ContentType = ContentType.POST,
                           **kwargs) -> PostResult:
        """
        Post to Instagram. Requires an image or video URL.
        Instagram Graph API doesn't support text-only posts.
        """
        self._ensure_connected()
        await self.rate_limiter.acquire()

        if not self._ig_user_id:
            return PostResult(
                success=False,
                error="Instagram Business Account ID not configured",
                platform="instagram",
                action=ActionResult.FAILED
            )

        if not media_url:
            return PostResult(
                success=False,
                error="Instagram requires image or video content",
                platform="instagram",
                action=ActionResult.NOT_SUPPORTED
            )

        try:
            async with httpx.AsyncClient() as client:
                # Step 1: Create media container
                container_data = {
                    "caption": text,
                    "access_token": self._access_token,
                }

                if content_type in (ContentType.REEL, ContentType.VIDEO):
                    container_data["media_type"] = "REELS"
                    container_data["video_url"] = media_url
                else:
                    container_data["image_url"] = media_url

                container_resp = await client.post(
                    f"{GRAPH_API_BASE}/{self._ig_user_id}/media",
                    data=container_data,
                )
                container = container_resp.json()

                if "id" not in container:
                    error = container.get("error", {}).get("message", "Container creation failed")
                    return PostResult(success=False, error=error, platform="instagram",
                                     action=ActionResult.FAILED)

                container_id = container["id"]

                # Step 2: Publish the container
                publish_resp = await client.post(
                    f"{GRAPH_API_BASE}/{self._ig_user_id}/media_publish",
                    data={
                        "creation_id": container_id,
                        "access_token": self._access_token,
                    }
                )
                publish = publish_resp.json()

                if "id" in publish:
                    post_id = publish["id"]
                    return PostResult(
                        success=True,
                        post_id=post_id,
                        post_url=f"https://www.instagram.com/p/{post_id}/",
                        platform="instagram",
                    )
                else:
                    error = publish.get("error", {}).get("message", "Publish failed")
                    return PostResult(success=False, error=error, platform="instagram",
                                     action=ActionResult.FAILED)

        except (PlatformRateLimitError, PlatformAuthError):
            raise
        except Exception as e:
            return PostResult(success=False, error=str(e), platform="instagram",
                              action=ActionResult.FAILED)

    # ── Reading / Monitoring ────────────────────────────────────────

    @retry_on_failure(max_retries=2)
    async def get_comments(self, post_id: str,
                           since: Optional[datetime] = None,
                           limit: int = 50) -> List[Comment]:
        """Get comments on an Instagram media post."""
        self._ensure_connected()
        await self.rate_limiter.acquire()

        comments = []
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.get(
                    f"{GRAPH_API_BASE}/{post_id}/comments",
                    params={
                        "fields": "id,text,timestamp,username,like_count,replies{id,text,timestamp,username}",
                        "limit": min(limit, 50),
                        "access_token": self._access_token,
                    }
                )

                if resp.status_code == 200:
                    data = resp.json()
                    for c in data.get("data", []):
                        created = datetime.fromisoformat(
                            c.get("timestamp", "").replace("Z", "+00:00")
                        ) if c.get("timestamp") else None
                        if since and created and created < since:
                            continue
                        comments.append(Comment(
                            comment_id=c.get("id", ""),
                            post_id=post_id,
                            author_handle=c.get("username", ""),
                            text=c.get("text", ""),
                            created_at=created,
                            like_count=c.get("like_count", 0),
                            reply_count=len(c.get("replies", {}).get("data", [])),
                            platform="instagram",
                            raw_data=c,
                        ))
        except Exception as e:
            logger.error(f"Instagram get_comments error: {e}")

        return comments

    @retry_on_failure(max_retries=2)
    async def get_mentions(self, since: Optional[datetime] = None,
                           limit: int = 50) -> List[Mention]:
        """Get mentions/tags of Little Nate on Instagram."""
        self._ensure_connected()
        await self.rate_limiter.acquire()

        mentions = []
        if not self._ig_user_id:
            return mentions

        try:
            async with httpx.AsyncClient() as client:
                resp = await client.get(
                    f"{GRAPH_API_BASE}/{self._ig_user_id}/tags",
                    params={
                        "fields": "id,caption,timestamp,username,permalink",
                        "limit": min(limit, 50),
                        "access_token": self._access_token,
                    }
                )

                if resp.status_code == 200:
                    data = resp.json()
                    for m in data.get("data", []):
                        created = datetime.fromisoformat(
                            m.get("timestamp", "").replace("Z", "+00:00")
                        ) if m.get("timestamp") else None
                        if since and created and created < since:
                            continue
                        mentions.append(Mention(
                            mention_id=m.get("id", ""),
                            author_handle=m.get("username", ""),
                            text=m.get("caption", ""),
                            context_url=m.get("permalink"),
                            mention_type="tag",
                            created_at=created,
                            platform="instagram",
                            raw_data=m,
                        ))
        except Exception as e:
            logger.error(f"Instagram get_mentions error: {e}")

        return mentions

    @retry_on_failure(max_retries=2)
    async def get_feed(self, limit: int = 20) -> List[FeedItem]:
        """Get Little Nate's own Instagram media."""
        self._ensure_connected()
        await self.rate_limiter.acquire()

        items = []
        if not self._ig_user_id:
            return items

        try:
            async with httpx.AsyncClient() as client:
                resp = await client.get(
                    f"{GRAPH_API_BASE}/{self._ig_user_id}/media",
                    params={
                        "fields": "id,caption,media_type,timestamp,like_count,comments_count,permalink",
                        "limit": min(limit, 50),
                        "access_token": self._access_token,
                    }
                )

                if resp.status_code == 200:
                    data = resp.json()
                    for m in data.get("data", []):
                        items.append(FeedItem(
                            item_id=m.get("id", ""),
                            author_handle="littlenate",
                            text=m.get("caption", ""),
                            item_type=m.get("media_type", "IMAGE").lower(),
                            like_count=m.get("like_count", 0),
                            comment_count=m.get("comments_count", 0),
                            created_at=datetime.fromisoformat(
                                m.get("timestamp", "").replace("Z", "+00:00")
                            ) if m.get("timestamp") else None,
                            url=m.get("permalink"),
                            platform="instagram",
                            raw_data=m,
                        ))
        except Exception as e:
            logger.error(f"Instagram get_feed error: {e}")

        return items

    async def get_own_posts(self, limit: int = 20) -> List[FeedItem]:
        return await self.get_feed(limit)

    # ── Engagement ──────────────────────────────────────────────────

    @retry_on_failure(max_retries=2)
    async def reply_to_comment(self, comment_id: str, text: str,
                                post_id: Optional[str] = None) -> ReplyResult:
        """Reply to a comment on Instagram."""
        self._ensure_connected()
        await self.rate_limiter.acquire()

        target_id = post_id or comment_id
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.post(
                    f"{GRAPH_API_BASE}/{target_id}/replies",
                    data={
                        "message": text,
                        "access_token": self._access_token,
                    }
                )

                if resp.status_code == 200:
                    data = resp.json()
                    return ReplyResult(
                        success=True,
                        reply_id=data.get("id"),
                        action=ActionResult.SUCCESS
                    )
                else:
                    error = resp.json().get("error", {}).get("message", str(resp.status_code))
                    return ReplyResult(success=False, error=error, action=ActionResult.FAILED)
        except Exception as e:
            return ReplyResult(success=False, error=str(e), action=ActionResult.FAILED)

    # ── Moderation ──────────────────────────────────────────────────

    @retry_on_failure(max_retries=2)
    async def delete_comment(self, comment_id: str,
                              post_id: Optional[str] = None) -> ModerateResult:
        """Delete a comment on Instagram."""
        self._ensure_connected()
        await self.rate_limiter.acquire()

        try:
            async with httpx.AsyncClient() as client:
                resp = await client.delete(
                    f"{GRAPH_API_BASE}/{comment_id}",
                    params={"access_token": self._access_token}
                )

                if resp.status_code == 200:
                    return ModerateResult(success=True, action_taken="deleted")
                else:
                    return ModerateResult(
                        success=False,
                        error=f"Delete failed: {resp.status_code}",
                        action=ActionResult.FAILED
                    )
        except Exception as e:
            return ModerateResult(success=False, error=str(e), action=ActionResult.FAILED)

    async def hide_comment(self, comment_id: str,
                           post_id: Optional[str] = None) -> ModerateResult:
        """Hide a comment on Instagram (set hidden=true)."""
        self._ensure_connected()
        await self.rate_limiter.acquire()

        try:
            async with httpx.AsyncClient() as client:
                resp = await client.post(
                    f"{GRAPH_API_BASE}/{comment_id}",
                    data={
                        "hide": "true",
                        "access_token": self._access_token,
                    }
                )

                if resp.status_code == 200:
                    return ModerateResult(success=True, action_taken="hidden")
                else:
                    return ModerateResult(
                        success=False,
                        error=f"Hide failed: {resp.status_code}",
                        action=ActionResult.FAILED
                    )
        except Exception as e:
            return ModerateResult(success=False, error=str(e), action=ActionResult.FAILED)

    # ── Notification / Engagement Discovery ────────────────────────

    async def get_follower_count(self) -> int:
        """Get current follower count for delta tracking."""
        if not self._connected or not self._ig_user_id:
            return 0
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.get(
                    f"{GRAPH_API_BASE}/{self._ig_user_id}",
                    params={
                        "fields": "followers_count",
                        "access_token": self._access_token,
                    }
                )
                if resp.status_code == 200:
                    return resp.json().get("followers_count", 0)
        except Exception as e:
            logger.error(f"Instagram get_follower_count error: {e}")
        return 0

    # ── Analytics ───────────────────────────────────────────────────

    async def get_analytics(self) -> PlatformAnalytics:
        """Get Instagram account analytics."""
        if not self._connected or not self._ig_user_id:
            return PlatformAnalytics(platform="instagram")

        try:
            async with httpx.AsyncClient() as client:
                resp = await client.get(
                    f"{GRAPH_API_BASE}/{self._ig_user_id}",
                    params={
                        "fields": "followers_count,follows_count,media_count",
                        "access_token": self._access_token,
                    }
                )
                if resp.status_code == 200:
                    data = resp.json()
                    return PlatformAnalytics(
                        followers=data.get("followers_count", 0),
                        following=data.get("follows_count", 0),
                        total_posts=data.get("media_count", 0),
                        platform="instagram",
                        raw_data=data,
                    )
        except Exception as e:
            logger.error(f"Instagram analytics error: {e}")

        return PlatformAnalytics(platform="instagram")
