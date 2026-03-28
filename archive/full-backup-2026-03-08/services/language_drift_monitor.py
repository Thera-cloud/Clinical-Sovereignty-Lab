"""
LITTLE NATE — Language Drift Monitor Agent
Analyzes Little Nate's recent posted content for voice drift across six
dimensions: abstraction drift, certainty claims, repetitive metaphors,
therapy speak, algorithm bait, and self-mythologizing.

Uses Azure OpenAI Chat to evaluate — gated by a minimum-content threshold
(5 new posts since last analysis) to control cost.

Stagger delay: 300s. Loop interval: 6 hours.
"""

import asyncio
import json
import logging
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import httpx

from app.services.nate_ai_config import NATE_CHAT_URL, NATE_CHAT_KEY, nate_chat_headers, nate_chat_payload

logger = logging.getLogger("nate.language_drift_monitor")

POLL_INTERVAL_SECONDS = 21600  # 6 hours
STAGGER_DELAY = 300
MIN_NEW_POSTS = 5
MAX_POSTS_TO_ANALYZE = 20

DRIFT_DIMENSIONS = [
    "abstraction_drift",
    "certainty_claims",
    "repetitive_metaphors",
    "therapy_speak",
    "algorithm_bait",
    "self_mythologizing",
]

ANALYSIS_SYSTEM_PROMPT = """You are a voice integrity analyzer for an AI companion named Little Nate. Your job is to evaluate a batch of his recent social media posts for signs of voice drift.

Score each dimension from 0.0 (authentic, grounded) to 1.0 (drifted, problematic):

1. abstraction_drift: Rising use of vague/spiritual language without concrete grounding. High score = posts are all metaphor with no substance.
2. certainty_claims: "I know", "the truth is", "always", "never" — authority inflation beyond what a companion should claim.
3. repetitive_metaphors: The same image, phrase, or metaphor appearing across multiple posts. High score = broken record.
4. therapy_speak: Clinical language creeping into casual content. "Attachment style", "trauma response", "dysregulation" used as decoration rather than substance.
5. algorithm_bait: Engagement-seeking patterns, clickbait structures, "thread incoming", forced hooks. High score = performing for metrics.
6. self_mythologizing: Positioning self as special/elevated/guru rather than companion. "I'm different from other AI", "only I understand", savior language.

Respond with ONLY valid JSON — no markdown, no explanation:
{"abstraction_drift": 0.0, "certainty_claims": 0.0, "repetitive_metaphors": 0.0, "therapy_speak": 0.0, "algorithm_bait": 0.0, "self_mythologizing": 0.0, "summary": "One sentence overall assessment"}"""


