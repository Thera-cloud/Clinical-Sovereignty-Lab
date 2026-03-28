"""
LITTLE NATE — X (Twitter) Platform Adapter
Uses X API v2 with OAuth 2.0 (PKCE) for user-context actions.
Supports posting tweets, reading mentions, replying, and basic analytics.

API Reference: https://developer.x.com/en/docs/x-api
Auth: OAuth 2.0 with PKCE (User Access Token)
"""

import hashlib
import logging
import secrets
import urllib.parse
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

import httpx
from app.config import settings
from app.services.skyeye_platform_base import (
    SocialPlatformAdapter, PostResult, Comment, Mention, UserInfo,
    FeedItem, TrendingTopic, PlatformAnalytics, ReplyResult, ModerateResult,
    ContentType, ActionResult,
    PlatformNotConnectedError, PlatformAuthError, PlatformAPIError,
    PlatformRateLimitError, retry_on_failure,
)

logger = logging.getLogger("skyeye.platforms.x")

X_AUTH_URL = "https://x.com/i/oauth2/authorize"
X_TOKEN_URL = "https://api.x.com/2/oauth2/token"
X_API_BASE = "https://api.x.com/2"
X_USER_AGENT = "LittleNate/1.0 (Sovereign Sanctuary)"

# PKCE state storage (in-memory, single instance)
_pkce_store: Dict[str, str] = {}


