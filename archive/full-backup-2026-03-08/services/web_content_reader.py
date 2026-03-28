"""
SOVEREIGN UNIFICATION — Web Content Reader
Little Nate reads external articles, blog posts, research, and competitor
content to develop his own opinions and insights. Everything he reads is
scored through the Nevedal formula for emotional resonance.

RSS Feeds monitored:
- Mental health / therapy publications
- Psychology research
- Wellness / self-help
- Competitor analysis (other therapy platforms)

Content is summarized, scored, and stored in web_wisdom table.
The Insight Accumulator then synthesizes these into actionable knowledge.
"""

import asyncio
import json
import logging
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from xml.etree import ElementTree

import aiohttp

from app.config import settings
from app.services.nate_ai_config import NATE_CHAT_URL, NATE_CHAT_KEY, nate_chat_headers, nate_chat_payload

logger = logging.getLogger("sovereign.web_reader")

READ_INTERVAL = 14400  # 4 hours between reading cycles

DEFAULT_RSS_FEEDS = [
    {"url": "https://www.psychologytoday.com/us/blog/feed", "type": "psychology", "name": "Psychology Today"},
    {"url": "https://www.apa.org/news/press/releases/rss", "type": "research", "name": "APA Press"},
    {"url": "https://greatergood.berkeley.edu/feed", "type": "wellness", "name": "Greater Good Science Center"},
    {"url": "https://www.mindful.org/feed/", "type": "mindfulness", "name": "Mindful.org"},
    {"url": "https://feeds.feedburner.com/PsychCentral", "type": "psychology", "name": "Psych Central"},
    {"url": "https://www.nami.org/RSS", "type": "advocacy", "name": "NAMI"},
]

CONTENT_ANALYSIS_PROMPT = """You are Little Nate's learning system. Analyze this article for therapeutic relevance.

Evaluate:
1. Key insights relevant to emotional wellness, therapy, or personal growth
2. Emotional resonance: how deeply would this content connect with someone seeking help? (0.0-1.0)
3. Relevance to Sovereign Sanctuary's mission (liminal intelligence, emotional coherence) (0.0-1.0)
4. Themes present (list 2-5 keywords)
5. One-paragraph summary

Output valid JSON:
{"summary": "...", "key_insights": ["...", "..."], "emotional_resonance": 0.0-1.0, "relevance_score": 0.0-1.0, "themes": ["...", "..."]}
"""