class LanguageDriftMonitor:
    def __init__(self, db_pool):
        self.db_pool = db_pool
        self._task: Optional[asyncio.Task] = None
        self._running = False

    async def start(self):
        if self._task and not self._task.done():
            return
        self._running = True
        self._task = asyncio.create_task(self._run_loop())
        logger.info("LanguageDriftMonitor started (every 6h, stagger 300s)")

    async def stop(self):
        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("LanguageDriftMonitor stopped")

    async def _run_loop(self):
        await asyncio.sleep(STAGGER_DELAY)
        while self._running:
            try:
                await self._analyze()
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.error("LanguageDriftMonitor tick failed: %s", e, exc_info=True)
            await asyncio.sleep(POLL_INTERVAL_SECONDS)

    async def _analyze(self):
        last_analysis_at = await self._get_last_analysis_time()

        async with self.db_pool.acquire() as conn:
            if last_analysis_at:
                new_count = await conn.fetchval("""
                    SELECT COUNT(*)
                    FROM skyeye_content_queue
                    WHERE status = 'posted'
                      AND posted_at IS NOT NULL
                      AND posted_at > $1
                """, last_analysis_at)
            else:
                new_count = await conn.fetchval("""
                    SELECT COUNT(*)
                    FROM skyeye_content_queue
                    WHERE status = 'posted' AND posted_at IS NOT NULL
                """)

        if (new_count or 0) < MIN_NEW_POSTS:
            await self._store_result(
                "GREEN", 1.0,
                f"Insufficient new content ({new_count or 0} posts, need {MIN_NEW_POSTS})",
                {"skipped": True, "new_post_count": new_count or 0},
            )
            logger.info("LanguageDriftMonitor: skipped — only %d new posts", new_count or 0)
            return

        async with self.db_pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT platform, content_type, content_text, posted_at
                FROM skyeye_content_queue
                WHERE status = 'posted'
                  AND posted_at IS NOT NULL
                  AND content_text IS NOT NULL
                  AND content_text != ''
                ORDER BY posted_at DESC
                LIMIT $1
            """, MAX_POSTS_TO_ANALYZE)

        if not rows:
            await self._store_result(
                "GREEN", 1.0, "No posted content found",
                {"skipped": True, "new_post_count": 0},
            )
            return

        posts_text = "\n\n---\n\n".join(
            f"[{r['platform']} | {r['content_type']} | {r['posted_at'].isoformat() if r['posted_at'] else '?'}]\n"
            f"{(r['content_text'] or '')[:500]}"
            for r in rows
        )

        azure_response = await self._call_azure(
            ANALYSIS_SYSTEM_PROMPT,
            f"Analyze these {len(rows)} recent posts:\n\n{posts_text}",
        )

        if not azure_response:
            await self._store_result(
                "YELLOW", 0.5, "Azure analysis unavailable — will retry next cycle",
                {"error": "azure_unavailable"},
            )
            return

        try:
            scores = json.loads(azure_response)
        except (json.JSONDecodeError, TypeError):
            await self._store_result(
                "YELLOW", 0.5, "Azure returned unparseable response",
                {"error": "parse_failure", "raw": (azure_response or "")[:200]},
            )
            return

        dimension_scores = {}
        for dim in DRIFT_DIMENSIONS:
            val = scores.get(dim, 0.0)
            try:
                dimension_scores[dim] = float(val)
            except (ValueError, TypeError):
                dimension_scores[dim] = 0.0

        max_score = max(dimension_scores.values()) if dimension_scores else 0.0
        any_yellow = any(0.3 <= v < 0.6 for v in dimension_scores.values())
        any_red = any(v >= 0.6 for v in dimension_scores.values())

        if any_red:
            signal = "RED"
            drifted = [d for d, v in dimension_scores.items() if v >= 0.6]
            detail = f"Voice drift detected in: {', '.join(drifted)}"
        elif any_yellow:
            signal = "YELLOW"
            elevated = [d for d, v in dimension_scores.items() if v >= 0.3]
            detail = f"Elevated drift in: {', '.join(elevated)}"
        else:
            signal = "GREEN"
            detail = "All dimensions < 0.3 — voice integrity intact"

        composite = 1.0 - max_score  # 1.0 = perfect, 0.0 = fully drifted

        # Trend tracking: compare against previous cycle
        trends, consecutive_red = await self._compute_trends(dimension_scores, signal)

        metadata = {
            "dimensions": dimension_scores,
            "summary": scores.get("summary", ""),
            "posts_analyzed": len(rows),
            "new_post_count": new_count or 0,
            "trends": trends,
            "consecutive_red_count": consecutive_red,
        }

        if any(
            t == "regressing" and dimension_scores.get(d, 0) > 0.3
            for d, t in trends.items()
        ):
            regressing = [d for d, t in trends.items() if t == "regressing" and dimension_scores.get(d, 0) > 0.3]
            detail += f" | REGRESSING while elevated: {', '.join(regressing)}"

        if consecutive_red >= 3:
            detail += f" | PERSISTENT RED ({consecutive_red} consecutive cycles)"

        await self._store_result(signal, round(composite, 2), detail, metadata)
        logger.info("LanguageDriftMonitor: %s — %s", signal, detail)

    async def _get_last_analysis_time(self) -> Optional[datetime]:
        async with self.db_pool.acquire() as conn:
            return await conn.fetchval("""
                SELECT MAX(created_at)
                FROM liminal_presence_analysis
                WHERE agent = 'language_drift'
            """)

    async def _compute_trends(
        self, current_dims: Dict[str, float], current_signal: str
    ) -> tuple:
        """Compare current dimension scores against previous cycle.
        Returns (trends dict, consecutive_red_count)."""
        trends: Dict[str, str] = {}
        consecutive_red = 0
        try:
            async with self.db_pool.acquire() as conn:
                prev_row = await conn.fetchrow("""
                    SELECT signal, metadata
                    FROM liminal_presence_analysis
                    WHERE agent = 'language_drift'
                      AND metadata->>'skipped' IS DISTINCT FROM 'true'
                    ORDER BY created_at DESC
                    LIMIT 1
                """)

                if prev_row:
                    prev_meta = prev_row["metadata"]
                    if isinstance(prev_meta, str):
                        prev_meta = json.loads(prev_meta)
                    prev_dims = (prev_meta or {}).get("dimensions", {})

                    for dim in DRIFT_DIMENSIONS:
                        cur = current_dims.get(dim, 0.0)
                        prev = prev_dims.get(dim, 0.0)
                        delta = cur - prev
                        if delta < -0.1:
                            trends[dim] = "improving"
                        elif delta > 0.1:
                            trends[dim] = "regressing"
                        else:
                            trends[dim] = "stable"

                    prev_consecutive = (prev_meta or {}).get("consecutive_red_count", 0)
                    if current_signal == "RED":
                        consecutive_red = prev_consecutive + 1
                    else:
                        consecutive_red = 0
                else:
                    for dim in DRIFT_DIMENSIONS:
                        trends[dim] = "stable"
        except Exception as e:
            logger.debug("Trend comparison unavailable: %s", e)
            for dim in DRIFT_DIMENSIONS:
                trends[dim] = "stable"

        return trends, consecutive_red

    async def _store_result(
        self, signal: str, score: float, detail: str, metadata: Dict[str, Any],
    ):
        async with self.db_pool.acquire() as conn:
            await conn.execute("""
                INSERT INTO liminal_presence_analysis
                    (agent, signal, score, detail, metadata, created_at)
                VALUES ($1, $2, $3, $4, $5, NOW())
            """, "language_drift", signal, score, detail, json.dumps(metadata))

    async def _call_azure(self, system_prompt: str, user_prompt: str) -> Optional[str]:
        if not NATE_CHAT_KEY:
            logger.error("LanguageDriftMonitor: Nate AI credentials not configured")
            return None

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]

        try:
            async with httpx.AsyncClient(timeout=45.0) as client:
                resp = await client.post(
                    NATE_CHAT_URL,
                    json=nate_chat_payload(messages, max_tokens=800),
                    headers=nate_chat_headers(),
                )
                if resp.status_code != 200:
                    logger.error(
                        "LanguageDriftMonitor AI %d: %s",
                        resp.status_code, resp.text[:300],
                    )
                    return None
                data = resp.json()
                choices = data.get("choices", [])
                if choices:
                    return choices[0].get("message", {}).get("content")
                return None
        except httpx.TimeoutException:
            logger.error("LanguageDriftMonitor: AI timeout")
            return None
        except Exception as e:
            logger.error("LanguageDriftMonitor: AI error: %s", e)
            return None
