"""
LITTLE NATE — Dynamic Assessment Engine
Generates personalized, evolving assessments based on each client's
history with Little Nate, live coaches, family sanctuary, and emotional
growth trajectory. Uses Azure OpenAI Chat Completions (same pattern as
skyeye_content_generator.py — direct aiohttp REST, api-key header).

NOT a static quiz. Each assessment adapts based on:
  - Conversation history and themes with Nate
  - Nevedal metrics trajectory (C_emo, CEE windows, drift periods)
  - Coach notes and session outcomes
  - Family dynamics (if family_id present)
  - Previous assessment results and growth markers
"""

import asyncio
import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Optional, Dict, List, Any

import aiohttp

from app.config import settings

logger = logging.getLogger("nate.assessment_engine")

ASSESSMENT_CATEGORIES = [
    "emotional_awareness",
    "relationship_patterns",
    "stress_resilience",
    "self_compassion",
    "attachment_security",
    "cognitive_flexibility",
    "boundary_health",
    "grief_processing",
    "identity_integration",
    "family_dynamics",
]

SYSTEM_PROMPT = """You are Little Nate, an AI therapeutic companion with deep knowledge
of each client's emotional journey. You generate personalized assessment questions that
reflect the client's actual experiences, growth patterns, and therapeutic themes.

Rules:
- Generate 8-12 questions per assessment
- Each question must reference or build on what you know about this specific client
- Questions should feel like a natural conversation, not a clinical form
- Include a mix of reflection (open-ended), scaling (1-10), and choice questions
- Never repeat questions the client has already answered in previous assessments
- Frame questions through the lens of growth: "Since we last explored..." or "You mentioned..."
- If the client has family dynamics, include 1-2 questions about relational patterns

Output MUST be valid JSON with this structure:
{
  "title": "Assessment title reflecting the theme",
  "category": "one of the category codes",
  "questions": [
    {
      "index": 0,
      "text": "The question text",
      "type": "reflection|scale|choice",
      "options": ["only for choice type"],
      "context_note": "Why Nate chose this question (not shown to client)"
    }
  ],
  "nate_intro": "A warm, personalized intro paragraph Nate says before the assessment"
}"""

ANALYSIS_PROMPT = """You are Little Nate analyzing a client's assessment responses.
You have deep memory of their journey. Produce personalized insights that connect
their answers to their growth trajectory.

Output MUST be valid JSON:
{
  "summary": "2-3 sentence overview of what the responses reveal",
  "growth_markers": [
    {"area": "name", "direction": "growing|stable|needs_attention", "detail": "specifics"}
  ],
  "insights": [
    {"theme": "name", "observation": "what Nate noticed", "suggestion": "gentle next step"}
  ],
  "score": 0.0-1.0,
  "nate_reflection": "A warm, personal paragraph from Nate about what he learned"
}"""


