"""
Nate Autonomous Agent Template — Phase 10 of Sovereign Quantum Nate Build.

Base class `NateAutonomousAgent` with observe → recall → reason → propose → crystallize
cycle. Uses inference router (Phase 7), knowledge recall (Phase 9),
crystal storage (Phase 4), coherence governance (Phase 9).

The propose() step generates structured innovation proposals when an agent
discovers high-confidence, actionable insights that could improve the system.
Proposals require admin approval via /api/nate-agent/innovations/pending.

Subclasses: MarketingIntelligence, ClinicalPattern, CoachDiscovery,
ThreatIntelligence, CulturalIntelligence, ResearchSynthesis.
"""

import asyncio
import json
import logging
import time
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# Domain creativity temperatures
DOMAIN_TEMPERATURES = {
    "clinical": 0.3,
    "defense": 0.3,
    "coding": 0.3,
    "research": 0.6,
    "coaching": 0.5,
    "marketing": 0.8,
    "culture": 0.9,
}


class NateAutonomousAgent(ABC):
    """
    Base class for self-learning domain agents.

    Lifecycle: observe() → recall() → reason() → propose() → crystallize()
    All operations flow through the inference router for provider-agnostic AI.
    The propose() step generates innovation proposals for high-confidence insights.
    """

    _PROPOSE_CONFIDENCE_THRESHOLD = 0.7
    _PROPOSE_COOLDOWN_HOURS = 12
    _PROPOSE_MAX_PER_DAY = 3

    def __init__(
        self,
        agent_name: str,
        domain: str,
        cycle_hours: float = 4.0,
        db_pool=None,
        app_state=None,
    ):
        self.agent_name = agent_name
        self.domain = domain
        self.cycle_hours = cycle_hours
        self._db_pool = db_pool
        self._app_state = app_state
        self._running = False
        self._task: Optional[asyncio.Task] = None
        self._cycle_count = 0
        self._last_cycle = datetime.min.replace(tzinfo=timezone.utc)
        self._temperature = DOMAIN_TEMPERATURES.get(domain, 0.6)
        self._last_proposal_time: float = 0
        self._proposals_today: int = 0
        self._proposals_today_date: Optional[str] = None

    async def start(self):
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._run_loop())
        logger.info("%s agent started (domain=%s, cycle=%sh)", self.agent_name, self.domain, self.cycle_hours)

    async def stop(self):
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    async def _run_loop(self):
        await asyncio.sleep(330)
        while self._running:
            try:
                await self.cycle()
                self._cycle_count += 1
                self._last_cycle = datetime.now(timezone.utc)
            except Exception as e:
                logger.warning("%s cycle error: %s", self.agent_name, e)

            await asyncio.sleep(int(self.cycle_hours * 3600))

    async def cycle(self):
        """Full observe → recall → reason → propose → crystallize cycle."""
        observations = await self.observe()
        if not observations:
            return

        context = await self.recall(observations)
        insights = await self.reason(observations, context)

        if insights:
            await self.propose(insights)
            await self.crystallize(insights)

    # ── Observe ──

    @abstractmethod
    async def observe(self) -> List[Dict[str, Any]]:
        """
        Gather new observations from domain-specific sources.
        Returns list of observation dicts with 'text', 'source', 'created_at'.
        """
        ...

    # ── Recall ──

    async def recall(self, observations: List[Dict]) -> str:
        """Semantic recall of related existing knowledge."""
        if not observations:
            return ""

        query = " ".join(o.get("text", "")[:200] for o in observations[:5])[:1000]

        try:
            from app.services.vectorize_service import semantic_search_all, is_vectorize_configured
            if is_vectorize_configured():
                results = await semantic_search_all(query, limit=5)
                if results:
                    return "\n".join(
                        f"- {r.get('text', '')[:300]}" for r in results
                        if r.get("score", 0) >= 0.5
                    )
        except Exception as e:
            logger.debug("%s recall failed: %s", self.agent_name, e)

        return ""

    # ── Reason ──

    async def reason(
        self,
        observations: List[Dict],
        context: str,
    ) -> List[Dict[str, Any]]:
        """Use inference router to generate insights from observations + context."""
        if not observations:
            return []

        obs_text = "\n".join(f"- {o.get('text', '')[:300]}" for o in observations[:10])
        prompt = self._build_reasoning_prompt(obs_text, context)

        try:
            inference = getattr(self._app_state, "inference_router", None) if self._app_state else None
            if inference:
                result = await inference.generate(
                    prompt=prompt,
                    system=self._get_system_prompt(),
                    tier="analytical",
                    temperature=self._temperature,
                    domain=self.domain,
                    max_tokens=800,
                )
                text = result.get("text", "") if isinstance(result, dict) else str(result)
                if text and len(text) > 30:
                    return [{"text": text.strip(), "domain": self.domain, "source": self.agent_name}]
        except Exception as e:
            logger.warning("%s reasoning failed: %s", self.agent_name, e)

        return []

    def _build_reasoning_prompt(self, observations: str, context: str) -> str:
        return (
            f"Domain: {self.domain}\n\n"
            f"New observations:\n{observations}\n\n"
            f"Existing knowledge:\n{context or '(none)'}\n\n"
            f"Synthesize one actionable insight from these observations. "
            f"Be specific and factual."
        )

    def _get_system_prompt(self) -> str:
        return (
            f"You are a {self.domain} intelligence agent for Little Nate. "
            f"Analyze domain observations and extract actionable insights. "
            f"Never fabricate data. If uncertain, say so."
        )

    # ── Propose ──

    async def propose(self, insights: List[Dict]):
        """
        Generate innovation proposals from high-confidence insights.

        Circuit breakers:
        - Max _PROPOSE_MAX_PER_DAY proposals per day per agent
        - Cooldown of _PROPOSE_COOLDOWN_HOURS between proposals
        - Only insights exceeding _PROPOSE_CONFIDENCE_THRESHOLD trigger proposals
        """
        if not self._db_pool or not insights:
            return

        now = time.time()
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

        if self._proposals_today_date != today:
            self._proposals_today = 0
            self._proposals_today_date = today

        if self._proposals_today >= self._PROPOSE_MAX_PER_DAY:
            return
        if (now - self._last_proposal_time) < (self._PROPOSE_COOLDOWN_HOURS * 3600):
            return

        for insight in insights:
            text = insight.get("text", "")
            if len(text) < 100:
                continue

            inference = getattr(self._app_state, "inference_router", None) if self._app_state else None
            if not inference:
                continue

            try:
                eval_prompt = (
                    f"You are a system improvement analyst for Little Nate.\n"
                    f"Domain: {self.domain}\n\n"
                    f"Insight:\n{text[:1500]}\n\n"
                    f"Does this insight suggest a concrete system improvement that could be implemented "
                    f"as a new formula, D1 table, widget, or webhook?\n"
                    f"If yes, respond with a JSON object:\n"
                    f'{{"actionable": true, "extension_type": "formula|table|widget|webhook", '
                    f'"executive_summary": "...", "problem_statement": "...", '
                    f'"proposed_solution": {{}}, "system_impact": {{}}, '
                    f'"rollback_plan": "..."}}\n'
                    f"If no, respond with: {{\"actionable\": false}}"
                )
                result = await inference.generate(
                    prompt=eval_prompt,
                    system="You are a precise system architect. Output only valid JSON.",
                    tier="utility",
                    temperature=0.3,
                    domain=self.domain,
                    max_tokens=500,
                )
                result_text = result.get("text", "") if isinstance(result, dict) else str(result)
                result_text = result_text.strip()

                start_idx = result_text.find("{")
                end_idx = result_text.rfind("}") + 1
                if start_idx >= 0 and end_idx > start_idx:
                    parsed = json.loads(result_text[start_idx:end_idx])
                else:
                    continue

                if not parsed.get("actionable"):
                    continue

                async with self._db_pool.acquire() as conn:
                    await conn.execute("""
                        INSERT INTO innovation_proposals
                        (proposed_by, extension_type, domain, executive_summary,
                         problem_statement, proposed_solution, system_impact,
                         rollback_plan, dependencies, success_criteria)
                        VALUES ($1, $2, $3, $4, $5, $6::jsonb, $7::jsonb, $8,
                                '[]'::jsonb, '[]'::jsonb)
                    """,
                        f"agent:{self.agent_name}",
                        parsed.get("extension_type", "formula"),
                        self.domain,
                        parsed.get("executive_summary", text[:200]),
                        parsed.get("problem_statement", text[:500]),
                        json.dumps(parsed.get("proposed_solution", {})),
                        json.dumps(parsed.get("system_impact", {})),
                        parsed.get("rollback_plan", "Deactivate extension via admin API"),
                    )
                self._proposals_today += 1
                self._last_proposal_time = now
                logger.info("%s submitted innovation proposal: %s",
                            self.agent_name, parsed.get("executive_summary", "")[:100])
                break  # one proposal per cycle max

            except (json.JSONDecodeError, KeyError):
                continue
            except Exception as e:
                logger.debug("%s proposal generation failed: %s", self.agent_name, e)
                continue

    # ── Crystallize ──

    async def crystallize(self, insights: List[Dict]):
        """Feed insights to the memory crystallizer for storage."""
        crystallizer = getattr(self._app_state, "nate_memory_crystallizer", None) if self._app_state else None
        if not crystallizer:
            return

        for insight in insights:
            fragment = {
                "text": insight.get("text", "")[:2000],
                "source": f"agent:{self.agent_name}",
                "domain": self.domain,
                "scope": "global" if self.domain not in ("clinical", "defense") else "admin_only",
                "created_at": datetime.now(timezone.utc),
            }
            crystallizer._harvest_buffer.append(fragment)

        # Trigger auto-research for low-confidence topics
        if self._db_pool:
            await self._trigger_research_if_needed(insights)

    async def _trigger_research_if_needed(self, insights: List[Dict]):
        """Auto-schedule research for low-confidence insights (Phase 10.4)."""
        for insight in insights:
            text = insight.get("text", "")
            if len(text) < 50:
                continue

            try:
                from app.services.search_proxy import SecureSearchProxy
                proxy = SecureSearchProxy(data_dir="/tmp/nate_agent_search")
                search_query = text[:100].split(".")[0]
                result = await proxy.execute_search(search_query, coach_id="system")
                if result and result.get("results"):
                    summary = result["results"][0].get("snippet", "")[:500]
                    if summary and self._db_pool:
                        async with self._db_pool.acquire() as conn:
                            await conn.execute("""
                                INSERT INTO web_wisdom (query, summary, source, searched_at)
                                VALUES ($1, $2, $3, NOW())
                                ON CONFLICT DO NOTHING
                            """, search_query, summary, f"auto_research:{self.agent_name}")
            except Exception:
                pass

    def get_status(self) -> Dict[str, Any]:
        return {
            "agent": self.agent_name,
            "domain": self.domain,
            "running": self._running,
            "cycle_count": self._cycle_count,
            "last_cycle": self._last_cycle.isoformat() if self._last_cycle != datetime.min.replace(tzinfo=timezone.utc) else None,
            "temperature": self._temperature,
        }


