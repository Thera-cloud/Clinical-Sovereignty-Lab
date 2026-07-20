"""Scored topic pool for Little Nate Dispatch.

# QUANTUM-CRYSTAL-ARCH — Newsletter Growth Engine
"""
from __future__ import annotations

import json
import logging
import os
import re
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger("nate.newsletter_topic_engine")

TOPIC_DOMAINS = (
    "neurodivergence",
    "arts",
    "military",
    "grief",
    "relationships",
    "parenting",
    "burnout",
    "sleep",
    "fitness",
    "curiosity",
    "self_compassion",
    "general",
)

DOMAIN_KEYWORDS = {
    "neurodivergence": (
        "adhd", "autism", "neurodiverg", "sensory", "executive function",
        "masking", "unmask", "asd",
    ),
    "arts": (
        "movie", "film", "play", "theater", "theatre", "museum", "music",
        "art", "gallery", "novel", "book", "album", "broadway",
    ),
    "military": (
        "veteran", "military", "deployment", "war", "ptsd", "moral injury",
        "soldier", "reintegration",
    ),
    "fitness": ("fitness", "workout", "exercise", "movement", "body"),
    "grief": ("grief", "loss", "bereave", "mourning"),
    "burnout": ("burnout", "exhausted", "overwhelm"),
    "curiosity": ("curious", "learning", "growth", "wonder"),
}


def infer_domain(text: str) -> str:
    t = (text or "").lower()
    for domain, keys in DOMAIN_KEYWORDS.items():
        if any(k in t for k in keys):
            return domain
    return "general"


def _slug_key(title: str) -> str:
    return re.sub(r"[^a-z0-9_]+", "_", (title or "topic").lower())[:64].strip("_") or "topic"


def novelty_penalty(title: str, recent_topics: List[str]) -> float:
    """0..1 penalty; 1.0 means exact/near match to a recent sent topic."""
    t = (title or "").lower().strip()
    if not t:
        return 0.0
    for r in recent_topics:
        rr = (r or "").lower().strip()
        if not rr:
            continue
        if t == rr:
            return 1.0
        if t in rr or rr in t:
            return 0.85
        # token overlap
        ta, ra = set(t.split()), set(rr.split())
        if ta and ra:
            overlap = len(ta & ra) / max(len(ta), len(ra))
            if overlap >= 0.6:
                return 0.7 * overlap
    return 0.0


def score_candidate(
    *,
    foresight: float = 0.0,
    news_velocity: float = 0.0,
    chat_bucket: float = 0.0,
    seasonal_boost: float = 0.0,
    share_velocity: float = 0.0,
    rating_boost: float = 0.0,
    novelty: float = 0.0,
) -> float:
    """Higher is better. Novelty subtracts."""
    raw = (
        1.2 * float(foresight)
        + 1.5 * float(news_velocity)
        + 0.9 * min(float(chat_bucket) / 10.0, 1.0)
        + 0.8 * float(seasonal_boost)
        + 0.7 * float(share_velocity)
        + 0.6 * float(rating_boost)
        - 2.0 * float(novelty)
    )
    return round(raw, 4)


async def _recent_sent_topics(conn, limit: int = 8) -> List[str]:
    rows = await conn.fetch(
        """
        SELECT topic FROM newsletter_issues
        WHERE status = 'sent' AND topic IS NOT NULL
        ORDER BY sent_at DESC NULLS LAST
        LIMIT $1
        """,
        limit,
    )
    return [r["topic"] for r in rows if r.get("topic")]


async def _chat_signal_map(conn) -> Dict[str, int]:
    rows = await conn.fetch(
        """
        SELECT theme, count_bucket FROM newsletter_chat_signals
        WHERE week_bucket >= CURRENT_DATE - INTERVAL '28 days'
        ORDER BY count_bucket DESC
        LIMIT 40
        """
    )
    return {r["theme"]: int(r["count_bucket"] or 0) for r in rows}


async def _share_velocity_map(conn) -> Dict[str, float]:
    rows = await conn.fetch(
        """
        SELECT i.topic, COALESCE(s.share_count, 0)::float AS shares
        FROM newsletter_issues i
        LEFT JOIN newsletter_library_stats s ON s.slug = i.slug
        WHERE i.status = 'sent' AND i.sent_at > NOW() - INTERVAL '90 days'
        """
    )
    out: Dict[str, float] = {}
    for r in rows:
        if r["topic"]:
            out[r["topic"].lower()] = min(1.0, float(r["shares"] or 0) / 20.0)
    return out


async def _rating_boost_map(conn) -> Dict[str, float]:
    rows = await conn.fetch(
        """
        SELECT i.topic, AVG(f.helpful_score)::float AS avg_h, COUNT(*)::int AS n
        FROM newsletter_feedback f
        JOIN newsletter_issues i ON i.id = f.issue_id
        WHERE f.helpful_score IS NOT NULL
          AND f.created_at > NOW() - INTERVAL '120 days'
          AND i.topic IS NOT NULL
        GROUP BY i.topic
        HAVING COUNT(*) >= 2
        """
    )
    out: Dict[str, float] = {}
    for r in rows:
        # normalize 1-5 → 0-1 around midpoint 3
        out[r["topic"].lower()] = max(0.0, min(1.0, ((r["avg_h"] or 3) - 3) / 2.0 + 0.5))
    return out


