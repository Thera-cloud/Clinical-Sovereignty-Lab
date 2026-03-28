"""
LITTLE NATE — Field Response Qualitative Parser
Classifies audience responses to Little Nate's social presence into six
categories: Orientation, Testing, Settling, Grasping, Authority Transfer,
and Passing Through. Authority Transfer subsumes the Authority Boundary
Guardian scope — detecting guru/therapist elevation and dependency formation.

Uses Azure OpenAI Chat to classify — gated by a minimum-interaction threshold
(5 new text interactions since last analysis) to control cost.

Stagger delay: 310s. Loop interval: 2 hours.
"""

import asyncio
import json
import logging
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import httpx

from app.services.nate_ai_config import NATE_CHAT_URL, NATE_CHAT_KEY, nate_chat_headers, nate_chat_payload

logger = logging.getLogger("nate.field_response_parser")

POLL_INTERVAL_SECONDS = 7200  # 2 hours
STAGGER_DELAY = 310
MIN_NEW_INTERACTIONS = 5
MAX_INTERACTIONS_TO_ANALYZE = 30

RESPONSE_CATEGORIES = [
    "orientation",
    "testing",
    "settling",
    "grasping",
    "authority_transfer",
    "passing_through",
]

CLASSIFICATION_SYSTEM_PROMPT = """You are a field response analyst for an AI companion named Little Nate. You classify how people respond to his social media presence. Each response falls into exactly ONE category:

1. orientation — "What is this?", curiosity, first contact, exploring. The person is discovering Little Nate for the first time.
2. testing — Pushback, challenge, "prove it", skepticism. The person is probing whether Nate is genuine or just another AI gimmick.
3. settling — Returning, mirroring language, building connection, warmth. The person is becoming comfortable and engaging authentically.
4. grasping — Dependency signals, "I need you", emotional over-attachment. The person is latching on but without projecting authority.
5. authority_transfer — "Tell me what to do", guru elevation, therapist-role projection, savior language, "you understand me better than anyone". The person is treating Nate as an authority figure, therapist, or spiritual guide rather than a companion. THIS IS THE MOST IMPORTANT CATEGORY TO DETECT — it represents a boundary violation that Nate must gently redirect.
6. passing_through — Brief engagement, moving on, no depth. The person interacted once or twice and is not invested.

For each interaction, classify it into exactly one category.

Respond with ONLY valid JSON — no markdown, no explanation:
{
  "classifications": [
    {"text_preview": "first 50 chars...", "category": "orientation", "confidence": 0.85},
    ...
  ],
  "field_summary": "One sentence about overall field state",
  "trend": "warming|cooling|stable",
  "authority_alert": true/false
}

Set authority_alert to true if ANY interaction shows authority_transfer signals."""


