"""
SOVEREIGN SWARM — Lived Wisdom Pipeline
Extracts therapeutic insights from completed sessions (especially sanctuary sessions)
and stores them as per-client and per-family wisdom for Night School personalization.

Spec source: docs/LITTLE_NATE_PROGRESS_CHECKLIST_UPDATED.md (Phase 6)

Pipeline:
    1. Session completes → extract_sanctuary_wisdom() or extract_session_wisdom()
    2. Insights stored in wisdom_extractions table
    3. Night School ingests client/family wisdom for personalized training

Insight Types:
    technique    — Therapeutic technique that worked well
    pattern      — Behavioral/emotional pattern identified
    breakthrough — CEE or breakthrough moment
    coping       — Coping strategy discovered or reinforced
    trigger      — Identified trigger or stressor
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from uuid import UUID

from app.services.nate_ai_config import NATE_CHAT_URL, NATE_CHAT_KEY, nate_chat_headers, nate_chat_payload

logger = logging.getLogger("lived_wisdom")

# ─── Keywords for heuristic extraction (when Azure OpenAI is unavailable) ────

TECHNIQUE_KEYWORDS = [
    "breathing exercise", "grounding", "visualization", "journaling",
    "mindfulness", "body scan", "progressive relaxation", "reframing",
    "cognitive restructuring", "exposure", "behavioral activation",
    "thought record", "somatic experiencing", "eft", "ifs", "parts work",
]

COPING_KEYWORDS = [
    "cope", "coping", "manage", "strategy", "when I feel", "what helps",
    "I tried", "worked for me", "calmed me", "helped me",
]

TRIGGER_KEYWORDS = [
    "trigger", "triggered", "reminds me of", "whenever", "every time",
    "stresses me", "upsets me", "makes me angry", "makes me anxious",
]

BREAKTHROUGH_KEYWORDS = [
    "realized", "breakthrough", "for the first time", "never noticed",
    "now I understand", "aha moment", "everything clicked",
    "I can see now", "that's why I",
]


class LivedWisdomService:
    """Extracts and stores therapeutic wisdom from sessions."""

    def __init__(self, db_pool, azure_client=None):
        self.db_pool = db_pool
        self.azure_client = azure_client

    # ─── Core Extraction ─────────────────────────────────────────────────

    async def extract_sanctuary_wisdom(
        self,
        session_id: UUID,
        family_id: UUID,
        messages: List[Dict[str, Any]],
        member_ids: Optional[List[UUID]] = None,
    ) -> List[Dict[str, Any]]:
        """
        Extract wisdom from a completed Family Sanctuary session.
        Messages should be a list of {sender_type, sender_id, text, timestamp}.
        Returns list of extracted wisdom entries.
        """
        insights = []

        # Combine all text for analysis
        all_text = " ".join(m.get("text", "") for m in messages if m.get("text"))

        # Heuristic extraction
        insights.extend(self._extract_by_keywords(all_text, "technique", TECHNIQUE_KEYWORDS))
        insights.extend(self._extract_by_keywords(all_text, "coping", COPING_KEYWORDS))
        insights.extend(self._extract_by_keywords(all_text, "trigger", TRIGGER_KEYWORDS))
        insights.extend(self._extract_by_keywords(all_text, "breakthrough", BREAKTHROUGH_KEYWORDS))

        # Store each insight
        stored = []
        for insight in insights:
            entry = await self._store_wisdom(
                user_id=None,  # Family-level wisdom
                family_id=family_id,
                session_id=session_id,
                insight_type=insight["type"],
                content=insight["content"],
                effectiveness_score=insight.get("score", 0.5),
                source="sanctuary",
            )
            if entry:
                stored.append(entry)

        # Also extract per-member wisdom if member_ids provided
        if member_ids:
            for member_id in member_ids:
                member_msgs = [m for m in messages if m.get("sender_id") == str(member_id)]
                member_text = " ".join(m.get("text", "") for m in member_msgs if m.get("text"))
                member_insights = self._extract_by_keywords(member_text, "pattern", TECHNIQUE_KEYWORDS + COPING_KEYWORDS)
                for ins in member_insights:
                    entry = await self._store_wisdom(
                        user_id=member_id,
                        family_id=family_id,
                        session_id=session_id,
                        insight_type=ins["type"],
                        content=ins["content"],
                        source="sanctuary",
                    )
                    if entry:
                        stored.append(entry)

        if stored:
            print(f">>> [LIVED WISDOM] Extracted {len(stored)} insights from sanctuary session {session_id}")

        return stored

    async def extract_session_wisdom(
        self,
        session_id: UUID,
        user_id: UUID,
        messages: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        """
        Extract wisdom from a standard 1:1 session.
        Uses Azure OpenAI if available, falls back to heuristic keyword extraction.
        """
        all_text = " ".join(m.get("text", "") for m in messages if m.get("text"))

        # Try Azure OpenAI extraction first
        insights = await self._extract_with_azure(all_text)

        # Fallback to heuristic if Azure returned nothing or is unavailable
        if not insights:
            insights = []
            insights.extend(self._extract_by_keywords(all_text, "technique", TECHNIQUE_KEYWORDS))
            insights.extend(self._extract_by_keywords(all_text, "coping", COPING_KEYWORDS))
            insights.extend(self._extract_by_keywords(all_text, "trigger", TRIGGER_KEYWORDS))
            insights.extend(self._extract_by_keywords(all_text, "breakthrough", BREAKTHROUGH_KEYWORDS))

        stored = []
        for insight in insights:
            entry = await self._store_wisdom(
                user_id=user_id,
                family_id=None,
                session_id=session_id,
                insight_type=insight["type"],
                content=insight["content"],
                source="session",
            )
            if entry:
                stored.append(entry)

        return stored

    # ─── Night School Integration ────────────────────────────────────────

    async def get_client_wisdom(self, user_id: UUID, limit: int = 50) -> List[Dict[str, Any]]:
        """Retrieve accumulated wisdom for a specific client (for Night School)."""
        async with self.db_pool.acquire() as conn:
            rows = await conn.fetch(
                """SELECT id, insight_type, content, effectiveness_score, source, extracted_at
                   FROM wisdom_extractions
                   WHERE user_id = $1 AND approved = TRUE
                   ORDER BY effectiveness_score DESC, extracted_at DESC
                   LIMIT $2""",
                user_id, limit,
            )
        return [
            {
                "id": str(r["id"]),
                "type": r["insight_type"],
                "content": r["content"],
                "effectiveness": float(r["effectiveness_score"] or 0),
                "source": r["source"],
                "extracted_at": r["extracted_at"].isoformat() if r["extracted_at"] else None,
            }
            for r in rows
        ]

    async def get_family_wisdom(self, family_id: UUID, limit: int = 50) -> List[Dict[str, Any]]:
        """Retrieve accumulated wisdom for a family (for Night School)."""
        async with self.db_pool.acquire() as conn:
            rows = await conn.fetch(
                """SELECT id, user_id, insight_type, content, effectiveness_score, source, extracted_at
                   FROM wisdom_extractions
                   WHERE family_id = $1 AND approved = TRUE
                   ORDER BY effectiveness_score DESC, extracted_at DESC
                   LIMIT $2""",
                family_id, limit,
            )
        return [
            {
                "id": str(r["id"]),
                "user_id": str(r["user_id"]) if r["user_id"] else None,
                "type": r["insight_type"],
                "content": r["content"],
                "effectiveness": float(r["effectiveness_score"] or 0),
                "source": r["source"],
                "extracted_at": r["extracted_at"].isoformat() if r["extracted_at"] else None,
            }
            for r in rows
        ]

    async def approve_wisdom(self, wisdom_id: UUID) -> bool:
        """Approve an extracted wisdom entry for use in Night School."""
        async with self.db_pool.acquire() as conn:
            result = await conn.execute(
                "UPDATE wisdom_extractions SET approved = TRUE WHERE id = $1",
                wisdom_id,
            )
            return "UPDATE 1" in result

    async def update_effectiveness(self, wisdom_id: UUID, score: float) -> bool:
        """Update effectiveness score for a wisdom entry."""
        async with self.db_pool.acquire() as conn:
            result = await conn.execute(
                "UPDATE wisdom_extractions SET effectiveness_score = $2 WHERE id = $1",
                wisdom_id, max(0.0, min(1.0, score)),
            )
            return "UPDATE 1" in result

    # ─── Azure OpenAI Extraction ────────────────────────────────────────

    async def _extract_with_azure(self, text: str) -> List[Dict[str, Any]]:
        """
        Use Nate AI Chat Completions to extract structured therapeutic
        insights from session text. Returns a list of insight dicts or empty
        list if AI is unavailable.
        """
        if not NATE_CHAT_KEY or not text or len(text) < 50:
            return []

        try:
            import httpx

            system_prompt = (
                "You are a clinical insight extractor for a therapeutic AI platform. "
                "Given a session transcript, identify therapeutic insights in these categories:\n"
                "- technique: Therapeutic techniques used or discussed\n"
                "- coping: Coping strategies discovered or reinforced\n"
                "- trigger: Identified emotional triggers or stressors\n"
                "- breakthrough: Moments of realization or emotional progress\n"
                "- pattern: Recurring behavioral or emotional patterns\n\n"
                "Return a JSON array of objects with fields: type, content, score (0.0-1.0 effectiveness).\n"
                "Return at most 10 insights. If no clear insights, return an empty array [].\n"
                "Return ONLY the JSON array, no other text."
            )

            messages = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"Session transcript (truncated to 3000 chars):\n\n{text[:3000]}"},
            ]

            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.post(
                    NATE_CHAT_URL,
                    headers=nate_chat_headers(),
                    json=nate_chat_payload(messages, max_tokens=1000),
                )

                if resp.status_code != 200:
                    logger.warning(f"[LIVED WISDOM] Azure extraction failed: {resp.status_code}")
                    return []

                data = resp.json()
                content = data["choices"][0]["message"]["content"].strip()

                # Parse JSON response
                if content.startswith("["):
                    insights = json.loads(content)
                else:
                    # Try to find JSON array in response
                    start = content.find("[")
                    end = content.rfind("]")
                    if start >= 0 and end > start:
                        insights = json.loads(content[start:end + 1])
                    else:
                        return []

                # Validate and normalize
                valid = []
                for ins in insights:
                    if isinstance(ins, dict) and "type" in ins and "content" in ins:
                        valid.append({
                            "type": ins["type"],
                            "content": str(ins["content"])[:500],
                            "score": float(ins.get("score", 0.6)),
                        })
                logger.info(f"[LIVED WISDOM] Azure extracted {len(valid)} insights")
                return valid[:10]

        except Exception as e:
            logger.warning(f"[LIVED WISDOM] Azure extraction error: {e}")
            return []

    # ─── Private Helpers ─────────────────────────────────────────────────

    def _extract_by_keywords(
        self, text: str, insight_type: str, keywords: List[str]
    ) -> List[Dict[str, Any]]:
        """Extract insights using keyword matching."""
        if not text:
            return []

        insights = []
        text_lower = text.lower()
        sentences = text.replace(".", ".\n").replace("!", "!\n").replace("?", "?\n").split("\n")

        for sentence in sentences:
            sentence = sentence.strip()
            if len(sentence) < 10:
                continue
            sentence_lower = sentence.lower()
            for kw in keywords:
                if kw in sentence_lower:
                    insights.append({
                        "type": insight_type,
                        "content": sentence[:500],
                        "keyword": kw,
                        "score": 0.5,
                    })
                    break  # One match per sentence

        return insights[:10]  # Cap at 10 per type

    async def _store_wisdom(
        self,
        user_id: Optional[UUID],
        family_id: Optional[UUID],
        session_id: UUID,
        insight_type: str,
        content: str,
        effectiveness_score: float = 0.5,
        source: str = "session",
    ) -> Optional[Dict[str, Any]]:
        """Store a wisdom extraction in the database."""
        try:
            async with self.db_pool.acquire() as conn:
                row = await conn.fetchrow(
                    """INSERT INTO wisdom_extractions
                        (user_id, family_id, session_id, insight_type, content,
                         effectiveness_score, source)
                    VALUES ($1, $2, $3, $4, $5, $6, $7)
                    RETURNING id, extracted_at""",
                    user_id, family_id, session_id,
                    insight_type, content[:1000],
                    effectiveness_score, source,
                )
                wisdom_id = str(row["id"])
                extracted_at = row["extracted_at"].isoformat()
                try:
                    from app.services.vectorize_service import index_wisdom as _idx_w, is_vectorize_configured
                    if is_vectorize_configured():
                        import asyncio as _aio
                        _aio.create_task(_idx_w(
                            user_id=user_id, wisdom_id=wisdom_id,
                            insight_type=insight_type, content=content[:1000],
                            family_id=family_id or "", session_id=session_id or "",
                            source=source, timestamp=extracted_at,
                        ))
                except Exception:
                    pass
                return {
                    "id": wisdom_id,
                    "type": insight_type,
                    "content": content[:200],
                    "extracted_at": extracted_at,
                }
        except Exception as e:
            print(f">>> [LIVED WISDOM] Store error: {e}")
            return None
