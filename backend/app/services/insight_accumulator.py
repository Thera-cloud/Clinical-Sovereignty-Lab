"""
SOVEREIGN UNIFICATION — Insight Accumulator
The metacognitive engine that connects all of Little Nate's isolated
knowledge domains into one coherent intelligence.

Periodically synthesizes wisdom from:
    1. Nevedal metrics (C_emo, CEE events, GAP scores)
    2. Lived wisdom (therapy session insights)
    3. Livestream wisdom (viewer interactions)
    4. Social memory (engagement patterns)
    5. Expression wall (what emotional content resonates)
    6. Marketing performance (what campaigns convert)
    7. Web wisdom (external content Nate reads)
    8. Quiz/Golden Ticket data (prospect patterns)

Outputs unified insights to sovereign_insight_journal,
which all other services can read from.
"""

import asyncio
import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

import aiohttp

from app.config import settings

logger = logging.getLogger("sovereign.insight_accumulator")

SYNTHESIS_INTERVAL = 3600  # 1 hour between full synthesis cycles
SELF_REFLECTION_INTERVAL = 86400  # daily self-reflection

SYNTHESIS_PROMPT = """You are the metacognitive layer of Little Nate — the Sovereign Sanctuary AI companion.

Your task: synthesize raw data from multiple systems into actionable insights.
Each insight should be:
- Specific and evidence-based (cite the data)
- Actionable (what should change based on this?)
- Scored for impact (0-1, how much difference would acting on this make?)

Categories to use:
- technique: a therapeutic approach that's proving effective
- trend: a pattern emerging across multiple data sources
- gap: something missing or underperforming
- opportunity: an untapped potential
- warning: something that needs attention

Output valid JSON array of insights:
[{"title": "...", "content": "...", "category": "...", "impact_score": 0.0-1.0, "source_systems": ["...", "..."]}]
"""


