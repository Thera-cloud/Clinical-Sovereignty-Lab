"""
Code Intelligence Agent — 7th Domain Agent (domain="coding").

Autonomously learns code knowledge from internet sources, crystallizes
actionable patterns as TENSION crystals, and tracks dual-brain coherence
via the Nevedal C_emo formula. Every resolved TENSION becomes a future
LOCKED recall — the critical multiplier loop.

EXA Methodology v5: This agent is the primary knowledge harvester for
the ExaFLOPS-equivalent intelligence growth model. Each cycle:
  1. observe() — scan code RSS, GitHub trending, StackOverflow
  2. recall()  — check existing code crystals to avoid duplication
  3. reason()  — synthesize novel insights via sovereign 14B inference
  4. propose() — generate innovation proposals for high-confidence finds
  5. crystallize() — store as TENSION crystals in PG + Vectorize + R2

Crystal pruning (not decay): Code crystals never time-decay. They are
pruned only when confidence drops below the C_emo-aware floor or when
superseded by a higher-confidence crystal on the same topic.
"""

import asyncio
import hashlib
import json
import logging
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

try:
    from app.services.nate_agent_template import NateAutonomousAgent
except ImportError:
    NateAutonomousAgent = object

CODE_RSS_SOURCES = [
    {"url": "https://dev.to/feed", "name": "Dev.to"},
    {"url": "https://hnrss.org/best?count=10", "name": "Hacker News Best"},
    {"url": "https://realpython.com/atom.xml", "name": "Real Python"},
    {"url": "https://blog.python.org/feeds/posts/default", "name": "Python Blog"},
    {"url": "https://medium.com/feed/flutter", "name": "Flutter Medium"},
]

SEARCH_SUFFIXES = [
    "python implementation best practices",
    "production code example",
    "common pitfalls and fixes",
    "performance optimization",
]

TECH_STACK_TAGS = [
    "python", "fastapi", "flutter", "dart", "postgresql", "redis",
    "asyncio", "websocket", "cloudflare-workers", "docker",
    "javascript", "typescript", "react", "tailwind",
]