def _seasonal_boost(label: Optional[str], target_week) -> float:
    if not target_week:
        return 0.0
    today = date.today()
    try:
        tw = target_week if isinstance(target_week, date) else target_week.date()
    except Exception:
        return 0.15 if label else 0.0
    days = abs((tw - today).days)
    if days <= 14:
        return 1.0
    if days <= 45:
        return 0.5
    if label:
        return 0.15
    return 0.0


async def collect_candidates(db_pool) -> List[Dict[str, Any]]:
    if not db_pool:
        return []
    candidates: List[Dict[str, Any]] = []
    async with db_pool.acquire() as conn:
        recent = await _recent_sent_topics(conn, 8)
        chat = await _chat_signal_map(conn)
        shares = await _share_velocity_map(conn)
        ratings = await _rating_boost_map(conn)

        for theme, bucket in chat.items():
            if bucket < 2:
                continue
            nov = novelty_penalty(theme, recent)
            candidates.append(
                {
                    "topic_key": _slug_key(theme),
                    "title": theme[:120],
                    "seasonal_window": None,
                    "domain": infer_domain(theme),
                    "rationale": f"chat_signal_n={bucket}",
                    "score": score_candidate(
                        chat_bucket=bucket,
                        share_velocity=shares.get(theme.lower(), 0),
                        rating_boost=ratings.get(theme.lower(), 0),
                        novelty=nov,
                    ),
                    "novelty": nov,
                }
            )

        forecasts = await conn.fetch(
            """
            SELECT topic_key, seasonal_label, foresight_score, news_velocity,
                   target_week, metadata
            FROM newsletter_topic_forecast
            WHERE target_week IS NULL
               OR target_week >= CURRENT_DATE - INTERVAL '21 days'
            ORDER BY created_at DESC
            LIMIT 80
            """
        )
        seen_keys = {c["topic_key"] for c in candidates}
        for f in forecasts:
            key = f["topic_key"]
            if key in seen_keys:
                # bump existing with forecast scores
                for c in candidates:
                    if c["topic_key"] == key:
                        c["score"] = score_candidate(
                            foresight=f["foresight_score"] or 0,
                            news_velocity=f["news_velocity"] or 0,
                            chat_bucket=chat.get(c["title"], 0),
                            seasonal_boost=_seasonal_boost(
                                f["seasonal_label"], f["target_week"]
                            ),
                            share_velocity=shares.get(c["title"].lower(), 0),
                            rating_boost=ratings.get(c["title"].lower(), 0),
                            novelty=c.get("novelty", 0),
                        )
                        break
                continue
            title = key.replace("_", " ")[:120]
            meta = f["metadata"] or {}
            if isinstance(meta, str):
                try:
                    meta = json.loads(meta)
                except Exception:
                    meta = {}
            domain = (meta.get("domain") if isinstance(meta, dict) else None) or infer_domain(
                title + " " + (f["seasonal_label"] or "")
            )
            nov = novelty_penalty(title, recent)
            candidates.append(
                {
                    "topic_key": key[:64],
                    "title": (meta.get("title") if isinstance(meta, dict) else None)
                    or title,
                    "seasonal_window": f["seasonal_label"],
                    "domain": domain,
                    "rationale": f"forecast_score={f['foresight_score']}",
                    "score": score_candidate(
                        foresight=f["foresight_score"] or 0,
                        news_velocity=f["news_velocity"] or 0,
                        seasonal_boost=_seasonal_boost(
                            f["seasonal_label"], f["target_week"]
                        ),
                        novelty=nov,
                    ),
                    "novelty": nov,
                }
            )
            seen_keys.add(key)

    candidates.sort(key=lambda c: c["score"], reverse=True)
    return candidates


async def select_best_topic(db_pool) -> Dict[str, Any]:
    """Pick highest-scoring novel topic; bootstrap default if pool empty."""
    from app.services.newsletter_pipeline import _load_symbolic_hints

    hints = await _load_symbolic_hints(db_pool)
    pool = await collect_candidates(db_pool)
    # Prefer novelty < 0.85
    for c in pool:
        if c.get("novelty", 0) < 0.85:
            return {
                "topic_key": c["topic_key"],
                "title": c["title"][:120],
                "seasonal_window": c.get("seasonal_window"),
                "domain": c.get("domain") or "general",
                "rationale": f"{c.get('rationale')}|score={c['score']}",
                "symbolic_hints": hints,
            }
    return {
        "topic_key": "curiosity_lifelong_learning",
        "title": "Staying curious when the world feels loud",
        "seasonal_window": None,
        "domain": "curiosity",
        "rationale": "default_bootstrap_growth",
        "symbolic_hints": hints,
    }


