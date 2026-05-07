"""
LITTLE NATE — TikTok Platform Adapter
Uses TikTok Content Posting API + TikTok API for Business.
Tier 1 platform. Primary for short-form video + casual voice.

API Reference: https://developers.tiktok.com/doc/content-posting-api-overview
Auth: OAuth 2.0 (Authorization Code Flow)
"""

import logging
from datetime import datetime, timedelta, timezone
from typing import Dict, Any, List, Optional

import httpx
from app.config import settings
from app.services.skyeye_platform_base import (
    SocialPlatformAdapter, PostResult, Comment, Mention, UserInfo,
    FeedItem, TrendingTopic, PlatformAnalytics, ReplyResult, ModerateResult,
    ContentType, ActionResult,
    PlatformNotConnectedError, PlatformAuthError, PlatformAPIError,
    PlatformRateLimitError, retry_on_failure,
)

logger = logging.getLogger("skyeye.platforms.tiktok")

TIKTOK_AUTH_URL = "https://www.tiktok.com/v2/auth/authorize/"
TIKTOK_TOKEN_URL = "https://open.tiktokapis.com/v2/oauth/token/"
TIKTOK_API_BASE = "https://open.tiktokapis.com/v2"


class TikTokAdapter(SocialPlatformAdapter):
    """TikTok platform adapter using the TikTok API for Business."""

    def __init__(self, db_pool, rate_limit_seconds: float = 10.0):
        super().__init__("tiktok", db_pool, rate_limit_seconds)
        self.client_key = getattr(settings, "TIKTOK_CLIENT_KEY", "")
        self.client_secret = getattr(settings, "TIKTOK_CLIENT_SECRET", "")
        self._access_token: Optional[str] = None
        self._open_id: Optional[str] = None

    @property
    def _has_credentials(self) -> bool:
        return bool(self.client_key and self.client_secret)

    # ── Authentication ──────────────────────────────────────────────

    async def authenticate(self) -> bool:
        """Load stored tokens and verify they work."""
        if not self._has_credentials:
            logger.info("TikTok: No client credentials configured")
            self._connected = False
            return False

        tokens = await self._load_tokens()
        if not tokens or not tokens.get("access_token"):
            logger.info("TikTok: No stored tokens found")
            self._connected = False
            return False

        self._access_token = tokens["access_token"]
        self._open_id = tokens.get("account_id")

        # Check if token is expired (compare aware UTC — PG returns tz-aware timestamps)
        exp = tokens.get("token_expiry")
        now_utc = datetime.now(timezone.utc)
        if exp:
            if getattr(exp, "tzinfo", None) is None:
                exp = exp.replace(tzinfo=timezone.utc)
            if exp < now_utc:
                logger.info("TikTok: Token expired, attempting refresh")
                if await self.refresh_token():
                    return True
                logger.warning(
                    "TikTok: Refresh failed — verifying access token anyway "
                    "(token_expiry in DB may be stale)"
                )

        # Verify token by calling user info
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.get(
                    f"{TIKTOK_API_BASE}/user/info/",
                    headers={"Authorization": f"Bearer {self._access_token}"},
                    params={"fields": "open_id,display_name,avatar_url,follower_count"}
                )
                if resp.status_code == 200:
                    self._connected = True
                    await self._update_token_status("connected")
                    logger.info("TikTok: Authenticated successfully")
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
            logger.error(f"TikTok auth verification failed: {e}")
            return False

    async def refresh_token(self) -> bool:
        """Refresh the TikTok access token."""
        tokens = await self._load_tokens()
        if not tokens or not tokens.get("refresh_token"):
            self._connected = False
            await self._update_token_status("expired", "No refresh token available")
            return False

        try:
            async with httpx.AsyncClient() as client:
                resp = await client.post(TIKTOK_TOKEN_URL, data={
                    "client_key": self.client_key,
                    "client_secret": self.client_secret,
                    "grant_type": "refresh_token",
                    "refresh_token": tokens["refresh_token"],
                })
                data = resp.json()

                if resp.status_code == 200 and "access_token" in data:
                    self._access_token = data["access_token"]
                    self._open_id = data.get("open_id", self._open_id)
                    expiry = datetime.now(timezone.utc) + timedelta(
                        seconds=data.get("expires_in", 86400)
                    )
                    await self._save_tokens(
                        access_token=data["access_token"],
                        refresh_token=data.get("refresh_token"),
                        token_expiry=expiry,
                        scopes=data.get("scope"),
                        account_id=self._open_id,
                    )
                    self._connected = True
                    logger.info("TikTok: Token refreshed successfully")
                    return True
                else:
                    error = data.get("error_description", "Unknown error")
                    self._last_error = f"Refresh failed: {error}"
                    self._connected = False
                    await self._update_token_status("expired", self._last_error)
                    return False
        except Exception as e:
            self._last_error = str(e)
            self._connected = False
            logger.error(f"TikTok token refresh failed: {e}")
            return False

    async def get_oauth_url(self, redirect_uri: str) -> str:
        """Generate TikTok OAuth authorization URL."""
        import urllib.parse
        params = {
            "client_key": self.client_key,
            "response_type": "code",
            "scope": "user.info.basic,video.publish,video.list,comment.list,comment.list.manage",
            "redirect_uri": redirect_uri,
            "state": "skyeye_tiktok",
        }
        return f"{TIKTOK_AUTH_URL}?{urllib.parse.urlencode(params)}"

    async def handle_oauth_callback(self, code: str, redirect_uri: str) -> bool:
        """Exchange authorization code for tokens."""
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.post(TIKTOK_TOKEN_URL, data={
                    "client_key": self.client_key,
                    "client_secret": self.client_secret,
                    "code": code,
                    "grant_type": "authorization_code",
                    "redirect_uri": redirect_uri,
                })
                data = resp.json()

                if resp.status_code == 200 and "access_token" in data:
                    expiry = datetime.now(timezone.utc) + timedelta(
                        seconds=data.get("expires_in", 86400)
                    )
                    await self._save_tokens(
                        access_token=data["access_token"],
                        refresh_token=data.get("refresh_token"),
                        token_expiry=expiry,
                        scopes=data.get("scope"),
                        account_id=data.get("open_id"),
                    )
                    self._access_token = data["access_token"]
                    self._open_id = data.get("open_id")
                    self._connected = True
                    logger.info("TikTok: OAuth callback processed successfully")
                    return True
                else:
                    error = data.get("error_description", "Token exchange failed")
                    self._last_error = error
                    logger.error(f"TikTok OAuth callback failed: {error}")
                    return False
        except Exception as e:
            self._last_error = str(e)
            logger.error(f"TikTok OAuth callback error: {e}")
            return False

    # ── Content Publishing ──────────────────────────────────────────

    @retry_on_failure(max_retries=2)
    async def post_content(self, text: str, media_url: Optional[str] = None,
                           content_type: ContentType = ContentType.POST,
                           **kwargs) -> PostResult:
        """
        Post content to TikTok.

        TikTok's Content Posting API requires video — text-only posts
        are not natively supported. For text posts, we'll use the
        photo/slideshow mode if available, or return a helpful error.
        """
        self._ensure_connected()
        await self.rate_limiter.acquire()

        # TikTok primarily supports video content
        if not media_url:
            return PostResult(
                success=False,
                error="TikTok requires video/photo content. Text-only posts are not supported.",
                platform="tiktok",
                action=ActionResult.NOT_SUPPORTED
            )

        try:
            async with httpx.AsyncClient() as client:
                # Step 1: Initialize upload
                init_resp = await client.post(
                    f"{TIKTOK_API_BASE}/post/publish/inbox/video/init/",
                    headers={
                        "Authorization": f"Bearer {self._access_token}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "post_info": {
                            "title": text[:150],  # TikTok title limit
                            "privacy_level": "PUBLIC_TO_EVERYONE",
                            "disable_duet": False,
                            "disable_comment": False,
                            "disable_stitch": False,
                        },
                        "source_info": {
                            "source": "PULL_FROM_URL",
                            "video_url": media_url,
                        }
                    }
                )

                if init_resp.status_code == 200:
                    data = init_resp.json()
                    publish_id = data.get("data", {}).get("publish_id", "")
                    return PostResult(
                        success=True,
                        post_id=publish_id,
                        platform="tiktok",
                    )
                elif init_resp.status_code == 429:
                    raise PlatformRateLimitError("tiktok")
                elif init_resp.status_code == 401:
                    raise PlatformAuthError("tiktok", "Token expired during post")
                else:
                    error_data = init_resp.json()
                    error_msg = error_data.get("error", {}).get("message", str(init_resp.status_code))
                    return PostResult(
                        success=False,
                        error=error_msg,
                        platform="tiktok",
                        action=ActionResult.FAILED
                    )
        except (PlatformRateLimitError, PlatformAuthError):
            raise
        except Exception as e:
            return PostResult(
                success=False,
                error=str(e),
                platform="tiktok",
                action=ActionResult.FAILED
            )

    # ── Reading / Monitoring ────────────────────────────────────────

    @retry_on_failure(max_retries=2)
    async def get_comments(self, post_id: str,
                           since: Optional[datetime] = None,
                           limit: int = 50) -> List[Comment]:
        """Get comments on a TikTok video."""
        self._ensure_connected()
        await self.rate_limiter.acquire()

        comments = []
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.post(
                    f"{TIKTOK_API_BASE}/comment/list/",
                    headers={
                        "Authorization": f"Bearer {self._access_token}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "video_id": post_id,
                        "max_count": min(limit, 100),
                    }
                )

                if resp.status_code == 200:
                    data = resp.json()
                    for c in data.get("data", {}).get("comments", []):
                        created = datetime.utcfromtimestamp(c.get("create_time", 0))
                        if since and created < since:
                            continue
                        comments.append(Comment(
                            comment_id=str(c.get("id", "")),
                            post_id=post_id,
                            author_handle=c.get("user", {}).get("unique_id", ""),
                            author_name=c.get("user", {}).get("nickname", ""),
                            text=c.get("text", ""),
                            created_at=created,
                            like_count=c.get("likes", 0),
                            platform="tiktok",
                            raw_data=c,
                        ))
                elif resp.status_code == 429:
                    raise PlatformRateLimitError("tiktok")
                elif resp.status_code == 401:
                    raise PlatformAuthError("tiktok", "Token expired")
        except (PlatformRateLimitError, PlatformAuthError):
            raise
        except Exception as e:
            logger.error(f"TikTok get_comments error: {e}")

        return comments

    @retry_on_failure(max_retries=2)
    async def get_mentions(self, since: Optional[datetime] = None,
                           limit: int = 50) -> List[Mention]:
        """
        TikTok does not have a native mentions API in the current
        Content Posting API scope. Returns empty list.
        Mentions would need to be discovered through comment scanning.
        """
        return []

    @retry_on_failure(max_retries=2)
    async def get_feed(self, limit: int = 20) -> List[FeedItem]:
        """
        Get Little Nate's own video list (TikTok doesn't expose other users'
        feeds through the API — only your own content).
        """
        self._ensure_connected()
        await self.rate_limiter.acquire()

        items = []
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.post(
                    f"{TIKTOK_API_BASE}/video/list/",
                    headers={
                        "Authorization": f"Bearer {self._access_token}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "max_count": min(limit, 20),
                        "fields": "id,title,create_time,like_count,comment_count,share_count,view_count,video_description"
                    }
                )

                if resp.status_code == 200:
                    data = resp.json()
                    for v in data.get("data", {}).get("videos", []):
                        items.append(FeedItem(
                            item_id=str(v.get("id", "")),
                            author_handle="littlenate",
                            text=v.get("video_description", v.get("title", "")),
                            item_type="video",
                            like_count=v.get("like_count", 0),
                            comment_count=v.get("comment_count", 0),
                            share_count=v.get("share_count", 0),
                            view_count=v.get("view_count", 0),
                            created_at=datetime.utcfromtimestamp(v.get("create_time", 0)),
                            platform="tiktok",
                            raw_data=v,
                        ))
        except Exception as e:
            logger.error(f"TikTok get_feed error: {e}")

        return items

    async def get_own_posts(self, limit: int = 20) -> List[FeedItem]:
        """Alias for get_feed on TikTok (same API)."""
        return await self.get_feed(limit)

    # ── Engagement ──────────────────────────────────────────────────

    @retry_on_failure(max_retries=2)
    async def reply_to_comment(self, comment_id: str, text: str,
                                post_id: Optional[str] = None) -> ReplyResult:
        """
        Reply to a comment on TikTok.
        Note: TikTok's comment reply API is limited.
        """
        self._ensure_connected()
        await self.rate_limiter.acquire()

        try:
            async with httpx.AsyncClient() as client:
                resp = await client.post(
                    f"{TIKTOK_API_BASE}/comment/reply/",
                    headers={
                        "Authorization": f"Bearer {self._access_token}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "video_id": post_id or "",
                        "comment_id": comment_id,
                        "text": text[:150],  # TikTok comment length limit
                    }
                )

                if resp.status_code == 200:
                    return ReplyResult(success=True, action=ActionResult.SUCCESS)
                elif resp.status_code == 429:
                    raise PlatformRateLimitError("tiktok")
                else:
                    return ReplyResult(
                        success=False,
                        error=f"Reply failed: {resp.status_code}",
                        action=ActionResult.FAILED
                    )
        except (PlatformRateLimitError, PlatformAuthError):
            raise
        except Exception as e:
            return ReplyResult(success=False, error=str(e), action=ActionResult.FAILED)

    # ── Moderation ──────────────────────────────────────────────────

    @retry_on_failure(max_retries=2)
    async def delete_comment(self, comment_id: str,
                              post_id: Optional[str] = None) -> ModerateResult:
        """Delete a comment on a TikTok video."""
        self._ensure_connected()
        await self.rate_limiter.acquire()

        try:
            async with httpx.AsyncClient() as client:
                resp = await client.post(
                    f"{TIKTOK_API_BASE}/comment/delete/",
                    headers={
                        "Authorization": f"Bearer {self._access_token}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "video_id": post_id or "",
                        "comment_id": comment_id,
                    }
                )

                if resp.status_code == 200:
                    return ModerateResult(
                        success=True,
                        action_taken="deleted",
                        action=ActionResult.SUCCESS
                    )
                else:
                    return ModerateResult(
                        success=False,
                        error=f"Delete failed: {resp.status_code}",
                        action=ActionResult.FAILED
                    )
        except Exception as e:
            return ModerateResult(success=False, error=str(e), action=ActionResult.FAILED)

    # ── Analytics ───────────────────────────────────────────────────

    async def get_analytics(self) -> PlatformAnalytics:
        """Get TikTok account analytics (basic from user info)."""
        if not self._connected:
            return PlatformAnalytics(platform="tiktok")

        try:
            async with httpx.AsyncClient() as client:
                resp = await client.get(
                    f"{TIKTOK_API_BASE}/user/info/",
                    headers={"Authorization": f"Bearer {self._access_token}"},
                    params={
                        "fields": "follower_count,following_count,likes_count,video_count"
                    }
                )
                if resp.status_code == 200:
                    user = resp.json().get("data", {}).get("user", {})
                    return PlatformAnalytics(
                        followers=user.get("follower_count", 0),
                        following=user.get("following_count", 0),
                        total_posts=user.get("video_count", 0),
                        total_likes=user.get("likes_count", 0),
                        platform="tiktok",
                        raw_data=user,
                    )
        except Exception as e:
            logger.error(f"TikTok analytics error: {e}")

        return PlatformAnalytics(platform="tiktok")
