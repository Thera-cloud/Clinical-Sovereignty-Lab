"""
LITTLE NATE — Universal Mention Agent

Background agent that monitors @LittleNate mentions across social platforms
and auto-replies with AI-generated responses via the NateSummonService pipeline.

Platforms monitored:
  - X (Twitter): polls /users/{id}/mentions every 2 minutes
  - LinkedIn: polls comments on own posts every 5 minutes

Rate limits:
  - X: max 15 replies per hour (stay well under 50 tweets/24h API limit)
  - LinkedIn: max 10 replies per hour
  - Per-user cooldown: 1 reply per user per 30 minutes (prevent loops)

Cycle interval: 120 seconds
Stagger delay: 45 seconds
"""

import asyncio
import json
import logging
import re
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Set

logger = logging.getLogger("nate.mention_agent")

CYCLE_SECONDS = 120
STAGGER_DELAY = 45
X_REPLIES_PER_HOUR = 15
LINKEDIN_REPLIES_PER_HOUR = 10
USER_COOLDOWN_SECONDS = 1800
MAX_RESPONSE_LENGTH_X = 270
MAX_RESPONSE_LENGTH_LINKEDIN = 1250

INVOKE_PATTERNS = [
    re.compile(r"@littlenate\b", re.IGNORECASE),
    re.compile(r"@little_nate\b", re.IGNORECASE),
    re.compile(r"@LittleNate\b"),
    re.compile(r"\blittle\s*nate\s*,?\s*(ask|help|what|how|why|can you|tell me|explain)", re.IGNORECASE),
]

IGNORE_PATTERNS = [
    re.compile(r"^(rt|retweet)\b", re.IGNORECASE),
    re.compile(r"^@\w+\s+@\w+\s+@\w+\s+@\w+"),  # mass-mention spam
]


def _is_invocation(text: str) -> bool:
    for pat in IGNORE_PATTERNS:
        if pat.search(text):
            return False
    for pat in INVOKE_PATTERNS:
        if pat.search(text):
            return True
    return False


def _extract_question(text: str) -> str:
    cleaned = re.sub(r"@\w+", "", text).strip()
    cleaned = re.sub(r"\b(ask|hey|hi|hello)\b\s*,?\s*", "", cleaned, count=1, flags=re.IGNORECASE).strip()
    return cleaned or text


