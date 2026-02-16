"""
LITTLE NATE — LinkedIn Platform Adapter
Uses LinkedIn Posts API (v202401) + Community Management API + Pages Data Portability API.
Tier 2 platform. Professional voice — thought leadership + articles.

API Reference: https://learn.microsoft.com/en-us/linkedin/
Auth: OAuth 2.0 (3-legged), tokens expire every 60 days.

Capabilities:
  - Proactive token refresh (7-day warning window before 60-day expiry)
  - Organic publishing via Posts API (text, article, newsletter)
  - Comment monitoring with pagination across all own posts
  - Reply to comments via versioned REST API
  - Organization analytics via Pages Data Portability API
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

# Versioned API header — all REST API calls must include this
LINKEDIN_API_VERSION = "202401"

# Token refresh proactive window — refresh if expiry is within this many days
PROACTIVE_REFRESH_DAYS = 7


def _linkedin_headers(access_token: str, content_type: bool = False) -> Dict[str, str]:
    """Standard headers for LinkedIn REST API calls."""
    headers = {
        "Authorization": f"Bearer {access_token}",
        "LinkedIn-Version": LINKEDIN_API_VERSION,
    }
    if content_type:
        headers["Content-Type"] = "application/json"
    return headers


class LinkedInAdapter(SocialPlatformAdapter):
    """
    LinkedIn platform adapter for SkyEye.

    Implements the full lifecycle: OAuth 2.0 with proactive 60-day token
    refresh, organic publishing via the modern Posts API, paginated comment
    monitoring, and organization-level analytics via the Pages Data
    Portability API.
    """

    def __init__(self, db_pool, rate_limit_seconds: float = 20.0):
        super().__init__("linkedin", db_pool, rate_limit_seconds)
        self.client_id = getattr(settings, "LINKEDIN_CLIENT_ID", "")
        self.client_secret = getattr(settings, "LINKEDIN_CLIENT_SECRET", "")
        self._access_token: Optional[str] = None
        self._person_urn: Optional[str] = None   # urn:li:person:XXXX
        self._org_urn: Optional[str] = None       # urn:li:organization:XXXX

    @property
    def _has_credentials(self) -> bool:
        return bool(self.client_id and self.client_secret)

    # ── Authentication ──────────────────────────────────────────────

    async def authenticate(self) -> bool:
        """
        Authenticate with LinkedIn. Validates stored token, performs
        proactive refresh if within 7 days of expiry, and resolves
        the organization URN for analytics.
        """
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

        # Check if token is already expired
        token_expiry = tokens.get("token_expiry")
        if token_expiry and token_expiry < datetime.utcnow():
            logger.info("LinkedIn: Token expired, attempting refresh")
            return await self.refresh_token()

        # Proactive refresh: if within 7 days of expiry, refresh now
        if token_expiry:
            days_until_expiry = (token_expiry - datetime.utcnow()).days
            if days_until_expiry <= PROACTIVE_REFRESH_DAYS:
                logger.info(
                    f"LinkedIn: Token expires in {days_until_expiry} days, "
                    f"proactively refreshing (threshold: {PROACTIVE_REFRESH_DAYS}d)"
                )
                refreshed = await self.refresh_token()
                if refreshed:
                    # Continue to validate below with refreshed token
                    pass
                else:
                    logger.warning("LinkedIn: Proactive refresh failed, using current token")

        # Validate the token by calling userinfo
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.get(
                    f"{LINKEDIN_API_BASE}/userinfo",
                    headers={"Authorization": f"Bearer {self._access_token}"}
                )
                if resp.status_code == 200:
                    data = resp.json()
                    self._person_urn = f"urn:li:person:{data.get('sub', '')}"
                    self._connected = True
                    await self._update_token_status("connected")

                    # Resolve organization URN for analytics (non-blocking)
                    try:
                        await self._resolve_org_urn()
                    except Exception as org_err:
                        logger.debug(f"LinkedIn: Org URN resolution deferred: {org_err}")

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
        """
        Refresh the OAuth 2.0 access token using the stored refresh token.
        LinkedIn access tokens expire every 60 days (5,184,000 seconds).
        """
        tokens = await self._load_tokens()
        if not tokens or not tokens.get("refresh_token"):
            self._connected = False
            await self._update_token_status("expired", "No refresh token available")
            return False

        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
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
                        refresh_token=data.get("refresh_token", tokens.get("refresh_token")),
                        token_expiry=expiry,
                    )
                    self._connected = True
                    logger.info(f"LinkedIn: Token refreshed, new expiry: {expiry.isoformat()}")
                    return True
                else:
                    error_msg = data.get("error_description", data.get("error", "Unknown"))
                    logger.error(f"LinkedIn: Token refresh failed: {error_msg}")
                    self._connected = False
                    await self._update_token_status("expired", error_msg)
                    return False
        except Exception as e:
            self._last_error = str(e)
            logger.error(f"LinkedIn: Token refresh exception: {e}")
            self._connected = False
            return False

    async def check_token_health(self) -> Dict[str, Any]:
        """
        Check the health of the stored LinkedIn token.
        Called by the SkyEye session engine at each session start.

        Returns:
            dict with {status, days_until_expiry, needs_refresh, token_expiry,
                       last_refreshed, connected}
        """
        tokens = await self._load_tokens()
        if not tokens or not tokens.get("access_token"):
            return {
                "status": "no_token",
                "days_until_expiry": 0,
                "needs_refresh": False,
                "connected": False,
            }

        token_expiry = tokens.get("token_expiry")
        last_refreshed = tokens.get("last_refreshed")

        if not token_expiry:
            return {
                "status": "unknown_expiry",
                "days_until_expiry": None,
                "needs_refresh": True,
                "token_expiry": None,
                "last_refreshed": last_refreshed,
                "connected": self._connected,
            }

        now = datetime.utcnow()
        days_until_expiry = (token_expiry - now).days if token_expiry > now else 0
        is_expired = token_expiry < now
        needs_refresh = is_expired or days_until_expiry <= PROACTIVE_REFRESH_DAYS

        if is_expired:
            status = "expired"
        elif days_until_expiry <= PROACTIVE_REFRESH_DAYS:
            status = "expiring_soon"
        else:
            status = "healthy"

        return {
            "status": status,
            "days_until_expiry": days_until_expiry,
            "needs_refresh": needs_refresh,
            "token_expiry": token_expiry.isoformat() if token_expiry else None,
            "last_refreshed": last_refreshed.isoformat() if last_refreshed else None,
            "connected": self._connected,
        }

    # ── OAuth Flow ──────────────────────────────────────────────────

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
            async with httpx.AsyncClient(timeout=15.0) as client:
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

                # Resolve org URN now that we have fresh tokens
                try:
                    await self._resolve_org_urn()
                except Exception:
                    pass

                logger.info(f"LinkedIn: OAuth complete for {person_name}, "
                            f"token expires {expiry.isoformat()}")
                return True
        except Exception as e:
            self._last_error = str(e)
            return False

    # ── Organization URN Resolution ─────────────────────────────────

    async def _resolve_org_urn(self) -> Optional[str]:
        """
        Find the LinkedIn Organization page this user administers.
        Required for analytics via the Pages Data Portability API.

        Calls GET /organizationAcls?q=roleAssignee&role=ADMINISTRATOR
        and caches the first organization URN found.
        """
        if self._org_urn:
            return self._org_urn

        if not self._access_token:
            return None

        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.get(
                    f"{LINKEDIN_REST_BASE}/organizationAcls",
                    params={
                        "q": "roleAssignee",
                        "role": "ADMINISTRATOR",
                    },
                    headers=_linkedin_headers(self._access_token),
                )

                if resp.status_code == 200:
                    data = resp.json()
                    elements = data.get("elements", [])
                    if elements:
                        # Extract organization URN from first result
                        org_ref = elements[0].get("organization")
                        if org_ref:
                            self._org_urn = org_ref
                            logger.info(f"LinkedIn: Resolved organization URN: {self._org_urn}")
                            return self._org_urn

                        # Alternative: check organizationalTarget field
                        org_target = elements[0].get("organizationalTarget")
                        if org_target:
                            self._org_urn = org_target
                            logger.info(f"LinkedIn: Resolved organization URN: {self._org_urn}")
                            return self._org_urn

                    logger.debug("LinkedIn: No administered organizations found")
                else:
                    logger.debug(f"LinkedIn: Org ACLs returned {resp.status_code}")
        except Exception as e:
            logger.debug(f"LinkedIn: Org URN resolution error: {e}")

        return None

    # ── Content Publishing (Posts API) ──────────────────────────────

    @retry_on_failure(max_retries=2)
    async def post_content(self, text: str, media_url: Optional[str] = None,
                           content_type: ContentType = ContentType.POST,
                           **kwargs) -> PostResult:
        """
        Publish content to LinkedIn using the modern Posts API.

        Supports:
          - Text posts (content_type=POST)
          - Article shares (content_type=ARTICLE or media_url provided)
          - kwargs: title, description (for articles)

        Endpoint: POST /rest/posts (LinkedIn-Version: 202401)
        """
        self._ensure_connected()
        await self.rate_limiter.acquire()

        if not self._person_urn:
            return PostResult(success=False, error="No LinkedIn person URN",
                              platform="linkedin", action=ActionResult.FAILED)

        try:
            # Build the Posts API request body
            post_body: Dict[str, Any] = {
                "author": self._person_urn,
                "commentary": text,
                "visibility": "PUBLIC",
                "distribution": {
                    "feedDistribution": "MAIN_FEED",
                    "targetEntities": [],
                    "thirdPartyDistributionChannels": [],
                },
                "lifecycleState": "PUBLISHED",
            }

            # Article content (link share with optional title/description)
            if media_url or content_type == ContentType.ARTICLE:
                post_body["content"] = {
                    "article": {
                        "source": media_url or "",
                        "title": kwargs.get("title", ""),
                        "description": kwargs.get("description", ""),
                    }
                }

            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.post(
                    f"{LINKEDIN_REST_BASE}/posts",
                    json=post_body,
                    headers=_linkedin_headers(self._access_token, content_type=True),
                )

                if resp.status_code in (200, 201):
                    post_urn = resp.headers.get(
                        "x-restli-id",
                        resp.headers.get("X-RestLi-Id", "")
                    )
                    # Try response body as fallback
                    if not post_urn:
                        try:
                            resp_data = resp.json()
                            post_urn = resp_data.get("id", "")
                        except Exception:
                            pass

                    post_url = None
                    if post_urn:
                        post_url = f"https://www.linkedin.com/feed/update/{post_urn}/"

                    logger.info(f"LinkedIn: Published post {post_urn}")
                    return PostResult(
                        success=True,
                        post_id=post_urn,
                        post_url=post_url,
                        platform="linkedin",
                    )
                elif resp.status_code == 401:
                    raise PlatformAuthError("linkedin")
                elif resp.status_code == 429:
                    raise PlatformRateLimitError("linkedin")
                else:
                    error_data = {}
                    try:
                        error_data = resp.json()
                    except Exception:
                        pass
                    error_msg = error_data.get("message", f"Post failed: {resp.status_code}")
                    logger.error(f"LinkedIn: Post failed: {error_msg}")
                    return PostResult(
                        success=False,
                        error=error_msg,
                        platform="linkedin",
                        action=ActionResult.FAILED,
                    )
        except (PlatformRateLimitError, PlatformAuthError):
            raise
        except Exception as e:
            return PostResult(success=False, error=str(e), platform="linkedin",
                              action=ActionResult.FAILED)

    # ── Reading / Monitoring ────────────────────────────────────────

    @retry_on_failure(max_retries=2)
    async def get_feed(self, limit: int = 20) -> List[FeedItem]:
        """
        Get own LinkedIn posts using the Posts API author query.

        Endpoint: GET /rest/posts?q=author&author={person_urn}&count={limit}
        """
        self._ensure_connected()
        await self.rate_limiter.acquire()

        if not self._person_urn:
            return []

        items: List[FeedItem] = []
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.get(
                    f"{LINKEDIN_REST_BASE}/posts",
                    params={
                        "q": "author",
                        "author": self._person_urn,
                        "count": min(limit, 50),
                        "sortBy": "LAST_MODIFIED",
                    },
                    headers=_linkedin_headers(self._access_token),
                )

                if resp.status_code == 200:
                    data = resp.json()
                    for post in data.get("elements", []):
                        post_urn = post.get("id", post.get("$URN", ""))
                        commentary = post.get("commentary", "")
                        created_ts = post.get("createdAt", 0)

                        created_at = None
                        if created_ts:
                            try:
                                created_at = datetime.utcfromtimestamp(created_ts / 1000)
                            except (ValueError, OSError):
                                pass

                        # Extract engagement stats if available
                        likes_count = post.get("likesSummary", {}).get("totalLikes", 0)
                        comments_count = post.get("commentsSummary", {}).get("totalFirstLevelComments", 0)

                        items.append(FeedItem(
                            item_id=post_urn,
                            author_handle=self._person_urn or "",
                            text=commentary,
                            created_at=created_at,
                            likes=likes_count,
                            comments=comments_count,
                            platform="linkedin",
                            url=f"https://www.linkedin.com/feed/update/{post_urn}/" if post_urn else None,
                            raw_data=post,
                        ))
                elif resp.status_code == 401:
                    raise PlatformAuthError("linkedin")
                else:
                    logger.warning(f"LinkedIn: get_feed returned {resp.status_code}")
        except (PlatformAuthError, PlatformRateLimitError):
            raise
        except Exception as e:
            logger.error(f"LinkedIn get_feed error: {e}")

        return items

    async def get_own_posts(self, limit: int = 20) -> List[FeedItem]:
        return await self.get_feed(limit)

    @retry_on_failure(max_retries=2)
    async def get_comments(self, post_id: str,
                           since: Optional[datetime] = None,
                           limit: int = 50) -> List[Comment]:
        """
        Get comments on a LinkedIn post with cursor-based pagination.

        Endpoint: GET /rest/socialActions/{post_id}/comments
        Paginates using 'start' and 'count' params until limit reached
        or no more results.
        """
        self._ensure_connected()
        await self.rate_limiter.acquire()

        comments: List[Comment] = []
        page_size = min(limit, 50)
        start = 0

        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                while len(comments) < limit:
                    resp = await client.get(
                        f"{LINKEDIN_REST_BASE}/socialActions/{post_id}/comments",
                        params={
                            "start": start,
                            "count": page_size,
                        },
                        headers=_linkedin_headers(self._access_token),
                    )

                    if resp.status_code != 200:
                        if resp.status_code == 401:
                            raise PlatformAuthError("linkedin")
                        logger.warning(
                            f"LinkedIn: get_comments returned {resp.status_code} "
                            f"for post {post_id}"
                        )
                        break

                    data = resp.json()
                    elements = data.get("elements", [])

                    if not elements:
                        break  # No more comments

                    for c in elements:
                        created_time = c.get("created", {}).get("time")
                        created_at = None
                        if created_time:
                            try:
                                created_at = datetime.utcfromtimestamp(created_time / 1000)
                            except (ValueError, OSError):
                                pass

                        # Filter by 'since' if provided
                        if since and created_at and created_at < since:
                            continue

                        comments.append(Comment(
                            comment_id=c.get("$URN", c.get("id", "")),
                            post_id=post_id,
                            author_handle=c.get("actor", ""),
                            text=c.get("message", {}).get("text", ""),
                            created_at=created_at,
                            platform="linkedin",
                            raw_data=c,
                        ))

                    # Check if there are more pages
                    paging = data.get("paging", {})
                    total = paging.get("total", len(elements))
                    start += len(elements)

                    if start >= total or len(elements) < page_size:
                        break  # All pages consumed

                    # Rate-limit between pages
                    await self.rate_limiter.acquire()

        except (PlatformAuthError, PlatformRateLimitError):
            raise
        except Exception as e:
            logger.error(f"LinkedIn get_comments error: {e}")

        return comments[:limit]

    async def poll_all_post_comments(
        self,
        since: Optional[datetime] = None,
        limit: int = 100,
        max_posts: int = 10,
    ) -> List[Comment]:
        """
        Fetch comments across all recent own posts.
        Used by the SkyEye session engine during the observe phase
        to discover new engagement on LinkedIn content.

        Args:
            since: Only return comments created after this timestamp
            limit: Maximum total comments to return
            max_posts: Maximum number of own posts to scan
        """
        posts = await self.get_feed(limit=max_posts)
        all_comments: List[Comment] = []

        for post in posts:
            if len(all_comments) >= limit:
                break
            remaining = limit - len(all_comments)
            comments = await self.get_comments(
                post.item_id, since=since, limit=remaining
            )
            all_comments.extend(comments)

        return all_comments[:limit]

    @retry_on_failure(max_retries=2)
    async def get_mentions(self, since: Optional[datetime] = None,
                           limit: int = 50) -> List[Mention]:
        """LinkedIn mentions API is limited. Returns empty list."""
        return []

    # ── Engagement ──────────────────────────────────────────────────

    @retry_on_failure(max_retries=2)
    async def reply_to_comment(self, comment_id: str, text: str,
                                post_id: Optional[str] = None) -> ReplyResult:
        """Reply to a LinkedIn comment via versioned REST API."""
        self._ensure_connected()
        await self.rate_limiter.acquire()

        if not post_id:
            return ReplyResult(success=False, error="post_id required for LinkedIn replies",
                               action=ActionResult.FAILED)

        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.post(
                    f"{LINKEDIN_REST_BASE}/socialActions/{post_id}/comments",
                    json={
                        "actor": self._person_urn,
                        "message": {"text": text},
                        "parentComment": comment_id,
                    },
                    headers=_linkedin_headers(self._access_token, content_type=True),
                )

                if resp.status_code in (200, 201):
                    reply_urn = ""
                    try:
                        reply_data = resp.json()
                        reply_urn = reply_data.get("$URN", reply_data.get("id", ""))
                    except Exception:
                        reply_urn = resp.headers.get("x-restli-id", "")

                    return ReplyResult(
                        success=True,
                        reply_id=reply_urn,
                        action=ActionResult.SUCCESS,
                    )
                elif resp.status_code == 401:
                    raise PlatformAuthError("linkedin")
                elif resp.status_code == 429:
                    raise PlatformRateLimitError("linkedin")
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
        """Delete a LinkedIn comment (limited to own comments or page admin)."""
        self._ensure_connected()
        await self.rate_limiter.acquire()

        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.delete(
                    f"{LINKEDIN_REST_BASE}/socialActions/{post_id}/comments/{comment_id}",
                    headers=_linkedin_headers(self._access_token),
                )
                if resp.status_code == 204:
                    return ModerateResult(success=True, action_taken="deleted")
                elif resp.status_code == 401:
                    raise PlatformAuthError("linkedin")
                else:
                    return ModerateResult(
                        success=False,
                        error=f"Delete failed: {resp.status_code}",
                        action=ActionResult.FAILED,
                    )
        except (PlatformAuthError, PlatformRateLimitError):
            raise
        except Exception as e:
            return ModerateResult(success=False, error=str(e), action=ActionResult.FAILED)

    # ── Analytics (Pages Data Portability API) ──────────────────────

    async def get_analytics(self) -> PlatformAnalytics:
        """
        Get LinkedIn organization analytics via the Pages Data Portability API.

        Fetches:
          - Organization follower statistics
          - Share statistics (impressions, clicks, likes, comments, shares)
          - Page view statistics

        Requires r_organization_social and rw_organization_admin scopes
        (both already requested in the OAuth flow).
        """
        if not self._connected:
            return PlatformAnalytics(platform="linkedin")

        # Resolve org URN if we don't have it yet
        if not self._org_urn:
            await self._resolve_org_urn()

        if not self._org_urn:
            logger.debug("LinkedIn: No organization URN — returning person-level analytics")
            return await self._get_person_analytics()

        analytics = PlatformAnalytics(platform="linkedin")
        raw: Dict[str, Any] = {}

        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                # ── Follower statistics ──
                try:
                    follower_resp = await client.get(
                        f"{LINKEDIN_REST_BASE}/networkSizes/{self._org_urn}",
                        params={"edgeType": "CompanyFollowedByMember"},
                        headers=_linkedin_headers(self._access_token),
                    )
                    if follower_resp.status_code == 200:
                        follower_data = follower_resp.json()
                        analytics.followers = follower_data.get(
                            "firstDegreeSize", 0
                        )
                        raw["follower_data"] = follower_data
                except Exception as e:
                    logger.debug(f"LinkedIn: Follower stats error: {e}")

                # ── Share statistics (org-level engagement) ──
                try:
                    share_resp = await client.get(
                        f"{LINKEDIN_REST_BASE}/organizationalEntityShareStatistics",
                        params={
                            "q": "organizationalEntity",
                            "organizationalEntity": self._org_urn,
                        },
                        headers=_linkedin_headers(self._access_token),
                    )
                    if share_resp.status_code == 200:
                        share_data = share_resp.json()
                        elements = share_data.get("elements", [])
                        if elements:
                            totals = elements[0].get("totalShareStatistics", {})
                            analytics.total_views = totals.get("impressionCount", 0)
                            analytics.total_likes = totals.get("likeCount", 0)
                            analytics.total_comments = totals.get("commentCount", 0)
                            analytics.total_posts = totals.get("shareCount", 0)

                            # Compute engagement rate
                            impressions = totals.get("impressionCount", 0)
                            clicks = totals.get("clickCount", 0)
                            engagements = (
                                totals.get("likeCount", 0)
                                + totals.get("commentCount", 0)
                                + totals.get("shareCount", 0)
                                + clicks
                            )
                            if impressions > 0:
                                analytics.engagement_rate = round(
                                    engagements / impressions, 4
                                )

                            raw["share_statistics"] = totals
                except Exception as e:
                    logger.debug(f"LinkedIn: Share stats error: {e}")

                # ── Page statistics (views by section, visitors) ──
                try:
                    page_resp = await client.get(
                        f"{LINKEDIN_REST_BASE}/organizationPageStatistics",
                        params={
                            "q": "organization",
                            "organization": self._org_urn,
                        },
                        headers=_linkedin_headers(self._access_token),
                    )
                    if page_resp.status_code == 200:
                        page_data = page_resp.json()
                        elements = page_data.get("elements", [])
                        if elements:
                            page_stats = elements[0]
                            # Aggregate page views across all sections
                            total_views = 0
                            for view_data in page_stats.get("views", {}).get(
                                "allPageViews", {}).get("pageViews", []):
                                total_views += view_data.get("views", 0)

                            raw["page_statistics"] = page_stats
                            raw["total_page_views"] = total_views
                except Exception as e:
                    logger.debug(f"LinkedIn: Page stats error: {e}")

        except Exception as e:
            logger.error(f"LinkedIn analytics error: {e}")

        analytics.raw_data = raw
        return analytics

    async def _get_person_analytics(self) -> PlatformAnalytics:
        """
        Fallback analytics when no organization page is available.
        Returns basic profile-level data from own posts.
        """
        analytics = PlatformAnalytics(platform="linkedin")

        try:
            posts = await self.get_feed(limit=20)
            if posts:
                total_likes = sum(p.likes or 0 for p in posts)
                total_comments = sum(p.comments or 0 for p in posts)
                analytics.total_posts = len(posts)
                analytics.total_likes = total_likes
                analytics.total_comments = total_comments

                if posts:
                    analytics.top_post_id = max(
                        posts, key=lambda p: (p.likes or 0) + (p.comments or 0)
                    ).item_id

                # Approximate engagement rate from post data
                if analytics.total_posts > 0:
                    avg_engagement = (total_likes + total_comments) / analytics.total_posts
                    analytics.engagement_rate = round(avg_engagement / 100, 4)

                analytics.raw_data = {
                    "source": "person_posts",
                    "post_count": len(posts),
                }
        except Exception as e:
            logger.debug(f"LinkedIn: Person analytics fallback error: {e}")

        return analytics
