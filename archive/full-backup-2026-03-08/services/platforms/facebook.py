"""
LITTLE NATE — Facebook Platform Adapter
Uses Meta Graph API (Facebook Pages API).
Tier 2 platform. Shares auth flow with Instagram via Meta.

API Reference: https://developers.facebook.com/docs/pages-api/
Auth: OAuth 2.0 (Meta / Facebook Login) — shared credentials with Instagram
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
    PlatformNotConnectedError, PlatformAuthError, PlatformRateLimitError,
    retry_on_failure,
)

logger = logging.getLogger("skyeye.platforms.facebook")

META_AUTH_URL = "https://www.facebook.com/v19.0/dialog/oauth"
META_TOKEN_URL = "https://graph.facebook.com/v19.0/oauth/access_token"
GRAPH_API_BASE = "https://graph.facebook.com/v19.0"


class FacebookAdapter(SocialPlatformAdapter):
    """Facebook Pages adapter via Meta Graph API."""

    def __init__(self, db_pool, rate_limit_seconds: float = 10.0):
        super().__init__("facebook", db_pool, rate_limit_seconds)
        self.app_id = getattr(settings, "FACEBOOK_APP_ID", "")
        self.app_secret = getattr(settings, "FACEBOOK_APP_SECRET", "")
        self._access_token: Optional[str] = None  # Page access token
        self._page_id: Optional[str] = None

    @property
    def _has_credentials(self) -> bool:
        return bool(self.app_id and self.app_secret)

    # ── Authentication ──────────────────────────────────────────────

    async def authenticate(self) -> bool:
        if not self._has_credentials:
            logger.info("Facebook: No app credentials configured")
            self._connected = False
            return False

        tokens = await self._load_tokens()
        if not tokens or not tokens.get("access_token"):
            self._connected = False
            return False

        self._access_token = tokens["access_token"]
        self._page_id = tokens.get("account_id")

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
                    return True
                elif resp.status_code == 401:
                    return await self.refresh_token()
                else:
                    self._connected = False
                    return False
        except Exception as e:
            self._last_error = str(e)
            self._connected = False
            return False

    async def refresh_token(self) -> bool:
        """Facebook page tokens are long-lived by default; attempt exchange.
        fb_exchange_token requires the current token to be valid; if it's
        already dead the exchange is futile and we skip to re-auth required."""
        if not self._access_token:
            tokens = await self._load_tokens()
            self._access_token = tokens.get("access_token") if tokens else None

        if not self._access_token:
            self._connected = False
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
                    logger.warning("Facebook: Token is dead, fb_exchange_token would fail — skipping")
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

                if "access_token" in data:
                    self._access_token = data["access_token"]
                    expiry = datetime.now(timezone.utc) + timedelta(
                        seconds=data.get("expires_in", 5184000)
                    )
                    await self._save_tokens(
                        access_token=data["access_token"],
                        token_expiry=expiry,
                    )
                    self._connected = True
                    return True
                else:
                    self._connected = False
                    return False
        except Exception as e:
            self._last_error = str(e)
            self._connected = False
            return False

    async def get_oauth_url(self, redirect_uri: str) -> str:
        import urllib.parse
        params = {
            "client_id": self.app_id,
            "redirect_uri": redirect_uri,
            "scope": "pages_show_list,pages_read_engagement,pages_manage_posts,pages_manage_engagement,pages_manage_metadata",
            "response_type": "code",
            "state": "skyeye_facebook",
        }
        return f"{META_AUTH_URL}?{urllib.parse.urlencode(params)}"

    async def handle_oauth_callback(self, code: str, redirect_uri: str) -> bool:
        try:
            async with httpx.AsyncClient() as client:
                # Exchange code for user token
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

                user_token = data["access_token"]

                # Get long-lived token
                ll_resp = await client.get(
                    f"{GRAPH_API_BASE}/oauth/access_token",
                    params={
                        "grant_type": "fb_exchange_token",
                        "client_id": self.app_id,
                        "client_secret": self.app_secret,
                        "fb_exchange_token": user_token,
                    }
                )
                ll_data = ll_resp.json()
                long_token = ll_data.get("access_token", user_token)

                # Get pages and page access token
                pages_resp = await client.get(
                    f"{GRAPH_API_BASE}/me/accounts",
                    params={"access_token": long_token}
                )
                pages = pages_resp.json().get("data", [])

                if not pages:
                    self._last_error = "No Facebook pages found"
                    return False

                # Use the first page
                page = pages[0]
                page_token = page.get("access_token", long_token)
                page_id = page.get("id")
                page_name = page.get("name")

                expiry = datetime.now(timezone.utc) + timedelta(days=60)
                await self._save_tokens(
                    access_token=page_token,
                    token_expiry=expiry,
                    account_id=page_id,
                    account_name=page_name,
                )
                self._access_token = page_token
                self._page_id = page_id
                self._connected = True
                return True
        except Exception as e:
            self._last_error = str(e)
            return False

    # ── Content Publishing ──────────────────────────────────────────

    @retry_on_failure(max_retries=2)
    async def post_content(self, text: str, media_url: Optional[str] = None,
                           content_type: ContentType = ContentType.POST,
                           **kwargs) -> PostResult:
        """Post to Facebook page. Supports text and photo/link posts."""
        self._ensure_connected()
        await self.rate_limiter.acquire()

        if not self._page_id:
            return PostResult(success=False, error="No Facebook page ID",
                              platform="facebook", action=ActionResult.FAILED)

        try:
            async with httpx.AsyncClient() as client:
                if media_url:
                    # Photo post
                    resp = await client.post(
                        f"{GRAPH_API_BASE}/{self._page_id}/photos",
                        data={
                            "url": media_url,
                            "caption": text,
                            "access_token": self._access_token,
                        }
                    )
                else:
                    # Text post
                    resp = await client.post(
                        f"{GRAPH_API_BASE}/{self._page_id}/feed",
                        data={
                            "message": text,
                            "access_token": self._access_token,
                        }
                    )

                if resp.status_code == 200:
                    data = resp.json()
                    post_id = data.get("id", data.get("post_id", ""))
                    return PostResult(
                        success=True,
                        post_id=post_id,
                        post_url=f"https://www.facebook.com/{post_id}" if post_id else None,
                        platform="facebook",
                    )
                elif resp.status_code == 429:
                    raise PlatformRateLimitError("facebook")
                else:
                    error = resp.json().get("error", {}).get("message", str(resp.status_code))
                    return PostResult(success=False, error=error, platform="facebook",
                                     action=ActionResult.FAILED)
        except (PlatformRateLimitError, PlatformAuthError):
            raise
        except Exception as e:
            return PostResult(success=False, error=str(e), platform="facebook",
                              action=ActionResult.FAILED)

    # ── Reading / Monitoring ────────────────────────────────────────

    @retry_on_failure(max_retries=2)
    async def get_comments(self, post_id: str,
                           since: Optional[datetime] = None,
                           limit: int = 50) -> List[Comment]:
        """Get comments on a Facebook page post."""
        self._ensure_connected()
        await self.rate_limiter.acquire()

        comments = []
        try:
            async with httpx.AsyncClient() as client:
                params: Dict[str, Any] = {
                    "fields": "id,message,created_time,from{id,name},like_count,comment_count",
                    "limit": min(limit, 100),
                    "access_token": self._access_token,
                }
                if since:
                    params["since"] = int(since.timestamp())

                resp = await client.get(
                    f"{GRAPH_API_BASE}/{post_id}/comments",
                    params=params,
                )

                if resp.status_code == 200:
                    data = resp.json()
                    for c in data.get("data", []):
                        from_data = c.get("from", {})
                        comments.append(Comment(
                            comment_id=c.get("id", ""),
                            post_id=post_id,
                            author_handle=from_data.get("name", ""),
                            author_id=from_data.get("id", ""),
                            text=c.get("message", ""),
                            created_at=datetime.fromisoformat(
                                c.get("created_time", "").replace("+0000", "+00:00")
                            ) if c.get("created_time") else None,
                            like_count=c.get("like_count", 0),
                            reply_count=c.get("comment_count", 0),
                            platform="facebook",
                            raw_data=c,
                        ))
        except Exception as e:
            logger.error(f"Facebook get_comments error: {e}")

        return comments

    @retry_on_failure(max_retries=2)
    async def get_mentions(self, since: Optional[datetime] = None,
                           limit: int = 50) -> List[Mention]:
        """Get mentions/tags of the Facebook page."""
        self._ensure_connected()
        await self.rate_limiter.acquire()

        mentions = []
        if not self._page_id:
            return mentions

        try:
            async with httpx.AsyncClient() as client:
                resp = await client.get(
                    f"{GRAPH_API_BASE}/{self._page_id}/tagged",
                    params={
                        "fields": "id,message,created_time,from{id,name},permalink_url",
                        "limit": min(limit, 50),
                        "access_token": self._access_token,
                    }
                )

                if resp.status_code == 200:
                    for m in resp.json().get("data", []):
                        from_data = m.get("from", {})
                        mentions.append(Mention(
                            mention_id=m.get("id", ""),
                            author_handle=from_data.get("name", ""),
                            author_id=from_data.get("id", ""),
                            text=m.get("message", ""),
                            context_url=m.get("permalink_url"),
                            mention_type="tag",
                            created_at=datetime.fromisoformat(
                                m.get("created_time", "").replace("+0000", "+00:00")
                            ) if m.get("created_time") else None,
                            platform="facebook",
                            raw_data=m,
                        ))
        except Exception as e:
            logger.error(f"Facebook get_mentions error: {e}")

        return mentions

    @retry_on_failure(max_retries=2)
    async def get_feed(self, limit: int = 20) -> List[FeedItem]:
        """Get Facebook page's own posts."""
        self._ensure_connected()
        await self.rate_limiter.acquire()

        items = []
        if not self._page_id:
            return items

        try:
            async with httpx.AsyncClient() as client:
                resp = await client.get(
                    f"{GRAPH_API_BASE}/{self._page_id}/posts",
                    params={
                        "fields": "id,message,created_time,likes.summary(true),comments.summary(true),shares,permalink_url",
                        "limit": min(limit, 100),
                        "access_token": self._access_token,
                    }
                )

                if resp.status_code == 200:
                    for p in resp.json().get("data", []):
                        items.append(FeedItem(
                            item_id=p.get("id", ""),
                            author_handle="littlenate",
                            text=p.get("message", ""),
                            item_type="post",
                            like_count=p.get("likes", {}).get("summary", {}).get("total_count", 0),
                            comment_count=p.get("comments", {}).get("summary", {}).get("total_count", 0),
                            share_count=p.get("shares", {}).get("count", 0),
                            created_at=datetime.fromisoformat(
                                p.get("created_time", "").replace("+0000", "+00:00")
                            ) if p.get("created_time") else None,
                            url=p.get("permalink_url"),
                            platform="facebook",
                            raw_data=p,
                        ))
        except Exception as e:
            logger.error(f"Facebook get_feed error: {e}")

        return items

    async def get_own_posts(self, limit: int = 20) -> List[FeedItem]:
        return await self.get_feed(limit)

    # ── Engagement ──────────────────────────────────────────────────

    @retry_on_failure(max_retries=2)
    async def reply_to_comment(self, comment_id: str, text: str,
                                post_id: Optional[str] = None) -> ReplyResult:
        """Reply to a Facebook comment."""
        self._ensure_connected()
        await self.rate_limiter.acquire()

        try:
            async with httpx.AsyncClient() as client:
                resp = await client.post(
                    f"{GRAPH_API_BASE}/{comment_id}/comments",
                    data={
                        "message": text,
                        "access_token": self._access_token,
                    }
                )

                if resp.status_code == 200:
                    return ReplyResult(
                        success=True,
                        reply_id=resp.json().get("id"),
                        action=ActionResult.SUCCESS
                    )
                else:
                    return ReplyResult(
                        success=False,
                        error=f"Reply failed: {resp.status_code}",
                        action=ActionResult.FAILED
                    )
        except Exception as e:
            return ReplyResult(success=False, error=str(e), action=ActionResult.FAILED)

    # ── Moderation ──────────────────────────────────────────────────

    @retry_on_failure(max_retries=2)
    async def delete_comment(self, comment_id: str,
                              post_id: Optional[str] = None) -> ModerateResult:
        """Delete a Facebook comment."""
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
        """Hide a Facebook comment."""
        self._ensure_connected()
        await self.rate_limiter.acquire()

        try:
            async with httpx.AsyncClient() as client:
                resp = await client.post(
                    f"{GRAPH_API_BASE}/{comment_id}",
                    data={
                        "is_hidden": "true",
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
        """Get current follower/fan count for delta tracking."""
        if not self._connected:
            return 0
        target_id = self._page_id or "me"
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.get(
                    f"{GRAPH_API_BASE}/{target_id}",
                    params={
                        "fields": "followers_count,fan_count",
                        "access_token": self._access_token,
                    }
                )
                if resp.status_code == 200:
                    data = resp.json()
                    return data.get("followers_count", data.get("fan_count", 0))
        except Exception as e:
            logger.error(f"Facebook get_follower_count error: {e}")
        return 0

    @retry_on_failure(max_retries=2)
    async def get_post_reactions(self, post_id: str, limit: int = 100) -> List[Dict]:
        """Get reactions (likes, love, etc.) on a Facebook post."""
        self._ensure_connected()
        await self.rate_limiter.acquire()
        reactions: List[Dict] = []
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.get(
                    f"{GRAPH_API_BASE}/{post_id}/reactions",
                    params={
                        "limit": min(limit, 100),
                        "access_token": self._access_token,
                    }
                )
                if resp.status_code == 200:
                    for r in resp.json().get("data", []):
                        reactions.append({
                            "actor": r.get("name", ""),
                            "actor_id": r.get("id", ""),
                            "type": r.get("type", "LIKE"),
                        })
                elif resp.status_code == 401:
                    raise PlatformAuthError("facebook")
        except (PlatformAuthError, PlatformRateLimitError):
            raise
        except Exception as e:
            logger.error(f"Facebook get_post_reactions error: {e}")
        return reactions

    # ── Analytics ───────────────────────────────────────────────────

    async def get_analytics(self) -> PlatformAnalytics:
        """Get Facebook page or profile analytics."""
        if not self._connected:
            return PlatformAnalytics(platform="facebook")

        target_id = self._page_id or "me"
        analytics = PlatformAnalytics(platform="facebook")

        try:
            async with httpx.AsyncClient() as client:
                resp = await client.get(
                    f"{GRAPH_API_BASE}/{target_id}",
                    params={
                        "fields": "followers_count,fan_count,friends",
                        "access_token": self._access_token,
                    }
                )
                if resp.status_code == 200:
                    data = resp.json()
                    analytics.followers = data.get(
                        "followers_count",
                        data.get("fan_count", 0)
                    )
                    friends = data.get("friends", {})
                    if not analytics.followers and friends:
                        analytics.followers = friends.get("summary", {}).get("total_count", 0)
                    analytics.raw_data = data

                posts = await self.get_feed(limit=20)
                if posts:
                    analytics.total_posts = len(posts)
                    analytics.total_likes = sum(p.likes or 0 for p in posts)
                    analytics.total_comments = sum(p.comments or 0 for p in posts)
                    if analytics.total_posts > 0:
                        eng = (analytics.total_likes + analytics.total_comments) / analytics.total_posts
                        analytics.engagement_rate = round(eng / max(analytics.followers, 1), 4)
        except Exception as e:
            logger.error(f"Facebook analytics error: {e}")

        return analytics