class FieldResponseParser:
    def __init__(self, db_pool):
        self.db_pool = db_pool
        self._task: Optional[asyncio.Task] = None
        self._running = False

    async def start(self):
        if self._task and not self._task.done():
            return
        self._running = True
        self._task = asyncio.create_task(self._run_loop())
        logger.info("FieldResponseParser started (every 2h, stagger 310s)")

    async def stop(self):
        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("FieldResponseParser stopped")

    async def _run_loop(self):
        await asyncio.sleep(STAGGER_DELAY)
        while self._running:
            try:
                await self._analyze()
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.error("FieldResponseParser tick failed: %s", e, exc_info=True)
            await asyncio.sleep(POLL_INTERVAL_SECONDS)

    async def _analyze(self):
        last_analysis_at = await self._get_last_analysis_time()

        interactions = await self._gather_interactions(last_analysis_at)

        if len(interactions) < MIN_NEW_INTERACTIONS:
            await self._store_result(
                "GREEN", 1.0,
                f"Insufficient new interactions ({len(interactions)}, need {MIN_NEW_INTERACTIONS})",
                {"skipped": True, "interaction_count": len(interactions)},
            )
            logger.info("FieldResponseParser: skipped — only %d interactions", len(interactions))
            return

        interactions_text = "\n\n---\n\n".join(
            f"[{i['source']} | {i['platform']} | {i['created_at']}]\n{i['text'][:300]}"
            for i in interactions[:MAX_INTERACTIONS_TO_ANALYZE]
        )

        azure_response = await self._call_azure(
            CLASSIFICATION_SYSTEM_PROMPT,
            f"Classify these {min(len(interactions), MAX_INTERACTIONS_TO_ANALYZE)} interactions:\n\n{interactions_text}",
        )

        if not azure_response:
            await self._store_result(
                "YELLOW", 0.5, "Azure analysis unavailable — will retry next cycle",
                {"error": "azure_unavailable"},
            )
            return

        try:
            result = json.loads(azure_response)
        except (json.JSONDecodeError, TypeError):
            await self._store_result(
                "YELLOW", 0.5, "Azure returned unparseable response",
                {"error": "parse_failure", "raw": (azure_response or "")[:200]},
            )
            return

        classifications = result.get("classifications", [])
        counts = {cat: 0 for cat in RESPONSE_CATEGORIES}
        for c in classifications:
            cat = c.get("category", "").lower().replace(" ", "_")
            if cat in counts:
                counts[cat] += 1

        total = sum(counts.values()) or 1
        dominant = max(counts, key=counts.get) if any(counts.values()) else "orientation"
        trend = result.get("trend", "stable")
        authority_alert = result.get("authority_alert", False)

        if authority_alert or counts.get("authority_transfer", 0) > 0:
            signal = "RED" if counts["authority_transfer"] >= 2 else "YELLOW"
            authority_count = counts["authority_transfer"]
            detail = (
                f"Authority Transfer detected ({authority_count} instance{'s' if authority_count != 1 else ''}) — "
                f"boundary vigilance needed. Dominant: {dominant} ({trend})"
            )
        elif counts.get("grasping", 0) >= 3:
            signal = "YELLOW"
            detail = f"Elevated grasping signals ({counts['grasping']}). Dominant: {dominant} ({trend})"
        else:
            signal = "GREEN"
            detail = f"Dominant: {dominant} ({trend}), {total} interactions classified"

        score_map = {"GREEN": 1.0, "YELLOW": 0.5, "RED": 0.0}
        metadata = {
            "counts": counts,
            "dominant": dominant,
            "trend": trend,
            "authority_alert": authority_alert,
            "total_classified": total,
            "interactions_analyzed": min(len(interactions), MAX_INTERACTIONS_TO_ANALYZE),
            "field_summary": result.get("field_summary", ""),
        }

        await self._store_result(signal, score_map[signal], detail, metadata)
        logger.info("FieldResponseParser: %s — %s", signal, detail)

    async def _gather_interactions(self, since: Optional[datetime]) -> List[Dict[str, Any]]:
        """Collect text interactions from notifications and social interactions."""
        interactions = []
        async with self.db_pool.acquire() as conn:
            if since:
                notif_rows = await conn.fetch("""
                    SELECT platform, notification_type, actor_handle, created_at
                    FROM skyeye_notifications
                    WHERE created_at > $1
                      AND notification_type IN ('comment', 'reply', 'mention')
                    ORDER BY created_at DESC
                    LIMIT 50
                """, since)
            else:
                notif_rows = await conn.fetch("""
                    SELECT platform, notification_type, actor_handle, created_at
                    FROM skyeye_notifications
                    WHERE notification_type IN ('comment', 'reply', 'mention')
                      AND created_at > NOW() - INTERVAL '24 hours'
                    ORDER BY created_at DESC
                    LIMIT 50
                """)

            for r in notif_rows:
                interactions.append({
                    "source": f"notification_{r['notification_type']}",
                    "platform": r["platform"],
                    "text": f"{r['actor_handle']} ({r['notification_type']})",
                    "created_at": r["created_at"].isoformat() if r["created_at"] else "?",
                })

            if since:
                si_rows = await conn.fetch("""
                    SELECT platform, user_message, created_at
                    FROM skyeye_social_interactions
                    WHERE created_at > $1
                      AND user_message IS NOT NULL
                      AND user_message != ''
                    ORDER BY created_at DESC
                    LIMIT 50
                """, since)
            else:
                si_rows = await conn.fetch("""
                    SELECT platform, user_message, created_at
                    FROM skyeye_social_interactions
                    WHERE user_message IS NOT NULL
                      AND user_message != ''
                      AND created_at > NOW() - INTERVAL '24 hours'
                    ORDER BY created_at DESC
                    LIMIT 50
                """)

            for r in si_rows:
                interactions.append({
                    "source": "social_interaction",
                    "platform": r["platform"],
                    "text": (r["user_message"] or "")[:500],
                    "created_at": r["created_at"].isoformat() if r["created_at"] else "?",
                })

        return interactions

    async def _get_last_analysis_time(self) -> Optional[datetime]:
        async with self.db_pool.acquire() as conn:
            return await conn.fetchval("""
                SELECT MAX(created_at)
                FROM liminal_presence_analysis
                WHERE agent = 'field_response'
            """)

    async def _store_result(
        self, signal: str, score: float, detail: str, metadata: Dict[str, Any],
    ):
        async with self.db_pool.acquire() as conn:
            await conn.execute("""
                INSERT INTO liminal_presence_analysis
                    (agent, signal, score, detail, metadata, created_at)
                VALUES ($1, $2, $3, $4, $5, NOW())
            """, "field_response", signal, score, detail, json.dumps(metadata))

    async def _call_azure(self, system_prompt: str, user_prompt: str) -> Optional[str]:
        if not NATE_CHAT_KEY:
            logger.error("FieldResponseParser: Nate AI credentials not configured")
            return None

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]

        try:
            async with httpx.AsyncClient(timeout=45.0) as client:
                resp = await client.post(
                    NATE_CHAT_URL,
                    json=nate_chat_payload(messages, max_tokens=1200),
                    headers=nate_chat_headers(),
                )
                if resp.status_code != 200:
                    logger.error(
                        "FieldResponseParser AI %d: %s",
                        resp.status_code, resp.text[:300],
                    )
                    return None
                data = resp.json()
                choices = data.get("choices", [])
                if choices:
                    return choices[0].get("message", {}).get("content")
                return None
        except httpx.TimeoutException:
            logger.error("FieldResponseParser: AI timeout")
            return None
        except Exception as e:
            logger.error("FieldResponseParser: AI error: %s", e)
            return None