async def mine_crystal_themes(db_pool) -> int:
    """Aggregate anonymized clinical crystal themes (≥5 users) into forecast."""
    if not db_pool:
        return 0
    from app.services.newsletter_signals import upsert_topic_forecast

    written = 0
    try:
        async with db_pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT LOWER(SUBSTRING(crystal_text FROM 1 FOR 80)) AS theme_stub,
                       COUNT(DISTINCT user_id)::int AS n_users
                FROM nate_intelligence_crystals
                WHERE domain = 'clinical'
                  AND superseded_by IS NULL
                  AND COALESCE(scope, 'global') NOT IN ('archived')
                  AND created_at > NOW() - INTERVAL '45 days'
                  AND user_id IS NOT NULL
                  AND LENGTH(crystal_text) > 40
                GROUP BY 1
                HAVING COUNT(DISTINCT user_id) >= 5
                ORDER BY n_users DESC
                LIMIT 8
                """
            )
        for r in rows:
            stub = (r["theme_stub"] or "").strip()
            if len(stub) < 12:
                continue
            # strip to a short theme phrase
            theme = re.sub(r"\s+", " ", stub)[:80]
            key = _slug_key(theme)
            await upsert_topic_forecast(
                db_pool,
                key,
                seasonal_label="crystal_aggregate",
                foresight_score=min(0.85, 0.4 + r["n_users"] / 40.0),
                news_velocity=0.0,
            )
            written += 1
    except Exception as e:
        logger.warning("mine_crystal_themes: %s", e)
    return written


async def ideate_topics_llm(db_pool) -> int:
    """Propose domain-rotated topics via inference router; write to forecast."""
    if not db_pool or os.getenv("ENABLE_NEWSLETTER_TOPIC_LLM", "true").strip().lower() in (
        "0",
        "false",
        "no",
        "off",
    ):
        return 0
    from app.services.newsletter_signals import upsert_topic_forecast

    recent: List[str] = []
    signals: List[str] = []
    try:
        async with db_pool.acquire() as conn:
            recent = await _recent_sent_topics(conn, 8)
            chat = await _chat_signal_map(conn)
            signals = list(chat.keys())[:10]
    except Exception as e:
        logger.warning("ideate context: %s", e)

    domain_cycle = TOPIC_DOMAINS[datetime.now(timezone.utc).timetuple().tm_yday % len(TOPIC_DOMAINS)]
    prompt = (
        "You write topic ideas for Little Nate Dispatch, a mental-health education newsletter "
        "(not therapy, not medical advice). Propose exactly 5 JSON objects in a JSON array. "
        "Each object: topic_key (snake_case), title (human, under 100 chars), domain, angle "
        "(one sentence therapeutic/educational framing). "
        f"Prioritize domain '{domain_cycle}' plus rotate across: neurodivergence, arts/culture "
        "(movies, plays, museums, music), military/veterans/war coping, fitness, grief, "
        "relationships, burnout, curiosity. "
        "Avoid political positions; for politics/war headlines frame nervous-system coping only. "
        "Do not name private individuals negatively. "
        f"Avoid repeating these recent topics: {recent}. "
        f"Audience signals: {signals}. "
        "Return ONLY the JSON array."
    )
    text = ""
    try:
        from app.services.nate_inference_router import NateInferenceRouter

        router = NateInferenceRouter()
        result = await router.generate(
            prompt,
            system="You are an editorial topic strategist for a clinical-education newsletter.",
            domain="marketing",
            max_tokens=900,
        )
        text = (result.get("text") if isinstance(result, dict) else str(result)) or ""
    except Exception as e:
        logger.warning("ideate_topics_llm inference: %s", e)
        return 0

    # Extract JSON array
    m = re.search(r"\[[\s\S]*\]", text)
    if not m:
        return 0
    try:
        items = json.loads(m.group(0))
    except Exception:
        return 0
    written = 0
    for item in items[:5]:
        if not isinstance(item, dict):
            continue
        title = str(item.get("title") or "").strip()[:120]
        key = str(item.get("topic_key") or _slug_key(title))[:64]
        domain = str(item.get("domain") or infer_domain(title))[:32]
        if not title or not key:
            continue
        try:
            async with db_pool.acquire() as conn:
                await conn.execute(
                    """
                    INSERT INTO newsletter_topic_forecast
                        (topic_key, seasonal_label, target_week, news_velocity,
                         foresight_score, metadata)
                    VALUES ($1, $2, CURRENT_DATE + 7, 0, $3, $4::jsonb)
                    """,
                    key,
                    "llm_ideation",
                    0.55,
                    json.dumps(
                        {
                            "domain": domain,
                            "title": title,
                            "angle": str(item.get("angle") or "")[:300],
                            "source": "llm_ideation",
                        }
                    ),
                )
            written += 1
        except Exception as e:
            logger.warning("ideate insert: %s", e)
    return written


async def refresh_topic_pool(db_pool) -> Dict[str, Any]:
    """Crystal mine + LLM ideation (called from agent / hive)."""
    crystals = await mine_crystal_themes(db_pool)
    llm = await ideate_topics_llm(db_pool)
    return {"crystal_themes": crystals, "llm_topics": llm}