# ═══════════════════════════════════════════════════════════════
# Domain Filing Agents
# ═══════════════════════════════════════════════════════════════

class MarketingIntelligenceAgent(NateAutonomousAgent):
    """Observes marketing playbook, post analytics, funnel data, growth aggregates."""

    def __init__(self, **kwargs):
        super().__init__("MarketingIntelligence", "marketing", cycle_hours=4, **kwargs)

    async def observe(self) -> List[Dict]:
        # QUANTUM-CRYSTAL-ARCH — Phase 5: widen observe; never trial chat text
        observations: List[Dict] = []
        if not self._db_pool:
            return observations
        now = datetime.now(timezone.utc)

        async with self._db_pool.acquire() as conn:
            try:
                rows = await conn.fetch("""
                    SELECT type, content, platform, created_at
                    FROM skyeye_activity
                    WHERE created_at > NOW() - INTERVAL '4 hours'
                      AND type IN ('post_published', 'campaign_touchpoint', 'engagement_detected')
                    ORDER BY created_at DESC LIMIT 20
                """)
                for r in rows:
                    observations.append({
                        "text": f"[{r['type']}] {(r['content'] or '')[:300]}",
                        "source": "skyeye_activity",
                        "created_at": r["created_at"],
                    })
            except Exception as e:
                logger.debug("Marketing observe skyeye_activity: %s", e)

            try:
                rows = await conn.fetch("""
                    SELECT platform, post_id, likes, reposts, comments, impressions, captured_at
                    FROM skyeye_post_analytics
                    WHERE captured_at > NOW() - INTERVAL '7 days'
                    ORDER BY captured_at DESC LIMIT 15
                """)
                for r in rows:
                    observations.append({
                        "text": (
                            f"[post_analytics] {r['platform']} likes={r.get('likes')} "
                            f"reposts={r.get('reposts')} comments={r.get('comments')} "
                            f"impressions={r.get('impressions')}"
                        ),
                        "source": "skyeye_post_analytics",
                        "created_at": r.get("captured_at") or now,
                    })
            except Exception as e:
                logger.debug("Marketing observe post_analytics: %s", e)

            try:
                rows = await conn.fetch("""
                    SELECT stage, COUNT(*)::int AS n
                    FROM funnel_routing_log
                    WHERE created_at > NOW() - INTERVAL '7 days'
                    GROUP BY stage ORDER BY n DESC LIMIT 10
                """)
                for r in rows:
                    observations.append({
                        "text": f"[funnel_routing] stage={r['stage']} n={r['n']}",
                        "source": "funnel_routing_log",
                        "created_at": now,
                    })
            except Exception as e:
                logger.debug("Marketing observe funnel: %s", e)

            try:
                rows = await conn.fetch("""
                    SELECT content_type, status, COUNT(*)::int AS n
                    FROM marketing_content
                    WHERE updated_at > NOW() - INTERVAL '14 days'
                    GROUP BY content_type, status ORDER BY n DESC LIMIT 12
                """)
                for r in rows:
                    observations.append({
                        "text": (
                            f"[marketing_content] type={r['content_type']} "
                            f"status={r['status']} n={r['n']}"
                        ),
                        "source": "marketing_content",
                        "created_at": now,
                    })
            except Exception as e:
                logger.debug("Marketing observe marketing_content: %s", e)

            try:
                rows = await conn.fetch("""
                    SELECT content_kind, SUM(score)::float AS s, COUNT(*)::int AS n
                    FROM bwas_weekly
                    WHERE week_bucket >= CURRENT_DATE - 28
                    GROUP BY content_kind ORDER BY s DESC NULLS LAST LIMIT 10
                """)
                for r in rows:
                    observations.append({
                        "text": (
                            f"[bwas_weekly] kind={r['content_kind']} "
                            f"score={r['s']} rows={r['n']}"
                        ),
                        "source": "bwas_weekly",
                        "created_at": now,
                    })
            except Exception as e:
                logger.debug("Marketing observe bwas: %s", e)

            try:
                rows = await conn.fetch("""
                    SELECT theme, SUM(count_bucket)::int AS total
                    FROM try_theme_weekly
                    WHERE week_bucket >= CURRENT_DATE - 28
                    GROUP BY theme ORDER BY total DESC LIMIT 10
                """)
                for r in rows:
                    if (r["theme"] or "") == "ops_only":
                        continue
                    observations.append({
                        "text": f"[try_theme_weekly] theme={r['theme']} total={r['total']}",
                        "source": "try_theme_weekly",
                        "created_at": now,
                    })
            except Exception as e:
                logger.debug("Marketing observe try_themes: %s", e)

            try:
                rows = await conn.fetch("""
                    SELECT keyword, audience, demand_prior, priority_score, status
                    FROM keyword_queue
                    WHERE status IN ('queued', 'in_progress', 'done')
                    ORDER BY priority_score DESC NULLS LAST LIMIT 10
                """)
                for r in rows:
                    observations.append({
                        "text": (
                            f"[keyword_queue] {r['keyword']} aud={r['audience']} "
                            f"demand={r['demand_prior']} score={r['priority_score']} "
                            f"status={r['status']}"
                        ),
                        "source": "keyword_queue",
                        "created_at": now,
                    })
            except Exception as e:
                logger.debug("Marketing observe keywords: %s", e)

            try:
                rows = await conn.fetch("""
                    SELECT test_name, status, winner, verdict, hypothesis
                    FROM content_ab_tests
                    ORDER BY created_at DESC LIMIT 8
                """)
                for r in rows:
                    observations.append({
                        "text": (
                            f"[content_ab_tests] {r['test_name']} status={r['status']} "
                            f"winner={r.get('winner')} verdict={r.get('verdict')}"
                        ),
                        "source": "content_ab_tests",
                        "created_at": now,
                    })
            except Exception as e:
                logger.debug("Marketing observe ab_tests: %s", e)

        return observations

    async def recall(self, observations: List[Dict]) -> str:
        """Phase 5: FederatedSearch domain=marketing via growth crystal_bridge."""
        if not observations:
            return ""
        query = " ".join(o.get("text", "")[:200] for o in observations[:5])[:1000]
        try:
            from app.services.growth.crystal_bridge import recall_marketing

            ctx = await recall_marketing(
                self._db_pool, query, app_state=self._app_state, limit=5
            )
            if ctx:
                return ctx
        except Exception as e:
            logger.debug("Marketing FederatedSearch recall failed: %s", e)
        return await super().recall(observations)

    async def crystallize(self, insights: List[Dict]):
        """Route marketing insights through growth crystal_bridge allowlist."""
        try:
            from app.services.growth.crystal_bridge import harvest_marketing_insight

            for insight in insights:
                harvest_marketing_insight(
                    self._app_state,
                    text=insight.get("text", ""),
                    source="agent:MarketingIntelligence",
                )
            if self._db_pool:
                await self._trigger_research_if_needed(insights)
            return
        except Exception as e:
            logger.debug("Marketing crystal_bridge harvest failed: %s", e)
        await super().crystallize(insights)


