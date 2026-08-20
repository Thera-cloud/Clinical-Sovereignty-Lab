"""
LITTLE NATE — SkyEye Platform Abstraction Layer
Abstract base class and shared types for all social media platform adapters.

Every platform adapter (TikTok, Instagram, YouTube, Reddit, LinkedIn,
Facebook, Pinterest) implements SocialPlatformAdapter to provide a
unified interface for the session engine, content generator, and monitor.

SAFETY: All outbound content is filtered before reaching any adapter.
"""

import asyncio
import functools
import logging
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional

try:
    from cryptography.fernet import Fernet, InvalidToken
except ImportError:
    Fernet = None  # type: ignore
    InvalidToken = Exception  # type: ignore

logger = logging.getLogger("skyeye.platforms")


# =============================================================================
# SHARED DATA TYPES
# =============================================================================

class ContentType(str, Enum):
    POST = "post"
    REPLY = "reply"
    STORY = "story"
    REEL = "reel"
    VIDEO = "video"
    PIN = "pin"
    COMMUNITY_POST = "community_post"
    ARTICLE = "article"


class ControlMode(str, Enum):
    FULL = "full"               # Little Nate posts autonomously
    APPROVAL = "approval"       # Posts queue for admin approval
    OBSERVATION = "observation"  # Read-only, no posting


class ConnectionStatus(str, Enum):
    CONNECTED = "connected"
    DISCONNECTED = "disconnected"
    EXPIRED = "expired"
    REVOKED = "revoked"
    ERROR = "error"


class ActionResult(str, Enum):
    SUCCESS = "success"
    FAILED = "failed"
    SKIPPED = "skipped"
    NOT_SUPPORTED = "not_supported"
    RATE_LIMITED = "rate_limited"
    AUTH_EXPIRED = "auth_expired"


@dataclass
class PostResult:
    """Result of posting content to a platform."""
    success: bool
    post_id: Optional[str] = None       # Platform's native post ID
    post_url: Optional[str] = None      # Direct URL to the post
    error: Optional[str] = None
    platform: str = ""
    action: ActionResult = ActionResult.SUCCESS


@dataclass
class Comment:
    """A comment or reply on a post."""
    comment_id: str
    post_id: str
    author_handle: str
    author_name: str = ""
    author_id: str = ""
    text: str = ""
    created_at: Optional[datetime] = None
    like_count: int = 0
    reply_count: int = 0
    is_reply: bool = False
    parent_comment_id: Optional[str] = None
    platform: str = ""
    raw_data: Dict[str, Any] = field(default_factory=dict)


@dataclass
class Mention:
    """A mention or tag of Little Nate on a platform."""
    mention_id: str
    author_handle: str
    author_name: str = ""
    author_id: str = ""
    text: str = ""
    context_url: Optional[str] = None   # URL where the mention occurred
    mention_type: str = "mention"        # mention/tag/quote/repost
    created_at: Optional[datetime] = None
    platform: str = ""
    raw_data: Dict[str, Any] = field(default_factory=dict)


@dataclass
class UserInfo:
    """Public info about a social media user."""
    user_id: str
    handle: str
    display_name: str = ""
    bio: str = ""
    follower_count: int = 0
    following_count: int = 0
    post_count: int = 0
    is_verified: bool = False
    account_created: Optional[datetime] = None
    profile_url: Optional[str] = None
    platform: str = ""
    raw_data: Dict[str, Any] = field(default_factory=dict)


@dataclass
class FeedItem:
    """An item from a platform's feed (post, video, etc.)."""
    item_id: str
    author_handle: str
    author_name: str = ""
    text: str = ""
    media_url: Optional[str] = None
    item_type: str = "post"
    like_count: int = 0
    comment_count: int = 0
    share_count: int = 0
    view_count: int = 0
    created_at: Optional[datetime] = None
    url: Optional[str] = None
    platform: str = ""
    raw_data: Dict[str, Any] = field(default_factory=dict)


@dataclass
class TrendingTopic:
    """A trending topic or hashtag on a platform."""
    name: str
    description: str = ""
    post_count: int = 0
    category: str = ""
    url: Optional[str] = None
    platform: str = ""