class NateMentionAgent:
    """Monitors social platform mentions and auto-replies via NateSummonService."""

    def __init__(self, db_pool, app_state=None):
        self.db_pool = db_pool
        self._app_state = app_state
        self._task: Optional[asyncio.Task] = None
        self._running = False

        self._responded_x: Set[str] = set()
        self._responded_linkedin: Set[str] = set()
        self._user_cooldowns: Dict[str, float] = {}
        self._x_reply_timestamps: List[float] = []
        self._linkedin_reply_timestamps: List[float] = []
        self._last_x_check: Optional[datetime] = None
        self._last_linkedin_check: Optional[datetime] = None
        self._x_adapter = None
        self._linkedin_adapter = None

    async def start(self):
        if self._task and not self._task.done():
            return
        self._running = True
        self._task = asyncio.create_task(self._run_loop())
        logger.info("NateMentionAgent started (cycle %ds, stagger %ds)", CYCLE_SECONDS, STAGGER_DELAY)

    async def stop(self):
        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("NateMentionAgent stopped")

    async def _run_loop(self):
        await asyncio.sleep(STAGGER_DELAY)
        while self._running:
            try:
                await self._init_adapters()
                await self._check_x_mentions()
                await self._check_linkedin_comments()
                self._prune_caches()
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.error("NateMentionAgent cycle failed: %s", e, exc_info=True)
            await asyncio.sleep(CYCLE_SECONDS)

    async def _init_adapters(self):
        if self._x_adapter and self._x_adapter._connected:
            return
        try:
            from app.services.platforms.x_twitter import XTwitterAdapter
            adapter = XTwitterAdapter(db_pool=self.db_pool)
            if await adapter.authenticate():
                self._x_adapter = adapter
                logger.info("NateMentionAgent: X adapter authenticated as @%s", adapter._username)
        except Exception as e:
            logger.debug("NateMentionAgent: X adapter init failed: %s", e)

        if self._linkedin_adapter and self._linkedin_adapter._connected:
            return
        try:
            from app.services.platforms.linkedin import LinkedInAdapter
            adapter = LinkedInAdapter(db_pool=self.db_pool)
            if await adapter.authenticate():
                self._linkedin_adapter = adapter
                logger.info("NateMentionAgent: LinkedIn adapter authenticated")
        except Exception as e:
            logger.debug("NateMentionAgent: LinkedIn adapter init failed: %s", e)

    def _can_reply_x(self) -> bool:
        now = time.time()
        self._x_reply_timestamps = [t for t in self._x_reply_timestamps if now - t < 3600]
        return len(self._x_reply_timestamps) < X_REPLIES_PER_HOUR

    def _can_reply_linkedin(self) -> bool:
        now = time.time()
        self._linkedin_reply_timestamps = [t for t in self._linkedin_reply_timestamps if now - t < 3600]
        return len(self._linkedin_reply_timestamps) < LINKEDIN_REPLIES_PER_HOUR

    def _user_on_cooldown(self, handle: str) -> bool:
        last = self._user_cooldowns.get(handle, 0)
        return (time.time() - last) < USER_COOLDOWN_SECONDS

    async def _check_x_mentions(self):
        if not self._x_adapter or not self._x_adapter._connected:
            return
        if not self._can_reply_x():
            return

        since = self._last_x_check or (datetime.now(timezone.utc) - timedelta(minutes=5))
        try:
            mentions = await self._x_adapter.get_mentions(since=since, limit=20)
            self._last_x_check = datetime.now(timezone.utc)
        except Exception as e:
            logger.warning("NateMentionAgent: X get_mentions failed: %s", e)
            return

        for mention in mentions:
            if mention.mention_id in self._responded_x:
                continue
            if not _is_invocation(mention.text):
                continue
            if self._user_on_cooldown(mention.author_handle):
                continue
            if not self._can_reply_x():
                break

            question = _extract_question(mention.text)
            if len(question) < 3:
                continue

            response = await self._generate_response(question, "x", mention.author_handle)
            if not response:
                continue

            truncated = self._truncate_for_x(response, mention.author_handle)

            try:
                result = await self._x_adapter.reply_to_comment(
                    comment_id=mention.mention_id,
                    text=truncated,
                )
                if result.success:
                    self._responded_x.add(mention.mention_id)
                    self._x_reply_timestamps.append(time.time())
                    self._user_cooldowns[mention.author_handle] = time.time()
                    await self._log_activity("x", mention.author_handle, question, truncated, mention.mention_id)
                    logger.info("NateMentionAgent: replied to @%s on X (tweet %s)", mention.author_handle, mention.mention_id)
                else:
                    logger.warning("NateMentionAgent: X reply failed for %s: %s", mention.mention_id, result.error)
            except Exception as e:
                logger.warning("NateMentionAgent: X reply exception for %s: %s", mention.mention_id, e)

    async def _check_linkedin_comments(self):
        if not self._linkedin_adapter or not self._linkedin_adapter._connected:
            return
        if not self._can_reply_linkedin():
            return

        since = self._last_linkedin_check or (datetime.now(timezone.utc) - timedelta(minutes=10))
        try:
            posts = await self._linkedin_adapter.get_own_posts(limit=5)
            self._last_linkedin_check = datetime.now(timezone.utc)
        except Exception as e:
            logger.debug("NateMentionAgent: LinkedIn get_own_posts failed: %s", e)
            return

        for post in posts:
            if not self._can_reply_linkedin():
                break
            try:
                comments = await self._linkedin_adapter.get_comments(post.item_id, since=since, limit=10)
            except Exception:
                continue

            for comment in comments:
                if comment.comment_id in self._responded_linkedin:
                    continue
                if not _is_invocation(comment.text):
                    continue
                if self._user_on_cooldown(comment.author_handle):
                    continue

                question = _extract_question(comment.text)
                if len(question) < 3:
                    continue

                response = await self._generate_response(question, "linkedin", comment.author_handle)
                if not response:
                    continue

                truncated = response[:MAX_RESPONSE_LENGTH_LINKEDIN]

                try:
                    result = await self._linkedin_adapter.reply_to_comment(
                        comment_id=comment.comment_id,
                        text=truncated,
                        post_id=post.item_id,
                    )
                    if result.success:
                        self._responded_linkedin.add(comment.comment_id)
                        self._linkedin_reply_timestamps.append(time.time())
                        self._user_cooldowns[comment.author_handle] = time.time()
                        await self._log_activity("linkedin", comment.author_handle, question, truncated, comment.comment_id)
                        logger.info("NateMentionAgent: replied to %s on LinkedIn", comment.author_handle)
                except Exception as e:
                    logger.warning("NateMentionAgent: LinkedIn reply failed: %s", e)

    async def _generate_response(self, question: str, platform: str, author: str) -> Optional[str]:
        summon = getattr(self._app_state, "nate_summon_service", None) if self._app_state else None
        if not summon:
            logger.debug("NateMentionAgent: NateSummonService not available")
            return None
        try:
            result = await summon.process_summon(
                message=question,
                channel=f"mention_{platform}",
                context={"platform": platform, "author": author, "type": "mention_reply"},
            )
            return result.response
        except Exception as e:
            logger.warning("NateMentionAgent: AI generation failed: %s", e)
            return None

    def _truncate_for_x(self, response: str, author: str) -> str:
        prefix = f"@{author} "
        budget = 280 - len(prefix)
        if len(response) <= budget:
            return f"{prefix}{response}"
        cutoff = response[:budget - 3].rfind(" ")
        if cutoff < budget // 2:
            cutoff = budget - 3
        return f"{prefix}{response[:cutoff]}..."

    def _prune_caches(self):
        if len(self._responded_x) > 5000:
            self._responded_x = set(list(self._responded_x)[-2500:])
        if len(self._responded_linkedin) > 2000:
            self._responded_linkedin = set(list(self._responded_linkedin)[-1000:])
        cutoff = time.time() - USER_COOLDOWN_SECONDS * 2
        self._user_cooldowns = {k: v for k, v in self._user_cooldowns.items() if v > cutoff}

    async def _log_activity(self, platform: str, author: str, question: str, response: str, ref_id: str):
        if not self.db_pool:
            return
        try:
            async with self.db_pool.acquire() as conn:
                await conn.execute(
                    """INSERT INTO skyeye_activity (platform, type, content, severity, created_at)
                       VALUES ($1, 'nate_mention_reply', $2, 'info', NOW())""",
                    platform,
                    json.dumps({
                        "author": author,
                        "question": question[:500],
                        "response": response[:500],
                        "ref_id": ref_id,
                    }),
                )
        except Exception:
            pass

    def get_status(self) -> Dict[str, Any]:
        return {
            "x_connected": bool(self._x_adapter and self._x_adapter._connected),
            "linkedin_connected": bool(self._linkedin_adapter and self._linkedin_adapter._connected),
            "x_responded_count": len(self._responded_x),
            "linkedin_responded_count": len(self._responded_linkedin),
            "x_replies_this_hour": len(self._x_reply_timestamps),
            "linkedin_replies_this_hour": len(self._linkedin_reply_timestamps),
            "users_on_cooldown": len(self._user_cooldowns),
        }