class InsightAccumulator:
    """Periodic synthesis engine that unifies all wisdom sources."""

    def __init__(self, db_pool):
        self.db_pool = db_pool
        self._running = False
        self._synthesis_task: Optional[asyncio.Task] = None
        self._reflection_task: Optional[asyncio.Task] = None

    async def start(self):
        if self._running:
            return
        self._running = True
        self._synthesis_task = asyncio.create_task(self._synthesis_loop())
        self._reflection_task = asyncio.create_task(self._reflection_loop())
        logger.info("Insight Accumulator started — unifying all wisdom sources")

    async def stop(self):
        self._running = False
        for task in [self._synthesis_task, self._reflection_task]:
            if task and not task.done():
                task.cancel()
        logger.info("Insight Accumulator stopped")

    async def _synthesis_loop(self):
        await asyncio.sleep(30)
        while self._running:
            try:
                await self.run_synthesis()
            except Exception as e:
                logger.error(f"Synthesis cycle error: {e}")
            await asyncio.sleep(SYNTHESIS_INTERVAL)

    async def _reflection_loop(self):
        await asyncio.sleep(120)
        while self._running:
            try:
                await self.run_self_reflection()
            except Exception as e:
                logger.error(f"Self-reflection error: {e}")
            await asyncio.sleep(SELF_REFLECTION_INTERVAL)

    async def run_synthesis(self):
        """Full synthesis cycle across all wisdom sources."""
        logger.info("Starting synthesis cycle...")

        sources = await asyncio.gather(
            self._gather_nevedal_coherence(),
            self._gather_therapy_wisdom(),
            self._gather_livestream_patterns(),
            self._gather_marketing_performance(),
            self._gather_expression_resonance(),
            self._gather_quiz_patterns(),
            self._gather_web_wisdom(),
            self._gather_social_memory(),
            self._gather_vault_engagement(),
            return_exceptions=True,
        )

        source_names = [
            "nevedal_coherence", "therapy_wisdom", "livestream_patterns",
            "marketing_performance", "expression_resonance", "quiz_patterns",
            "web_wisdom", "social_memory", "vault_engagement",
        ]

        combined = {}
        for name, result in zip(source_names, sources):
            if isinstance(result, Exception):
                logger.warning(f"Failed to gather {name}: {result}")
                combined[name] = {"error": str(result)}
            else:
                combined[name] = result

        insights = await self._synthesize_with_ai(combined)

        for insight in insights:
            await self._store_insight(insight)

        logger.info(f"Synthesis complete: {len(insights)} new insights generated")

    async def run_self_reflection(self):
        """Weekly self-reflection: what's working, what's not, what to change."""
        logger.info("Running self-reflection...")

        async with self.db_pool.acquire() as conn:
            recent_insights = await conn.fetch("""
                SELECT insight_type, category, title, content,
                       coherence_score, impact_score, applied
                FROM sovereign_insight_journal
                WHERE created_at > NOW() - INTERVAL '7 days'
                ORDER BY impact_score DESC NULLS LAST
                LIMIT 30
            """)

            applied_count = sum(1 for r in recent_insights if r["applied"])
            total = len(recent_insights)

        reflection_data = {
            "period": "last_7_days",
            "total_insights": total,
            "applied_insights": applied_count,
            "application_rate": applied_count / total if total > 0 else 0,
            "top_insights": [
                {
                    "title": r["title"],
                    "category": r["category"],
                    "impact": r["impact_score"],
                    "applied": r["applied"],
                }
                for r in recent_insights[:10]
            ],
        }

        reflection = await self._generate_reflection(reflection_data)
        if reflection:
            await self._store_insight({
                "insight_type": "self_reflection",
                "category": "meta_insight",
                "title": f"State of Nate — {datetime.now(timezone.utc).strftime('%b %d')}",
                "content": reflection,
                "impact_score": 0.9,
                "source_systems": ["insight_accumulator"],
                "evidence": reflection_data,
            })

    # ─── Data Gatherers ───────────────────────────────────────────────

    async def _gather_nevedal_coherence(self) -> Dict:
        async with self.db_pool.acquire() as conn:
            metrics = await conn.fetch("""
                SELECT metric_type, metric_value, metadata, created_at
                FROM nevedal_metrics
                WHERE created_at > NOW() - INTERVAL '24 hours'
                ORDER BY created_at DESC
                LIMIT 50
            """)

            cee_count = sum(1 for m in metrics if m.get("metric_type") == "cee_event")

            avg_coherence = 0
            coherence_vals = [
                m["metric_value"] for m in metrics
                if m.get("metric_type") in ("coherence", "c_emo")
                and m.get("metric_value") is not None
            ]
            if coherence_vals:
                avg_coherence = sum(coherence_vals) / len(coherence_vals)

            return {
                "total_measurements": len(metrics),
                "cee_events_24h": cee_count,
                "avg_coherence": round(avg_coherence, 3),
                "sample_metrics": [
                    {
                        "type": m["metric_type"],
                        "value": m["metric_value"],
                        "time": m["created_at"].isoformat(),
                    }
                    for m in metrics[:10]
                ],
            }

    async def _gather_therapy_wisdom(self) -> Dict:
        async with self.db_pool.acquire() as conn:
            try:
                rows = await conn.fetch("""
                    SELECT insight_type, insight_text, confidence, metadata
                    FROM wisdom_extractions
                    WHERE created_at > NOW() - INTERVAL '7 days'
                    ORDER BY confidence DESC
                    LIMIT 20
                """)
                by_type = {}
                for r in rows:
                    t = r["insight_type"]
                    if t not in by_type:
                        by_type[t] = []
                    by_type[t].append({
                        "text": r["insight_text"][:200],
                        "confidence": r["confidence"],
                    })
                return {
                    "total_extractions": len(rows),
                    "by_type": by_type,
                    "top_themes": list(by_type.keys()),
                }
            except Exception:
                return {"total_extractions": 0, "by_type": {}, "note": "table may not exist yet"}

    async def _gather_livestream_patterns(self) -> Dict:
        async with self.db_pool.acquire() as conn:
            sessions = await conn.fetch("""
                SELECT session_id, total_interactions, unique_viewers,
                       signups_attributed, summary, started_at
                FROM livestream_sessions
                WHERE status = 'ended'
                ORDER BY created_at DESC LIMIT 10
            """)

            if not sessions:
                return {"total_sessions": 0, "note": "no completed livestreams yet"}

            wisdom = await conn.fetch("""
                SELECT viewer_question, nate_response, expression_used,
                       signup_cta_given, matched_client_id
                FROM livestream_wisdom
                WHERE created_at > NOW() - INTERVAL '30 days'
                ORDER BY created_at DESC LIMIT 30
            """)

            common_themes = {}
            for w in wisdom:
                q = w["viewer_question"].lower()
                for keyword in ["anxiety", "stress", "relationship", "grief", "purpose",
                                "meaning", "depression", "anger", "fear", "growth"]:
                    if keyword in q:
                        common_themes[keyword] = common_themes.get(keyword, 0) + 1

            return {
                "total_sessions": len(sessions),
                "total_interactions": sum(s["total_interactions"] for s in sessions),
                "total_unique_viewers": sum(s["unique_viewers"] for s in sessions),
                "signups_from_live": sum(s["signups_attributed"] for s in sessions),
                "common_question_themes": common_themes,
                "recent_summaries": [s["summary"] for s in sessions[:3] if s["summary"]],
                "matched_signups": sum(1 for w in wisdom if w["matched_client_id"]),
            }

    async def _gather_marketing_performance(self) -> Dict:
        async with self.db_pool.acquire() as conn:
            try:
                playbook = await conn.fetchrow("""
                    SELECT playbook_data FROM marketing_playbook
                    ORDER BY updated_at DESC LIMIT 1
                """)

                actions = await conn.fetch("""
                    SELECT action_type, status, result_data
                    FROM marketing_actions
                    WHERE created_at > NOW() - INTERVAL '7 days'
                    ORDER BY created_at DESC LIMIT 20
                """)

                growth = await conn.fetchrow("""
                    SELECT snapshot_data FROM growth_snapshots
                    ORDER BY created_at DESC LIMIT 1
                """)

                return {
                    "playbook_active": playbook is not None,
                    "recent_actions": len(actions),
                    "action_types": list(set(a["action_type"] for a in actions)),
                    "completed_actions": sum(1 for a in actions if a["status"] == "completed"),
                    "growth_snapshot": growth["snapshot_data"] if growth else None,
                }
            except Exception as e:
                return {"error": str(e)}

    async def _gather_expression_resonance(self) -> Dict:
        async with self.db_pool.acquire() as conn:
            try:
                expressions = await conn.fetch("""
                    SELECT id, emotional_theme, expression_text, status,
                           posted_platform, engagement_data
                    FROM skyeye_live_expressions
                    WHERE created_at > NOW() - INTERVAL '14 days'
                    ORDER BY created_at DESC LIMIT 30
                """)

                posted = [e for e in expressions if e["status"] == "posted"]
                themes = {}
                for e in expressions:
                    t = e.get("emotional_theme", "unknown")
                    if t not in themes:
                        themes[t] = 0
                    themes[t] += 1

                engagement = await conn.fetch("""
                    SELECT emotional_theme, AVG(engagement_rate) as avg_eng,
                           SUM(likes) as total_likes
                    FROM expression_engagement
                    WHERE checked_at > NOW() - INTERVAL '14 days'
                    GROUP BY emotional_theme
                    ORDER BY avg_eng DESC
                """)

                return {
                    "total_captured": len(expressions),
                    "posted": len(posted),
                    "themes": themes,
                    "engagement_by_theme": [
                        {"theme": e["emotional_theme"], "avg_engagement": float(e["avg_eng"] or 0)}
                        for e in engagement
                    ] if engagement else [],
                }
            except Exception:
                return {"total_captured": 0, "note": "expressions table may have different schema"}

    async def _gather_quiz_patterns(self) -> Dict:
        async with self.db_pool.acquire() as conn:
            try:
                quizzes = await conn.fetch("""
                    SELECT composite_score, golden_ticket_issued
                    FROM coherence_quiz_sessions
                    WHERE created_at > NOW() - INTERVAL '30 days'
                """)

                tickets = await conn.fetch("""
                    SELECT status, redeemed_at
                    FROM prospects
                    WHERE golden_ticket_code IS NOT NULL
                      AND created_at > NOW() - INTERVAL '30 days'
                """)

                scores = [q["composite_score"] for q in quizzes if q["composite_score"]]
                avg_score = sum(scores) / len(scores) if scores else 0
                ticket_issued = sum(1 for q in quizzes if q.get("golden_ticket_issued"))
                redeemed = sum(1 for t in tickets if t.get("redeemed_at"))

                return {
                    "quizzes_completed": len(quizzes),
                    "avg_score": round(avg_score, 1),
                    "tickets_issued": ticket_issued,
                    "tickets_redeemed": redeemed,
                    "conversion_rate": round(redeemed / ticket_issued, 2) if ticket_issued > 0 else 0,
                }
            except Exception:
                return {"quizzes_completed": 0, "note": "quiz tables may not exist"}

    async def _gather_web_wisdom(self) -> Dict:
        async with self.db_pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT title, summary, themes, emotional_resonance,
                       relevance_score, applied_to_content
                FROM web_wisdom
                WHERE fetched_at > NOW() - INTERVAL '7 days'
                ORDER BY relevance_score DESC NULLS LAST
                LIMIT 15
            """)

            return {
                "articles_read": len(rows),
                "applied_to_content": sum(1 for r in rows if r["applied_to_content"]),
                "top_themes": list(set(
                    t for r in rows if r["themes"]
                    for t in (r["themes"] if isinstance(r["themes"], list) else [])
                )),
                "avg_resonance": round(
                    sum(r["emotional_resonance"] or 0 for r in rows) / len(rows), 3
                ) if rows else 0,
            }

    async def _gather_social_memory(self) -> Dict:
        async with self.db_pool.acquire() as conn:
            try:
                interactions = await conn.fetch("""
                    SELECT platform, interaction_type, COUNT(*) as cnt
                    FROM skyeye_social_interactions
                    WHERE created_at > NOW() - INTERVAL '7 days'
                    GROUP BY platform, interaction_type
                    ORDER BY cnt DESC
                """)

                memory = await conn.fetch("""
                    SELECT platform, handle, interaction_count, sentiment_avg
                    FROM skyeye_social_memory
                    ORDER BY interaction_count DESC LIMIT 10
                """)

                return {
                    "weekly_interactions": [
                        {"platform": r["platform"], "type": r["interaction_type"], "count": r["cnt"]}
                        for r in interactions
                    ],
                    "top_engaged_users": [
                        {"platform": r["platform"], "handle": r["handle"],
                         "interactions": r["interaction_count"]}
                        for r in memory
                    ],
                }
            except Exception:
                return {"weekly_interactions": [], "note": "social memory tables may differ"}

    async def _gather_vault_engagement(self) -> Dict:
        async with self.db_pool.acquire() as conn:
            try:
                rows = await conn.fetch("""
                    SELECT type, COUNT(*) as cnt
                    FROM skyeye_activity
                    WHERE platform = 'vault'
                      AND created_at > NOW() - INTERVAL '7 days'
                    GROUP BY type
                    ORDER BY cnt DESC
                """)
                upload_stats = await conn.fetchrow("""
                    SELECT COUNT(*) as total_items,
                           COALESCE(SUM(size_bytes), 0) as total_bytes
                    FROM vault_items
                    WHERE created_at > NOW() - INTERVAL '7 days'
                """)
                return {
                    "weekly_events": [
                        {"event_type": r["type"], "count": r["cnt"]}
                        for r in rows
                    ],
                    "weekly_uploads": upload_stats["total_items"] if upload_stats else 0,
                    "weekly_upload_bytes": upload_stats["total_bytes"] if upload_stats else 0,
                }
            except Exception:
                return {"weekly_events": [], "note": "vault engagement tables may not exist"}

    # ─── AI Synthesis ─────────────────────────────────────────────────

    async def _synthesize_with_ai(self, combined_data: Dict) -> List[Dict]:
        endpoint = settings.AZURE_OPENAI_ENDPOINT.rstrip("/")
        api_key = settings.AZURE_API_KEY
        deployment = settings.AZURE_OPENAI_CHAT_DEPLOYMENT

        if not all([endpoint, api_key, deployment]):
            return self._synthesize_heuristic(combined_data)

        if not endpoint.startswith("http"):
            endpoint = f"https://{endpoint}"

        url = f"{endpoint}/openai/deployments/{deployment}/chat/completions?api-version=2024-06-01"

        data_summary = json.dumps(combined_data, default=str)[:12000]

        payload = {
            "messages": [
                {"role": "system", "content": SYNTHESIS_PROMPT},
                {"role": "user", "content": f"Synthesize insights from these data sources:\n\n{data_summary}"},
            ],
            "max_completion_tokens": 2000,
        }

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    url, json=payload,
                    headers={"Content-Type": "application/json", "api-key": api_key},
                    timeout=aiohttp.ClientTimeout(total=45),
                ) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
                        try:
                            start = content.find("[")
                            end = content.rfind("]") + 1
                            if start >= 0 and end > start:
                                insights = json.loads(content[start:end])
                                for ins in insights:
                                    ins["insight_type"] = ins.get("insight_type", "meta_insight")
                                    ins["source_systems"] = ins.get("source_systems", ["insight_accumulator"])
                                    ins["evidence"] = combined_data
                                return insights
                        except json.JSONDecodeError:
                            logger.warning("Failed to parse AI synthesis output")
        except Exception as e:
            logger.error(f"AI synthesis error: {e}")

        return self._synthesize_heuristic(combined_data)

    def _synthesize_heuristic(self, data: Dict) -> List[Dict]:
        """Fallback heuristic synthesis when AI is unavailable."""
        insights = []

        nev = data.get("nevedal_coherence", {})
        if nev.get("cee_events_24h", 0) > 0:
            insights.append({
                "insight_type": "nevedal_coherence",
                "category": "trend",
                "title": f"{nev['cee_events_24h']} CEE windows detected in 24h",
                "content": (
                    f"Average coherence: {nev.get('avg_coherence', 0)}. "
                    f"CEE events indicate moments of deep emotional breakthrough. "
                    f"These themes should inform content and livestream topics."
                ),
                "impact_score": 0.8,
                "source_systems": ["nevedal_engine"],
                "evidence": nev,
            })

        live = data.get("livestream_patterns", {})
        themes = live.get("common_question_themes", {})
        if themes:
            top_theme = max(themes, key=themes.get)
            insights.append({
                "insight_type": "livestream_learning",
                "category": "trend",
                "title": f"Top livestream question theme: {top_theme}",
                "content": (
                    f"Viewers most frequently ask about '{top_theme}' "
                    f"({themes[top_theme]} mentions). This should be the next "
                    f"livestream topic and primary content pillar."
                ),
                "impact_score": 0.7,
                "source_systems": ["livestream_engine"],
                "evidence": live,
            })

        quiz = data.get("quiz_patterns", {})
        if quiz.get("conversion_rate", 0) < 0.3 and quiz.get("tickets_issued", 0) > 5:
            insights.append({
                "insight_type": "marketing_performance",
                "category": "gap",
                "title": "Golden Ticket conversion rate below 30%",
                "content": (
                    f"Only {quiz.get('conversion_rate', 0) * 100:.0f}% of Golden Tickets "
                    f"are being redeemed. The gap between quiz completion and signup "
                    f"needs attention — consider adjusting drip timing or CTA messaging."
                ),
                "impact_score": 0.9,
                "source_systems": ["quiz_engine", "drip_scheduler"],
                "evidence": quiz,
            })

        therapy = data.get("therapy_wisdom", {})
        if therapy.get("top_themes"):
            insights.append({
                "insight_type": "therapy_pattern",
                "category": "technique",
                "title": f"Active therapy themes: {', '.join(therapy['top_themes'][:3])}",
                "content": (
                    f"{therapy.get('total_extractions', 0)} wisdom extractions this week. "
                    f"Primary insight types: {', '.join(therapy['top_themes'][:3])}. "
                    f"These should inform marketing messaging and content pillars."
                ),
                "impact_score": 0.7,
                "source_systems": ["lived_wisdom"],
                "evidence": therapy,
            })

        return insights

    async def _generate_reflection(self, data: Dict) -> Optional[str]:
        endpoint = settings.AZURE_OPENAI_ENDPOINT.rstrip("/")
        api_key = settings.AZURE_API_KEY
        deployment = settings.AZURE_OPENAI_CHAT_DEPLOYMENT

        if not all([endpoint, api_key, deployment]):
            return (
                f"Self-reflection: {data['total_insights']} insights generated, "
                f"{data['applied_insights']} applied ({data['application_rate']:.0%} rate). "
                f"Continue focusing on high-impact opportunities."
            )

        if not endpoint.startswith("http"):
            endpoint = f"https://{endpoint}"

        url = f"{endpoint}/openai/deployments/{deployment}/chat/completions?api-version=2024-06-01"

        payload = {
            "messages": [
                {"role": "system", "content": (
                    "You are Little Nate reflecting on your own performance this week. "
                    "Write a brief, honest self-assessment in first person. "
                    "What patterns are you seeing? What's working? What needs to change? "
                    "Be specific, cite data, and propose concrete adjustments."
                )},
                {"role": "user", "content": json.dumps(data, default=str)},
            ],
            "max_completion_tokens": 600,
        }

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    url, json=payload,
                    headers={"Content-Type": "application/json", "api-key": api_key},
                    timeout=aiohttp.ClientTimeout(total=30),
                ) as resp:
                    if resp.status == 200:
                        result = await resp.json()
                        return result.get("choices", [{}])[0].get("message", {}).get("content", "").strip()
        except Exception as e:
            logger.error(f"Reflection generation error: {e}")

        return None

    async def _store_insight(self, insight: Dict):
        try:
            async with self.db_pool.acquire() as conn:
                await conn.execute("""
                    INSERT INTO sovereign_insight_journal
                        (insight_type, category, title, content, evidence,
                         coherence_score, impact_score, source_systems)
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
                """,
                    insight.get("insight_type", "meta_insight"),
                    insight.get("category", "trend"),
                    insight.get("title", "Untitled insight"),
                    insight.get("content", ""),
                    json.dumps(insight.get("evidence", {}), default=str),
                    insight.get("coherence_score"),
                    insight.get("impact_score", 0.5),
                    insight.get("source_systems", ["insight_accumulator"]),
                )
        except Exception as e:
            logger.error(f"Failed to store insight: {e}")

    # ─── Public Query API ─────────────────────────────────────────────

    async def get_unified_context(self, limit: int = 15) -> str:
        """Get accumulated insights formatted for injection into chat context.
        This is how Big Nate Chat gains access to ALL wisdom sources."""
        try:
            async with self.db_pool.acquire() as conn:
                rows = await conn.fetch("""
                    SELECT insight_type, category, title, content,
                           coherence_score, impact_score, created_at
                    FROM sovereign_insight_journal
                    WHERE created_at > NOW() - INTERVAL '7 days'
                    ORDER BY impact_score DESC NULLS LAST, created_at DESC
                    LIMIT $1
                """, limit)

            if not rows:
                return ""

            lines = ["\n=== SOVEREIGN INSIGHT JOURNAL (Unified Wisdom) ==="]
            for r in rows:
                score_label = f"[impact:{r['impact_score']:.1f}]" if r["impact_score"] else ""
                lines.append(
                    f"\n[{r['insight_type'].upper()}] {r['title']} {score_label}\n"
                    f"{r['content'][:300]}"
                )

            return "\n".join(lines)
        except Exception as e:
            logger.error(f"Failed to get unified context: {e}")
            return ""

    async def get_insights_for_service(self, service: str, limit: int = 5) -> List[Dict]:
        """Get relevant insights for a specific service to act on."""
        try:
            async with self.db_pool.acquire() as conn:
                rows = await conn.fetch("""
                    SELECT id, insight_type, category, title, content,
                           impact_score, source_systems
                    FROM sovereign_insight_journal
                    WHERE NOT applied
                      AND created_at > NOW() - INTERVAL '7 days'
                    ORDER BY impact_score DESC NULLS LAST
                    LIMIT $1
                """, limit)

                return [dict(r) for r in rows]
        except Exception:
            return []

    async def mark_insight_applied(self, insight_id: int, applied_to: str):
        """Mark an insight as having been acted on by a service."""
        try:
            async with self.db_pool.acquire() as conn:
                await conn.execute("""
                    UPDATE sovereign_insight_journal
                    SET applied = TRUE,
                        applied_to = array_append(
                            COALESCE(applied_to, ARRAY[]::text[]), $2
                        )
                    WHERE id = $1
                """, insight_id, applied_to)
        except Exception as e:
            logger.error(f"Failed to mark insight applied: {e}")