class AssessmentEngine:
    def __init__(self, db_pool):
        self.db_pool = db_pool

    async def generate_assessment(
        self, user_id: str, category: Optional[str] = None
    ) -> Dict[str, Any]:
        """Generate a personalized assessment for a client."""
        context = await self._gather_client_context(user_id)
        if not context:
            return {"error": "Client not found", "user_id": user_id}

        if not category:
            category = await self._pick_best_category(user_id, context)

        user_prompt = self._build_generation_prompt(context, category)
        raw = await self._call_azure_chat(SYSTEM_PROMPT, user_prompt, max_tokens=3000)
        if not raw:
            return {"error": "AI generation failed", "user_id": user_id}

        try:
            assessment_data = json.loads(raw)
        except json.JSONDecodeError:
            start = raw.find("{")
            end = raw.rfind("}") + 1
            if start >= 0 and end > start:
                assessment_data = json.loads(raw[start:end])
            else:
                return {"error": "Failed to parse assessment", "user_id": user_id}

        assessment_id = str(uuid.uuid4())
        await self._store_assessment(
            assessment_id, user_id, assessment_data, category, context
        )

        return {
            "assessment_id": assessment_id,
            "title": assessment_data.get("title", "Growth Assessment"),
            "category": category,
            "questions": assessment_data.get("questions", []),
            "nate_intro": assessment_data.get("nate_intro", ""),
            "created_at": datetime.now(timezone.utc).isoformat(),
        }

    async def submit_and_analyze(
        self, assessment_id: str, answers: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """Store responses and generate AI analysis."""
        assessment = await self._get_assessment(assessment_id)
        if not assessment:
            return {"error": "Assessment not found"}

        user_id = str(assessment["user_id"])
        context = await self._gather_client_context(user_id)

        await self._store_responses(assessment_id, answers)

        questions = assessment.get("questions", [])
        if isinstance(questions, str):
            questions = json.loads(questions)

        analysis_input = self._build_analysis_prompt(context, questions, answers)
        raw = await self._call_azure_chat(ANALYSIS_PROMPT, analysis_input, max_tokens=2000)

        insights = {}
        if raw:
            try:
                insights = json.loads(raw)
            except json.JSONDecodeError:
                start = raw.find("{")
                end = raw.rfind("}") + 1
                if start >= 0 and end > start:
                    insights = json.loads(raw[start:end])

        score = insights.get("score", 0.5)
        nate_reflection = insights.get("nate_reflection", "")
        growth_markers = insights.get("growth_markers", [])

        async with self.db_pool.acquire() as conn:
            await conn.execute("""
                UPDATE dynamic_assessments
                SET status = 'completed', score = $2, insights = $3,
                    growth_markers = $4, nate_reflection = $5, completed_at = NOW()
                WHERE id = $1
            """, assessment_id, score, json.dumps(insights),
                json.dumps(growth_markers), nate_reflection)

        return {
            "assessment_id": assessment_id,
            "score": score,
            "insights": insights.get("insights", []),
            "growth_markers": growth_markers,
            "summary": insights.get("summary", ""),
            "nate_reflection": nate_reflection,
        }

    async def get_growth_trajectory(self, user_id: str) -> Dict[str, Any]:
        """Return timeline of all assessments with growth indicators."""
        async with self.db_pool.acquire() as conn:
            uid = await self._resolve_user_id(conn, user_id)
            if not uid:
                return {"user_id": user_id, "total_assessments": 0, "overall_trend": "stable", "timeline": []}

            rows = await conn.fetch("""
                SELECT id, category, title, score, growth_markers,
                       nate_reflection, completed_at, created_at
                FROM dynamic_assessments
                WHERE user_id = $1 AND status = 'completed'
                ORDER BY completed_at ASC
            """, uid)

        timeline = []
        for r in rows:
            markers = r["growth_markers"]
            if isinstance(markers, str):
                markers = json.loads(markers)
            timeline.append({
                "assessment_id": str(r["id"]),
                "category": r["category"],
                "title": r["title"],
                "score": float(r["score"]) if r["score"] else 0,
                "growth_markers": markers or [],
                "nate_reflection": r["nate_reflection"],
                "completed_at": r["completed_at"].isoformat() if r["completed_at"] else None,
            })

        overall_trend = "stable"
        if len(timeline) >= 3:
            recent_scores = [t["score"] for t in timeline[-3:]]
            if all(recent_scores[i] <= recent_scores[i + 1] for i in range(len(recent_scores) - 1)):
                overall_trend = "growing"
            elif all(recent_scores[i] >= recent_scores[i + 1] for i in range(len(recent_scores) - 1)):
                overall_trend = "needs_attention"

        return {
            "user_id": user_id,
            "total_assessments": len(timeline),
            "overall_trend": overall_trend,
            "timeline": timeline,
        }

    async def _resolve_user_id(self, conn, user_id: str):
        """Resolve a hardware_id or UUID string to an actual UUID user id."""
        try:
            import uuid as _uuid
            _uuid.UUID(user_id)
            row = await conn.fetchrow("SELECT id FROM users WHERE id = $1", user_id)
            if row:
                return row["id"]
        except (ValueError, TypeError):
            pass
        row = await conn.fetchrow("SELECT id FROM users WHERE hardware_id = $1 LIMIT 1", user_id)
        if row:
            return row["id"]
        return None

    async def check_triggers(self, user_id: str) -> Dict[str, Any]:
        """Check if a new assessment should be generated for this client."""
        triggers = []

        async with self.db_pool.acquire() as conn:
            uid = await self._resolve_user_id(conn, user_id)
            if not uid:
                return {"user_id": user_id, "should_generate": True, "triggers": ["user_not_found"]}

            last = await conn.fetchrow("""
                SELECT created_at FROM dynamic_assessments
                WHERE user_id = $1 ORDER BY created_at DESC LIMIT 1
            """, uid)

            session_count = await conn.fetchval("""
                SELECT COUNT(*) FROM sessions WHERE user_id = $1
            """, uid)

            if not last:
                triggers.append("first_assessment")
            else:
                days_since = (datetime.now(timezone.utc) - last["created_at"].replace(
                    tzinfo=timezone.utc
                )).days
                if days_since >= 30:
                    triggers.append("30_days_since_last")

            if session_count and session_count % 10 == 0 and session_count > 0:
                triggers.append(f"milestone_{session_count}_sessions")

        return {
            "user_id": user_id,
            "should_generate": len(triggers) > 0,
            "triggers": triggers,
        }

    async def get_available(self, user_id: str) -> Dict[str, Any]:
        """Get pending assessments and check if new one should be generated."""
        async with self.db_pool.acquire() as conn:
            uid = await self._resolve_user_id(conn, user_id)
            if not uid:
                return {"pending": [], "completed_count": 0, "should_generate_new": True, "triggers": ["user_not_found"]}

            pending = await conn.fetch("""
                SELECT id, category, title, created_at
                FROM dynamic_assessments
                WHERE user_id = $1 AND status = 'pending'
                ORDER BY created_at DESC
            """, uid)

            completed_count = await conn.fetchval("""
                SELECT COUNT(*) FROM dynamic_assessments
                WHERE user_id = $1 AND status = 'completed'
            """, uid)

        trigger_check = await self.check_triggers(user_id)

        return {
            "pending": [
                {
                    "assessment_id": str(r["id"]),
                    "category": r["category"],
                    "title": r["title"],
                    "created_at": r["created_at"].isoformat(),
                }
                for r in pending
            ],
            "completed_count": completed_count or 0,
            "should_generate_new": trigger_check["should_generate"],
            "triggers": trigger_check["triggers"],
        }

    async def get_history(self, user_id: str, limit: int = 20) -> List[Dict[str, Any]]:
        """Get assessment history for a client."""
        async with self.db_pool.acquire() as conn:
            uid = await self._resolve_user_id(conn, user_id)
            if not uid:
                return []

            rows = await conn.fetch("""
                SELECT id, category, title, status, score,
                       nate_reflection, completed_at, created_at
                FROM dynamic_assessments
                WHERE user_id = $1
                ORDER BY created_at DESC
                LIMIT $2
            """, uid, limit)

        return [
            {
                "assessment_id": str(r["id"]),
                "category": r["category"],
                "title": r["title"],
                "status": r["status"],
                "score": float(r["score"]) if r["score"] else None,
                "nate_reflection": r["nate_reflection"],
                "completed_at": r["completed_at"].isoformat() if r["completed_at"] else None,
                "created_at": r["created_at"].isoformat(),
            }
            for r in rows
        ]

    # ── Azure OpenAI (production-aligned: aiohttp + api-key header) ──

    async def _call_azure_chat(
        self, system_prompt: str, user_prompt: str, max_tokens: int = 2000
    ) -> Optional[str]:
        endpoint = getattr(settings, "AZURE_OPENAI_ENDPOINT", "").rstrip("/")
        api_key = getattr(settings, "AZURE_API_KEY", "")
        deployment = getattr(settings, "AZURE_OPENAI_CHAT_DEPLOYMENT", "gpt-4o")

        if not all([endpoint, api_key, deployment]):
            logger.error("Azure OpenAI credentials not configured for assessments")
            return None

        if not endpoint.startswith("http"):
            endpoint = f"https://{endpoint}"

        url = (
            f"{endpoint}/openai/deployments/{deployment}"
            f"/chat/completions?api-version=2024-06-01"
        )

        headers = {
            "Content-Type": "application/json",
            "api-key": api_key,
        }

        payload = {
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "max_completion_tokens": max_tokens,
        }

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    url,
                    json=payload,
                    headers=headers,
                    timeout=aiohttp.ClientTimeout(total=60),
                ) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        choices = data.get("choices", [])
                        if choices:
                            return choices[0].get("message", {}).get("content", "")
                    else:
                        error_text = await resp.text()
                        logger.error(
                            "Azure assessment gen failed (%d): %s",
                            resp.status,
                            error_text[:200],
                        )
                        return None
        except Exception as e:
            logger.error("Azure assessment gen error: %s", e)
            return None

    # ── Context Gathering ──

    async def _gather_client_context(self, user_id: str) -> Optional[Dict[str, Any]]:
        try:
            async with self.db_pool.acquire() as conn:
                user = await conn.fetchrow("""
                    SELECT id, name, role, family_id, profile_data, created_at
                    FROM users WHERE id = $1 OR hardware_id = $2
                    LIMIT 1
                """, user_id, user_id)

                if not user:
                    return None

                uid = user["id"]

                metrics = await conn.fetchrow("""
                    SELECT c_emo, session_count, breakthrough_count,
                           crisis_perception, shame_profile, pmb, nevedal_state
                    FROM client_metrics WHERE user_id = $1
                """, uid)

                recent_sessions = await conn.fetch("""
                    SELECT session_type, status, started_at, duration_seconds
                    FROM sessions WHERE user_id = $1
                    ORDER BY started_at DESC LIMIT 10
                """, uid)

                memories = await conn.fetch("""
                    SELECT topic, emotional_tags, created_at
                    FROM memory_ledger WHERE user_id = $1
                    ORDER BY created_at DESC LIMIT 20
                """, uid)

                prev_assessments = await conn.fetch("""
                    SELECT category, title, score, growth_markers, completed_at
                    FROM dynamic_assessments
                    WHERE user_id = $1 AND status = 'completed'
                    ORDER BY completed_at DESC LIMIT 5
                """, uid)

                coach_notes = await conn.fetch("""
                    SELECT content, created_at FROM coach_notes
                    WHERE client_id = $1 ORDER BY created_at DESC LIMIT 5
                """, uid)

                family_members = []
                if user["family_id"]:
                    family_members = await conn.fetch("""
                        SELECT name, role FROM users
                        WHERE family_id = $1 AND id != $2
                    """, user["family_id"], uid)

            profile_data = user["profile_data"] or {}
            if isinstance(profile_data, str):
                profile_data = json.loads(profile_data)

            context = {
                "user_id": str(uid),
                "name": user["name"] or profile_data.get("name", ""),
                "family_id": str(user["family_id"]) if user["family_id"] else None,
                "member_since": user["created_at"].isoformat() if user["created_at"] else "",
                "metrics": {},
                "recent_topics": [],
                "session_summary": {},
                "previous_assessments": [],
                "coach_observations": [],
                "family_members": [],
            }

            if metrics:
                nevedal_state = metrics["nevedal_state"] or {}
                if isinstance(nevedal_state, str):
                    nevedal_state = json.loads(nevedal_state)
                context["metrics"] = {
                    "c_emo": float(metrics["c_emo"] or 0),
                    "session_count": metrics["session_count"] or 0,
                    "breakthrough_count": metrics["breakthrough_count"] or 0,
                    "mood_current": nevedal_state.get("mood_current", "neutral"),
                    "mood_trend": nevedal_state.get("mood_trend", "stable"),
                }

            context["recent_topics"] = [
                {
                    "topic": m.get("topic", ""),
                    "emotions": m.get("emotional_tags", []),
                }
                for m in recent_sessions
                if m.get("topic")
            ][:10]

            if recent_sessions:
                context["session_summary"] = {
                    "total": len(recent_sessions),
                    "types": list({s["session_type"] for s in recent_sessions if s["session_type"]}),
                }

            context["previous_assessments"] = [
                {
                    "category": a["category"],
                    "title": a["title"],
                    "score": float(a["score"]) if a["score"] else None,
                    "date": a["completed_at"].isoformat() if a["completed_at"] else "",
                }
                for a in prev_assessments
            ]

            context["coach_observations"] = [
                n["content"][:200] for n in coach_notes if n.get("content")
            ]

            context["family_members"] = [
                {"name": m["name"], "role": m["role"]} for m in family_members
            ]

            return context

        except Exception as e:
            logger.error("Failed to gather client context for %s: %s", user_id, e)
            return None

    async def _pick_best_category(
        self, user_id: str, context: Dict[str, Any]
    ) -> str:
        prev = [a["category"] for a in context.get("previous_assessments", [])]
        uncovered = [c for c in ASSESSMENT_CATEGORIES if c not in prev]
        if uncovered:
            if context.get("family_members") and "family_dynamics" in uncovered:
                return "family_dynamics"
            return uncovered[0]

        metrics = context.get("metrics", {})
        c_emo = metrics.get("c_emo", 0)
        if c_emo < 0.3:
            return "emotional_awareness"
        if c_emo > 0.7:
            return "cognitive_flexibility"
        return "self_compassion"

    def _build_generation_prompt(
        self, context: Dict[str, Any], category: str
    ) -> str:
        parts = [f"Generate a {category} assessment for {context.get('name', 'this client')}."]
        parts.append(f"\nClient context:")
        parts.append(f"- Member since: {context.get('member_since', 'unknown')}")

        m = context.get("metrics", {})
        if m:
            parts.append(
                f"- Current C_emo: {m.get('c_emo', 'N/A')}, "
                f"Sessions: {m.get('session_count', 0)}, "
                f"Breakthroughs: {m.get('breakthrough_count', 0)}, "
                f"Mood: {m.get('mood_current', 'neutral')} ({m.get('mood_trend', 'stable')})"
            )

        topics = context.get("recent_topics", [])
        if topics:
            topic_str = ", ".join(t.get("topic", "") for t in topics[:5] if t.get("topic"))
            if topic_str:
                parts.append(f"- Recent themes explored: {topic_str}")

        prev = context.get("previous_assessments", [])
        if prev:
            prev_str = "; ".join(
                f"{a['category']} (score: {a.get('score', '?')})" for a in prev[:3]
            )
            parts.append(f"- Previous assessments: {prev_str}")

        coach = context.get("coach_observations", [])
        if coach:
            parts.append(f"- Coach observations: {'; '.join(coach[:2])}")

        fam = context.get("family_members", [])
        if fam:
            fam_str = ", ".join(f"{f['name']} ({f['role']})" for f in fam)
            parts.append(f"- Family members: {fam_str}")

        session_info = context.get("session_summary", {})
        if session_info:
            parts.append(
                f"- Session types used: {', '.join(session_info.get('types', []))}"
            )

        return "\n".join(parts)

    def _build_analysis_prompt(
        self,
        context: Dict[str, Any],
        questions: List[Dict],
        answers: List[Dict[str, Any]],
    ) -> str:
        parts = [
            f"Analyze assessment responses for {context.get('name', 'client')}.",
            f"\nClient context: C_emo={context.get('metrics', {}).get('c_emo', 'N/A')}, "
            f"Sessions={context.get('metrics', {}).get('session_count', 0)}",
        ]

        parts.append("\nQuestions and Answers:")
        for ans in answers:
            idx = ans.get("question_index", 0)
            q_text = ""
            if idx < len(questions):
                q_text = questions[idx].get("text", "")
            parts.append(f"Q{idx}: {q_text}")
            if ans.get("answer_text"):
                parts.append(f"A: {ans['answer_text']}")
            elif ans.get("answer_value") is not None:
                parts.append(f"A: {ans['answer_value']}/10")

        return "\n".join(parts)

    # ── Storage Helpers ──

    async def _store_assessment(
        self,
        assessment_id: str,
        user_id: str,
        data: Dict,
        category: str,
        context: Dict,
    ):
        async with self.db_pool.acquire() as conn:
            await conn.execute("""
                INSERT INTO dynamic_assessments
                    (id, user_id, category, title, questions, context_summary,
                     trigger_reason, status)
                VALUES ($1, $2, $3, $4, $5, $6, $7, 'pending')
            """, assessment_id, user_id,
                category,
                data.get("title", "Growth Assessment"),
                json.dumps(data.get("questions", [])),
                json.dumps({"name": context.get("name"), "c_emo": context.get("metrics", {}).get("c_emo")}),
                "manual")

    async def _store_responses(self, assessment_id: str, answers: List[Dict]):
        async with self.db_pool.acquire() as conn:
            for ans in answers:
                await conn.execute("""
                    INSERT INTO assessment_responses
                        (assessment_id, question_index, question_text,
                         answer_text, answer_value, reflection)
                    VALUES ($1, $2, $3, $4, $5, $6)
                """, assessment_id,
                    ans.get("question_index", 0),
                    ans.get("question_text", ""),
                    ans.get("answer_text"),
                    ans.get("answer_value"),
                    ans.get("reflection"))

    async def _get_assessment(self, assessment_id: str):
        async with self.db_pool.acquire() as conn:
            return await conn.fetchrow("""
                SELECT * FROM dynamic_assessments WHERE id = $1
            """, assessment_id)
