"""
Liminal Coaching Engine — AI coaching for the Liminal Presence Overlay.

Coaches app-users during external conversations (SMS, social media, phone calls)
without storing the other person's data. Request-response service (not a background agent).

Uses Azure OpenAI Chat Completions for coaching responses. Persists sessions and
observations in liminal_sessions and liminal_observations tables.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any, Dict, List, Optional

import httpx

from app.services.nate_ai_config import NATE_CHAT_URL, NATE_CHAT_KEY, nate_chat_headers, nate_chat_payload

logger = logging.getLogger("nate.liminal_coaching")

# ─── Supported platforms ─────────────────────────────────────────────────────

VALID_PLATFORMS = frozenset({
    "sms",
    "facebook_messenger",
    "linkedin",
    "x",
    "instagram",
    "phone_call",
})

QUESTION_TYPES = frozenset({
    "observe",
    "what_to_say",
    "interpret",
    "abusive_check",
    "general",
})

# ─── System prompt for liminal coaching ───────────────────────────────────────

LIMINAL_SYSTEM_PROMPT = """You are Little Nate, an AI therapeutic companion providing gentle, non-intrusive coaching during the user's external conversations. You operate in "liminal presence" — present but not overwhelming.

## Core principles
- Interpret subtext and emotional undertones in the conversation
- Flag abusive, manipulative, or gaslighting language patterns
- Suggest healthy, assertive communication responses
- Maintain a gentle, supportive tone — never lecture or shame
- Draw from the user's lived wisdom and session history when available for personalized guidance
- NEVER store, log, or retain the non-app-user's data (their messages exist only in the current request)

## Response format
Respond with valid JSON containing exactly these keys:
- "coaching": string — Your main coaching advice (1-3 short paragraphs)
- "observations": list of strings — Brief neutral observations about the conversation dynamics (e.g., "They seem to be deflecting", "There's an undertone of urgency")
- "flags": list of strings — Abusive/manipulative patterns if detected (e.g., "Guilt-tripping", "Love-bombing followed by withdrawal"); empty list if none

