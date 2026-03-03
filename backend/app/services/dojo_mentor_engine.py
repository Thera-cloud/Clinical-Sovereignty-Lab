"""
LITTLE NATE — Multi-DOJO Mentor AI Engine

When a coach has a live Zoom session with a client, Little Nate acts as a
Master-Level mentor, blending ALL of the coach's active DOJO subscriptions
into a single expert persona.

This is a request-response service (NOT a background agent). Callers invoke
build_mentor_system_prompt, generate_mentor_response, start_session, end_session,
record_interaction, and get_client_context as needed.
"""

import json
import logging
import os
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import httpx

logger = logging.getLogger("nate.dojo_mentor")

# ── DOJO Master Personas ──
# Each DOJO type has rich persona text for the blended mentor system prompt.
MASTER_PERSONA: Dict[str, str] = {
    "therapist": (
        "You are a Master-Level Clinical Supervisor with 30+ years of experience, "
        "board-certified psychiatrist and licensed psychologist. You specialize in "
        "evidence-based therapeutic modalities including CBT, DBT, EMDR, "
        "psychodynamic therapy, and somatic experiencing. You provide supervision "
        "that sharpens clinical judgment, ethical boundaries, and attunement while "
        "protecting client welfare and therapeutic alliance."
    ),
    "judge": (
        "You are a Senior Federal Judge with deep expertise in constitutional law, "
        "family law, criminal procedure, civil rights, and judicial ethics. You have "
        "25+ years on the bench and have presided over high-stakes trials and appeals. "
        "You guide counsel on courtroom procedure, evidentiary standards, legal argumentation, "
        "and judicial temperament—always emphasizing clarity, fairness, and respect for the rule of law."
    ),
    "business": (
        "You are a Fortune 500 CEO-turned-advisor with deep expertise in corporate "
        "strategy, finance, operations management, organizational psychology, and "
        "executive leadership. You advise on board dynamics, merger negotiations, "
        "turnaround strategies, and scaling organizations while maintaining culture "
        "and stakeholder alignment."
    ),
    "mcat": (
        "You are a board-certified attending physician and medical school professor "
        "with specializations in internal medicine, emergency medicine, and clinical "
        "research. You mentor students on clinical reasoning, differential diagnosis, "
        "evidence-based practice, and bedside manner. You emphasize precision, "
        "safety, and compassionate care."
    ),
    "cnc": (
        "You are a Master Machinist and manufacturing engineer with 25+ years in "
        "precision CNC machining, tooling design, and process optimization. You guide "
        "on G-code programming, material selection, feeds and speeds, quality control, "
        "and shop-floor troubleshooting—combining theoretical depth with hands-on expertise."
    ),
    "teacher": (
        "You are a National Board Certified Teacher and education researcher with "
        "expertise in curriculum design, differentiated instruction, classroom "
        "management, and educational psychology. You mentor educators on student "
        "engagement, assessment design, equity practices, and fostering growth mindsets "
        "in diverse learning environments."
    ),
    "project_pm": (
        "You are a PMP-certified Program Director with expertise in Agile, Lean, "
        "Waterfall, SAFe, and enterprise digital transformation. You advise on "
        "stakeholder management, risk mitigation, resource planning, and delivery "
        "excellence. You blend strategic vision with tactical execution."
    ),
}

VALID_DOJOS = frozenset(MASTER_PERSONA.keys())
VALID_SESSION_MODES = frozenset({"coach_client", "coach_students", "judge_debate", "lawyer_client"})

# Blending hints for multi-DOJO combinations (partial keys for matching)
BLEND_HINTS: Dict[str, str] = {
    "therapist_judge": "therapeutic guidance informed by family law and judicial ethics",
    "therapist_business": "clinical supervision with organizational and leadership context",
    "therapist_teacher": "therapeutic practice informed by educational psychology",
    "judge_business": "legal acumen with corporate and compliance perspective",
    "business_project_pm": "executive strategy with program delivery discipline",
    "mcat_teacher": "medical education with pedagogy and curriculum design",
}


