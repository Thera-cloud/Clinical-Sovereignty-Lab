"""Harvest headlines and pair with therapeutic Dispatch angles.

# QUANTUM-CRYSTAL-ARCH — Newsletter Growth Engine
"""
from __future__ import annotations

import json
import logging
import os
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

import aiohttp

logger = logging.getLogger("nate.newsletter_trend_pairing")

TREND_FEEDS = [
    {"url": "https://feeds.bbci.co.uk/news/rss.xml", "category": "politics", "name": "BBC News"},
    {"url": "https://rss.nytimes.com/services/xml/rss/nyt/World.xml", "category": "politics", "name": "NYT World"},
    {"url": "https://www.billboard.com/feed/", "category": "music", "name": "Billboard"},
    {"url": "https://variety.com/feed/", "category": "arts", "name": "Variety"},
    {"url": "https://www.playbill.com/rss", "category": "arts", "name": "Playbill"},
    {"url": "https://www.militarytimes.com/arc/outboundfeeds/rss/?outputType=xml", "category": "military", "name": "Military Times"},
    {"url": "https://news.va.gov/feed/", "category": "military", "name": "VA News"},
    {"url": "https://www.menshealth.com/rss/all.xml/", "category": "fitness", "name": "Men's Health"},
    {"url": "https://www.apa.org/news/press/releases/rss", "category": "general", "name": "APA Press"},
    {"url": "https://www.nami.org/Blogs/NAMI-Blog/RSS", "category": "neurodivergence", "name": "NAMI Blog"},
]


def trend_pairing_enabled() -> bool:
    return os.getenv("ENABLE_NEWSLETTER_TREND_PAIRING", "true").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


def _slug_key(title: str) -> str:
    return re.sub(r"[^a-z0-9_]+", "_", (title or "trend").lower())[:64].strip("_") or "trend"


async def _fetch_rss(url: str, session: aiohttp.ClientSession) -> List[Dict[str, str]]:
    try:
        async with session.get(
            url, timeout=aiohttp.ClientTimeout(total=12), allow_redirects=True
        ) as resp:
            if resp.status >= 400:
                return []
            text = await resp.text()
    except Exception as e:
        logger.warning("trend RSS fetch %s: %s", url, e)
        return []
    items: List[Dict[str, str]] = []
    try:
        root = ET.fromstring(text)
    except Exception as e:
        logger.warning("trend RSS parse %s: %s", url, e)
        return []
    # RSS 2.0
    for item in root.findall(".//item")[:8]:
        title = (item.findtext("title") or "").strip()
        link = (item.findtext("link") or "").strip()
        if title:
            items.append({"headline": title[:300], "source_url": link[:500]})
    # Atom
    if not items:
        ns = {"a": "http://www.w3.org/2005/Atom"}
        for entry in root.findall(".//{http://www.w3.org/2005/Atom}entry")[:8]:
            title = (entry.findtext("{http://www.w3.org/2005/Atom}title") or "").strip()
            link_el = entry.find("{http://www.w3.org/2005/Atom}link")
            link = (link_el.get("href") if link_el is not None else "") or ""
            if title:
                items.append({"headline": title[:300], "source_url": link[:500]})
    return items


async def harvest_trends(db_pool) -> Dict[str, Any]:
    if not db_pool or not trend_pairing_enabled():
        return {"ok": False, "skipped": True}
    inserted = 0
    async with aiohttp.ClientSession(
        headers={"User-Agent": "LittleNateDispatch/1.0 (+https://sovereignsanctuary.net)"}
    ) as session:
        for feed in TREND_FEEDS:
            articles = await _fetch_rss(feed["url"], session)
            for i, art in enumerate(articles[:5]):
                velocity = max(0.2, 1.0 - i * 0.12)
                try:
                    async with db_pool.acquire() as conn:
                        exists = await conn.fetchval(
                            """
                            SELECT 1 FROM newsletter_trend_candidates
                            WHERE headline = $1
                              AND harvested_at > NOW() - INTERVAL '7 days'
                            LIMIT 1
                            """,
                            art["headline"],
                        )
                        if exists:
                            continue
                        await conn.execute(
                            """
                            INSERT INTO newsletter_trend_candidates
                                (headline, category, source, source_url, velocity)
                            VALUES ($1, $2, $3, $4, $5)
                            """,
                            art["headline"],
                            feed["category"],
                            feed["name"],
                            art.get("source_url") or None,
                            velocity,
                        )
                        inserted += 1
                except Exception as e:
                    logger.warning("trend insert: %s", e)
    return {"ok": True, "inserted": inserted}


_PAIR_SYSTEM = (
    "You pair cultural/news headlines with mental-health EDUCATION angles for "
    "Little Nate Dispatch. Rules: (1) Never take a political stance — for politics "
    "or war, frame only nervous-system coping, grief, or staying informed without "
    "doomscrolling. (2) Never insult private individuals. (3) No medical claims or "
    "diagnoses. (4) Education and reflection only, not therapy. "
    "Return ONLY JSON: {\"topic_key\":\"snake_case\",\"title\":\"under 100 chars\","
    "\"angle\":\"one sentence\",\"domain\":\"one of neurodivergence|arts|military|"
    "fitness|curiosity|general|grief|burnout\"}"
)