@dataclass
class PlatformAnalytics:
    """Aggregated analytics for Little Nate's account on a platform."""
    followers: int = 0
    following: int = 0
    total_posts: int = 0
    total_likes: int = 0
    total_comments: int = 0
    total_views: int = 0
    engagement_rate: float = 0.0
    follower_growth_7d: int = 0
    top_post_id: Optional[str] = None
    period: str = "7d"
    platform: str = ""
    raw_data: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ReplyResult:
    """Result of replying to a comment."""
    success: bool
    reply_id: Optional[str] = None
    error: Optional[str] = None
    action: ActionResult = ActionResult.SUCCESS


@dataclass
class ModerateResult:
    """Result of a moderation action (delete/hide/block)."""
    success: bool
    action_taken: str = ""   # deleted/hidden/blocked/reported
    error: Optional[str] = None
    action: ActionResult = ActionResult.SUCCESS


# =============================================================================
# TOKEN ENCRYPTION (Fernet symmetric — AES-128-CBC + HMAC-SHA256)
# =============================================================================

class TokenEncryptionError(RuntimeError):
    """Raised in strict mode when an OAuth token cannot be encrypted safely."""


class TokenCipher:
    """
    Encrypt / decrypt OAuth tokens at rest using Fernet.

    Behaviour:
    - If SKYEYE_TOKEN_ENCRYPTION_KEY is set → full encryption.
    - decrypt() auto-detects legacy plaintext tokens (they won't start
      with 'gAAAAA') and returns them unchanged, so existing DB rows
      don't break after enabling encryption.

    Fail-closed policy (Slice 0.5):
    - In production (ENVIRONMENT=production) or when ENCRYPTION_STRICT=true,
      encrypt() raises TokenEncryptionError if the key is missing or the
      encryption operation fails. This prevents an OAuth token from being
      silently written to disk in plaintext when the operator expected AES.
    - Dev / test / staging keeps the historic plaintext passthrough so local
      runs don't need a key configured.
    """

    _instance: Optional["TokenCipher"] = None
    _fernet: Optional[Any] = None
    _warned: bool = False
    _strict: bool = False

    @classmethod
    def get(cls) -> "TokenCipher":
        """Singleton accessor — lazy-inits on first call."""
        if cls._instance is None:
            cls._instance = cls()
            cls._instance._init_cipher()
        return cls._instance

    def _init_cipher(self):
        import os as _os

        try:
            from app.config import settings  # Docker / production
        except ImportError:
            try:
                from backend.app.config import settings  # local dev fallback
            except ImportError:
                settings = None  # tests / bare-metal — env-only

        # Prefer live env vars over cached pydantic settings so tests and
        # runtime overrides both work. Settings is only a fallback.
        _env = (
            _os.getenv("ENVIRONMENT")
            or (getattr(settings, "ENVIRONMENT", "") if settings else "")
            or ""
        ).strip().lower()
        _override = (_os.getenv("ENCRYPTION_STRICT") or "").strip().lower()
        if _override in ("true", "1", "yes", "on"):
            self._strict = True
        elif _override in ("false", "0", "no", "off"):
            self._strict = False
        else:
            self._strict = _env == "production"

        key = (
            _os.getenv("SKYEYE_TOKEN_ENCRYPTION_KEY")
            or (getattr(settings, "SKYEYE_TOKEN_ENCRYPTION_KEY", "") if settings else "")
            or ""
        )
        if key and Fernet is not None:
            try:
                self._fernet = Fernet(key.encode() if isinstance(key, str) else key)
                logger.info(
                    "TokenCipher: Fernet encryption enabled (strict=%s)", self._strict
                )
            except Exception as exc:
                logger.error(f"TokenCipher: Invalid encryption key — {exc}")
                self._fernet = None
        else:
            if not self._warned:
                if Fernet is None:
                    msg = (
                        "TokenCipher: cryptography package not installed"
                    )
                else:
                    msg = "TokenCipher: SKYEYE_TOKEN_ENCRYPTION_KEY is empty"
                if self._strict:
                    logger.error("%s — writes will fail in strict mode", msg)
                else:
                    logger.warning("%s — tokens will be stored in PLAINTEXT", msg)
                self._warned = True
            self._fernet = None

    # ── public API ──────────────────────────────────────────────────

    def encrypt(self, plaintext: str) -> str:
        """Encrypt a token string.

        Strict mode: raises TokenEncryptionError if the key is missing or
        encryption fails. Non-strict mode: falls back to plaintext with a
        warning (legacy dev/test behavior).
        """
        if not plaintext:
            return plaintext
        if self._fernet is None:
            if self._strict:
                raise TokenEncryptionError(
                    "TokenCipher.encrypt called in strict mode without a valid key"
                )
            return plaintext
        try:
            return self._fernet.encrypt(plaintext.encode()).decode()
        except Exception as exc:
            if self._strict:
                logger.error("TokenCipher.encrypt failed in strict mode: %s", exc)
                raise TokenEncryptionError(f"TokenCipher.encrypt failed: {exc}") from exc
            logger.error(f"TokenCipher.encrypt failed: {exc}")
            return plaintext

    def decrypt(self, ciphertext: str) -> str:
        """
        Decrypt a token string.
        Gracefully handles legacy plaintext values (they won't start with 'gAAAAA').
        """
        if not ciphertext:
            return ciphertext
        if self._fernet is None:
            return ciphertext
        # Fernet tokens always start with 'gAAAAA'
        if not ciphertext.startswith("gAAAAA"):
            return ciphertext  # legacy plaintext — pass through
        try:
            return self._fernet.decrypt(ciphertext.encode()).decode()
        except InvalidToken:
            logger.warning(
                "TokenCipher.decrypt: InvalidToken — returning raw value "
                "(may be legacy plaintext or wrong key)"
            )
            return ciphertext
        except Exception as exc:
            logger.error(f"TokenCipher.decrypt failed: {exc}")
            return ciphertext

    def is_strict(self) -> bool:
        """Whether this cipher instance is running in fail-closed strict mode."""
        return bool(self._strict)