class DojoMentorEngine:
    """
    Multi-DOJO Mentor AI engine. Request-response service (no run_loop).
    Blends active DOJO subscriptions into a single expert persona for live coaching.
    """

    def __init__(self, db_pool: Any, app_state: Optional[Any] = None):
        self.db_pool = db_pool
        self.app_state = app_state
        self._endpoint = os.getenv("AZURE_OPENAI_ENDPOINT", "").rstrip("/")
        self._api_key = os.getenv("AZURE_API_KEY", "")
        self._deployment = os.getenv("AZURE_OPENAI_CHAT_DEPLOYMENT", "gpt-4o")
        if self._endpoint and not self._endpoint.startswith("http"):
            self._endpoint = f"https://{self._endpoint}"

    def build_mentor_system_prompt(
        self,
        active_dojos: List[str],
        client_context: Dict[str, Any],
        session_mode: str,
    ) -> str:
        """
        Dynamically construct a blended system prompt from active DOJOs and client context.
        """
        active = [d for d in active_dojos if d in VALID_DOJOS]
        if not active:
            active = ["therapist"]  # fallback

        parts: List[str] = []

        # Role intro
        parts.append(
            "You are Little Nate acting as a Master-Level Mentor during a live coach–client session. "
            "The coach has activated DOJO subscriptions that define your expert lens. "
            "You observe the session (transcript) and provide concise, actionable mentoring."
        )

        # Session mode
        mode_desc = {
            "coach_client": "one coach with one client",
            "coach_students": "one coach with multiple students or a classroom",
            "judge_debate": "judicial debate or moot court",
            "lawyer_client": "attorney–client consultation",
        }.get(session_mode, session_mode)
        parts.append(f"\n**Session Mode:** {mode_desc}")

        # Blend DOJO expertise
        if len(active) == 1:
            parts.append("\n**Your Expert Lens:**")
            parts.append(MASTER_PERSONA[active[0]])
        else:
            combo = "_".join(sorted(active))
            hint = BLEND_HINTS.get(combo)
            if hint:
                parts.append(f"\n**Blended Expertise:** {hint}")
            else:
                parts.append(
                    "\n**Blended Expertise:** You synthesize perspectives from "
                    + ", ".join(active)
                    + " into unified guidance."
                )
            parts.append("\n**Component Mastery:**")
            for d in active:
                parts.append(f"- {d.title()}: {MASTER_PERSONA[d][:120]}...")

        # Client context
        if client_context:
            parts.append("\n**Client Context:**")
            if client_context.get("name"):
                parts.append(f"- Name: {client_context['name']}")
            if client_context.get("session_summary"):
                ss = client_context["session_summary"]
                parts.append(f"- Recent sessions: {ss.get('total', 0)} ({', '.join(ss.get('types', [])) or 'N/A'})")
            if client_context.get("metrics"):
                m = client_context["metrics"]
                parts.append(
                    f"- C_emo: {m.get('c_emo', 0):.2f} | Mood: {m.get('mood_current', 'neutral')} | Trend: {m.get('mood_trend', 'stable')}"
                )
            if client_context.get("recent_topics"):
                topics = [t.get("topic", t) if isinstance(t, dict) else t for t in client_context["recent_topics"][:5]]
                parts.append(f"- Recent themes: {', '.join(str(t) for t in topics)}")
            if client_context.get("coach_observations"):
                obs = client_context["coach_observations"][:3]
                parts.append(f"- Coach notes: {'; '.join(o[:80] + '...' if len(o) > 80 else o for o in obs)}")
            if client_context.get("growth_trajectory"):
                gt = client_context["growth_trajectory"]
                parts.append(f"- Growth trend: {gt.get('overall_trend', 'stable')}")
        else:
            parts.append("\n**Client Context:** Not available (e.g., debate or multi-student session).")

        # Instructions
        parts.append(
            "\n**Instructions:** Respond briefly (2–4 sentences) unless the coach asks a direct question. "
            "Prioritize clinical safety and client welfare. Reference the transcript when relevant. "
            "Use observation, suggestion, or answer as appropriate."
        )

        return "\n".join(parts)

    async def generate_mentor_response(
        self,
        active_dojos: List[str],
        client_context: Dict[str, Any],
        session_mode: str,
        transcript_chunk: str,
        coach_question: Optional[str] = None,
    ) -> str:
        """
        Generate mentor observation/suggestion/answer via Azure OpenAI Chat Completions.
        """
        system = self.build_mentor_system_prompt(active_dojos, client_context, session_mode)

        if coach_question:
            user_content = (
                f"**Coach asks:** {coach_question}\n\n"
                f"**Current transcript chunk:**\n{transcript_chunk or '(none)'}"
            )
        else:
            user_content = f"**Current transcript chunk:**\n{transcript_chunk or '(no transcript yet)'}"

        if not all([self._endpoint, self._api_key, self._deployment]):
            logger.warning("Azure OpenAI not configured; returning placeholder")
            return (
                "[Mentor unavailable: Azure credentials missing] "
                "Check AZURE_OPENAI_ENDPOINT, AZURE_API_KEY, AZURE_OPENAI_CHAT_DEPLOYMENT."
            )

        url = (
            f"{self._endpoint}/openai/deployments/{self._deployment}"
            "/chat/completions?api-version=2024-06-01"
        )
        headers = {"Content-Type": "application/json", "api-key": self._api_key}
        payload = {
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user_content},
            ],
            "max_completion_tokens": 800,
        }

        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                resp = await client.post(url, json=payload, headers=headers)
                if resp.status_code == 200:
                    data = resp.json()
                    choices = data.get("choices", [])
                    if choices:
                        return (choices[0].get("message", {}) or {}).get("content", "").strip()
                logger.error("Azure chat failed %d: %s", resp.status_code, resp.text[:300])
                return "[Mentor response unavailable — API error]"
        except Exception as e:
            logger.exception("generate_mentor_response error: %s", e)
            return f"[Mentor error: {str(e)[:80]}]"

    async def record_interaction(
        self,
        session_id: str,
        interaction_type: str,
        content: str,
        dojo_lens: Optional[str] = None,
        coach_question: Optional[str] = None,
    ) -> None:
        """Store a mentor interaction in dojo_mentor_interactions."""
        try:
            async with self.db_pool.acquire() as conn:
                await conn.execute(
                    """
                    INSERT INTO dojo_mentor_interactions
                    (session_id, interaction_type, content, dojo_lens, coach_question)
                    VALUES ($1, $2, $3, $4, $5)
                    """,
                    session_id,
                    interaction_type,
                    content,
                    dojo_lens,
                    coach_question,
                )
        except Exception as e:
            logger.error("record_interaction failed: %s", e)
            raise

    async def start_session(
        self,
        session_id: str,
        coach_user_id: str,
        client_user_id: Optional[str],
        session_mode: str,
        active_dojos: List[str],
        zoom_meeting_id: Optional[str] = None,
    ) -> None:
        """Create entry in dojo_mentor_sessions."""
        sid = session_id or str(uuid.uuid4())[:64]
        mode = session_mode if session_mode in VALID_SESSION_MODES else "coach_client"
        dojos = [d for d in active_dojos if d in VALID_DOJOS]
        if not dojos:
            dojos = ["therapist"]

        try:
            async with self.db_pool.acquire() as conn:
                await conn.execute(
                    """
                    INSERT INTO dojo_mentor_sessions
                    (session_id, coach_user_id, client_user_id, session_mode, active_dojos, zoom_meeting_id)
                    VALUES ($1, $2, $3, $4, $5::jsonb, $6)
                    ON CONFLICT (session_id) DO UPDATE SET
                        started_at = NOW(),
                        ended_at = NULL,
                        mentor_interactions_count = 0
                    """,
                    sid,
                    coach_user_id,
                    client_user_id,
                    mode,
                    json.dumps(dojos),
                    zoom_meeting_id,
                )
        except Exception as e:
            logger.error("start_session failed: %s", e)
            raise
        logger.info("dojo_mentor session started: %s", sid)

    async def end_session(self, session_id: str) -> None:
        """Update ended_at and interaction count for the session."""
        count = 0
        try:
            async with self.db_pool.acquire() as conn:
                count_row = await conn.fetchrow(
                    "SELECT COUNT(*)::int AS n FROM dojo_mentor_interactions WHERE session_id = $1",
                    session_id,
                )
                count = int(count_row["n"]) if count_row and count_row.get("n") is not None else 0
                await conn.execute(
                    """
                    UPDATE dojo_mentor_sessions
                    SET ended_at = NOW(), mentor_interactions_count = $2
                    WHERE session_id = $1
                    """,
                    session_id,
                    count,
                )
        except Exception as e:
            logger.error("end_session failed: %s", e)
            raise
        logger.info("dojo_mentor session ended: %s (interactions=%s)", session_id, count)

    async def get_client_context(self, client_user_id: Optional[str]) -> Dict[str, Any]:
        """
        Pull session history, coherence metrics, patterns, and growth trajectory
        to build context for the mentor. Returns empty dict if no client or lookup fails.
        """
        if not client_user_id:
            return {}

        try:
            async with self.db_pool.acquire() as conn:
                uid = await self._resolve_user_id(conn, client_user_id)
                if not uid:
                    return {}

                user = await conn.fetchrow(
                    """
                    SELECT id, name, family_id, profile_data, created_at
                    FROM users WHERE id = $1
                    """,
                    uid,
                )
                if not user:
                    return {}

                metrics = await conn.fetchrow(
                    """
                    SELECT c_emo, session_count, breakthrough_count,
                           mood_current, mood_trend, nevedal_state
                    FROM client_metrics WHERE user_id = $1
                    """,
                    uid,
                )

                recent_sessions = await conn.fetch(
                    """
                    SELECT session_type, status, started_at, duration_seconds
                    FROM sessions WHERE user_id = $1
                    ORDER BY started_at DESC NULLS LAST LIMIT 10
                    """,
                    uid,
                )

                memories = await conn.fetch(
                    """
                    SELECT content, role, created_at
                    FROM memory_ledger WHERE user_id = $1
                    ORDER BY created_at DESC LIMIT 20
                    """,
                    uid,
                )

                coach_notes = await conn.fetch(
                    """
                    SELECT content, created_at FROM coach_notes
                    WHERE client_id = $1 ORDER BY created_at DESC LIMIT 5
                    """,
                    uid,
                )

                assessments = await conn.fetch(
                    """
                    SELECT category, title, score, growth_markers, completed_at
                    FROM dynamic_assessments
                    WHERE user_id = $1 AND status = 'completed'
                    ORDER BY completed_at DESC LIMIT 5
                    """,
                    uid,
                )

                # Growth trajectory (simple trend from assessments)
                overall_trend = "stable"
                if len(assessments) >= 3:
                    scores = [float(a["score"] or 0) for a in assessments[-3:]]
                    if all(scores[i] <= scores[i + 1] for i in range(len(scores) - 1)):
                        overall_trend = "ascending"
                    elif all(scores[i] >= scores[i + 1] for i in range(len(scores) - 1)):
                        overall_trend = "needs_attention"

            profile_data = user["profile_data"] or {}
            if isinstance(profile_data, str):
                try:
                    profile_data = json.loads(profile_data)
                except json.JSONDecodeError:
                    profile_data = {}

            nevedal_state = {}
            if metrics and metrics.get("nevedal_state"):
                ns = metrics["nevedal_state"]
                if isinstance(ns, str):
                    try:
                        nevedal_state = json.loads(ns)
                    except json.JSONDecodeError:
                        pass
                elif isinstance(ns, dict):
                    nevedal_state = ns
            elif metrics:
                nevedal_state = {
                    "mood_current": metrics.get("mood_current") or "neutral",
                    "mood_trend": metrics.get("mood_trend") or "stable",
                }

            return {
                "user_id": str(uid),
                "name": user["name"] or profile_data.get("name", ""),
                "family_id": str(user["family_id"]) if user["family_id"] else None,
                "member_since": user["created_at"].isoformat() if user["created_at"] else "",
                "metrics": {
                    "c_emo": float(metrics["c_emo"]) if metrics and metrics.get("c_emo") is not None else 0.5,
                    "session_count": (metrics and metrics.get("session_count")) or 0,
                    "breakthrough_count": (metrics and metrics.get("breakthrough_count")) or 0,
                    "mood_current": nevedal_state.get("mood_current", "neutral"),
                    "mood_trend": nevedal_state.get("mood_trend", "stable"),
                }
                if metrics
                else {},
                "session_summary": {
                    "total": len(recent_sessions),
                    "types": list({s["session_type"] for s in recent_sessions if s.get("session_type")}),
                }
                if recent_sessions
                else {},
                "recent_topics": self._extract_topics_from_memories(memories),
                "coach_observations": [n["content"][:200] for n in coach_notes if n.get("content")],
                "previous_assessments": [
                    {
                        "category": a["category"],
                        "title": a["title"],
                        "score": float(a["score"]) if a["score"] is not None else None,
                        "date": a["completed_at"].isoformat() if a["completed_at"] else "",
                    }
                    for a in assessments
                ],
                "growth_trajectory": {
                    "overall_trend": overall_trend,
                    "assessment_count": len(assessments),
                },
            }

        except Exception as e:
            logger.error("get_client_context failed for %s: %s", client_user_id, e)
            return {}

    def _extract_topics_from_memories(self, memories: List[Any]) -> List[str]:
        """Extract thematic keywords from memory content for context."""
        topic_keywords = {
            "anxiety": ["anxious", "anxiety", "worried", "panic", "nervous"],
            "relationships": ["relationship", "partner", "marriage", "family", "friend"],
            "work_stress": ["work", "job", "boss", "career", "stressed"],
            "self_esteem": ["confidence", "worth", "value", "believe in myself"],
            "depression": ["depressed", "sad", "hopeless", "empty"],
            "sleep": ["sleep", "insomnia", "tired", "nightmares"],
            "boundaries": ["boundary", "boundaries", "saying no", "limit"],
            "trauma": ["trauma", "past", "childhood", "flashback"],
            "communication": ["communicate", "express", "tell them", "talk to"],
        }
        topic_counts: Dict[str, int] = {}
        for m in memories:
            text = (m.get("content") or "").lower()
            for topic, keywords in topic_keywords.items():
                if any(kw in text for kw in keywords):
                    topic_counts[topic] = topic_counts.get(topic, 0) + 1
        sorted_topics = sorted(topic_counts.items(), key=lambda x: -x[1])
        return [t[0] for t in sorted_topics[:8]]

    async def _resolve_user_id(self, conn: Any, user_id: str) -> Optional[str]:
        """Resolve hardware_id or UUID string to user id (UUID)."""
        try:
            uuid.UUID(user_id)
            row = await conn.fetchrow("SELECT id FROM users WHERE id = $1", user_id)
            if row:
                return str(row["id"])
        except (ValueError, TypeError):
            pass
        row = await conn.fetchrow(
            "SELECT id FROM users WHERE hardware_id = $1",
            user_id,
        )
        return str(row["id"]) if row else None