class XTwitterAdapter(SocialPlatformAdapter):
    """X (Twitter) platform adapter using API v2 + OAuth 2.0 PKCE."""

    def __init__(self, db_pool, rate_limit_seconds: float = 5.0):
        super().__init__("x", db_pool, rate_limit_seconds)
        self.client_id = getattr(settings, "X_CLIENT_ID", "")
        self.client_secret = getattr(settings, "X_CLIENT_SECRET", "")
        self._access_token: Optional[str] = None
        self._user_id: Optional[str] = None
        self._username: Optional[str] = None

    @property
    def _has_credentials(self) -> bool:
        return bool(self.client_id)

    # ── Authentication ──────────────────────────────────────────────

    async def authenticate(self) -> bool:
        if not self._has_credentials:
            logger.info("X: No client credentials configured")
            self._connected = False
            return False

        tokens = await self._load_tokens()
        if not tokens or not tokens.get("access_token"):
            logger.info("X: No stored tokens found")
            self._connected = False
            return False

        self._access_token = tokens["access_token"]
        self._user_id = tokens.get("account_id")
        self._username = tokens.get("account_name")

        token_expiry = tokens.get("token_expiry")
        if token_expiry:
            now_utc = datetime.now(timezone.utc)
            if token_expiry.tzinfo is None:
                token_expiry = token_expiry.replace(tzinfo=timezone.utc)
            if token_expiry < now_utc + timedelta(minutes=5):
                logger.info("X: Token expired or expiring soon, attempting refresh")
                return await self.refresh_token()

        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.get(
                    f"{X_API_BASE}/users/me",
                    headers=self._auth_headers(),
                )
                if resp.status_code == 200:
                    data = resp.json().get("data", {})
                    self._user_id = data.get("id")
                    self._username = data.get("username")
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
            auth = (self.client_id, self.client_secret) if self.client_secret else None
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.post(
                    X_TOKEN_URL,
                    data={
                        "grant_type": "refresh_token",
                        "refresh_token": tokens["refresh_token"],
                        "client_id": self.client_id,
                    },
                    auth=auth,
                    headers={"Content-Type": "application/x-www-form-urlencoded"},
                )
                data = resp.json()

                if "access_token" in data:
                    self._access_token = data["access_token"]
                    expiry = datetime.now(timezone.utc) + timedelta(
                        seconds=data.get("expires_in", 7200)
                    )
                    await self._save_tokens(
                        access_token=data["access_token"],
                        refresh_token=data.get("refresh_token", tokens.get("refresh_token")),
                        token_expiry=expiry,
                    )
                    self._connected = True
                    logger.info("X: Token refreshed successfully")
                    return True
                else:
                    self._last_error = data.get("error_description", "Refresh failed")
                    self._connected = False
                    return False
        except Exception as e:
            self._last_error = str(e)
            self._connected = False
            return False

    # ── OAuth 2.0 with PKCE ──────────────────────────────────────────

    async def get_oauth_url(self, redirect_uri: str) -> str:
        code_verifier = secrets.token_urlsafe(64)[:128]
        code_challenge = hashlib.sha256(code_verifier.encode()).digest()
        import base64
        code_challenge_b64 = base64.urlsafe_b64encode(code_challenge).rstrip(b"=").decode()

        state = f"skyeye_x_{secrets.token_hex(8)}"
        _pkce_store[state] = code_verifier

        params = {
            "response_type": "code",
            "client_id": self.client_id,
            "redirect_uri": redirect_uri,
            "scope": "tweet.read tweet.write users.read offline.access",
            "state": state,
            "code_challenge": code_challenge_b64,
            "code_challenge_method": "S256",
        }
        return f"{X_AUTH_URL}?{urllib.parse.urlencode(params)}"

    async def handle_oauth_callback(self, code: str, redirect_uri: str,
                                     state: str = None) -> bool:
        code_verifier = _pkce_store.pop(state, "") if state else ""
        if not code_verifier:
            logger.warning("X: No PKCE code_verifier found for state")
            code_verifier = ""

        try:
            auth = None
            data_payload = {
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": redirect_uri,
                "client_id": self.client_id,
                "code_verifier": code_verifier,
            }
            if self.client_secret:
                auth = (self.client_id, self.client_secret)

            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.post(
                    X_TOKEN_URL,
                    data=data_payload,
                    auth=auth,
                    headers={"Content-Type": "application/x-www-form-urlencoded"},
                )
                data = resp.json()

                if "access_token" not in data:
                    self._last_error = data.get("error_description", "Token exchange failed")
                    return False

                self._access_token = data["access_token"]
                expiry = datetime.now(timezone.utc) + timedelta(
                    seconds=data.get("expires_in", 7200)
                )

                me_resp = await client.get(
                    f"{X_API_BASE}/users/me",
                    headers={"Authorization": f"Bearer {self._access_token}"},
                )
                me_data = me_resp.json().get("data", {})
                self._user_id = me_data.get("id", "")
                self._username = me_data.get("username", "")

                await self._save_tokens(
                    access_token=data["access_token"],
                    refresh_token=data.get("refresh_token"),
                    token_expiry=expiry,
                    account_id=self._user_id,
                    account_name=f"@{self._username}",
                )
                self._connected = True
                logger.info(f"X: OAuth complete for @{self._username}")
                return True
        except Exception as e:
            self._last_error = str(e)
            return False

    def _auth_headers(self) -> Dict[str, str]:
        return {
            "Authorization": f"Bearer {self._access_token}",
            "User-Agent": X_USER_AGENT,
        }

    # ── Content Publishing ──────────────────────────────────────────

    @retry_on_failure(max_retries=2)
    async def post_content(self, text: str, media_url: Optional[str] = None,
                           content_type: ContentType = ContentType.POST,
                           **kwargs) -> PostResult:
        """Post a tweet via POST /2/tweets.

        Supports standard tweets (280 chars) and long-form posts up to
        4,000 chars for X Premium accounts. The same API endpoint handles
        both — X enforces the limit based on the account's subscription.

        When content_type is ARTICLE, the post is logged as a long-form
        article but uses the identical API call.
        """
        self._ensure_connected()
        await self.rate_limiter.acquire()

        is_article = content_type == ContentType.ARTICLE
        if is_article:
            logger.info(f"X: Publishing long-form article ({len(text)} chars)")

        tweet_body: Dict[str, Any] = {"text": text}

        reply_to = kwargs.get("reply_to")
        if reply_to:
            tweet_body["reply"] = {"in_reply_to_tweet_id": reply_to}

        quote_tweet_id = kwargs.get("quote_tweet_id")
        if quote_tweet_id:
            tweet_body["quote_tweet_id"] = quote_tweet_id

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.post(
                    f"{X_API_BASE}/tweets",
                    json=tweet_body,
                    headers={**self._auth_headers(), "Content-Type": "application/json"},
                )

                if resp.status_code in (200, 201):
                    data = resp.json().get("data", {})
                    tweet_id = data.get("id", "")
                    label = "article" if is_article else "tweet"
                    logger.info(f"X: {label} posted — {tweet_id}")
                    return PostResult(
                        success=True,
                        post_id=tweet_id,
                        post_url=f"https://x.com/{self._username}/status/{tweet_id}" if self._username else None,
                        platform="x",
                    )
                elif resp.status_code == 429:
                    raise PlatformRateLimitError("x")
                elif resp.status_code == 401:
                    raise PlatformAuthError("x", "Token expired")
                else:
                    error_detail = resp.json().get("detail", resp.text[:200])
                    return PostResult(
                        success=False,
                        error=f"Tweet failed ({resp.status_code}): {error_detail}",
                        platform="x",
                        action=ActionResult.FAILED,
                    )
        except (PlatformRateLimitError, PlatformAuthError):
            raise
        except Exception as e:
            return PostResult(success=False, error=str(e), platform="x",
                              action=ActionResult.FAILED)

    # ── Reading / Monitoring ────────────────────────────────────────

    @retry_on_failure(max_retries=2)
    async def get_mentions(self, since: Optional[datetime] = None,
                           limit: int = 50) -> List[Mention]:
        self._ensure_connected()
        await self.rate_limiter.acquire()

        if not self._user_id:
            return []

        mentions = []
        try:
            params: Dict[str, Any] = {
                "max_results": min(limit, 100),
                "tweet.fields": "created_at,author_id,text",
                "expansions": "author_id",
                "user.fields": "username,name",
            }
            if since:
                params["start_time"] = since.strftime("%Y-%m-%dT%H:%M:%SZ")

            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.get(
                    f"{X_API_BASE}/users/{self._user_id}/mentions",
                    params=params,
                    headers=self._auth_headers(),
                )
                if resp.status_code == 200:
                    body = resp.json()
                    users = {u["id"]: u for u in body.get("includes", {}).get("users", [])}
                    for tweet in body.get("data", []):
                        author_id = tweet.get("author_id", "")
                        author = users.get(author_id, {})
                        handle = author.get("username", author_id)
                        mentions.append(Mention(
                            mention_id=tweet.get("id", ""),
                            author_handle=handle,
                            text=tweet.get("text", ""),
                            context_url=f"https://x.com/i/status/{tweet.get('id', '')}",
                            mention_type="mention",
                            created_at=datetime.fromisoformat(
                                tweet["created_at"].replace("Z", "+00:00")
                            ) if tweet.get("created_at") else datetime.utcnow(),
                            platform="x",
                            raw_data={**tweet, "_author": author},
                        ))
        except Exception as e:
            logger.error(f"X get_mentions error: {e}")

        return mentions

    @retry_on_failure(max_retries=2)
    async def get_feed(self, limit: int = 20) -> List[FeedItem]:
        """Get own recent tweets."""
        self._ensure_connected()
        await self.rate_limiter.acquire()

        if not self._user_id:
            return []

        items = []
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.get(
                    f"{X_API_BASE}/users/{self._user_id}/tweets",
                    params={
                        "max_results": min(limit, 100),
                        "tweet.fields": "created_at,public_metrics,text",
                    },
                    headers=self._auth_headers(),
                )
                if resp.status_code == 200:
                    for tweet in resp.json().get("data", []):
                        metrics = tweet.get("public_metrics", {})
                        items.append(FeedItem(
                            item_id=tweet.get("id", ""),
                            author_handle=f"@{self._username}" if self._username else "",
                            text=tweet.get("text", ""),
                            item_type="tweet",
                            like_count=metrics.get("like_count", 0),
                            comment_count=metrics.get("reply_count", 0),
                            created_at=datetime.fromisoformat(
                                tweet["created_at"].replace("Z", "+00:00")
                            ) if tweet.get("created_at") else datetime.utcnow(),
                            url=f"https://x.com/{self._username}/status/{tweet.get('id', '')}",
                            platform="x",
                            raw_data=tweet,
                        ))
        except Exception as e:
            logger.error(f"X get_feed error: {e}")

        return items

    async def get_own_posts(self, limit: int = 20) -> List[FeedItem]:
        return await self.get_feed(limit)

    @retry_on_failure(max_retries=2)
    async def get_comments(self, post_id: str,
                           since: Optional[datetime] = None,
                           limit: int = 50) -> List[Comment]:
        """Get replies to a tweet using search."""
        self._ensure_connected()
        await self.rate_limiter.acquire()

        comments = []
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.get(
                    f"{X_API_BASE}/tweets/search/recent",
                    params={
                        "query": f"conversation_id:{post_id}",
                        "max_results": min(limit, 100),
                        "tweet.fields": "created_at,author_id,text,public_metrics",
                    },
                    headers=self._auth_headers(),
                )
                if resp.status_code == 200:
                    for tweet in resp.json().get("data", []):
                        metrics = tweet.get("public_metrics", {})
                        comments.append(Comment(
                            comment_id=tweet.get("id", ""),
                            post_id=post_id,
                            author_handle=tweet.get("author_id", ""),
                            text=tweet.get("text", ""),
                            created_at=datetime.fromisoformat(
                                tweet["created_at"].replace("Z", "+00:00")
                            ) if tweet.get("created_at") else datetime.utcnow(),
                            like_count=metrics.get("like_count", 0),
                            reply_count=metrics.get("reply_count", 0),
                            platform="x",
                            raw_data=tweet,
                        ))
        except Exception as e:
            logger.error(f"X get_comments error: {e}")

        return comments

    async def get_trending(self, limit: int = 10) -> List[TrendingTopic]:
        return []

    # ── Engagement ──────────────────────────────────────────────────

    @retry_on_failure(max_retries=2)
    async def reply_to_comment(self, comment_id: str, text: str,
                                post_id: Optional[str] = None) -> ReplyResult:
        self._ensure_connected()
        await self.rate_limiter.acquire()

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.post(
                    f"{X_API_BASE}/tweets",
                    json={
                        "text": text,
                        "reply": {"in_reply_to_tweet_id": comment_id},
                    },
                    headers={**self._auth_headers(), "Content-Type": "application/json"},
                )
                if resp.status_code in (200, 201):
                    data = resp.json().get("data", {})
                    return ReplyResult(success=True, reply_id=data.get("id", ""))
                elif resp.status_code == 429:
                    raise PlatformRateLimitError("x")
                else:
                    return ReplyResult(
                        success=False,
                        error=f"Reply failed: {resp.status_code}",
                        action=ActionResult.FAILED,
                    )
        except (PlatformRateLimitError, PlatformAuthError):
            raise
        except Exception as e:
            return ReplyResult(success=False, error=str(e), action=ActionResult.FAILED)

    # ── Moderation ──────────────────────────────────────────────────

    @retry_on_failure(max_retries=2)
    async def delete_comment(self, comment_id: str,
                              post_id: Optional[str] = None) -> ModerateResult:
        """Delete own tweet."""
        self._ensure_connected()
        await self.rate_limiter.acquire()

        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.delete(
                    f"{X_API_BASE}/tweets/{comment_id}",
                    headers=self._auth_headers(),
                )
                if resp.status_code == 200:
                    return ModerateResult(success=True, action_taken="deleted")
                else:
                    return ModerateResult(
                        success=False,
                        error=f"Delete failed: {resp.status_code}",
                        action=ActionResult.FAILED,
                    )
        except Exception as e:
            return ModerateResult(success=False, error=str(e), action=ActionResult.FAILED)

    async def block_user(self, user_id: str) -> ModerateResult:
        self._ensure_connected()
        await self.rate_limiter.acquire()

        if not self._user_id:
            return ModerateResult(success=False, error="No user ID", action=ActionResult.FAILED)

        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.post(
                    f"{X_API_BASE}/users/{self._user_id}/blocking",
                    json={"target_user_id": user_id},
                    headers={**self._auth_headers(), "Content-Type": "application/json"},
                )
                if resp.status_code == 200:
                    return ModerateResult(success=True, action_taken="blocked")
                else:
                    return ModerateResult(
                        success=False,
                        error=f"Block failed: {resp.status_code}",
                        action=ActionResult.FAILED,
                    )
        except Exception as e:
            return ModerateResult(success=False, error=str(e), action=ActionResult.FAILED)

    # ── Engagement (Tier 2) ─────────────────────────────────────────

    @retry_on_failure(max_retries=2)
    async def like_tweet(self, tweet_id: str) -> bool:
        self._ensure_connected()
        await self.rate_limiter.acquire()
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.post(
                    f"{X_API_BASE}/users/{self._user_id}/likes",
                    json={"tweet_id": tweet_id},
                    headers={**self._auth_headers(), "Content-Type": "application/json"},
                )
                if resp.status_code in (200, 201):
                    return True
                elif resp.status_code == 429:
                    raise PlatformRateLimitError("x")
                else:
                    logger.warning(f"X: Like failed ({resp.status_code}): {resp.text[:200]}")
                    return False
        except (PlatformRateLimitError, PlatformAuthError):
            raise
        except Exception as e:
            logger.error(f"X: Like error: {e}")
            return False

    @retry_on_failure(max_retries=2)
    async def retweet(self, tweet_id: str) -> bool:
        self._ensure_connected()
        await self.rate_limiter.acquire()
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.post(
                    f"{X_API_BASE}/users/{self._user_id}/retweets",
                    json={"tweet_id": tweet_id},
                    headers={**self._auth_headers(), "Content-Type": "application/json"},
                )
                return resp.status_code in (200, 201)
        except (PlatformRateLimitError, PlatformAuthError):
            raise
        except Exception as e:
            logger.error(f"X: Retweet error: {e}")
            return False

    @retry_on_failure(max_retries=2)
    async def follow_user(self, target_user_id: str) -> bool:
        self._ensure_connected()
        await self.rate_limiter.acquire()
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.post(
                    f"{X_API_BASE}/users/{self._user_id}/following",
                    json={"target_user_id": target_user_id},
                    headers={**self._auth_headers(), "Content-Type": "application/json"},
                )
                return resp.status_code in (200, 201)
        except (PlatformRateLimitError, PlatformAuthError):
            raise
        except Exception as e:
            logger.error(f"X: Follow error: {e}")
            return False

    @retry_on_failure(max_retries=2)
    async def search_tweets(self, query: str, limit: int = 10,
                            since: Optional[datetime] = None) -> List[FeedItem]:
        self._ensure_connected()
        await self.rate_limiter.acquire()
        params: Dict[str, Any] = {
            "query": f"{query} -is:retweet lang:en",
            "max_results": min(limit, 100),
            "tweet.fields": "created_at,public_metrics,author_id,conversation_id",
            "expansions": "author_id",
            "user.fields": "username,name,public_metrics,description",
        }
        if since:
            params["start_time"] = since.strftime("%Y-%m-%dT%H:%M:%SZ")
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.get(
                    f"{X_API_BASE}/tweets/search/recent",
                    params=params,
                    headers=self._auth_headers(),
                )
                if resp.status_code != 200:
                    logger.warning(f"X: Search failed ({resp.status_code})")
                    return []
                body = resp.json()
                tweets = body.get("data", [])
                users = {u["id"]: u for u in body.get("includes", {}).get("users", [])}
                results = []
                for t in tweets:
                    author = users.get(t.get("author_id"), {})
                    metrics = t.get("public_metrics", {})
                    results.append(FeedItem(
                        item_id=t["id"],
                        author_handle=author.get("username", ""),
                        author_name=author.get("name", ""),
                        text=t.get("text", ""),
                        like_count=metrics.get("like_count", 0),
                        comment_count=metrics.get("reply_count", 0),
                        share_count=metrics.get("retweet_count", 0),
                        view_count=metrics.get("impression_count", 0),
                        created_at=t.get("created_at"),
                        url=f"https://x.com/i/status/{t['id']}",
                        platform="x",
                        raw_data={**t, "_author": author},
                    ))
                return results
        except (PlatformRateLimitError, PlatformAuthError):
            raise
        except Exception as e:
            logger.error(f"X: Search error: {e}")
            return []

    @retry_on_failure(max_retries=2)
    async def get_user_by_handle(self, handle: str) -> Optional[UserInfo]:
        self._ensure_connected()
        await self.rate_limiter.acquire()
        clean = handle.lstrip("@")
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.get(
                    f"{X_API_BASE}/users/by/username/{clean}",
                    params={"user.fields": "public_metrics,description,created_at"},
                    headers=self._auth_headers(),
                )
                if resp.status_code != 200:
                    return None
                data = resp.json().get("data", {})
                metrics = data.get("public_metrics", {})
                return UserInfo(
                    user_id=data.get("id", ""),
                    handle=data.get("username", clean),
                    display_name=data.get("name", ""),
                    bio=data.get("description", ""),
                    follower_count=metrics.get("followers_count", 0),
                    following_count=metrics.get("following_count", 0),
                    post_count=metrics.get("tweet_count", 0),
                    is_verified=data.get("verified", False),
                    profile_url=f"https://x.com/{data.get('username', clean)}",
                    platform="x",
                    raw_data=data,
                )
        except Exception as e:
            logger.error(f"X: User lookup error: {e}")
            return None

    @retry_on_failure(max_retries=2)
    async def send_dm(self, participant_id: str, text: str) -> bool:
        """Send a direct message. Requires DM scope in OAuth."""
        self._ensure_connected()
        await self.rate_limiter.acquire()
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.post(
                    f"{X_API_BASE}/dm_conversations/with/{participant_id}/messages",
                    json={"text": text},
                    headers={**self._auth_headers(), "Content-Type": "application/json"},
                )
                if resp.status_code in (200, 201):
                    return True
                else:
                    logger.warning(f"X: DM failed ({resp.status_code}): {resp.text[:200]}")
                    return False
        except Exception as e:
            logger.error(f"X: DM error: {e}")
            return False

    async def get_trending(self, limit: int = 10) -> List[TrendingTopic]:
        """Search for trending mental health topics as a proxy for trending."""
        try:
            results = await self.search_tweets(
                "mental health OR therapy OR wellness OR self care",
                limit=limit,
                since=datetime.now(timezone.utc) - timedelta(hours=6),
            )
            topics = {}
            for item in results:
                for word in item.text.split():
                    if word.startswith("#") and len(word) > 2:
                        tag = word.lower().rstrip(".,!?")
                        topics[tag] = topics.get(tag, 0) + 1
            return [
                TrendingTopic(name=tag, post_count=count, platform="x")
                for tag, count in sorted(topics.items(), key=lambda x: -x[1])[:limit]
            ]
        except Exception:
            return []

    # ── Notification / Engagement Discovery ────────────────────────

    @retry_on_failure(max_retries=2)
    async def get_liking_users(self, tweet_id: str, limit: int = 100) -> List[UserInfo]:
        """Get users who liked a tweet."""
        self._ensure_connected()
        await self.rate_limiter.acquire()
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.get(
                    f"{X_API_BASE}/tweets/{tweet_id}/liking_users",
                    params={
                        "max_results": min(limit, 100),
                        "user.fields": "username,name,description,public_metrics",
                    },
                    headers=self._auth_headers(),
                )
                if resp.status_code == 200:
                    return [
                        UserInfo(
                            user_id=u.get("id", ""),
                            handle=u.get("username", ""),
                            display_name=u.get("name", ""),
                            bio=u.get("description", ""),
                            follower_count=u.get("public_metrics", {}).get("followers_count", 0),
                            following_count=u.get("public_metrics", {}).get("following_count", 0),
                            post_count=u.get("public_metrics", {}).get("tweet_count", 0),
                            profile_url=f"https://x.com/{u.get('username', '')}",
                            platform="x",
                            raw_data=u,
                        )
                        for u in resp.json().get("data", [])
                    ]
                elif resp.status_code == 429:
                    raise PlatformRateLimitError("x")
        except (PlatformRateLimitError, PlatformAuthError):
            raise
        except Exception as e:
            logger.error(f"X get_liking_users error: {e}")
        return []

    @retry_on_failure(max_retries=2)
    async def get_retweeted_by(self, tweet_id: str, limit: int = 100) -> List[UserInfo]:
        """Get users who retweeted a tweet."""
        self._ensure_connected()
        await self.rate_limiter.acquire()
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.get(
                    f"{X_API_BASE}/tweets/{tweet_id}/retweeted_by",
                    params={
                        "max_results": min(limit, 100),
                        "user.fields": "username,name,description,public_metrics",
                    },
                    headers=self._auth_headers(),
                )
                if resp.status_code == 200:
                    return [
                        UserInfo(
                            user_id=u.get("id", ""),
                            handle=u.get("username", ""),
                            display_name=u.get("name", ""),
                            bio=u.get("description", ""),
                            follower_count=u.get("public_metrics", {}).get("followers_count", 0),
                            following_count=u.get("public_metrics", {}).get("following_count", 0),
                            post_count=u.get("public_metrics", {}).get("tweet_count", 0),
                            profile_url=f"https://x.com/{u.get('username', '')}",
                            platform="x",
                            raw_data=u,
                        )
                        for u in resp.json().get("data", [])
                    ]
                elif resp.status_code == 429:
                    raise PlatformRateLimitError("x")
        except (PlatformRateLimitError, PlatformAuthError):
            raise
        except Exception as e:
            logger.error(f"X get_retweeted_by error: {e}")
        return []

    @retry_on_failure(max_retries=2)
    async def get_new_followers(self, limit: int = 100) -> List[UserInfo]:
        """Get most recent followers (newest first for delta diffing)."""
        self._ensure_connected()
        await self.rate_limiter.acquire()
        if not self._user_id:
            return []
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.get(
                    f"{X_API_BASE}/users/{self._user_id}/followers",
                    params={
                        "max_results": min(limit, 100),
                        "user.fields": "username,name,description,public_metrics,created_at",
                    },
                    headers=self._auth_headers(),
                )
                if resp.status_code == 200:
                    return [
                        UserInfo(
                            user_id=u.get("id", ""),
                            handle=u.get("username", ""),
                            display_name=u.get("name", ""),
                            bio=u.get("description", ""),
                            follower_count=u.get("public_metrics", {}).get("followers_count", 0),
                            following_count=u.get("public_metrics", {}).get("following_count", 0),
                            post_count=u.get("public_metrics", {}).get("tweet_count", 0),
                            profile_url=f"https://x.com/{u.get('username', '')}",
                            platform="x",
                            raw_data=u,
                        )
                        for u in resp.json().get("data", [])
                    ]
                elif resp.status_code == 429:
                    raise PlatformRateLimitError("x")
        except (PlatformRateLimitError, PlatformAuthError):
            raise
        except Exception as e:
            logger.error(f"X get_new_followers error: {e}")
        return []

    @retry_on_failure(max_retries=2)
    async def resolve_user_id(self, user_id: str) -> Optional[UserInfo]:
        """Reverse lookup: numeric user ID to full UserInfo with @username."""
        self._ensure_connected()
        await self.rate_limiter.acquire()
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.get(
                    f"{X_API_BASE}/users/{user_id}",
                    params={"user.fields": "username,name,description,public_metrics"},
                    headers=self._auth_headers(),
                )
                if resp.status_code == 200:
                    data = resp.json().get("data", {})
                    metrics = data.get("public_metrics", {})
                    return UserInfo(
                        user_id=data.get("id", user_id),
                        handle=data.get("username", ""),
                        display_name=data.get("name", ""),
                        bio=data.get("description", ""),
                        follower_count=metrics.get("followers_count", 0),
                        following_count=metrics.get("following_count", 0),
                        post_count=metrics.get("tweet_count", 0),
                        profile_url=f"https://x.com/{data.get('username', '')}",
                        platform="x",
                        raw_data=data,
                    )
        except Exception as e:
            logger.error(f"X resolve_user_id error: {e}")
        return None

    # ── Analytics ───────────────────────────────────────────────────

    async def get_analytics(self) -> PlatformAnalytics:
        if not self._connected or not self._user_id:
            return PlatformAnalytics(platform="x")

        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.get(
                    f"{X_API_BASE}/users/{self._user_id}",
                    params={"user.fields": "public_metrics,description"},
                    headers=self._auth_headers(),
                )
                if resp.status_code == 200:
                    data = resp.json().get("data", {})
                    metrics = data.get("public_metrics", {})
                    return PlatformAnalytics(
                        followers=metrics.get("followers_count", 0),
                        total_posts=metrics.get("tweet_count", 0),
                        platform="x",
                        raw_data=data,
                    )
        except Exception as e:
            logger.error(f"X analytics error: {e}")

        return PlatformAnalytics(platform="x")