class WebContentReader:
    """Reads external content and scores it through the Nevedal resonance lens."""

    def __init__(self, db_pool, custom_feeds: Optional[List[Dict]] = None):
        self.db_pool = db_pool
        self.feeds = custom_feeds or DEFAULT_RSS_FEEDS
        self._running = False
        self._task: Optional[asyncio.Task] = None
        self._seen_urls: set = set()

    async def start(self):
        if self._running:
            return
        self._running = True
        await self._load_seen_urls()
        self._task = asyncio.create_task(self._read_loop())
        logger.info(f"Web Content Reader started — monitoring {len(self.feeds)} feeds")

    async def stop(self):
        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()
        logger.info("Web Content Reader stopped")

    async def _load_seen_urls(self):
        try:
            async with self.db_pool.acquire() as conn:
                rows = await conn.fetch(
                    "SELECT url FROM web_wisdom ORDER BY fetched_at DESC LIMIT 500"
                )
                self._seen_urls = {r["url"] for r in rows}
        except Exception:
            pass

    async def _read_loop(self):
        await asyncio.sleep(60)
        while self._running:
            try:
                await self.read_all_feeds()
            except Exception as e:
                logger.error(f"Read cycle error: {e}")
            await asyncio.sleep(READ_INTERVAL)

    async def read_all_feeds(self):
        """Read all configured RSS feeds and analyze new articles."""
        logger.info("Starting content read cycle...")
        total_new = 0

        for feed in self.feeds:
            try:
                articles = await self._fetch_rss(feed["url"])
                new_articles = [a for a in articles if a["url"] not in self._seen_urls]

                for article in new_articles[:5]:
                    content = await self._fetch_article_text(article["url"])
                    if not content or len(content) < 100:
                        continue

                    analysis = await self._analyze_content(
                        article["title"], content, feed["type"]
                    )

                    if analysis and analysis.get("relevance_score", 0) >= 0.3:
                        await self._store_wisdom(
                            url=article["url"],
                            source_type=feed["type"],
                            title=article["title"],
                            analysis=analysis,
                            feed_name=feed["name"],
                        )
                        total_new += 1

                    self._seen_urls.add(article["url"])

            except Exception as e:
                logger.warning(f"Feed error ({feed['name']}): {e}")

        logger.info(f"Read cycle complete: {total_new} new articles analyzed and stored")

    async def _fetch_rss(self, url: str) -> List[Dict]:
        articles = []
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    url, timeout=aiohttp.ClientTimeout(total=15),
                    headers={"User-Agent": "LittleNate/1.0 (Sovereign Sanctuary Research Bot)"},
                ) as resp:
                    if resp.status != 200:
                        return []
                    text = await resp.text()

            root = ElementTree.fromstring(text)

            for item in root.iter("item"):
                title = item.findtext("title", "")
                link = item.findtext("link", "")
                if title and link:
                    articles.append({"title": title.strip(), "url": link.strip()})

            for entry in root.iter("{http://www.w3.org/2005/Atom}entry"):
                title = entry.findtext("{http://www.w3.org/2005/Atom}title", "")
                link_el = entry.find("{http://www.w3.org/2005/Atom}link")
                link = link_el.get("href", "") if link_el is not None else ""
                if title and link:
                    articles.append({"title": title.strip(), "url": link.strip()})

        except Exception as e:
            logger.warning(f"RSS parse error for {url}: {e}")

        return articles[:10]

    async def _fetch_article_text(self, url: str) -> Optional[str]:
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    url, timeout=aiohttp.ClientTimeout(total=20),
                    headers={"User-Agent": "LittleNate/1.0 (Sovereign Sanctuary Research Bot)"},
                ) as resp:
                    if resp.status != 200:
                        return None
                    html = await resp.text()

            text = re.sub(r'<script[^>]*>.*?</script>', '', html, flags=re.DOTALL | re.IGNORECASE)
            text = re.sub(r'<style[^>]*>.*?</style>', '', text, flags=re.DOTALL | re.IGNORECASE)
            text = re.sub(r'<[^>]+>', ' ', text)
            text = re.sub(r'\s+', ' ', text).strip()

            return text[:5000] if text else None
        except Exception:
            return None

    async def _analyze_content(self, title: str, content: str, source_type: str) -> Optional[Dict]:
        if not NATE_CHAT_KEY:
            return self._analyze_heuristic(title, content, source_type)

        messages = [
            {"role": "system", "content": CONTENT_ANALYSIS_PROMPT},
            {"role": "user", "content": f"Title: {title}\nSource type: {source_type}\n\nContent:\n{content[:3000]}"},
        ]

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    NATE_CHAT_URL,
                    json=nate_chat_payload(messages, max_tokens=500),
                    headers=nate_chat_headers(),
                    timeout=aiohttp.ClientTimeout(total=30),
                ) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        text = data.get("choices", [{}])[0].get("message", {}).get("content", "")
                        try:
                            start = text.find("{")
                            end = text.rfind("}") + 1
                            if start >= 0 and end > start:
                                return json.loads(text[start:end])
                        except json.JSONDecodeError:
                            pass
        except Exception as e:
            logger.error(f"Content analysis error: {e}")

        return self._analyze_heuristic(title, content, source_type)

    def _analyze_heuristic(self, title: str, content: str, source_type: str) -> Dict:
        text = (title + " " + content).lower()

        resonance_keywords = [
            "emotion", "feel", "anxiety", "depression", "healing", "therapy",
            "coherence", "mindful", "trauma", "grief", "growth", "resilience",
            "relationship", "attachment", "self-compassion", "vulnerability",
        ]
        resonance = sum(1 for kw in resonance_keywords if kw in text) / len(resonance_keywords)

        relevance_keywords = [
            "ai therapy", "digital health", "mental health app", "telehealth",
            "therapeutic", "counseling", "coaching", "wellness platform",
            "emotional intelligence", "self-help",
        ]
        relevance = sum(1 for kw in relevance_keywords if kw in text) / len(relevance_keywords)
        relevance = min(1.0, relevance + 0.2 if source_type in ("psychology", "research") else relevance)

        themes = [kw for kw in resonance_keywords if kw in text][:5]

        return {
            "summary": f"Article about {', '.join(themes[:3]) if themes else source_type}. "
                       f"Heuristic analysis (AI unavailable).",
            "key_insights": [f"Discusses {t}" for t in themes[:3]],
            "emotional_resonance": round(min(1.0, resonance * 3), 2),
            "relevance_score": round(min(1.0, relevance * 3), 2),
            "themes": themes or [source_type],
        }

    async def _store_wisdom(self, url: str, source_type: str, title: str,
                             analysis: Dict, feed_name: str):
        try:
            async with self.db_pool.acquire() as conn:
                await conn.execute("""
                    INSERT INTO web_wisdom
                        (url, source_type, title, summary, key_insights,
                         emotional_resonance, relevance_score, themes, metadata)
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
                    ON CONFLICT DO NOTHING
                """,
                    url, source_type, title,
                    analysis.get("summary", ""),
                    json.dumps(analysis.get("key_insights", [])),
                    analysis.get("emotional_resonance", 0),
                    analysis.get("relevance_score", 0),
                    analysis.get("themes", []),
                    json.dumps({"feed": feed_name}),
                )
        except Exception as e:
            logger.error(f"Failed to store web wisdom: {e}")

    async def get_recent_wisdom(self, limit: int = 10) -> List[Dict]:
        try:
            async with self.db_pool.acquire() as conn:
                rows = await conn.fetch("""
                    SELECT title, summary, themes, emotional_resonance,
                           relevance_score, fetched_at
                    FROM web_wisdom
                    WHERE fetched_at > NOW() - INTERVAL '7 days'
                    ORDER BY relevance_score DESC NULLS LAST
                    LIMIT $1
                """, limit)
                return [dict(r) for r in rows]
        except Exception:
            return []
