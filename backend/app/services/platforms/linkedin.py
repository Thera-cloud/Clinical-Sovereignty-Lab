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
from datetime import datetime, timedelta, timezone
from typing import Dict, Any, List, Optional
from urllib.parse import quote as _url_quote

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
LINKEDIN_API_VERSION = "202601"

# Token refresh proactive window — refresh if expiry is within this many days
PROACTIVE_REFRESH_DAYS = 7


def _linkedin_headers(access_token: str, content_type: bool = False) -> Dict[str, str]:
    """Standard headers for LinkedIn REST API calls."""
    headers = {
        "Authorization": f"Bearer {access_token}",
        "LinkedIn-Version": LINKEDIN_API_VERSION,
        "X-Restli-Protocol-Version": "2.0.0",
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
        self._org_urn: Optional[str] = None       # legacy; prefer _company_org_urn
        self._company_access_token: Optional[str] = None
        self._company_org_urn: Optional[str] = None
        self._community_token: Optional[str] = None

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
        now = datetime.now(timezone.utc)
        if token_expiry:
            if token_expiry.tzinfo is None:
                token_expiry = token_expiry.replace(tzinfo=timezone.utc)
        if token_expiry and token_expiry < now:
            logger.info("LinkedIn: DB expiry in the past, attempting refresh")
            if await self.refresh_token():
                tokens = await self._load_tokens() or {}
                self._access_token = tokens.get("access_token", self._access_token)
                self._person_urn = tokens.get("account_id", self._person_urn)
                token_expiry = tokens.get("token_expiry")
                if token_expiry and token_expiry.tzinfo is None:
                    token_expiry = token_expiry.replace(tzinfo=timezone.utc)
            else:
                logger.warning(
                    "LinkedIn: Refresh failed — validating stored access token anyway "
                    "(token_expiry in DB may be stale)"
                )

        # Proactive refresh: if within 7 days of expiry, refresh now
        if token_expiry:
            days_until_expiry = (token_expiry - now).days
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

                    # Load community + company tokens (separate OAuth apps)
                    await self._load_community_token()
                    await self._load_company_token()

                    # Personal row may still carry org_urn for analytics fallback
                    try:
                        tokens_fresh = await self._load_tokens() or {}
                        self._org_urn = tokens_fresh.get("org_urn") or None
                    except Exception as org_err:
                        logger.debug(f"LinkedIn: Org URN load deferred: {org_err}")

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
                    expiry = datetime.now(timezone.utc) + timedelta(
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

    async def _load_company_token(self) -> None:
        """Load company-page OAuth token from platform='linkedin_company'."""
        if not self.db_pool:
            return
        try:
            from app.services.skyeye_platform_base import TokenCipher
            async with self.db_pool.acquire() as conn:
                row = await conn.fetchrow(
                    "SELECT access_token, org_urn FROM skyeye_platform_tokens "
                    "WHERE platform = 'linkedin_company' "
                    "AND access_token IS NOT NULL AND access_token != ''",
                )
            if row and row["access_token"]:
                cipher = TokenCipher.get()
                self._company_access_token = cipher.decrypt(row["access_token"])
                self._company_org_urn = row.get("org_urn")
                logger.info("LinkedIn: Company page token loaded")
        except Exception as e:
            logger.debug("LinkedIn: No company page token available: %s", e)

    async def _load_community_token(self):
        """Load the Community Management API token from skyeye_platform_tokens.

        The community token is stored under platform='linkedin_community'
        and is used for socialActions endpoints (comments, reactions)
        which require the Community Management API product.
        """
        if not self.db_pool:
            return
        try:
            from app.services.skyeye_platform_base import TokenCipher
            async with self.db_pool.acquire() as conn:
                row = await conn.fetchrow(
                    "SELECT access_token FROM skyeye_platform_tokens "
                    "WHERE platform = 'linkedin_community' "
                    "AND access_token IS NOT NULL AND access_token != ''",
                )
                if row and row["access_token"]:
                    cipher = TokenCipher.get()
                    self._community_token = cipher.decrypt(row["access_token"])
                    logger.info("LinkedIn: Community Management token loaded")
        except Exception as e:
            logger.debug("LinkedIn: No community token available: %s", e)

    @property
    def _social_actions_token(self) -> str:
        """Token to use for socialActions endpoints (comments, reactions).

        Prefers the Community Management app token if available,
        falls back to the main posting token.
        """
        return self._community_token or self._access_token

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

        now = datetime.now(timezone.utc)
        if token_expiry.tzinfo is None:
            token_expiry = token_expiry.replace(tzinfo=timezone.utc)
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
            "scope": "openid profile email w_member_social",
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

                expiry = datetime.now(timezone.utc) + timedelta(
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

    async def _save_org_urn(self, org_urn: str) -> None:
        """Persist the organization URN into skyeye_platform_tokens.org_urn."""
        if not self.db_pool:
            return
        try:
            async with self.db_pool.acquire() as conn:
                await conn.execute(
                    "UPDATE skyeye_platform_tokens SET org_urn = $1, updated_at = NOW() "
                    "WHERE platform = $2",
                    org_urn, self.platform_name,
                )
            self._org_urn = org_urn
            logger.info(f"LinkedIn: Persisted org_urn {org_urn}")
        except Exception as e:
            logger.warning(f"LinkedIn: Failed to persist org_urn: {e}")

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
          - kwargs: post_as = "person" | "company" | "both"
            * "person"  — personal profile only (default)
            * "company" — company page only (requires org_urn + w_organization_social)
            * "both"    — posts to personal profile AND company page; returns the
                          personal PostResult but logs both post IDs

        Endpoint: POST /rest/posts (LinkedIn-Version: 202401)
        """
        self._ensure_connected()
        await self.rate_limiter.acquire()

        post_as: str = kwargs.get("post_as", "person")

        if not self._person_urn:
            return PostResult(success=False, error="No LinkedIn person URN",
                              platform="linkedin", action=ActionResult.FAILED)

        async def _publish_as(author_urn: str, token: str) -> PostResult:
            """Inner helper — publish one post for the given author URN."""
            post_body: Dict[str, Any] = {
                "author": author_urn,
                "commentary": text,
                "visibility": "PUBLIC",
                "distribution": {
                    "feedDistribution": "MAIN_FEED",
                    "targetEntities": [],
                    "thirdPartyDistributionChannels": [],
                },
                "lifecycleState": "PUBLISHED",
            }
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
                    headers=_linkedin_headers(token, content_type=True),
                )
                if resp.status_code in (200, 201):
                    post_urn = resp.headers.get(
                        "x-restli-id",
                        resp.headers.get("X-RestLi-Id", "")
                    )
                    if not post_urn:
                        try:
                            post_urn = resp.json().get("id", "")
                        except Exception:
                            pass
                    post_url = (
                        f"https://www.linkedin.com/feed/update/{post_urn}/"
                        if post_urn else None
                    )
                    logger.info(f"LinkedIn: Published post {post_urn} as {author_urn}")
                    return PostResult(
                        success=True, post_id=post_urn, post_url=post_url,
                        platform="linkedin",
                    )
                elif resp.status_code == 401:
                    raise PlatformAuthError("linkedin")
                elif resp.status_code == 429:
                    raise PlatformRateLimitError("linkedin")
                else:
                    try:
                        err_msg = resp.json().get("message", f"Post failed: {resp.status_code}")
                    except Exception:
                        err_msg = f"Post failed: {resp.status_code}"
                    logger.error(f"LinkedIn: Post failed as {author_urn}: {err_msg}")
                    return PostResult(
                        success=False, error=err_msg,
                        platform="linkedin", action=ActionResult.FAILED,
                    )

        try:
            publish_targets: List[tuple] = []
            if post_as in ("person", "both"):
                if self._person_urn and self._access_token:
                    publish_targets.append((self._person_urn, self._access_token))
            if post_as in ("company", "both"):
                company_urn = self._company_org_urn or self._org_urn
                company_token = self._company_access_token
                if company_urn and company_token:
                    publish_targets.append((company_urn, company_token))
                elif post_as == "company":
                    return PostResult(
                        success=False,
                        error=(
                            "Company LinkedIn OAuth not connected. "
                            "Authorize SkyEye → LinkedIn Company Page (Engine4)."
                        ),
                        platform="linkedin",
                        action=ActionResult.FAILED,
                    )
                elif post_as == "both" and not company_token:
                    logger.warning(
                        "LinkedIn: post_as=both but company token missing; posting personal only"
                    )

            if not publish_targets:
                return PostResult(
                    success=False, error="No author URNs resolved",
                    platform="linkedin", action=ActionResult.FAILED,
                )

            first_result: Optional[PostResult] = None
            for urn, token in publish_targets:
                result = await _publish_as(urn, token)
                if first_result is None:
                    first_result = result

            return first_result or PostResult(
                success=False, error="No author URNs resolved",
                platform="linkedin", action=ActionResult.FAILED,
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
            encoded_post_id = _url_quote(post_id, safe="")
            async with httpx.AsyncClient(timeout=15.0) as client:
                while len(comments) < limit:
                    resp = await client.get(
                        f"{LINKEDIN_REST_BASE}/socialActions/{encoded_post_id}/comments",
                        params={
                            "start": start,
                            "count": page_size,
                        },
                        headers=_linkedin_headers(self._social_actions_token),
                    )

                    if resp.status_code != 200:
                        if resp.status_code == 401:
                            raise PlatformAuthError("linkedin")
                        if resp.status_code == 403:
                            logger.debug(
                                "LinkedIn: get_comments 403 for %s (Community Management API not enabled)",
                                post_id,
                            )
                            break
                        body = ""
                        try:
                            body = resp.json().get("message", resp.text[:200])
                        except Exception:
                            body = resp.text[:200]
                        logger.warning(
                            "LinkedIn: get_comments %s for post %s — %s",
                            resp.status_code, post_id, body,
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
            encoded_post_id = _url_quote(post_id, safe="")
            async with httpx.AsyncClient(timeout=15.0) as client:
                body = {
                    "actor": self._person_urn,
                    "object": post_id,
                    "message": {"text": text},
                    "parentComment": comment_id,
                }
                resp = await client.post(
                    f"{LINKEDIN_REST_BASE}/socialActions/{encoded_post_id}/comments",
                    json=body,
                    headers=_linkedin_headers(self._social_actions_token, content_type=True),
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
                elif resp.status_code == 403:
                    err_msg = ""
                    try:
                        err_msg = resp.json().get("message", "")
                    except Exception:
                        pass
                    return ReplyResult(
                        success=False,
                        error=f"Permission denied (Community Management API required): {err_msg}",
                        action=ActionResult.FAILED,
                    )
                else:
                    err_body = ""
                    try:
                        err_body = resp.json().get("message", resp.text[:200])
                    except Exception:
                        err_body = resp.text[:200]
                    return ReplyResult(
                        success=False,
                        error=f"Reply failed: {resp.status_code} — {err_body}",
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
            encoded_post_id = _url_quote(post_id or "", safe="")
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.delete(
                    f"{LINKEDIN_REST_BASE}/socialActions/{encoded_post_id}/comments/{comment_id}",
                    headers=_linkedin_headers(self._social_actions_token),
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

    # ── Notification / Engagement Discovery ────────────────────────

    @retry_on_failure(max_retries=2)
    async def get_post_reactions(self, post_id: str, limit: int = 100) -> List[Dict]:
        """Get likes/reactions on a LinkedIn post via socialActions."""
        self._ensure_connected()
        await self.rate_limiter.acquire()

        reactions: List[Dict] = []
        try:
            encoded_post_id = _url_quote(post_id, safe="")
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.get(
                    f"{LINKEDIN_REST_BASE}/socialActions/{encoded_post_id}/likes",
                    params={"start": 0, "count": min(limit, 100)},
                    headers=_linkedin_headers(self._social_actions_token),
                )
                if resp.status_code == 200:
                    for el in resp.json().get("elements", []):
                        reactions.append({
                            "actor": el.get("actor", ""),
                            "created_at": el.get("created", {}).get("time"),
                        })
                elif resp.status_code == 401:
                    raise PlatformAuthError("linkedin")
                elif resp.status_code == 429:
                    raise PlatformRateLimitError("linkedin")
        except (PlatformAuthError, PlatformRateLimitError):
            raise
        except Exception as e:
            logger.error(f"LinkedIn get_post_reactions error: {e}")

        return reactions

    async def get_follower_count(self) -> int:
        """Get current follower/connection count for delta tracking."""
        if not self._connected:
            return 0

        urn = self._org_urn or self._person_urn
        if not urn:
            return 0

        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.get(
                    f"{LINKEDIN_REST_BASE}/networkSizes/{urn}",
                    params={"edgeType": "CompanyFollowedByMember"},
                    headers=_linkedin_headers(self._access_token),
                )
                if resp.status_code == 200:
                    return resp.json().get("firstDegreeSize", 0)
        except Exception as e:
            logger.error(f"LinkedIn get_follower_count error: {e}")
        return 0

    # ── Analytics (Pages Data Portability API) ──────────────────────

    async def get_analytics(self) -> PlatformAnalytics:
        """
        Get LinkedIn organization analytics via the Pages Data Portability API.

        Fetches:
          - Organization follower statistics
          - Share statistics (impressions, clicks, likes, comments, shares)
          - Page view statistics

        Organization-level analytics require r_organization_social and
        rw_organization_admin scopes (Marketing Developer Platform approval).
        Falls back to person-level analytics when org scopes unavailable.
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
        Fetches connection count from the personal profile and post engagement.
        """
        analytics = PlatformAnalytics(platform="linkedin")

        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                # Fetch connection count via networkSizes (personal profile)
                if self._person_urn:
                    try:
                        conn_resp = await client.get(
                            f"{LINKEDIN_REST_BASE}/networkSizes/{self._person_urn}",
                            params={"edgeType": "CompanyFollowedByMember"},
                            headers=_linkedin_headers(self._access_token),
                        )
                        if conn_resp.status_code == 200:
                            analytics.followers = conn_resp.json().get("firstDegreeSize", 0)
                    except Exception:
                        pass

                    if analytics.followers == 0:
                        try:
                            conn_resp2 = await client.get(
                                f"{LINKEDIN_API_BASE}/connections?q=viewer&start=0&count=0",
                                headers={"Authorization": f"Bearer {self._access_token}"},
                            )
                            if conn_resp2.status_code == 200:
                                data = conn_resp2.json()
                                analytics.followers = data.get("_total", 0) or data.get("paging", {}).get("total", 0)
                        except Exception:
                            pass

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

                if analytics.total_posts > 0:
                    avg_engagement = (total_likes + total_comments) / analytics.total_posts
                    analytics.engagement_rate = round(avg_engagement / 100, 4)

                analytics.raw_data = {
                    "source": "person_profile",
                    "post_count": len(posts),
                    "connections": analytics.followers,
                }
        except Exception as e:
            logger.debug(f"LinkedIn: Person analytics fallback error: {e}")

        return analytics


class LinkedInCompanyAdapter(LinkedInAdapter):
    """LinkedIn adapter for company-page posting (Marketing Developer Platform).

    Uses LINKEDIN_COMPANY_CLIENT_ID/SECRET (Engine4) and stores its token
    under platform='linkedin_company'. Personal posting uses platform='linkedin'.
    """

    def __init__(self, db_pool, rate_limit_seconds: float = 20.0):
        SocialPlatformAdapter.__init__(self, "linkedin_company", db_pool, rate_limit_seconds)
        self.client_id = getattr(settings, "LINKEDIN_COMPANY_CLIENT_ID", "")
        self.client_secret = getattr(settings, "LINKEDIN_COMPANY_CLIENT_SECRET", "")
        self._access_token: Optional[str] = None
        self._person_urn: Optional[str] = None
        self._org_urn: Optional[str] = None
        self._company_access_token: Optional[str] = None
        self._company_org_urn: Optional[str] = None
        self._community_token: Optional[str] = None

    @property
    def _has_credentials(self) -> bool:
        return bool(self.client_id and self.client_secret)

    async def get_oauth_url(self, redirect_uri: str) -> str:
        import urllib.parse
        params = {
            "response_type": "code",
            "client_id": self.client_id,
            "redirect_uri": redirect_uri,
            "scope": "openid profile email w_organization_social",
            "state": "skyeye_linkedin_company",
        }
        return f"{LINKEDIN_AUTH_URL}?{urllib.parse.urlencode(params)}"

    async def handle_oauth_callback(self, code: str, redirect_uri: str, **kwargs) -> bool:
        ok = await LinkedInAdapter.handle_oauth_callback(self, code, redirect_uri)
        if ok:
            try:
                org_urn = await self._resolve_org_urn()
                if org_urn:
                    await self._save_org_urn(org_urn)
            except Exception as e:
                logger.warning("LinkedIn company OAuth: org URN resolution failed: %s", e)
        return ok


class LinkedInCommunityAdapter(LinkedInAdapter):
    """LinkedIn adapter for the Community Management API app.

    Uses separate OAuth credentials (LINKEDIN_COMMUNITY_CLIENT_ID/SECRET)
    and stores its token under platform='linkedin_community' in
    skyeye_platform_tokens. This token is also loaded by the main
    LinkedInAdapter for socialActions calls (comments, reactions).
    """

    def __init__(self, db_pool, rate_limit_seconds: float = 20.0):
        SocialPlatformAdapter.__init__(self, "linkedin_community", db_pool, rate_limit_seconds)
        self.client_id = getattr(settings, "LINKEDIN_COMMUNITY_CLIENT_ID", "")
        self.client_secret = getattr(settings, "LINKEDIN_COMMUNITY_CLIENT_SECRET", "")
        self._access_token: Optional[str] = None
        self._person_urn: Optional[str] = None
        self._org_urn: Optional[str] = None
        self._community_token: Optional[str] = None

    @property
    def _has_credentials(self) -> bool:
        return bool(self.client_id and self.client_secret)

    async def get_oauth_url(self, redirect_uri: str) -> str:
        import urllib.parse
        params = {
            "response_type": "code",
            "client_id": self.client_id,
            "redirect_uri": redirect_uri,
            "scope": "openid profile email w_member_social",
            "state": "skyeye_linkedin_community",
        }
        return f"{LINKEDIN_AUTH_URL}?{urllib.parse.urlencode(params)}"