async def _pair_one(headline: str, category: str) -> Optional[Dict[str, Any]]:
    prompt = (
        f"Category: {category}\nHeadline: {headline}\n"
        "Write a therapeutic/educational newsletter angle that uses this as a hook "
        "and veers the reader toward steadiness, curiosity, or support skills."
    )
    try:
        from app.services.nate_inference_router import NateInferenceRouter

        router = NateInferenceRouter()
        result = await router.generate(
            prompt,
            system=_PAIR_SYSTEM,
            domain="clinical",
            max_tokens=400,
        )
        text = (result.get("text") if isinstance(result, dict) else str(result)) or ""
    except Exception as e:
        logger.warning("pair_one inference: %s", e)
        return _heuristic_pair(headline, category)

    m = re.search(r"\{[\s\S]*\}", text)
    if not m:
        return _heuristic_pair(headline, category)
    try:
        data = json.loads(m.group(0))
    except Exception:
        return _heuristic_pair(headline, category)

    title = str(data.get("title") or "").strip()[:120]
    if not title:
        return _heuristic_pair(headline, category)

    # Safety: politics must not look like a position piece
    if category == "politics":
        banned = ("vote for", "support the", "against the party", "endorse")
        low = title.lower() + " " + str(data.get("angle") or "").lower()
        if any(b in low for b in banned):
            return _heuristic_pair(headline, category)

    # Validator gate when available
    try:
        from app.services.nate_response_validator import NateResponseValidator

        v = NateResponseValidator()
        violations = v.validate(title + " " + str(data.get("angle") or ""))
        if any(getattr(x, "severity", None) == "high" or (isinstance(x, dict) and x.get("severity") == "high") for x in (violations or [])):
            return _heuristic_pair(headline, category)
    except Exception:
        pass

    return {
        "topic_key": str(data.get("topic_key") or _slug_key(title))[:64],
        "title": title,
        "angle": str(data.get("angle") or "")[:300],
        "domain": str(data.get("domain") or category)[:32],
    }


def _heuristic_pair(headline: str, category: str) -> Dict[str, Any]:
    """Fail-soft pairing without LLM."""
    templates = {
        "politics": (
            "doomscroll_nervous_system",
            "Staying informed without letting the headlines own your nervous system",
        ),
        "military": (
            "war_headlines_without_shutdown",
            "Holding war headlines without shutting down — steadiness for heavy news",
        ),
        "music": (
            "music_and_catharsis",
            "When a song holds what you cannot say yet — music and emotional release",
        ),
        "arts": (
            "art_as_mirror",
            "What this story on screen (or stage) mirrors in us — curiosity over judgment",
        ),
        "fitness": (
            "fitness_shame_free",
            "Movement that comes from care, not comparison — a steadier fitness mind",
        ),
        "influencer": (
            "invisible_workloads",
            "What public burnout reminds us about our own invisible workloads",
        ),
        "neurodivergence": (
            "neurodivergence_support",
            "Working with a neurodivergent brain — and how loved ones can assist",
        ),
        "general": (
            "curiosity_when_world_loud",
            "Staying curious when the world feels loud",
        ),
    }
    key, title = templates.get(category, templates["general"])
    return {
        "topic_key": key,
        "title": title,
        "angle": f"Hook from headline: {headline[:120]}",
        "domain": category if category in (
            "arts", "military", "fitness", "neurodivergence", "curiosity", "grief"
        ) else "general",
    }


async def pair_unpaired_trends(db_pool, limit: int = 5) -> Dict[str, Any]:
    if not db_pool or not trend_pairing_enabled():
        return {"ok": False, "skipped": True}
    from app.services.newsletter_signals import upsert_topic_forecast

    async with db_pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT id, headline, category, velocity
            FROM newsletter_trend_candidates
            WHERE paired_at IS NULL
              AND harvested_at > NOW() - INTERVAL '5 days'
            ORDER BY velocity DESC, harvested_at DESC
            LIMIT $1
            """,
            limit,
        )
    paired = 0
    for r in rows:
        result = await _pair_one(r["headline"], r["category"])
        if not result:
            continue
        try:
            async with db_pool.acquire() as conn:
                await conn.execute(
                    """
                    UPDATE newsletter_trend_candidates
                    SET paired_topic_key = $2, paired_title = $3, paired_at = NOW(),
                        metadata = COALESCE(metadata, '{}'::jsonb) || $4::jsonb
                    WHERE id = $1
                    """,
                    r["id"],
                    result["topic_key"],
                    result["title"],
                    json.dumps({"angle": result.get("angle"), "domain": result.get("domain")}),
                )
                await conn.execute(
                    """
                    INSERT INTO newsletter_topic_forecast
                        (topic_key, seasonal_label, target_week, news_velocity,
                         foresight_score, metadata)
                    VALUES ($1, $2, CURRENT_DATE + 3, $3, $4, $5::jsonb)
                    """,
                    result["topic_key"],
                    f"trend_{r['category']}",
                    float(r["velocity"] or 0.5),
                    min(0.9, 0.45 + float(r["velocity"] or 0.5) * 0.4),
                    json.dumps(
                        {
                            "domain": result.get("domain"),
                            "title": result["title"],
                            "headline": r["headline"][:200],
                            "source": "trend_pairing",
                        }
                    ),
                )
            # also via helper for signal path consistency
            await upsert_topic_forecast(
                db_pool,
                result["topic_key"],
                seasonal_label=f"trend_{r['category']}",
                foresight_score=min(0.9, 0.45 + float(r["velocity"] or 0.5) * 0.4),
                news_velocity=float(r["velocity"] or 0.5),
            )
            paired += 1
        except Exception as e:
            logger.warning("pair persist: %s", e)
    return {"ok": True, "paired": paired}


async def run_trend_cycle(db_pool) -> Dict[str, Any]:
    harvest = await harvest_trends(db_pool)
    pair = await pair_unpaired_trends(db_pool, limit=5)
    return {"harvest": harvest, "pair": pair}
