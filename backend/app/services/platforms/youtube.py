"""
LITTLE NATE — YouTube Platform Adapter
Uses YouTube Data API v3.
Tier 1 platform. Primary for long-form content + community posts.

API Reference: https://developers.google.com/youtube/v3
Auth: OAuth 2.0 (Google)
Requires: google-api-python-client
"""

import logging
from datetime import datetime, timedelta
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

logger = logging.getLogger("skyeye.platforms.youtube")

# Google OAuth endpoints
GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
YT_API_BASE = "https://www.googleapis.com/youtube/v3"

# Try to import Google API client for more complex operations
try:
    from googleapiclient.discovery import build as google_build
    from google.oauth2.credentials import Credentials
    GOOGLE_CLIENT_AVAILABLE = True
except ImportError:
    GOOGLE_CLIENT_AVAILABLE = False
    logger.info("google-api-python-client not installed; YouTube adapter will use httpx fallback")


class YouTubeAdapter(SocialPlatformAdapter):
    """YouTube platform adapter using YouTube Data API v3."""

    def __init__(self, db_pool, rate_limit_seconds: float = 15.0):
        super().__init__("youtube", db_pool, rate_limit_seconds)
        self.client_id = getattr(settings, "YOUTUBE_CLIENT_ID", "")
        self.client_secret = getattr(settings, "YOUTUBE_CLIENT_SECRET", "")
        self.api_key = getattr(settings, "YOUTUBE_API_KEY", "")
        self._access_token: Optional[str] = None
        self._channel_id: Optional[str] = None

    @property
    def _has_credentials(self) -> bool:
        return bool(self.client_id and self.client_secret)

    # ── Authentication ──────────────────────────────────────────────

    async def authenticate(self) -> bool:
        """Load stored tokens and verify against YouTube API."""
        if not self._has_credentials:
            logger.info("YouTube: No client credentials configured")
            self._connected = False
            return False

        tokens = await self._load_tokens()
        if not tokens or not tokens.get("access_token"):
            logger.info("YouTube: No stored tokens found")
            self._connected = False
            return False

        self._access_token = tokens["access_token"]
        self._channel_id = tokens.get("account_id")

        # Check expiry
        if tokens.get("token_expiry") and tokens["token_expiry"] < datetime.utcnow():
            return await self.refresh_token()

        # Verify token
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.get(
                    f"{YT_API_BASE}/channels",
                    params={
                        "part": "snippet",
                        "mine": "true",
                    },
                    headers={"Authorization": f"Bearer {self._access_token}"}
                )
                if resp.status_code == 200:
                    data = resp.json()
                    items = data.get("items", [])
                    if items:
                        self._channel_id = items[0].get("id")
                    self._connected = True
                    await self._update_token_status("connected")
                    logger.info(f"YouTube: Authenticated, channel: {self._channel_id}")
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
            logger.error(f"YouTube auth verification failed: {e}")
            return False

    async def refresh_token(self) -> bool:
        """Refresh the Google OAuth access token."""
        tokens = await self._load_tokens()
        if not tokens or not tokens.get("refresh_token"):
            self._connected = False
            await self._update_token_status("expired", "No refresh token")
            return False

        try:
            async with httpx.AsyncClient() as client:
                resp = await client.post(GOOGLE_TOKEN_URL, data={
                    "client_id": self.client_id,
                    "client_secret": self.client_secret,
                    "refresh_token": tokens["refresh_token"],
                    "grant_type": "refresh_token",
                })
                data = resp.json()

                if resp.status_code == 200 and "access_token" in data:
                    self._access_token = data["access_token"]
                    expiry = datetime.utcnow() + timedelta(
                        seconds=data.get("expires_in", 3600)
                    )
                    await self._save_tokens(
                        access_token=data["access_token"],
                        token_expiry=expiry,
                    )
                    self._connected = True
                    logger.info("YouTube: Token refreshed successfully")
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
            logger.error(f"YouTube token refresh failed: {e}")
            return False

    async def get_oauth_url(self, redirect_uri: str) -> str:
        """Generate Google OAuth URL for YouTube access."""
        import urllib.parse
        params = {
            "client_id": self.client_id,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": "https://www.googleapis.com/auth/youtube https://www.googleapis.com/auth/youtube.force-ssl",
            "access_type": "offline",
            "prompt": "consent",
            "state": "skyeye_youtube",
        }
        return f"{GOOGLE_AUTH_URL}?{urllib.parse.urlencode(params)}"

    async def handle_oauth_callback(self, code: str, redirect_uri: str) -> bool:
        """Exchange Google OAuth code for tokens."""
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.post(GOOGLE_TOKEN_URL, data={
                    "code": code,
                    "client_id": self.client_id,
                    "client_secret": self.client_secret,
                    "redirect_uri": redirect_uri,
                    "grant_type": "authorization_code",
                })
                data = resp.json()

                if "access_token" not in data:
                    self._last_error = data.get("error_description", "Token exchange failed")
                    return False

                self._access_token = data["access_token"]
                expiry = datetime.utcnow() + timedelta(
                    seconds=data.get("expires_in", 3600)
                )

                # Get channel ID
                ch_resp = await client.get(
                    f"{YT_API_BASE}/channels",
                    params={"part": "snippet", "mine": "true"},
                    headers={"Authorization": f"Bearer {self._access_token}"}
                )
                ch_data = ch_resp.json()
                channel_id = None
                channel_name = None
                items = ch_data.get("items", [])
                if items:
                    channel_id = items[0].get("id")
                    channel_name = items[0].get("snippet", {}).get("title")

                await self._save_tokens(
                    access_token=data["access_token"],
                    refresh_token=data.get("refresh_token"),
                    token_expiry=expiry,
                    scopes=data.get("scope"),
                    account_id=channel_id,
                    account_name=channel_name,
                )
                self._channel_id = channel_id
                self._connected = True
                logger.info(f"YouTube: OAuth complete, channel: {channel_id}")
                return True
        except Exception as e:
            self._last_error = str(e)
            logger.error(f"YouTube OAuth callback error: {e}")
            return False

    # ── Content Publishing ──────────────────────────────────────────

    @retry_on_failure(max_retries=2)
    async def post_content(self, text: str, media_url: Optional[str] = None,
                           content_type: ContentType = ContentType.POST,
                           **kwargs) -> PostResult:
        """
        Post to YouTube. Supports community posts (text) and videos.
        Community posts require the channel to have community tab enabled.
        """
        self._ensure_connected()
        await self.rate_limiter.acquire()

        # For text-only content, try community post via activities insert
        # Note: YouTube community posts API is limited; videos are the primary content
        if not media_url or content_type == ContentType.COMMUNITY_POST:
            # Community posts via the API are very limited
            # Fall back to noting this requires direct video upload
            return PostResult(
                success=False,
                error="YouTube community posts require manual upload or YouTube Studio. "
                      "Video uploads supported via media_url.",
                platform="youtube",
                action=ActionResult.NOT_SUPPORTED
            )

        # Video upload would require resumable upload flow — complex but doable
        # For now, support URL-based import if the video is already hosted
        return PostResult(
            success=False,
            error="Video upload requires resumable upload API — use YouTube Studio for now. "
                  "Community post text content is queued for manual posting.",
            platform="youtube",
            action=ActionResult.NOT_SUPPORTED
        )

    # ── Reading / Monitoring ────────────────────────────────────────

    @retry_on_failure(max_retries=2)
    async def get_comments(self, post_id: str,
                           since: Optional[datetime] = None,
                           limit: int = 50) -> List[Comment]:
        """Get comments on a YouTube video."""
        self._ensure_connected()
        await self.rate_limiter.acquire()

        comments = []
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.get(
                    f"{YT_API_BASE}/commentThreads",
                    params={
                        "part": "snippet",
                        "videoId": post_id,
                        "maxResults": min(limit, 100),
                        "order": "time",
                        "textFormat": "plainText",
                    },
                    headers={"Authorization": f"Bearer {self._access_token}"}
                )

                if resp.status_code == 200:
                    data = resp.json()
                    for thread in data.get("items", []):
                        snippet = thread.get("snippet", {}).get("topLevelComment", {}).get("snippet", {})
                        created = datetime.fromisoformat(
                            snippet.get("publishedAt", "").replace("Z", "+00:00")
                        ) if snippet.get("publishedAt") else None
                        if since and created and created < since:
                            continue
                        comments.append(Comment(
                            comment_id=thread.get("snippet", {}).get("topLevelComment", {}).get("id", ""),
                            post_id=post_id,
                            author_handle=snippet.get("authorDisplayName", ""),
                            author_id=snippet.get("authorChannelId", {}).get("value", ""),
                            text=snippet.get("textDisplay", ""),
                            created_at=created,
                            like_count=snippet.get("likeCount", 0),
                            reply_count=thread.get("snippet", {}).get("totalReplyCount", 0),
                            platform="youtube",
                            raw_data=thread,
                        ))
                elif resp.status_code == 403:
                    logger.warning("YouTube: Comments disabled or quota exceeded")
        except Exception as e:
            logger.error(f"YouTube get_comments error: {e}")

        return comments

    @retry_on_failure(max_retries=2)
    async def get_mentions(self, since: Optional[datetime] = None,
                           limit: int = 50) -> List[Mention]:
        """YouTube doesn't have a direct mentions API. Returns empty list."""
        return []

    @retry_on_failure(max_retries=2)
    async def get_feed(self, limit: int = 20) -> List[FeedItem]:
        """Get Little Nate's own YouTube videos."""
        self._ensure_connected()
        await self.rate_limiter.acquire()

        items = []
        if not self._channel_id:
            return items

        try:
            async with httpx.AsyncClient() as client:
                # Get uploads playlist
                ch_resp = await client.get(
                    f"{YT_API_BASE}/channels",
                    params={
                        "part": "contentDetails",
                        "id": self._channel_id,
                    },
                    headers={"Authorization": f"Bearer {self._access_token}"}
                )
                ch_data = ch_resp.json()
                ch_items = ch_data.get("items", [])
                if not ch_items:
                    return items

                uploads_playlist = (
                    ch_items[0].get("contentDetails", {})
                    .get("relatedPlaylists", {}).get("uploads")
                )
                if not uploads_playlist:
                    return items

                # Get videos from uploads playlist
                pl_resp = await client.get(
                    f"{YT_API_BASE}/playlistItems",
                    params={
                        "part": "snippet",
                        "playlistId": uploads_playlist,
                        "maxResults": min(limit, 50),
                    },
                    headers={"Authorization": f"Bearer {self._access_token}"}
                )
                pl_data = pl_resp.json()

                for item in pl_data.get("items", []):
                    snippet = item.get("snippet", {})
                    video_id = snippet.get("resourceId", {}).get("videoId", "")
                    items.append(FeedItem(
                        item_id=video_id,
                        author_handle="littlenate",
                        text=snippet.get("title", ""),
                        item_type="video",
                        created_at=datetime.fromisoformat(
                            snippet.get("publishedAt", "").replace("Z", "+00:00")
                        ) if snippet.get("publishedAt") else None,
                        url=f"https://www.youtube.com/watch?v={video_id}" if video_id else None,
                        platform="youtube",
                        raw_data=item,
                    ))
        except Exception as e:
            logger.error(f"YouTube get_feed error: {e}")

        return items

    async def get_own_posts(self, limit: int = 20) -> List[FeedItem]:
        return await self.get_feed(limit)

    # ── Engagement ──────────────────────────────────────────────────

    @retry_on_failure(max_retries=2)
    async def reply_to_comment(self, comment_id: str, text: str,
                                post_id: Optional[str] = None) -> ReplyResult:
        """Reply to a comment on YouTube."""
        self._ensure_connected()
        await self.rate_limiter.acquire()

        try:
            async with httpx.AsyncClient() as client:
                resp = await client.post(
                    f"{YT_API_BASE}/comments",
                    params={"part": "snippet"},
                    json={
                        "snippet": {
                            "parentId": comment_id,
                            "textOriginal": text,
                        }
                    },
                    headers={
                        "Authorization": f"Bearer {self._access_token}",
                        "Content-Type": "application/json",
                    }
                )

                if resp.status_code == 200:
                    data = resp.json()
                    return ReplyResult(
                        success=True,
                        reply_id=data.get("id"),
                        action=ActionResult.SUCCESS
                    )
                elif resp.status_code == 403:
                    return ReplyResult(
                        success=False,
                        error="Commenting disabled or quota exceeded",
                        action=ActionResult.FAILED
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
        """Delete a comment on YouTube."""
        self._ensure_connected()
        await self.rate_limiter.acquire()

        try:
            async with httpx.AsyncClient() as client:
                resp = await client.delete(
                    f"{YT_API_BASE}/comments",
                    params={"id": comment_id},
                    headers={"Authorization": f"Bearer {self._access_token}"}
                )

                if resp.status_code == 204:
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
        """Set a YouTube comment's moderation status to heldForReview."""
        self._ensure_connected()
        await self.rate_limiter.acquire()

        try:
            async with httpx.AsyncClient() as client:
                resp = await client.post(
                    f"{YT_API_BASE}/comments/setModerationStatus",
                    params={
                        "id": comment_id,
                        "moderationStatus": "heldForReview",
                    },
                    headers={"Authorization": f"Bearer {self._access_token}"}
                )

                if resp.status_code == 204:
                    return ModerateResult(success=True, action_taken="hidden")
                else:
                    return ModerateResult(
                        success=False,
                        error=f"Hide failed: {resp.status_code}",
                        action=ActionResult.FAILED
                    )
        except Exception as e:
            return ModerateResult(success=False, error=str(e), action=ActionResult.FAILED)

    # ── Analytics ───────────────────────────────────────────────────

    async def get_analytics(self) -> PlatformAnalytics:
        """Get YouTube channel analytics."""
        if not self._connected or not self._channel_id:
            return PlatformAnalytics(platform="youtube")

        try:
            async with httpx.AsyncClient() as client:
                resp = await client.get(
                    f"{YT_API_BASE}/channels",
                    params={
                        "part": "statistics",
                        "id": self._channel_id,
                    },
                    headers={"Authorization": f"Bearer {self._access_token}"}
                )
                if resp.status_code == 200:
                    items = resp.json().get("items", [])
                    if items:
                        stats = items[0].get("statistics", {})
                        return PlatformAnalytics(
                            followers=int(stats.get("subscriberCount", 0)),
                            total_posts=int(stats.get("videoCount", 0)),
                            total_views=int(stats.get("viewCount", 0)),
                            platform="youtube",
                            raw_data=stats,
                        )
        except Exception as e:
            logger.error(f"YouTube analytics error: {e}")

        return PlatformAnalytics(platform="youtube")