class ClinicalPatternAgent(NateAutonomousAgent):
    """Observes anonymized coaching session patterns (min 5 clients for privacy)."""

    def __init__(self, **kwargs):
        super().__init__("ClinicalPattern", "clinical", cycle_hours=6, **kwargs)

    async def observe(self) -> List[Dict]:
        observations = []
        if not self._db_pool:
            return observations
        try:
            async with self._db_pool.acquire() as conn:
                row = await conn.fetchrow("""
                    SELECT COUNT(DISTINCT user_id) AS users,
                           AVG(c_emo) AS avg_coherence,
                           COUNT(*) AS measurements
                    FROM nevedal_metrics
                    WHERE recorded_at > NOW() - INTERVAL '6 hours'
                """)
                if row and (row["users"] or 0) >= 5:
                    observations.append({
                        "text": f"Aggregated coherence data: {row['users']} users, avg C_emo={row['avg_coherence']:.4f}, {row['measurements']} measurements",
                        "source": "nevedal_metrics",
                        "created_at": datetime.now(timezone.utc),
                    })
        except Exception as e:
            logger.debug("Clinical observe failed: %s", e)
        return observations


class CoachDiscoveryAgent(NateAutonomousAgent):
    """Observes coaching sessions, wisdom extractions, DOJO activity."""

    def __init__(self, **kwargs):
        super().__init__("CoachDiscovery", "coaching", cycle_hours=4, **kwargs)

    async def observe(self) -> List[Dict]:
        observations = []
        if not self._db_pool:
            return observations
        try:
            async with self._db_pool.acquire() as conn:
                rows = await conn.fetch("""
                    SELECT insight_text, insight_type, created_at
                    FROM wisdom_extractions
                    WHERE created_at > NOW() - INTERVAL '4 hours'
                      AND status = 'approved'
                    ORDER BY created_at DESC LIMIT 10
                """)
                for r in rows:
                    observations.append({
                        "text": f"[{r['insight_type']}] {r['insight_text'][:300]}",
                        "source": "wisdom_extractions",
                        "created_at": r["created_at"],
                    })
        except Exception as e:
            logger.debug("Coach observe failed: %s", e)
        return observations


