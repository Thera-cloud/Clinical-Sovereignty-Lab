"""
LITTLE NATE — Pinterest Platform Adapter
Uses Pinterest API v5.
Tier 2 platform. Visual inspiration boards + affirmation content.

API Reference: https://developers.pinterest.com/docs/api/v5/
Auth: OAuth 2.0

Note: Pinterest has limited interaction APIs — no commenting system.
Primary use: create pins (image + text), manage boards.
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

logger = logging.getLogger("skyeye.platforms.pinterest")

PINTEREST_AUTH_URL = "https://www.pinterest.com/oauth/"
PINTEREST_TOKEN_URL = "https://api.pinterest.com/v5/oauth/token"
PINTEREST_API_BASE = "https://api.pinterest.com/v5"


class PinterestAdapter(SocialPlatformAdapter):
    """Pinterest platform adapter via Pinterest API v5."""

    def __init__(self, db_pool, rate_limit_seconds: float = 15.0):
        super().__init__("pinterest", db_pool, rate_limit_seconds)
        self.app_id = getattr(settings, "PINTEREST_APP_ID", "")
        self.app_secret = getattr(settings, "PINTEREST_APP_SECRET", "")
        self._access_token: Optional[str] = None
        self._user_id: Optional[str] = None

    @property
    def _has_credentials(self) -> bool:
        return bool(self.app_id and self.app_secret)

    # ── Authentication ──────────────────────────────────────────────

    async def authenticate(self) -> bool:
        if not self._has_credentials:
            logger.info("Pinterest: No app credentials configured")
            self._connected = False
            return False

        tokens = await self._load_tokens()
        if not tokens or not tokens.get("access_token"):
            self._connected = False
            return False

        self._access_token = tokens["access_token"]
        self._user_id = tokens.get("account_id")

        if tokens.get("token_expiry") and tokens["token_expiry"] < datetime.utcnow():
            return await self.refresh_token()

        try:
            async with httpx.AsyncClient() as client:
                resp = await client.get(
                    f"{PINTEREST_API_BASE}/user_account",
                    headers={"Authorization": f"Bearer {self._access_token}"}
                )
                if resp.status_code == 200:
                    data = resp.json()
                    self._user_id = data.get("username")
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
            return False

        try:
            import base64
            auth_header = base64.b64encode(
                f"{self.app_id}:{self.app_secret}".encode()
            ).decode()

            async with httpx.AsyncClient() as client:
                resp = await client.post(
                    PINTEREST_TOKEN_URL,
                    data={
                        "grant_type": "refresh_token",
                        "refresh_token": tokens["refresh_token"],
                    },
                    headers={
                        "Authorization": f"Basic {auth_header}",
                        "Content-Type": "application/x-www-form-urlencoded",
                    }
                )
                data = resp.json()

                if "access_token" in data:
                    self._access_token = data["access_token"]
                    expiry = datetime.utcnow() + timedelta(
                        seconds=data.get("expires_in", 2592000)  # 30 days
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
            "client_id": self.app_id,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": "boards:read,boards:write,pins:read,pins:write,user_accounts:read",
            "state": "skyeye_pinterest",
        }
        return f"{PINTEREST_AUTH_URL}?{urllib.parse.urlencode(params)}"

    async def handle_oauth_callback(self, code: str, redirect_uri: str) -> bool:
        try:
            import base64
            auth_header = base64.b64encode(
                f"{self.app_id}:{self.app_secret}".encode()
            ).decode()

            async with httpx.AsyncClient() as client:
                resp = await client.post(
                    PINTEREST_TOKEN_URL,
                    data={
                        "grant_type": "authorization_code",
                        "code": code,
                        "redirect_uri": redirect_uri,
                    },
                    headers={
                        "Authorization": f"Basic {auth_header}",
                        "Content-Type": "application/x-www-form-urlencoded",
                    }
                )
                data = resp.json()

                if "access_token" not in data:
                    self._last_error = data.get("message", "Token exchange failed")
                    return False

                self._access_token = data["access_token"]

                # Get user info
                user_resp = await client.get(
                    f"{PINTEREST_API_BASE}/user_account",
                    headers={"Authorization": f"Bearer {self._access_token}"}
                )
                user_data = user_resp.json()

                expiry = datetime.utcnow() + timedelta(
                    seconds=data.get("expires_in", 2592000)
                )
                await self._save_tokens(
                    access_token=data["access_token"],
                    refresh_token=data.get("refresh_token"),
                    token_expiry=expiry,
                    account_id=user_data.get("username"),
                    account_name=user_data.get("username"),
                )
                self._user_id = user_data.get("username")
                self._connected = True
                return True
        except Exception as e:
            self._last_error = str(e)
            return False

    # ── Content Publishing ──────────────────────────────────────────

    @retry_on_failure(max_retries=2)
    async def post_content(self, text: str, media_url: Optional[str] = None,
                           content_type: ContentType = ContentType.PIN,
                           **kwargs) -> PostResult:
        """
        Create a pin on Pinterest. Requires an image URL.

        kwargs:
            board_id: str — target board ID (required)
            title: str — pin title
            link: str — destination URL for the pin
        """
        self._ensure_connected()
        await self.rate_limiter.acquire()

        if not media_url:
            return PostResult(
                success=False,
                error="Pinterest requires an image URL for pins",
                platform="pinterest",
                action=ActionResult.NOT_SUPPORTED
            )

        board_id = kwargs.get("board_id", "")
        if not board_id:
            return PostResult(
                success=False,
                error="Pinterest requires a board_id to create a pin",
                platform="pinterest",
                action=ActionResult.FAILED
            )

        try:
            async with httpx.AsyncClient() as client:
                pin_data = {
                    "board_id": board_id,
                    "description": text,
                    "media_source": {
                        "source_type": "image_url",
                        "url": media_url,
                    }
                }

                title = kwargs.get("title", text[:100])
                if title:
                    pin_data["title"] = title

                link = kwargs.get("link")
                if link:
                    pin_data["link"] = link

                resp = await client.post(
                    f"{PINTEREST_API_BASE}/pins",
                    json=pin_data,
                    headers={
                        "Authorization": f"Bearer {self._access_token}",
                        "Content-Type": "application/json",
                    }
                )

                if resp.status_code in (200, 201):
                    data = resp.json()
                    pin_id = data.get("id", "")
                    return PostResult(
                        success=True,
                        post_id=pin_id,
                        post_url=f"https://www.pinterest.com/pin/{pin_id}/" if pin_id else None,
                        platform="pinterest",
                    )
                elif resp.status_code == 429:
                    raise PlatformRateLimitError("pinterest")
                else:
                    error = resp.json().get("message", str(resp.status_code))
                    return PostResult(success=False, error=error, platform="pinterest",
                                     action=ActionResult.FAILED)
        except (PlatformRateLimitError, PlatformAuthError):
            raise
        except Exception as e:
            return PostResult(success=False, error=str(e), platform="pinterest",
                              action=ActionResult.FAILED)

    # ── Reading / Monitoring ────────────────────────────────────────
    # Pinterest has no comment system — these return empty lists

    @retry_on_failure(max_retries=2)
    async def get_comments(self, post_id: str,
                           since: Optional[datetime] = None,
                           limit: int = 50) -> List[Comment]:
        """Pinterest does not have a comment system. Returns empty list."""
        return []

    @retry_on_failure(max_retries=2)
    async def get_mentions(self, since: Optional[datetime] = None,
                           limit: int = 50) -> List[Mention]:
        """Pinterest does not have a mentions system. Returns empty list."""
        return []

    @retry_on_failure(max_retries=2)
    async def get_feed(self, limit: int = 20) -> List[FeedItem]:
        """Get Little Nate's own pins."""
        self._ensure_connected()
        await self.rate_limiter.acquire()

        items = []
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.get(
                    f"{PINTEREST_API_BASE}/pins",
                    params={"page_size": min(limit, 50)},
                    headers={"Authorization": f"Bearer {self._access_token}"}
                )

                if resp.status_code == 200:
                    data = resp.json()
                    for pin in data.get("items", []):
                        items.append(FeedItem(
                            item_id=pin.get("id", ""),
                            author_handle="littlenate",
                            text=pin.get("description", pin.get("title", "")),
                            item_type="pin",
                            created_at=datetime.fromisoformat(
                                pin.get("created_at", "").replace("Z", "+00:00")
                            ) if pin.get("created_at") else None,
                            url=f"https://www.pinterest.com/pin/{pin.get('id', '')}/",
                            platform="pinterest",
                            raw_data=pin,
                        ))
        except Exception as e:
            logger.error(f"Pinterest get_feed error: {e}")

        return items

    async def get_own_posts(self, limit: int = 20) -> List[FeedItem]:
        return await self.get_feed(limit)

    # ── Engagement ──────────────────────────────────────────────────

    @retry_on_failure(max_retries=2)
    async def reply_to_comment(self, comment_id: str, text: str,
                                post_id: Optional[str] = None) -> ReplyResult:
        """Pinterest does not support comments/replies."""
        return ReplyResult(
            success=False,
            error="Pinterest does not support comment replies",
            action=ActionResult.NOT_SUPPORTED
        )

    # ── Moderation ──────────────────────────────────────────────────

    @retry_on_failure(max_retries=2)
    async def delete_comment(self, comment_id: str,
                              post_id: Optional[str] = None) -> ModerateResult:
        """Pinterest does not have comments to delete."""
        return ModerateResult(
            success=False,
            error="Pinterest does not support comments",
            action=ActionResult.NOT_SUPPORTED
        )

    # ── Analytics ───────────────────────────────────────────────────

    async def get_analytics(self) -> PlatformAnalytics:
        """Get Pinterest account analytics."""
        if not self._connected:
            return PlatformAnalytics(platform="pinterest")

        try:
            async with httpx.AsyncClient() as client:
                resp = await client.get(
                    f"{PINTEREST_API_BASE}/user_account",
                    headers={"Authorization": f"Bearer {self._access_token}"}
                )
                if resp.status_code == 200:
                    data = resp.json()
                    return PlatformAnalytics(
                        followers=data.get("follower_count", 0),
                        following=data.get("following_count", 0),
                        total_posts=data.get("pin_count", 0),
                        platform="pinterest",
                        raw_data=data,
                    )
        except Exception as e:
            logger.error(f"Pinterest analytics error: {e}")

        return PlatformAnalytics(platform="pinterest")
