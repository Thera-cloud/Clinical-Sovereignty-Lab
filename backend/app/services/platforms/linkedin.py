"""
LITTLE NATE — LinkedIn Platform Adapter
Uses LinkedIn Community Management API + Share API.
Tier 2 platform. Professional voice — thought leadership + articles.

API Reference: https://learn.microsoft.com/en-us/linkedin/
Auth: OAuth 2.0 (3-legged)
"""

import logging
from datetime import datetime, timedelta
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

logger = logging.getLogger("skyeye.platforms.linkedin")

LINKEDIN_AUTH_URL = "https://www.linkedin.com/oauth/v2/authorization"
LINKEDIN_TOKEN_URL = "https://www.linkedin.com/oauth/v2/accessToken"
LINKEDIN_API_BASE = "https://api.linkedin.com/v2"
LINKEDIN_REST_BASE = "https://api.linkedin.com/rest"


class LinkedInAdapter(SocialPlatformAdapter):
    """LinkedIn platform adapter."""

    def __init__(self, db_pool, rate_limit_seconds: float = 20.0):
        super().__init__("linkedin", db_pool, rate_limit_seconds)
        self.client_id = getattr(settings, "LINKEDIN_CLIENT_ID", "")
        self.client_secret = getattr(settings, "LINKEDIN_CLIENT_SECRET", "")
        self._access_token: Optional[str] = None
        self._person_urn: Optional[str] = None  # urn:li:person:XXXX

    @property
    def _has_credentials(self) -> bool:
        return bool(self.client_id and self.client_secret)

    # ── Authentication ──────────────────────────────────────────────

    async def authenticate(self) -> bool:
        if not self._has_credentials:
            logger.info("LinkedIn: No client credentials configured")
            self._connected = False
            return False

        tokens = await self._load_tokens()
        if not tokens or not tokens.get("access_token"):
            self._connected = False
            return False

        self._access_token = tokens["access_token"]
        self._person_urn = tokens.get("account_id")

        if tokens.get("token_expiry") and tokens["token_expiry"] < datetime.utcnow():
            return await self.refresh_token()

        try:
            async with httpx.AsyncClient() as client:
                resp = await client.get(
                    f"{LINKEDIN_API_BASE}/userinfo",
                    headers={"Authorization": f"Bearer {self._access_token}"}
                )
                if resp.status_code == 200:
                    data = resp.json()
                    self._person_urn = f"urn:li:person:{data.get('sub', '')}"
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
        tokens = await self._load_tokens()
        if not tokens or not tokens.get("refresh_token"):
            self._connected = False
            await self._update_token_status("expired", "No refresh token")
            return False

        try:
            async with httpx.AsyncClient() as client:
                resp = await client.post(LINKEDIN_TOKEN_URL, data={
                    "grant_type": "refresh_token",
                    "refresh_token": tokens["refresh_token"],
                    "client_id": self.client_id,
                    "client_secret": self.client_secret,
                })
                data = resp.json()

                if "access_token" in data:
                    self._access_token = data["access_token"]
                    expiry = datetime.utcnow() + timedelta(
                        seconds=data.get("expires_in", 5184000)
                    )
                    await self._save_tokens(
                        access_token=data["access_token"],
                        refresh_token=data.get("refresh_token"),
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
            "response_type": "code",
            "client_id": self.client_id,
            "redirect_uri": redirect_uri,
            "scope": "openid profile email w_member_social r_organization_social rw_organization_admin",
            "state": "skyeye_linkedin",
        }
        return f"{LINKEDIN_AUTH_URL}?{urllib.parse.urlencode(params)}"

    async def handle_oauth_callback(self, code: str, redirect_uri: str) -> bool:
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.post(LINKEDIN_TOKEN_URL, data={
                    "grant_type": "authorization_code",
                    "code": code,
                    "redirect_uri": redirect_uri,
                    "client_id": self.client_id,
                    "client_secret": self.client_secret,
                })
                data = resp.json()

                if "access_token" not in data:
                    self._last_error = data.get("error_description", "Token exchange failed")
                    return False

                self._access_token = data["access_token"]

                # Get person URN
                me_resp = await client.get(
                    f"{LINKEDIN_API_BASE}/userinfo",
                    headers={"Authorization": f"Bearer {self._access_token}"}
                )
                me_data = me_resp.json()
                person_id = me_data.get("sub", "")
                person_name = me_data.get("name", "")

                expiry = datetime.utcnow() + timedelta(
                    seconds=data.get("expires_in", 5184000)
                )
                await self._save_tokens(
                    access_token=data["access_token"],
                    refresh_token=data.get("refresh_token"),
                    token_expiry=expiry,
                    account_id=f"urn:li:person:{person_id}",
                    account_name=person_name,
                )
                self._person_urn = f"urn:li:person:{person_id}"
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
        """Post a share to LinkedIn (text or article)."""
        self._ensure_connected()
        await self.rate_limiter.acquire()

        if not self._person_urn:
            return PostResult(success=False, error="No LinkedIn person URN",
                              platform="linkedin", action=ActionResult.FAILED)

        try:
            async with httpx.AsyncClient() as client:
                share_body: Dict[str, Any] = {
                    "author": self._person_urn,
                    "lifecycleState": "PUBLISHED",
                    "specificContent": {
                        "com.linkedin.ugc.ShareContent": {
                            "shareCommentary": {"text": text},
                            "shareMediaCategory": "NONE",
                        }
                    },
                    "visibility": {
                        "com.linkedin.ugc.MemberNetworkVisibility": "PUBLIC"
                    }
                }

                # If there's a media URL, treat as article share
                if media_url:
                    share_body["specificContent"]["com.linkedin.ugc.ShareContent"]["shareMediaCategory"] = "ARTICLE"
                    share_body["specificContent"]["com.linkedin.ugc.ShareContent"]["media"] = [{
                        "status": "READY",
                        "originalUrl": media_url,
                    }]

                resp = await client.post(
                    f"{LINKEDIN_API_BASE}/ugcPosts",
                    json=share_body,
                    headers={
                        "Authorization": f"Bearer {self._access_token}",
                        "Content-Type": "application/json",
                        "X-Restli-Protocol-Version": "2.0.0",
                    }
                )

                if resp.status_code in (200, 201):
                    post_id = resp.headers.get("X-RestLi-Id", resp.headers.get("x-restli-id", ""))
                    return PostResult(
                        success=True,
                        post_id=post_id,
                        post_url=f"https://www.linkedin.com/feed/update/{post_id}/" if post_id else None,
                        platform="linkedin",
                    )
                elif resp.status_code == 429:
                    raise PlatformRateLimitError("linkedin")
                else:
                    error_data = resp.json() if resp.headers.get("content-type", "").startswith("application/json") else {}
                    return PostResult(
                        success=False,
                        error=error_data.get("message", f"Post failed: {resp.status_code}"),
                        platform="linkedin",
                        action=ActionResult.FAILED
                    )
        except (PlatformRateLimitError, PlatformAuthError):
            raise
        except Exception as e:
            return PostResult(success=False, error=str(e), platform="linkedin",
                              action=ActionResult.FAILED)

    # ── Reading / Monitoring ────────────────────────────────────────

    @retry_on_failure(max_retries=2)
    async def get_comments(self, post_id: str,
                           since: Optional[datetime] = None,
                           limit: int = 50) -> List[Comment]:
        """Get comments on a LinkedIn post (via Community Management API)."""
        self._ensure_connected()
        await self.rate_limiter.acquire()

        comments = []
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.get(
                    f"{LINKEDIN_REST_BASE}/socialActions/{post_id}/comments",
                    params={"count": min(limit, 50)},
                    headers={
                        "Authorization": f"Bearer {self._access_token}",
                        "LinkedIn-Version": "202401",
                    }
                )

                if resp.status_code == 200:
                    data = resp.json()
                    for c in data.get("elements", []):
                        comments.append(Comment(
                            comment_id=c.get("$URN", c.get("id", "")),
                            post_id=post_id,
                            author_handle=c.get("actor", ""),
                            text=c.get("message", {}).get("text", ""),
                            created_at=datetime.utcfromtimestamp(
                                c.get("created", {}).get("time", 0) / 1000
                            ) if c.get("created", {}).get("time") else None,
                            platform="linkedin",
                            raw_data=c,
                        ))
        except Exception as e:
            logger.error(f"LinkedIn get_comments error: {e}")

        return comments

    @retry_on_failure(max_retries=2)
    async def get_mentions(self, since: Optional[datetime] = None,
                           limit: int = 50) -> List[Mention]:
        """LinkedIn mentions API is limited. Returns empty list."""
        return []

    @retry_on_failure(max_retries=2)
    async def get_feed(self, limit: int = 20) -> List[FeedItem]:
        """Get own LinkedIn posts. Limited by API availability."""
        # LinkedIn's Share API doesn't easily list own posts without specific URNs
        # This would require the Posts API with appropriate permissions
        return []

    async def get_own_posts(self, limit: int = 20) -> List[FeedItem]:
        return await self.get_feed(limit)

    # ── Engagement ──────────────────────────────────────────────────

    @retry_on_failure(max_retries=2)
    async def reply_to_comment(self, comment_id: str, text: str,
                                post_id: Optional[str] = None) -> ReplyResult:
        """Reply to a LinkedIn comment."""
        self._ensure_connected()
        await self.rate_limiter.acquire()

        if not post_id:
            return ReplyResult(success=False, error="post_id required for LinkedIn replies",
                               action=ActionResult.FAILED)

        try:
            async with httpx.AsyncClient() as client:
                resp = await client.post(
                    f"{LINKEDIN_REST_BASE}/socialActions/{post_id}/comments",
                    json={
                        "actor": self._person_urn,
                        "message": {"text": text},
                        "parentComment": comment_id,
                    },
                    headers={
                        "Authorization": f"Bearer {self._access_token}",
                        "Content-Type": "application/json",
                        "LinkedIn-Version": "202401",
                    }
                )

                if resp.status_code in (200, 201):
                    return ReplyResult(success=True, action=ActionResult.SUCCESS)
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
        """Delete a LinkedIn comment (limited to own comments or page admin)."""
        self._ensure_connected()
        await self.rate_limiter.acquire()

        try:
            async with httpx.AsyncClient() as client:
                resp = await client.delete(
                    f"{LINKEDIN_REST_BASE}/socialActions/{post_id}/comments/{comment_id}",
                    headers={
                        "Authorization": f"Bearer {self._access_token}",
                        "LinkedIn-Version": "202401",
                    }
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

    # ── Analytics ───────────────────────────────────────────────────

    async def get_analytics(self) -> PlatformAnalytics:
        """LinkedIn analytics require Organization access; basic only."""
        return PlatformAnalytics(platform="linkedin")