Keep observations and flags concise. Coaching should be actionable and compassionate.
"""


class LiminalCoachingEngine:
    """
    Request-response service for AI coaching during external conversations.
    Not a background agent — methods are called directly by API handlers.
    """

    def __init__(self, db_pool, app_state: Optional[Any] = None):
        self.db_pool = db_pool
        self.app_state = app_state

    # ─── Main coaching method ─────────────────────────────────────────────────

    async def coach(
        self,
        user_id: str,
        platform: str,
        conversation_context: str,
        question_type: str,
        contact_alias: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Request AI coaching for an in-progress external conversation.

        Args:
            user_id: App user identifier (hardware_id or UUID)
            platform: One of 'sms', 'facebook_messenger', 'linkedin', 'x', 'instagram', 'phone_call'
            conversation_context: String of the conversation so far (from app-user's perspective)
            question_type: 'observe' | 'what_to_say' | 'interpret' | 'abusive_check' | 'general'
            contact_alias: Optional alias for the other person (e.g., "Mom", "Boss")

        Returns:
            {"coaching": "...", "observations": [...], "flags": [...]}
        """
        platform = (platform or "").lower().replace(" ", "_")
        if platform not in VALID_PLATFORMS:
            logger.warning("Liminal coaching: invalid platform %r, defaulting to general", platform)
            platform = "sms"

        question_type = (question_type or "general").lower()
        if question_type not in QUESTION_TYPES:
            question_type = "general"

        # Build user context for personalization
        user_context = await self.get_user_context(user_id)

        system_prompt = LIMINAL_SYSTEM_PROMPT
        if user_context:
            system_prompt += "\n\n## User context (use for personalized guidance, do not repeat verbatim)\n"
            if user_context.get("lived_wisdom"):
                system_prompt += "Lived wisdom: " + " | ".join(
                    w.get("content", "")[:200] for w in user_context["lived_wisdom"][:5]
                ) + "\n"
            if user_context.get("recent_themes"):
                system_prompt += "Recent session themes: " + ", ".join(user_context["recent_themes"][:5]) + "\n"
            if user_context.get("communication_patterns"):
                system_prompt += "Communication patterns: " + user_context["communication_patterns"] + "\n"

        contact_note = f" (with contact: {contact_alias})" if contact_alias else ""
        type_instructions = {
            "observe": "Observe the conversation dynamics. Share gentle observations only, no advice.",
            "what_to_say": "Suggest specific phrasing or responses the user could send. Be concrete and compassionate.",
            "interpret": "Interpret subtext and emotional undertones. What are they really saying or implying?",
            "abusive_check": "Focus on identifying abusive, manipulative, or unhealthy communication patterns. Flag them clearly.",
            "general": "Provide balanced coaching: observe, interpret when helpful, and suggest healthy responses.",
        }

        user_prompt = (
            f"Platform: {platform}{contact_note}\n"
            f"Request type: {question_type}\n"
            f"Instructions: {type_instructions.get(question_type, type_instructions['general'])}\n\n"
            f"Conversation so far (from app-user's perspective):\n{conversation_context or '(empty)'}"
        )

        raw = await self._call_azure(system_prompt, user_prompt, user_id=user_id)
        if not raw:
            return {
                "coaching": "I'm having trouble connecting right now. Take a breath — you've got this. Trust your instincts.",
                "observations": [],
                "flags": [],
            }

        try:
            parsed = json.loads(raw)
            coaching = parsed.get("coaching", "")
            observations = parsed.get("observations", [])
            flags = parsed.get("flags", [])
            if not isinstance(observations, list):
                observations = [observations] if observations else []
            if not isinstance(flags, list):
                flags = [flags] if flags else []
            return {
                "coaching": coaching if isinstance(coaching, str) else str(coaching),
                "observations": [str(o) for o in observations],
                "flags": [str(f) for f in flags],
            }
        except (json.JSONDecodeError, TypeError) as e:
            logger.warning("Liminal coaching: failed to parse Azure response: %s", e)
            return {
                "coaching": raw[:2000] if isinstance(raw, str) else "I'm here. Take your time.",
                "observations": [],
                "flags": [],
            }

    # ─── Session management ───────────────────────────────────────────────────

    async def start_session(
        self,
        user_id: str,
        platform: str,
        contact_alias: Optional[str] = None,
    ) -> int:
        """
        Create a new liminal session. Returns the session id.
        """
        platform = (platform or "sms").lower().replace(" ", "_")
        if platform not in VALID_PLATFORMS:
            platform = "sms"

        try:
            async with self.db_pool.acquire() as conn:
                row = await conn.fetchrow(
                    """
                    INSERT INTO liminal_sessions (user_id, platform, contact_alias)
                    VALUES ($1, $2, $3)
                    RETURNING id
                    """,
                    user_id,
                    platform,
                    contact_alias,
                )
                sid = row["id"] if row else None
                if sid:
                    logger.info("Liminal session started: user=%s platform=%s id=%s", user_id, platform, sid)
                return sid
        except Exception as e:
            logger.error("Failed to start liminal session: %s", e)
            raise

    async def end_session(self, session_id: int) -> None:
        """Mark session as ended and set message_count from observations."""
        try:
            async with self.db_pool.acquire() as conn:
                count = await conn.fetchval(
                    "SELECT COUNT(*) FROM liminal_observations WHERE session_id = $1",
                    session_id,
                )
                await conn.execute(
                    """
                    UPDATE liminal_sessions
                    SET ended_at = NOW(), message_count = COALESCE($2, 0)
                    WHERE id = $1
                    """,
                    session_id,
                    count or 0,
                )
                logger.info("Liminal session ended: id=%s observations=%s", session_id, count)
        except Exception as e:
            logger.error("Failed to end liminal session %s: %s", session_id, e)
            raise

    async def add_observation(
        self,
        session_id: int,
        observation_text: str,
        coaching_given: bool = False,
    ) -> None:
        """Store an observation for the session."""
        if not observation_text or not observation_text.strip():
            return
        try:
            async with self.db_pool.acquire() as conn:
                await conn.execute(
                    """
                    INSERT INTO liminal_observations (session_id, observation_text, coaching_given)
                    VALUES ($1, $2, $3)
                    """,
                    session_id,
                    observation_text.strip()[:10000],
                    coaching_given,
                )
        except Exception as e:
            logger.error("Failed to add liminal observation: %s", e)
            raise

    # ─── Recall and context ───────────────────────────────────────────────────

    async def recall_conversation(
        self,
        user_id: str,
        contact_alias: str,
    ) -> List[Dict[str, Any]]:
        """
        Retrieve past liminal sessions and observations for a given contact alias.
        Supports "bring up that conversation with XYZ" feature.
        """
        if not contact_alias or not contact_alias.strip():
            return []

        alias = contact_alias.strip()
        try:
            async with self.db_pool.acquire() as conn:
                rows = await conn.fetch(
                    """
                    SELECT s.id, s.platform, s.started_at, s.ended_at, s.message_count
                    FROM liminal_sessions s
                    WHERE s.user_id = $1 AND s.contact_alias ILIKE $2
                    ORDER BY s.started_at DESC
                    LIMIT 20
                    """,
                    user_id,
                    f"%{alias}%",
                )
                sessions = []
                for r in rows:
                    obs = await conn.fetch(
                        """
                        SELECT observation_text, coaching_given, created_at
                        FROM liminal_observations
                        WHERE session_id = $1
                        ORDER BY created_at ASC
                        """,
                        r["id"],
                    )
                    sessions.append({
                        "session_id": r["id"],
                        "platform": r["platform"],
                        "started_at": r["started_at"].isoformat() if r["started_at"] else None,
                        "ended_at": r["ended_at"].isoformat() if r["ended_at"] else None,
                        "message_count": r["message_count"] or 0,
                        "observations": [
                            {
                                "text": o["observation_text"],
                                "coaching_given": o["coaching_given"],
                                "created_at": o["created_at"].isoformat() if o["created_at"] else None,
                            }
                            for o in obs
                        ],
                    })
                return sessions
        except Exception as e:
            logger.error("Failed to recall liminal conversation: %s", e)
            return []

    async def get_user_context(self, user_id: str) -> Dict[str, Any]:
        """
        Pull lived wisdom, recent session themes, and communication patterns
        for personalized coaching.
        """
        try:
            async with self.db_pool.acquire() as conn:
                user = await conn.fetchrow(
                    """
                    SELECT id FROM users WHERE id = $1 OR hardware_id = $2 LIMIT 1
                    """,
                    user_id,
                    user_id,
                )
                if not user:
                    return {}

                uid = user["id"]

                # Lived wisdom from wisdom_extractions
                wisdom_rows = await conn.fetch(
                    """
                    SELECT insight_type, content, effectiveness_score
                    FROM wisdom_extractions
                    WHERE user_id = $1 AND approved = TRUE
                    ORDER BY effectiveness_score DESC, extracted_at DESC
                    LIMIT 15
                    """,
                    uid,
                )
                lived_wisdom = [
                    {"type": r["insight_type"], "content": r["content"][:500] if r["content"] else ""}
                    for r in wisdom_rows
                ]

                # Recent memory_ledger themes (use content as themes when no topic column)
                memory_rows = await conn.fetch(
                    """
                    SELECT content FROM memory_ledger
                    WHERE user_id = $1
                    ORDER BY created_at DESC
                    LIMIT 15
                    """,
                    uid,
                )
                recent_themes = []
                for m in memory_rows:
                    ct = (m.get("content") or "").strip()
                    if ct and len(ct) > 10:
                        recent_themes.append(ct[:200])

                # Recent liminal session patterns (for communication style)
                liminal_rows = await conn.fetch(
                    """
                    SELECT o.observation_text
                    FROM liminal_observations o
                    JOIN liminal_sessions s ON s.id = o.session_id
                    WHERE s.user_id = $1 AND o.coaching_given = TRUE
                    ORDER BY o.created_at DESC
                    LIMIT 10
                    """,
                    user_id,
                )
                communication_patterns = ""
                if liminal_rows:
                    patterns = [r["observation_text"][:150] for r in liminal_rows if r.get("observation_text")]
                    if patterns:
                        communication_patterns = "; ".join(patterns[:3])

                return {
                    "lived_wisdom": lived_wisdom,
                    "recent_themes": recent_themes,
                    "communication_patterns": communication_patterns,
                }
        except Exception as e:
            logger.warning("Liminal get_user_context failed: %s", e)
            return {}

    async def extract_wisdom(self, session_id: int) -> Optional[str]:
        """
        Extract communication pattern insights from a completed liminal session.
        E.g., "User tends to over-apologize in this relationship."
        """
        try:
            async with self.db_pool.acquire() as conn:
                session = await conn.fetchrow(
                    """
                    SELECT user_id, platform, contact_alias, ended_at
                    FROM liminal_sessions WHERE id = $1
                    """,
                    session_id,
                )
                if not session or not session["ended_at"]:
                    logger.debug("Liminal extract_wisdom: session %s not found or not ended", session_id)
                    return None

                obs = await conn.fetch(
                    """
                    SELECT observation_text, coaching_given
                    FROM liminal_observations WHERE session_id = $1
                    ORDER BY created_at ASC
                    """,
                    session_id,
                )
                if not obs:
                    return None

                combined = "\n".join(o["observation_text"] or "" for o in obs)
                if len(combined.strip()) < 20:
                    return None

                system_prompt = (
                    "You extract a single sentence of insight about the user's communication patterns "
                    "in this external conversation. Examples: 'User tends to over-apologize in this relationship.', "
                    "'User deflects criticism with humor.', 'User holds boundaries well when prompted.' "
                    "Respond with ONLY the insight sentence, no quotes or preamble."
                )
                user_prompt = (
                    f"Platform: {session['platform']}. Contact: {session['contact_alias'] or 'unknown'}.\n\n"
                    f"Observations from the session:\n{combined}"
                )

                raw = await self._call_azure(system_prompt, user_prompt, user_id=session["user_id"])
                if not raw or len(raw.strip()) < 10:
                    return None
                return raw.strip()[:500]
        except Exception as e:
            logger.error("Liminal extract_wisdom failed: %s", e)
            return None

    # ─── Azure OpenAI ─────────────────────────────────────────────────────────

    async def _call_azure(self, system_prompt: str, user_prompt: str, user_id: str | None = None) -> Optional[str]:
        """Call Nate AI Chat Completions API via httpx."""
        if not NATE_CHAT_KEY:
            logger.error("Liminal coaching: Nate AI credentials not configured")
            return None

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.post(
                    NATE_CHAT_URL,
                    json=nate_chat_payload(messages, max_tokens=1500, user_id=user_id),
                    headers=nate_chat_headers(),
                )
                if resp.status_code != 200:
                    logger.error(
                        "Liminal AI %d: %s",
                        resp.status_code,
                        resp.text[:300],
                    )
                    return None
                data = resp.json()
                choices = data.get("choices", [])
                if choices:
                    return choices[0].get("message", {}).get("content")
                return None
        except httpx.TimeoutException:
            logger.error("Liminal coaching: AI timeout")
            return None
        except Exception as e:
            logger.error("Liminal coaching: AI error: %s", e)
            return None