class ThreatIntelligenceAgent(NateAutonomousAgent):
    """Observes defense alerts, Sentinel events, curiosity escalations."""

    def __init__(self, **kwargs):
        super().__init__("ThreatIntelligence", "defense", cycle_hours=2, **kwargs)

    async def observe(self) -> List[Dict]:
        observations = []
        if not self._db_pool:
            return observations
        try:
            async with self._db_pool.acquire() as conn:
                rows = await conn.fetch("""
                    SELECT type, content, created_at
                    FROM skyeye_activity
                    WHERE created_at > NOW() - INTERVAL '2 hours'
                      AND (type LIKE '%threat%' OR type LIKE '%sentinel%'
                           OR type LIKE '%defense%' OR type LIKE '%curiosity%')
                    ORDER BY created_at DESC LIMIT 20
                """)
                for r in rows:
                    observations.append({
                        "text": f"[DEFENSE:{r['type']}] {(r['content'] or '')[:300]}",
                        "source": "skyeye_activity",
                        "created_at": r["created_at"],
                    })
        except Exception as e:
            logger.debug("Threat observe failed: %s", e)
        return observations


class CulturalIntelligenceAgent(NateAutonomousAgent):
    """Observes social engagement, audience responses, language drift."""

    def __init__(self, **kwargs):
        super().__init__("CulturalIntelligence", "culture", cycle_hours=6, **kwargs)

    async def observe(self) -> List[Dict]:
        observations = []
        if not self._db_pool:
            return observations
        try:
            async with self._db_pool.acquire() as conn:
                rows = await conn.fetch("""
                    SELECT analysis_type, detail, created_at
                    FROM liminal_presence_analysis
                    WHERE created_at > NOW() - INTERVAL '6 hours'
                    ORDER BY created_at DESC LIMIT 10
                """)
                for r in rows:
                    observations.append({
                        "text": f"[{r['analysis_type']}] {(r['detail'] or '')[:300]}",
                        "source": "liminal_presence_analysis",
                        "created_at": r["created_at"],
                    })
        except Exception as e:
            logger.debug("Cultural observe failed: %s", e)
        return observations