# =============================================================================
# RATE LIMITER
# =============================================================================

class PlatformRateLimiter:
    """
    Per-platform rate limiter using token bucket algorithm.
    Ensures Little Nate respects each platform's API rate limits
    and doesn't behave unnaturally fast.
    """

    def __init__(self, platform: str, min_interval_seconds: float = 10.0,
                 max_burst: int = 3):
        self.platform = platform
        self.min_interval = min_interval_seconds
        self.max_burst = max_burst
        self._tokens = max_burst
        self._last_refill = time.monotonic()
        self._lock = asyncio.Lock()

    async def acquire(self) -> bool:
        """Wait until a rate limit token is available. Returns True when ready."""
        async with self._lock:
            now = time.monotonic()
            elapsed = now - self._last_refill
            # Refill tokens based on elapsed time
            new_tokens = elapsed / self.min_interval
            self._tokens = min(self.max_burst, self._tokens + new_tokens)
            self._last_refill = now

            if self._tokens >= 1.0:
                self._tokens -= 1.0
                return True
            else:
                # Wait until a token is available
                wait_time = (1.0 - self._tokens) * self.min_interval
                await asyncio.sleep(wait_time)
                self._tokens = 0.0
                self._last_refill = time.monotonic()
                return True

    @property
    def tokens_available(self) -> float:
        """Current approximate tokens available."""
        now = time.monotonic()
        elapsed = now - self._last_refill
        return min(self.max_burst, self._tokens + elapsed / self.min_interval)


# =============================================================================
# RETRY DECORATOR
# =============================================================================

