"""
LITTLE NATE — Reddit Platform Adapter
Uses Reddit API via asyncpraw (async PRAW) or httpx fallback.
Tier 1 platform. Primary for long-form discussion + community building.

API Reference: https://www.reddit.com/dev/api/
Auth: OAuth 2.0 (Script or Web App)
Optional dependency: asyncpraw
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

logger = logging.getLogger("skyeye.platforms.reddit")

REDDIT_AUTH_URL = "https://www.reddit.com/api/v1/authorize"
REDDIT_TOKEN_URL = "https://www.reddit.com/api/v1/access_token"
REDDIT_API_BASE = "https://oauth.reddit.com"

# Try async PRAW
try:
    import asyncpraw
    ASYNCPRAW_AVAILABLE = True
except ImportError:
    ASYNCPRAW_AVAILABLE = False
    logger.info("asyncpraw not installed; Reddit adapter will use httpx")


class RedditAdapter(SocialPlatformAdapter):
    """Reddit platform adapter."""

    def __init__(self, db_pool, rate_limit_seconds: float = 8.0):
        super().__init__("reddit", db_pool, rate_limit_seconds)
        self.client_id = getattr(settings, "REDDIT_CLIENT_ID", "")
        self.client_secret = getattr(settings, "REDDIT_CLIENT_SECRET", "")
        self.username = getattr(settings, "REDDIT_USERNAME", "")
        self.password = getattr(settings, "REDDIT_PASSWORD", "")
        self._access_token: Optional[str] = None
        self._reddit_user: Optional[str] = None
        self._praw_reddit = None

    @property
    def _has_credentials(self) -> bool:
        return bool(self.client_id and self.client_secret)

    # ── Authentication ──────────────────────────────────────────────

    async def authenticate(self) -> bool:
        """Authenticate with Reddit using script auth or stored tokens."""
        if not self._has_credentials:
            logger.info("Reddit: No client credentials configured")
            self._connected = False
            return False

        # Try script-level auth if username/password provided
        if self.username and self.password:
            return await self._script_auth()

        # Try stored tokens
        tokens = await self._load_tokens()
        if not tokens or not tokens.get("access_token"):
            logger.info("Reddit: No stored tokens found")
            self._connected = False
            return False

        self._access_token = tokens["access_token"]
        self._reddit_user = tokens.get("account_name")

        # Verify
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.get(
                    f"{REDDIT_API_BASE}/api/v1/me",
                    headers={
                        "Authorization": f"Bearer {self._access_token}",
                        "User-Agent": "LittleNate/1.0 (Sovereign Sanctuary)",
                    }
                )
                if resp.status_code == 200:
                    data = resp.json()
                    self._reddit_user = data.get("name")
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

    async def _script_auth(self) -> bool:
        """Authenticate using Reddit script-type application (username/password)."""
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.post(
                    REDDIT_TOKEN_URL,
                    data={
                        "grant_type": "password",
                        "username": self.username,
                        "password": self.password,
                    },
                    auth=(self.client_id, self.client_secret),
                    headers={"User-Agent": "LittleNate/1.0 (Sovereign Sanctuary)"},
                )
                data = resp.json()

                if "access_token" in data:
                    self._access_token = data["access_token"]
                    expiry = datetime.utcnow() + timedelta(
                        seconds=data.get("expires_in", 3600)
                    )
                    await self._save_tokens(
                        access_token=data["access_token"],
                        refresh_token=data.get("refresh_token"),
                        token_expiry=expiry,
                        scopes=data.get("scope"),
                        account_name=self.username,
                    )
                    self._reddit_user = self.username
                    self._connected = True
                    logger.info(f"Reddit: Script auth successful as {self.username}")
                    return True
                else:
                    self._last_error = data.get("error", "Auth failed")
                    self._connected = False
                    return False
        except Exception as e:
            self._last_error = str(e)
            self._connected = False
            logger.error(f"Reddit script auth failed: {e}")
            return False

    async def refresh_token(self) -> bool:
        """Refresh Reddit OAuth token."""
        tokens = await self._load_tokens()
        if not tokens or not tokens.get("refresh_token"):
            # Try script auth as fallback
            if self.username and self.password:
                return await self._script_auth()
            self._connected = False
            return False

        try:
            async with httpx.AsyncClient() as client:
                resp = await client.post(
                    REDDIT_TOKEN_URL,
                    data={
                        "grant_type": "refresh_token",
                        "refresh_token": tokens["refresh_token"],
                    },
                    auth=(self.client_id, self.client_secret),
                    headers={"User-Agent": "LittleNate/1.0 (Sovereign Sanctuary)"},
                )
                data = resp.json()

                if "access_token" in data:
                    self._access_token = data["access_token"]
                    expiry = datetime.utcnow() + timedelta(
                        seconds=data.get("expires_in", 3600)
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
        """Generate Reddit OAuth URL."""
        import urllib.parse
        params = {
            "client_id": self.client_id,
            "response_type": "code",
            "state": "skyeye_reddit",
            "redirect_uri": redirect_uri,
            "duration": "permanent",
            # FIX-REDDIT-SCOPE-ALIGN: dropped modflair/modposts/history/mysubreddits per scope trace; edit+flair retained (uncertain)
            "scope": "identity,submit,read,privatemessages,edit,flair",
        }
        return f"{REDDIT_AUTH_URL}?{urllib.parse.urlencode(params)}"

    async def handle_oauth_callback(self, code: str, redirect_uri: str) -> bool:
        """Exchange Reddit OAuth code for tokens."""
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.post(
                    REDDIT_TOKEN_URL,
                    data={
                        "grant_type": "authorization_code",
                        "code": code,
                        "redirect_uri": redirect_uri,
                    },
                    auth=(self.client_id, self.client_secret),
                    headers={"User-Agent": "LittleNate/1.0 (Sovereign Sanctuary)"},
                )
                data = resp.json()

                if "access_token" in data:
                    self._access_token = data["access_token"]
                    expiry = datetime.utcnow() + timedelta(
                        seconds=data.get("expires_in", 3600)
                    )

                    # Get username
                    me_resp = await client.get(
                        f"{REDDIT_API_BASE}/api/v1/me",
                        headers={
                            "Authorization": f"Bearer {self._access_token}",
                            "User-Agent": "LittleNate/1.0 (Sovereign Sanctuary)",
                        }
                    )
                    username = me_resp.json().get("name", "")

                    await self._save_tokens(
                        access_token=data["access_token"],
                        refresh_token=data.get("refresh_token"),
                        token_expiry=expiry,
                        scopes=data.get("scope"),
                        account_name=username,
                    )
                    self._reddit_user = username
                    self._connected = True
                    return True
                else:
                    self._last_error = data.get("error", "Token exchange failed")
                    return False
        except Exception as e:
            self._last_error = str(e)
            return False

    # ── Content Publishing ──────────────────────────────────────────

    @retry_on_failure(max_retries=2)
    async def post_content(self, text: str, media_url: Optional[str] = None,
                           content_type: ContentType = ContentType.POST,
                           **kwargs) -> PostResult:
        """
        Post to Reddit. Requires subreddit in kwargs.

        kwargs:
            subreddit: str — target subreddit (required)
            title: str — post title (required for link/self posts)
            flair_id: str — optional flair
        """
        self._ensure_connected()
        await self.rate_limiter.acquire()

        subreddit = kwargs.get("subreddit", "")
        title = kwargs.get("title", text[:300])

        if not subreddit:
            return PostResult(
                success=False,
                error="Reddit requires a subreddit target",
                platform="reddit",
                action=ActionResult.FAILED
            )

        try:
            async with httpx.AsyncClient() as client:
                post_data = {
                    "sr": subreddit,
                    "title": title,
                    "kind": "self",
                    "text": text,
                    "api_type": "json",
                }

                if media_url:
                    post_data["kind"] = "link"
                    post_data["url"] = media_url
                    del post_data["text"]

                if kwargs.get("flair_id"):
                    post_data["flair_id"] = kwargs["flair_id"]

                resp = await client.post(
                    f"{REDDIT_API_BASE}/api/submit",
                    data=post_data,
                    headers={
                        "Authorization": f"Bearer {self._access_token}",
                        "User-Agent": "LittleNate/1.0 (Sovereign Sanctuary)",
                    }
                )

                if resp.status_code == 200:
                    data = resp.json()
                    json_data = data.get("json", {}).get("data", {})
                    post_url = json_data.get("url", "")
                    post_id = json_data.get("name", json_data.get("id", ""))
                    errors = data.get("json", {}).get("errors", [])

                    if errors:
                        return PostResult(
                            success=False,
                            error=str(errors),
                            platform="reddit",
                            action=ActionResult.FAILED
                        )

                    return PostResult(
                        success=True,
                        post_id=post_id,
                        post_url=post_url,
                        platform="reddit",
                    )
                elif resp.status_code == 429:
                    raise PlatformRateLimitError("reddit")
                else:
                    return PostResult(
                        success=False,
                        error=f"Post failed: {resp.status_code}",
                        platform="reddit",
                        action=ActionResult.FAILED
                    )
        except (PlatformRateLimitError, PlatformAuthError):
            raise
        except Exception as e:
            return PostResult(success=False, error=str(e), platform="reddit",
                              action=ActionResult.FAILED)

    # ── Reading / Monitoring ────────────────────────────────────────

    @retry_on_failure(max_retries=2)
    async def get_comments(self, post_id: str,
                           since: Optional[datetime] = None,
                           limit: int = 50) -> List[Comment]:
        """Get comments on a Reddit post."""
        self._ensure_connected()
        await self.rate_limiter.acquire()

        comments = []
        try:
            # Reddit uses article endpoint: /comments/{post_id}
            article_id = post_id.replace("t3_", "")
            async with httpx.AsyncClient() as client:
                resp = await client.get(
                    f"{REDDIT_API_BASE}/comments/{article_id}",
                    params={"limit": min(limit, 100), "sort": "new"},
                    headers={
                        "Authorization": f"Bearer {self._access_token}",
                        "User-Agent": "LittleNate/1.0 (Sovereign Sanctuary)",
                    }
                )

                if resp.status_code == 200:
                    data = resp.json()
                    # Reddit returns [post, comments] listing
                    if len(data) > 1:
                        comment_listing = data[1].get("data", {}).get("children", [])
                        for c in comment_listing:
                            if c.get("kind") != "t1":
                                continue
                            cd = c.get("data", {})
                            created = datetime.utcfromtimestamp(cd.get("created_utc", 0))
                            if since and created < since:
                                continue
                            comments.append(Comment(
                                comment_id=cd.get("name", cd.get("id", "")),
                                post_id=post_id,
                                author_handle=cd.get("author", "[deleted]"),
                                text=cd.get("body", ""),
                                created_at=created,
                                like_count=cd.get("ups", 0),
                                reply_count=len(cd.get("replies", {}).get("data", {}).get("children", [])) if isinstance(cd.get("replies"), dict) else 0,
                                platform="reddit",
                                raw_data=cd,
                            ))
        except Exception as e:
            logger.error(f"Reddit get_comments error: {e}")

        return comments

    @retry_on_failure(max_retries=2)
    async def get_mentions(self, since: Optional[datetime] = None,
                           limit: int = 50) -> List[Mention]:
        """Get Reddit inbox mentions (username mentions)."""
        self._ensure_connected()
        await self.rate_limiter.acquire()

        mentions = []
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.get(
                    f"{REDDIT_API_BASE}/message/mentions",
                    params={"limit": min(limit, 100)},
                    headers={
                        "Authorization": f"Bearer {self._access_token}",
                        "User-Agent": "LittleNate/1.0 (Sovereign Sanctuary)",
                    }
                )

                if resp.status_code == 200:
                    data = resp.json()
                    for m in data.get("data", {}).get("children", []):
                        md = m.get("data", {})
                        created = datetime.utcfromtimestamp(md.get("created_utc", 0))
                        if since and created < since:
                            continue
                        mentions.append(Mention(
                            mention_id=md.get("name", md.get("id", "")),
                            author_handle=md.get("author", ""),
                            text=md.get("body", ""),
                            context_url=f"https://www.reddit.com{md.get('context', '')}",
                            mention_type="mention",
                            created_at=created,
                            platform="reddit",
                            raw_data=md,
                        ))
        except Exception as e:
            logger.error(f"Reddit get_mentions error: {e}")

        return mentions

    @retry_on_failure(max_retries=2)
    async def get_feed(self, limit: int = 20) -> List[FeedItem]:
        """Get Little Nate's own Reddit posts."""
        self._ensure_connected()
        await self.rate_limiter.acquire()

        items = []
        if not self._reddit_user:
            return items

        try:
            async with httpx.AsyncClient() as client:
                resp = await client.get(
                    f"{REDDIT_API_BASE}/user/{self._reddit_user}/submitted",
                    params={"limit": min(limit, 100), "sort": "new"},
                    headers={
                        "Authorization": f"Bearer {self._access_token}",
                        "User-Agent": "LittleNate/1.0 (Sovereign Sanctuary)",
                    }
                )

                if resp.status_code == 200:
                    data = resp.json()
                    for post in data.get("data", {}).get("children", []):
                        pd = post.get("data", {})
                        items.append(FeedItem(
                            item_id=pd.get("name", pd.get("id", "")),
                            author_handle=pd.get("author", ""),
                            text=pd.get("title", "") + "\n" + pd.get("selftext", ""),
                            item_type="self" if pd.get("is_self") else "link",
                            like_count=pd.get("ups", 0),
                            comment_count=pd.get("num_comments", 0),
                            created_at=datetime.utcfromtimestamp(pd.get("created_utc", 0)),
                            url=f"https://www.reddit.com{pd.get('permalink', '')}",
                            platform="reddit",
                            raw_data=pd,
                        ))
        except Exception as e:
            logger.error(f"Reddit get_feed error: {e}")

        return items

    async def get_own_posts(self, limit: int = 20) -> List[FeedItem]:
        return await self.get_feed(limit)

    async def get_trending(self, limit: int = 10) -> List[TrendingTopic]:
        """Get Reddit trending/popular posts."""
        if not self._connected:
            return []

        topics = []
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.get(
                    f"{REDDIT_API_BASE}/r/popular/hot",
                    params={"limit": min(limit, 25)},
                    headers={
                        "Authorization": f"Bearer {self._access_token}",
                        "User-Agent": "LittleNate/1.0 (Sovereign Sanctuary)",
                    }
                )
                if resp.status_code == 200:
                    for post in resp.json().get("data", {}).get("children", []):
                        pd = post.get("data", {})
                        topics.append(TrendingTopic(
                            name=pd.get("title", ""),
                            description=pd.get("subreddit_name_prefixed", ""),
                            post_count=pd.get("num_comments", 0),
                            platform="reddit",
                        ))
        except Exception as e:
            logger.error(f"Reddit get_trending error: {e}")

        return topics

    # ── Engagement ──────────────────────────────────────────────────

    @retry_on_failure(max_retries=2)
    async def reply_to_comment(self, comment_id: str, text: str,
                                post_id: Optional[str] = None) -> ReplyResult:
        """Reply to a Reddit comment."""
        self._ensure_connected()
        await self.rate_limiter.acquire()

        try:
            async with httpx.AsyncClient() as client:
                resp = await client.post(
                    f"{REDDIT_API_BASE}/api/comment",
                    data={
                        "thing_id": comment_id,
                        "text": text,
                        "api_type": "json",
                    },
                    headers={
                        "Authorization": f"Bearer {self._access_token}",
                        "User-Agent": "LittleNate/1.0 (Sovereign Sanctuary)",
                    }
                )

                if resp.status_code == 200:
                    data = resp.json()
                    errors = data.get("json", {}).get("errors", [])
                    if errors:
                        return ReplyResult(success=False, error=str(errors),
                                          action=ActionResult.FAILED)
                    reply_data = data.get("json", {}).get("data", {}).get("things", [])
                    reply_id = reply_data[0].get("data", {}).get("name", "") if reply_data else ""
                    return ReplyResult(success=True, reply_id=reply_id)
                elif resp.status_code == 429:
                    raise PlatformRateLimitError("reddit")
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
        """Delete a comment (only works if Little Nate is the author or a mod)."""
        self._ensure_connected()
        await self.rate_limiter.acquire()

        try:
            async with httpx.AsyncClient() as client:
                resp = await client.post(
                    f"{REDDIT_API_BASE}/api/del",
                    data={"id": comment_id},
                    headers={
                        "Authorization": f"Bearer {self._access_token}",
                        "User-Agent": "LittleNate/1.0 (Sovereign Sanctuary)",
                    }
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

    async def block_user(self, user_id: str) -> ModerateResult:
        """Block a Reddit user."""
        self._ensure_connected()
        await self.rate_limiter.acquire()

        try:
            async with httpx.AsyncClient() as client:
                resp = await client.post(
                    f"{REDDIT_API_BASE}/api/block_user",
                    data={"name": user_id},
                    headers={
                        "Authorization": f"Bearer {self._access_token}",
                        "User-Agent": "LittleNate/1.0 (Sovereign Sanctuary)",
                    }
                )
                if resp.status_code == 200:
                    return ModerateResult(success=True, action_taken="blocked")
                else:
                    return ModerateResult(
                        success=False,
                        error=f"Block failed: {resp.status_code}",
                        action=ActionResult.FAILED
                    )
        except Exception as e:
            return ModerateResult(success=False, error=str(e), action=ActionResult.FAILED)

    # ── Analytics ───────────────────────────────────────────────────

    async def get_analytics(self) -> PlatformAnalytics:
        """Get Reddit account analytics (basic karma/post counts)."""
        if not self._connected or not self._reddit_user:
            return PlatformAnalytics(platform="reddit")

        try:
            async with httpx.AsyncClient() as client:
                resp = await client.get(
                    f"{REDDIT_API_BASE}/api/v1/me",
                    headers={
                        "Authorization": f"Bearer {self._access_token}",
                        "User-Agent": "LittleNate/1.0 (Sovereign Sanctuary)",
                    }
                )
                if resp.status_code == 200:
                    data = resp.json()
                    return PlatformAnalytics(
                        followers=data.get("subreddit", {}).get("subscribers", 0),
                        total_likes=data.get("link_karma", 0) + data.get("comment_karma", 0),
                        platform="reddit",
                        raw_data=data,
                    )
        except Exception as e:
            logger.error(f"Reddit analytics error: {e}")

        return PlatformAnalytics(platform="reddit")