class ResearchSynthesisAgent(NateAutonomousAgent):
    """Observes web wisdom, intelligence crystals, knowledge gaps."""

    def __init__(self, **kwargs):
        super().__init__("ResearchSynthesis", "research", cycle_hours=4, **kwargs)

    async def observe(self) -> List[Dict]:
        observations = []
        if not self._db_pool:
            return observations
        try:
            async with self._db_pool.acquire() as conn:
                rows = await conn.fetch("""
                    SELECT query, summary, searched_at
                    FROM web_wisdom
                    WHERE searched_at > NOW() - INTERVAL '4 hours'
                    ORDER BY searched_at DESC LIMIT 15
                """)
                for r in rows:
                    observations.append({
                        "text": f"Q: {r['query']}\nA: {(r['summary'] or '')[:300]}",
                        "source": "web_wisdom",
                        "created_at": r["searched_at"],
                    })

                # Low-confidence crystals needing research
                weak = await conn.fetch("""
                    SELECT crystal_text, domain, confidence
                    FROM nate_intelligence_crystals
                    WHERE confidence < 0.5
                      AND superseded_by IS NULL
                      AND scope != 'archived'
                    ORDER BY confidence ASC LIMIT 5
                """)
                for r in weak:
                    observations.append({
                        "text": f"[LOW_CONF:{r['confidence']:.2f}] {r['crystal_text'][:200]}",
                        "source": "intelligence_crystals",
                        "created_at": datetime.now(timezone.utc),
                    })
        except Exception as e:
            logger.debug("Research observe failed: %s", e)

        # Autonomous internet search for knowledge enrichment
        await self._internet_observe(observations)
        return observations

    async def _internet_observe(self, observations: List[Dict]):
        """Search the internet for topics where crystals are weak or missing."""
        try:
            from app.services.search_proxy import SecureSearchProxy
            proxy = SecureSearchProxy(data_dir="/tmp/nate_research_agent")
        except Exception:
            return

        research_topics = []

        # Extract topics from low-confidence crystals
        for obs in observations:
            if obs.get("source") == "intelligence_crystals":
                _text = obs.get("text", "")
                _first_sentence = _text.split("]")[-1].strip().split(".")[0]
                if len(_first_sentence) > 15:
                    research_topics.append(f"{_first_sentence} research findings 2026")

        # Rotate through evergreen research topics
        _day = int(datetime.now(timezone.utc).strftime("%j"))
        _research_bank = [
            "therapeutic AI ethical guidelines clinical practice",
            "emotional coherence measurement voice biomarkers",
            "quantum cognition decision making theory",
            "BLE mesh networking group therapy applications",
            "trauma-informed AI design principles",
            "attachment theory digital therapeutic alliance",
            "psychedelic-assisted therapy integration techniques",
            "resilience factors substance abuse recovery",
            "motivational interviewing AI applications",
            "family systems therapy measurement outcomes",
            "neuroplasticity coaching evidence-based methods",
            "HIPAA compliance AI therapy platforms 2026",
        ]
        research_topics.append(_research_bank[_day % len(_research_bank)])

        for query in research_topics[:3]:
            try:
                result = await proxy.execute_search(
                    query, coach_id="research_agent", num_results=3
                )
                if result.get("success") and result.get("results"):
                    for sr in result["results"][:2]:
                        snippet = sr.get("snippet", "")
                        title = sr.get("title", "")
                        url = sr.get("url", "")
                        if len(snippet) > 40:
                            observations.append({
                                "text": (f"[Internet Research: {title}]\n"
                                         f"{snippet}\nSource: {url}"),
                                "source": "internet_research",
                                "created_at": datetime.now(timezone.utc),
                            })
            except Exception:
                continue
