"""
LITTLE NATE — Livestream Chat Pollers
Unified chat ingestion from X, YouTube, and LinkedIn live streams.
Each poller runs in a background task, normalizing messages into a
common format and pushing them to the engine's chat queue.
"""

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger("skyeye.livestream.chat")


class ChatMessage:
    """Normalized chat message from any platform."""
    __slots__ = ("platform", "viewer_handle", "text", "timestamp", "raw")

    def __init__(self, platform: str, viewer_handle: str, text: str,
                 timestamp: Optional[datetime] = None, raw: Any = None):
        self.platform = platform
        self.viewer_handle = viewer_handle
        self.text = text.strip()
        self.timestamp = timestamp or datetime.now(timezone.utc)
        self.raw = raw

    def to_dict(self) -> Dict[str, Any]:
        return {
            "platform": self.platform,
            "viewer_handle": self.viewer_handle,
            "text": self.text,
            "timestamp": self.timestamp.isoformat(),
        }


class BaseChatPoller:
    """Base class for platform-specific chat pollers."""

    def __init__(self, platform: str, db_pool, queue: asyncio.Queue,
                 poll_interval: float = 5.0):
        self.platform = platform
        self.db_pool = db_pool
        self.queue = queue
        self.poll_interval = poll_interval
        self._running = False
        self._task: Optional[asyncio.Task] = None
        self._seen_ids: set = set()

    async def start(self):
        self._running = True
        self._task = asyncio.create_task(self._poll_loop())
        logger.info(f"{self.platform} chat poller started")

    def stop(self):
        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()
        logger.info(f"{self.platform} chat poller stopped")

    async def _poll_loop(self):
        while self._running:
            try:
                messages = await self._fetch_messages()
                for msg in messages:
                    msg_id = f"{msg.platform}:{msg.viewer_handle}:{hash(msg.text)}"
                    if msg_id not in self._seen_ids:
                        self._seen_ids.add(msg_id)
                        await self.queue.put(msg.to_dict())
                if len(self._seen_ids) > 5000:
                    self._seen_ids = set(list(self._seen_ids)[-2000:])
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"{self.platform} poll error: {e}")
            await asyncio.sleep(self.poll_interval)

    async def _fetch_messages(self) -> List[ChatMessage]:
        raise NotImplementedError


class XChatPoller(BaseChatPoller):
    """Polls X (Twitter) for mentions and replies during a livestream."""

    def __init__(self, db_pool, queue: asyncio.Queue):
        super().__init__("x", db_pool, queue, poll_interval=8.0)

    async def _fetch_messages(self) -> List[ChatMessage]:
        from app.services.platforms import get_adapter
        adapter = get_adapter("x", self.db_pool)
        if not adapter:
            return []

        try:
            authenticated = await adapter.authenticate()
            if not authenticated:
                return []

            mentions = await adapter.get_mentions(limit=20)
            messages = []
            for m in mentions:
                messages.append(ChatMessage(
                    platform="x",
                    viewer_handle=m.author_handle,
                    text=m.text,
                    timestamp=m.created_at,
                    raw=m.raw_data,
                ))
            return messages
        except Exception as e:
            logger.error(f"X chat poll error: {e}")
            return []


class YouTubeChatPoller(BaseChatPoller):
    """Polls YouTube Live Chat messages during a livestream."""

    def __init__(self, db_pool, queue: asyncio.Queue):
        super().__init__("youtube", db_pool, queue, poll_interval=6.0)

    async def _fetch_messages(self) -> List[ChatMessage]:
        from app.services.platforms import get_adapter
        adapter = get_adapter("youtube", self.db_pool)
        if not adapter:
            return []

        try:
            authenticated = await adapter.authenticate()
            if not authenticated:
                return []

            comments = await adapter.get_comments("live", limit=20)
            messages = []
            for c in comments:
                messages.append(ChatMessage(
                    platform="youtube",
                    viewer_handle=c.author_handle,
                    text=c.text,
                    timestamp=c.created_at,
                    raw=c.raw_data,
                ))
            return messages
        except Exception as e:
            logger.error(f"YouTube chat poll error: {e}")
            return []


class LinkedInChatPoller(BaseChatPoller):
    """Polls LinkedIn post comments during a livestream."""

    def __init__(self, db_pool, queue: asyncio.Queue):
        super().__init__("linkedin", db_pool, queue, poll_interval=10.0)

    async def _fetch_messages(self) -> List[ChatMessage]:
        from app.services.platforms import get_adapter
        adapter = get_adapter("linkedin", self.db_pool)
        if not adapter:
            return []

        try:
            authenticated = await adapter.authenticate()
            if not authenticated:
                return []

            feed = await adapter.get_feed(limit=5)
            messages = []
            for post in feed[:1]:
                comments = await adapter.get_comments(post.item_id, limit=20)
                for c in comments:
                    messages.append(ChatMessage(
                        platform="linkedin",
                        viewer_handle=c.author_handle,
                        text=c.text,
                        timestamp=c.created_at,
                        raw=c.raw_data,
                    ))
            return messages
        except Exception as e:
            logger.error(f"LinkedIn chat poll error: {e}")
            return []


POLLER_MAP = {
    "x": XChatPoller,
    "youtube": YouTubeChatPoller,
    "linkedin": LinkedInChatPoller,
}


async def create_pollers(
    platforms: List[str], db_pool, queue: asyncio.Queue
) -> List[BaseChatPoller]:
    pollers = []
    for p in platforms:
        cls = POLLER_MAP.get(p)
        if cls:
            poller = cls(db_pool, queue)
            await poller.start()
            pollers.append(poller)
        else:
            logger.warning(f"No chat poller for platform: {p}")
    return pollers