def retry_on_failure(max_retries: int = 3, base_delay: float = 1.0,
                     max_delay: float = 30.0):
    """
    Retry decorator with exponential backoff for platform API calls.
    Does NOT retry on auth failures — those should be handled by re-auth flow.
    """
    def decorator(func):
        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            last_exception = None
            for attempt in range(max_retries + 1):
                try:
                    return await func(*args, **kwargs)
                except PlatformAuthError:
                    # Auth errors should not be retried — bubble up
                    raise
                except PlatformNotConnectedError:
                    # Not connected — no point retrying
                    raise
                except PlatformRateLimitError as e:
                    # Rate limited — wait the suggested time if available
                    wait = min(e.retry_after or (base_delay * (2 ** attempt)),
                               max_delay)
                    logger.warning(
                        f"Rate limited on {func.__name__}, "
                        f"waiting {wait:.1f}s (attempt {attempt + 1})"
                    )
                    await asyncio.sleep(wait)
                    last_exception = e
                except Exception as e:
                    last_exception = e
                    if attempt < max_retries:
                        delay = min(base_delay * (2 ** attempt), max_delay)
                        logger.warning(
                            f"Retrying {func.__name__} in {delay:.1f}s "
                            f"(attempt {attempt + 1}/{max_retries}): {e}"
                        )
                        await asyncio.sleep(delay)
            raise last_exception
        return wrapper
    return decorator


# =============================================================================
# CUSTOM EXCEPTIONS
# =============================================================================

class PlatformError(Exception):
    """Base exception for platform adapter errors."""
    pass


class PlatformNotConnectedError(PlatformError):
    """Platform credentials are not configured or tokens are missing."""
    def __init__(self, platform: str):
        self.platform = platform
        super().__init__(f"Platform '{platform}' is not connected. "
                         f"Configure OAuth credentials and connect first.")


class PlatformAuthError(PlatformError):
    """Authentication or token refresh failed."""
    def __init__(self, platform: str, detail: str = ""):
        self.platform = platform
        self.detail = detail
        super().__init__(f"Auth error on '{platform}': {detail}")


class PlatformRateLimitError(PlatformError):
    """API rate limit exceeded."""
    def __init__(self, platform: str, retry_after: Optional[float] = None):
        self.platform = platform
        self.retry_after = retry_after
        super().__init__(
            f"Rate limited on '{platform}'"
            + (f", retry after {retry_after}s" if retry_after else "")
        )


class PlatformAPIError(PlatformError):
    """Generic API error from the platform."""
    def __init__(self, platform: str, status_code: int = 0, detail: str = ""):
        self.platform = platform
        self.status_code = status_code
        self.detail = detail
        super().__init__(f"API error on '{platform}' ({status_code}): {detail}")


# =============================================================================
# ABSTRACT BASE ADAPTER
# =============================================================================