class CodeIntelligenceAgent(NateAutonomousAgent):
    """
    Self-learning code intelligence agent.

    Runs every 2 hours. Harvests code knowledge from RSS feeds, GitHub
    trending, and StackOverflow. Uses SecureSearchProxy for targeted
    internet research. Crystallizes actionable patterns as TENSION
    crystals indexed in nate-code-search Vectorize.
    """

    def __init__(self, db_pool=None, app_state=None):
        super().__init__(
            agent_name="CodeIntelligenceAgent",
            domain="coding",
            cycle_hours=2.0,
            db_pool=db_pool,
            app_state=app_state,
        )
        self._search_proxy = None
        self._crystallizer = None
        self._nevedal_engine = None
        self._inference_router = None
        self._cycle_detection_engine = None
        self._foresight_engine = None

    async def start(self):
        if self._app_state:
            self._search_proxy = getattr(self._app_state, "search_proxy", None)
            self._crystallizer = getattr(self._app_state, "crystallizer", None)
            self._nevedal_engine = getattr(self._app_state, "nevedal_engine", None)
            self._inference_router = getattr(self._app_state, "inference_router", None)
            self._cycle_detection_engine = getattr(self._app_state, "cycle_detection_engine", None)
            self._foresight_engine = getattr(self._app_state, "foresight_engine", None)
        await super().start()

    # ------------------------------------------------------------------
    # observe() — harvest code knowledge from multiple sources
    # ------------------------------------------------------------------

    async def observe(self) -> List[Dict[str, Any]]:
        observations = []

        # 1. Read from web_wisdom table (populated by WebContentReader's code RSS)
        if self._db_pool:
            try:
                async with self._db_pool.acquire() as conn:
                    rows = await conn.fetch("""
                        SELECT id, title, summary, url, source_type
                        FROM web_wisdom
                        WHERE source_type = 'code'
                          AND applied_to_content = false
                          AND created_at > NOW() - INTERVAL '48 hours'
                        ORDER BY created_at DESC
                        LIMIT 20
                    """)
                    for row in rows:
                        observations.append({
                            "source": "rss",
                            "title": row["title"],
                            "content": (row["summary"] or "")[:2000],
                            "url": row["url"],
                            "web_wisdom_id": row["id"],
                        })
                        await conn.execute(
                            "UPDATE web_wisdom SET applied_to_content = true WHERE id = $1",
                            row["id"],
                        )
            except Exception as e:
                logger.warning("CodeIntelligenceAgent: web_wisdom query failed: %s", e)

        # 2. StackOverflow hot questions (API, no auth needed)
        try:
            import aiohttp
            async with aiohttp.ClientSession() as session:
                tags = "python;fastapi;flutter"
                url = (
                    f"https://api.stackexchange.com/2.3/questions"
                    f"?order=desc&sort=hot&site=stackoverflow"
                    f"&tagged={tags}&filter=withbody&pagesize=5"
                )
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        for item in data.get("items", [])[:5]:
                            title = item.get("title", "")
                            body = item.get("body", "")[:1500]
                            body_text = re.sub(r"<[^>]+>", "", body)
                            observations.append({
                                "source": "stackoverflow",
                                "title": title,
                                "content": body_text,
                                "url": item.get("link", ""),
                                "tags": item.get("tags", []),
                            })
        except Exception as e:
            logger.warning("CodeIntelligenceAgent: StackOverflow fetch failed: %s", e)

        # 3. Targeted internet search for gaps in code crystals
        if self._search_proxy and self._db_pool:
            try:
                async with self._db_pool.acquire() as conn:
                    low_conf = await conn.fetch("""
                        SELECT crystal_text, domain, confidence, topics
                        FROM nate_intelligence_crystals
                        WHERE domain = 'coding'
                          AND confidence < 0.5
                          AND superseded_by IS NULL
                          AND scope != 'archived'
                        ORDER BY confidence ASC
                        LIMIT 3
                    """)
                for crystal in low_conf:
                    concept = (crystal["crystal_text"] or "")[:100]
                    suffix = SEARCH_SUFFIXES[self._cycle_count % len(SEARCH_SUFFIXES)]
                    query = f"{concept} {suffix}"
                    try:
                        results = await self._search_proxy.execute_search(query, max_results=3)
                        for r in results:
                            observations.append({
                                "source": "internet_research",
                                "title": r.get("title", ""),
                                "content": r.get("snippet", "")[:1500],
                                "url": r.get("url", ""),
                                "research_target": concept[:80],
                            })
                    except Exception as e:
                        logger.warning("CodeIntelligenceAgent: search failed for '%s': %s", concept[:40], e)
            except Exception as e:
                logger.warning("CodeIntelligenceAgent: low-confidence crystal query failed: %s", e)

        logger.info("CodeIntelligenceAgent: observed %d items from %d sources",
                     len(observations), len({o["source"] for o in observations}))
        return observations

    # ------------------------------------------------------------------
    # recall() — check existing crystals to avoid duplication
    # ------------------------------------------------------------------

    async def recall(self, observations: List[Dict]) -> List[Dict]:
        if not observations:
            return []

        novel = []
        for obs in observations:
            content_hash = hashlib.sha256(
                (obs.get("title", "") + obs.get("content", "")[:500]).encode()
            ).hexdigest()[:16]

            if self._db_pool:
                try:
                    async with self._db_pool.acquire() as conn:
                        exists = await conn.fetchval("""
                            SELECT COUNT(*) FROM nate_intelligence_crystals
                            WHERE domain = 'coding'
                              AND content_hash LIKE $1 || '%'
                              AND scope != 'archived'
                        """, content_hash[:12])
                        if exists and exists > 0:
                            continue
                except Exception:
                    pass

            obs["_content_hash"] = content_hash
            novel.append(obs)

        logger.info("CodeIntelligenceAgent: %d/%d observations are novel",
                     len(novel), len(observations))
        return novel

    # ------------------------------------------------------------------
    # reason() — synthesize code insights via sovereign 14B
    # ------------------------------------------------------------------

    async def reason(self, novel_observations: List[Dict], context: str = "") -> List[Dict]:
        if not novel_observations or not self._inference_router:
            return []

        insights = []
        batch = novel_observations[:10]

        for obs in batch:
            prompt = (
                f"Analyze this code knowledge and extract actionable patterns:\n\n"
                f"Title: {obs.get('title', 'N/A')}\n"
                f"Source: {obs.get('source', 'unknown')}\n"
                f"Content:\n{obs.get('content', '')[:1500]}\n\n"
                f"Extract:\n"
                f"1. Core pattern/technique (1-2 sentences)\n"
                f"2. When to use it (context)\n"
                f"3. Code example if applicable\n"
                f"4. Common mistakes to avoid\n"
                f"5. Relevant tags from: {', '.join(TECH_STACK_TAGS[:8])}"
            )

            try:
                result = await self._inference_router.generate(
                    prompt=prompt,
                    system="You are a senior software engineer. Extract concise, actionable code patterns. Be precise and practical.",
                    tier="coding",
                    domain="coding",
                    temperature=0.3,
                    max_tokens=800,
                )
                response = result.get("text", "")
                if len(response) > 50:
                    tags = self._extract_tags(response, obs)
                    insights.append({
                        "text": f"[CODE PATTERN] {obs.get('title', 'Untitled')}\n\n{response}",
                        "source": obs.get("source", "unknown"),
                        "source_url": obs.get("url", ""),
                        "tags": tags,
                        "confidence": min(0.7, result.get("confidence", 0.5)),
                        "provider": result.get("provider", "unknown"),
                        "signal": result.get("odpe_signal", "PROVISIONAL"),
                    })
            except Exception as e:
                logger.warning("CodeIntelligenceAgent: reasoning failed for '%s': %s",
                               obs.get("title", "")[:40], e)

        logger.info("CodeIntelligenceAgent: synthesized %d insights from %d observations",
                     len(insights), len(batch))
        return insights

    # ------------------------------------------------------------------
    # crystallize() — store as TENSION crystals
    # ------------------------------------------------------------------

    async def crystallize(self, insights: List[Dict]) -> int:
        if not insights or not self._crystallizer:
            return 0

        stored = 0
        for insight in insights:
            try:
                fragment = {
                    "text": insight["text"],
                    "source": f"code_agent:{insight.get('source', 'unknown')}",
                    "domain": "coding",
                    "scope": "global",
                    "topics": insight.get("tags", []),
                    "created_at": datetime.now(timezone.utc),
                }
                self._crystallizer._harvest_buffer.append(fragment)
                stored += 1

                # Track C_emo evolution after crystallization
                await self._track_coherence(insight)
            except Exception as e:
                logger.warning("CodeIntelligenceAgent: crystallize failed: %s", e)

        if stored > 0:
            await self._update_crystal_count()

        logger.info("CodeIntelligenceAgent: crystallized %d/%d insights", stored, len(insights))
        return stored

    # ------------------------------------------------------------------
    # TENSION crystal auto-creation from resolved coding queries
    # ------------------------------------------------------------------

    async def auto_crystallize_tension_resolution(
        self, query: str, response: str, provider: str, signal: str
    ):
        """
        Called after a coding TENSION/DEEP_TENSION query is resolved.
        The solution becomes a crystal so future similar queries resolve as LOCKED.
        This is the critical multiplier mechanism.
        """
        if signal not in ("TENSION", "DEEP_TENSION"):
            return
        if not self._crystallizer:
            return
        if len(response) < 100:
            return

        fragment = {
            "text": f"Problem: {query[:500]}\nSolution: {response[:1500]}",
            "source": f"tension_resolution:{provider}",
            "domain": "coding",
            "scope": "global",
            "topics": self._extract_tags(response, {"content": query}),
            "created_at": datetime.now(timezone.utc),
        }
        self._crystallizer._harvest_buffer.append(fragment)
        logger.info("CodeIntelligenceAgent: auto-crystallized TENSION resolution (provider=%s)", provider)

        await self._track_coherence({
            "signal": signal,
            "provider": provider,
            "confidence": 0.8 if provider == "sovereign" else 0.6,
        })

    # ------------------------------------------------------------------
    # Dual-brain coherence tracking (Nevedal C_emo for coding)
    # ------------------------------------------------------------------

    async def _track_coherence(self, insight: Dict):
        """Log coding coherence metrics to nevedal_coherence_log."""
        if not self._db_pool:
            return
        try:
            signal = insight.get("signal", "PROVISIONAL")
            provider = insight.get("provider", "unknown")

            async with self._db_pool.acquire() as conn:
                state = await conn.fetchrow(
                    "SELECT * FROM nevedal_domain_state WHERE domain = 'coding'"
                )
                if not state:
                    return

                p_ent = float(state["p_ent"])
                gamma_env = float(state["gamma_env"])
                crystal_count = int(state["crystal_count"])

                # Dual-brain agreement increases p_ent (entanglement)
                if provider in ("sovereign", "workers_ai"):
                    p_ent = min(1.0, p_ent + 0.005)
                if signal == "LOCKED":
                    p_ent = min(1.0, p_ent + 0.01)

                # Environmental noise decreases with each successful resolution
                if signal in ("TENSION", "DEEP_TENSION"):
                    gamma_env = max(0.01, gamma_env - 0.003)
                elif signal == "NOISE":
                    gamma_env = min(1.0, gamma_env + 0.01)

                # Tunneling factor: decreases barrier as crystal count grows
                t_tunnel = 1.0 * _compute_tunneling(crystal_count)

                # Compute C_emo
                beta = float(state["beta"])
                e_g = float(state["e_g"])
                hbar = 1.0
                denominator = gamma_env + (e_g / hbar)
                c_emo = (beta * p_ent * t_tunnel) / denominator if denominator > 0 else 0.0
                c_emo = max(0.0, min(1.0, c_emo))

                await conn.execute("""
                    UPDATE nevedal_domain_state
                    SET p_ent = $1, gamma_env = $2, T_tunnel = $3,
                        C_emo = $4, crystal_count = crystal_count + 1,
                        updated_at = NOW()
                    WHERE domain = 'coding'
                """, p_ent, gamma_env, t_tunnel, c_emo)

                await conn.execute("""
                    INSERT INTO nevedal_coherence_log
                    (domain, C_emo, p_ent, T_tunnel, gamma_env, E_G,
                     signal, provider, crystal_count)
                    VALUES ('coding', $1, $2, $3, $4, $5, $6, $7, $8)
                """, c_emo, p_ent, t_tunnel, gamma_env, e_g,
                    signal, provider, crystal_count + 1)

        except Exception as e:
            logger.warning("CodeIntelligenceAgent: coherence tracking failed: %s", e)

    async def _update_crystal_count(self):
        """Sync crystal_count in nevedal_domain_state from actual DB count."""
        if not self._db_pool:
            return
        try:
            async with self._db_pool.acquire() as conn:
                count = await conn.fetchval("""
                    SELECT COUNT(*) FROM nate_intelligence_crystals
                    WHERE domain = 'coding' AND scope != 'archived'
                """)
                await conn.execute("""
                    UPDATE nevedal_domain_state
                    SET crystal_count = $1, updated_at = NOW()
                    WHERE domain = 'coding'
                """, count or 0)
        except Exception as e:
            logger.warning("CodeIntelligenceAgent: crystal count sync failed: %s", e)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _extract_tags(self, text: str, obs: Dict) -> List[str]:
        """Extract relevant tech tags from text content."""
        combined = (text + " " + obs.get("content", "") + " " +
                    " ".join(obs.get("tags", []))).lower()
        found = [tag for tag in TECH_STACK_TAGS if tag in combined]
        return found[:6] if found else ["general"]


def _compute_tunneling(crystal_count: int, t_0: float = 1.0, lambda_decay: float = 50_000) -> float:
    """
    Quantum tunneling factor: barrier decreases as knowledge density grows.
    T(n) = T_0 * exp(-1 / (1 + n/lambda))
    At n=0, barrier is high (T≈0.37). At n=50k, barrier halves. At n→∞, T→T_0.
    """
    import math
    d = 1.0 / (1.0 + crystal_count / lambda_decay)
    return t_0 * math.exp(-d)