class SocialPlatformAdapter(ABC):
    """
    Abstract base class for all social media platform adapters.

    Every platform (TikTok, Instagram, YouTube, Reddit, LinkedIn,
    Facebook, Pinterest) implements this interface so the session engine,
    content generator, and monitor can interact with any platform
    through the same API.

    IMPORTANT:
    - All outbound content MUST be safety-filtered BEFORE calling post/reply
    - All adapters MUST respect rate limits via self.rate_limiter
    - All adapters MUST handle token expiry gracefully
    """

    def __init__(self, platform_name: str, db_pool, rate_limit_seconds: float = 10.0):
        self.platform_name = platform_name
        self.db_pool = db_pool
        self.rate_limiter = PlatformRateLimiter(
            platform_name, min_interval_seconds=rate_limit_seconds
        )
        self._connected = False
        self._last_error: Optional[str] = None

    @property
    def is_connected(self) -> bool:
        """Whether this adapter has valid credentials and is ready to use."""
        return self._connected

    @property
    def last_error(self) -> Optional[str]:
        """Last error message, if any."""
        return self._last_error

    # ── Authentication ──────────────────────────────────────────────

    @abstractmethod
    async def authenticate(self) -> bool:
        """
        Authenticate with the platform using stored credentials/tokens.
        Returns True if authentication succeeded.
        Sets self._connected = True on success.
        """
        ...

    @abstractmethod
    async def refresh_token(self) -> bool:
        """
        Refresh the OAuth access token using the refresh token.
        Returns True if refresh succeeded.
        Updates token in skyeye_platform_tokens table.
        """
        ...

    async def get_oauth_url(self, redirect_uri: str) -> str:
        """
        Generate the OAuth authorization URL for this platform.
        Override in subclass to support OAuth connect flow.
        """
        raise NotImplementedError(
            f"OAuth flow not implemented for {self.platform_name}"
        )

    async def handle_oauth_callback(self, code: str, redirect_uri: str) -> bool:
        """
        Handle the OAuth callback with the authorization code.
        Exchanges code for tokens and stores them.
        Override in subclass.
        """
        raise NotImplementedError(
            f"OAuth callback not implemented for {self.platform_name}"
        )

    # ── Content Publishing ──────────────────────────────────────────

    @abstractmethod
    async def post_content(self, text: str, media_url: Optional[str] = None,
                           content_type: ContentType = ContentType.POST,
                           **kwargs) -> PostResult:
        """
        Publish content to the platform.

        Args:
            text: The post text (already safety-filtered)
            media_url: Optional URL to image/video attachment
            content_type: Type of content being posted
            **kwargs: Platform-specific options (hashtags, subreddit, board, etc.)

        Returns:
            PostResult with success status, post_id, and post_url
        """
        ...

    # ── Reading / Monitoring ────────────────────────────────────────

    @abstractmethod
    async def get_comments(self, post_id: str,
                           since: Optional[datetime] = None,
                           limit: int = 50) -> List[Comment]:
        """
        Get comments on a specific post.
        If since is provided, only return comments after that timestamp.
        """
        ...

    @abstractmethod
    async def get_mentions(self, since: Optional[datetime] = None,
                           limit: int = 50) -> List[Mention]:
        """
        Get recent mentions/tags of Little Nate on this platform.
        """
        ...

    @abstractmethod
    async def get_feed(self, limit: int = 20) -> List[FeedItem]:
        """
        Get the platform's feed (trending, home feed, or relevant content).
        Used during the browse phase of sessions.
        """
        ...

    async def get_trending(self, limit: int = 10) -> List[TrendingTopic]:
        """
        Get trending topics/hashtags. Not all platforms support this.
        Returns empty list by default.
        """
        return []

    async def get_own_posts(self, limit: int = 20) -> List[FeedItem]:
        """
        Get Little Nate's own recent posts on this platform.
        Default implementation returns empty list — override in subclass.
        """
        return []

    # ── Engagement ──────────────────────────────────────────────────

    @abstractmethod
    async def reply_to_comment(self, comment_id: str, text: str,
                                post_id: Optional[str] = None) -> ReplyResult:
        """
        Reply to a comment. The text should already be safety-filtered.
        Some platforms require the post_id in addition to comment_id.
        """
        ...

    # ── Moderation ──────────────────────────────────────────────────

    @abstractmethod
    async def delete_comment(self, comment_id: str,
                              post_id: Optional[str] = None) -> ModerateResult:
        """
        Delete a comment on one of Little Nate's posts.
        Returns success status and the action taken.
        """
        ...

    async def hide_comment(self, comment_id: str,
                           post_id: Optional[str] = None) -> ModerateResult:
        """
        Hide a comment (make it invisible to others but not deleted).
        Not all platforms support this — default returns not_supported.
        """
        return ModerateResult(
            success=False,
            action_taken="",
            error="hide_comment not supported on this platform",
            action=ActionResult.NOT_SUPPORTED
        )

    async def block_user(self, user_id: str) -> ModerateResult:
        """
        Block a user on this platform.
        Default returns not_supported — override in subclass.
        """
        return ModerateResult(
            success=False,
            action_taken="",
            error="block_user not supported on this platform",
            action=ActionResult.NOT_SUPPORTED
        )

    async def report_content(self, content_id: str,
                              reason: str = "spam") -> ModerateResult:
        """
        Report content to the platform for review.
        Default returns not_supported — override in subclass.
        """
        return ModerateResult(
            success=False,
            action_taken="",
            error="report_content not supported on this platform",
            action=ActionResult.NOT_SUPPORTED
        )

    # ── User Info ───────────────────────────────────────────────────

    async def get_user_info(self, user_id: str) -> Optional[UserInfo]:
        """
        Get public info about a user on this platform.
        Default returns None — override in subclass.
        """
        return None

    # ── Analytics ───────────────────────────────────────────────────

    async def get_analytics(self) -> PlatformAnalytics:
        """
        Get aggregated analytics for Little Nate's account.
        Default returns empty analytics — override in subclass.
        """
        return PlatformAnalytics(platform=self.platform_name)

    # ── Token Storage Helpers ───────────────────────────────────────

    async def _load_tokens(self) -> Optional[Dict[str, Any]]:
        """Load stored tokens from skyeye_platform_tokens table.
        Decrypts access_token and refresh_token transparently."""
        if not self.db_pool:
            return None
        try:
            async with self.db_pool.acquire() as conn:
                row = await conn.fetchrow(
                    "SELECT * FROM skyeye_platform_tokens WHERE platform = $1",
                    self.platform_name
                )
                if not row:
                    return None
                data = dict(row)
                cipher = TokenCipher.get()
                if data.get("access_token"):
                    data["access_token"] = cipher.decrypt(data["access_token"])
                if data.get("refresh_token"):
                    data["refresh_token"] = cipher.decrypt(data["refresh_token"])
                return data
        except Exception as e:
            logger.error(f"Failed to load tokens for {self.platform_name}: {e}")
            return None

    async def _save_tokens(self, access_token: str,
                           refresh_token: Optional[str] = None,
                           token_expiry: Optional[datetime] = None,
                           scopes: Optional[str] = None,
                           account_id: Optional[str] = None,
                           account_name: Optional[str] = None):
        """Save tokens to skyeye_platform_tokens table.
        Encrypts access_token and refresh_token before writing."""
        if not self.db_pool:
            return
        try:
            cipher = TokenCipher.get()
            enc_access = cipher.encrypt(access_token)
            enc_refresh = cipher.encrypt(refresh_token) if refresh_token else refresh_token
            async with self.db_pool.acquire() as conn:
                await conn.execute("""
                    INSERT INTO skyeye_platform_tokens
                        (platform, access_token, refresh_token, token_expiry,
                         scopes, account_id, account_name, status,
                         last_refreshed, updated_at)
                    VALUES ($1, $2, $3, $4, $5, $6, $7, 'connected', NOW(), NOW())
                    ON CONFLICT (platform) DO UPDATE SET
                        access_token = $2,
                        refresh_token = COALESCE($3, skyeye_platform_tokens.refresh_token),
                        token_expiry = $4,
                        scopes = COALESCE($5, skyeye_platform_tokens.scopes),
                        account_id = COALESCE($6, skyeye_platform_tokens.account_id),
                        account_name = COALESCE($7, skyeye_platform_tokens.account_name),
                        status = 'connected',
                        error_message = NULL,
                        last_refreshed = NOW(),
                        updated_at = NOW()
                """, self.platform_name, enc_access, enc_refresh,
                     token_expiry, scopes, account_id, account_name)
        except Exception as e:
            logger.error(f"Failed to save tokens for {self.platform_name}: {e}")

    async def _update_token_status(self, status: str,
                                    error_message: Optional[str] = None):
        """Update the connection status in skyeye_platform_tokens."""
        if not self.db_pool:
            return
        try:
            async with self.db_pool.acquire() as conn:
                await conn.execute("""
                    UPDATE skyeye_platform_tokens
                    SET status = $2, error_message = $3, updated_at = NOW()
                    WHERE platform = $1
                """, self.platform_name, status, error_message)
        except Exception as e:
            logger.error(f"Failed to update token status for {self.platform_name}: {e}")

    # ── Utility ─────────────────────────────────────────────────────

    def _ensure_connected(self):
        """Raise PlatformNotConnectedError if not authenticated."""
        if not self._connected:
            raise PlatformNotConnectedError(self.platform_name)

    async def _rate_limited_call(self, coro):
        """Execute an async call after acquiring a rate limit token."""
        await self.rate_limiter.acquire()
        return await coro

    def __repr__(self):
        status = "connected" if self._connected else "disconnected"
        return f"<{self.__class__.__name__} platform={self.platform_name} {status}>"
