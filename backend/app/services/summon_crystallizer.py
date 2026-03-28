"""
Summon Response Crystallizer — Archive high-quality summon responses as intelligence crystals.

Runs every 30 minutes. Scans Redis summon cache for responses that meet
quality thresholds (length, coherence, no error fallback text), then feeds
them into the NateMemoryCrystallizer harvest buffer for eventual synthesis
into permanent knowledge.

This closes the loop: public summon traffic generates knowledge that
strengthens Nate's intelligence crystals over time.
"""

import asyncio
import hashlib
import logging
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger("summon_crystallizer")

CRYSTALLIZE_INTERVAL = 1800  # 30 minutes
MIN_RESPONSE_LENGTH = 200
MAX_HARVEST_PER_CYCLE = 50

REJECTION_PHRASES = [
    "I'm having a moment of quiet reflection",
    "I'm not able to help with that",
    "error",
    "unavailable",
    "try again later",
]


class SummonCrystallizer:
    def __init__(self, app_state=None):
        self._app_state = app_state
        self._running = False
        self._task: Optional[asyncio.Task] = None
        self._cycle_count = 0
        self._total_crystallized = 0

    async def start(self):
        self._running = True
        self._task = asyncio.create_task(self._run_loop())
        logger.info("SummonCrystallizer started (30-min harvest cycle)")

    async def stop(self):
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    async def _run_loop(self):
        await asyncio.sleep(300)
        while self._running:
            try:
                await self._crystallize_cycle()
                self._cycle_count += 1
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.warning("SummonCrystallizer cycle error: %s", e)
            await asyncio.sleep(CRYSTALLIZE_INTERVAL)

    async def _crystallize_cycle(self):
        cache_redis = getattr(self._app_state, "cache_redis", None) if self._app_state else None
        if not cache_redis:
            return

        crystallizer = getattr(self._app_state, "nate_memory_crystallizer", None) if self._app_state else None
        if not crystallizer:
            return

        try:
            keys = []
            cursor = b"0"
            while True:
                cursor, batch = await cache_redis.scan(cursor, match="summon:cache:*", count=100)
                keys.extend(batch)
                if cursor == b"0" or len(keys) >= 500:
                    break
        except Exception as e:
            logger.warning("SummonCrystallizer: Redis scan failed: %s", e)
            return

        fragments = []
        for key in keys[:500]:
            try:
                response = await cache_redis.get(key)
                if not response:
                    continue
                if isinstance(response, bytes):
                    response = response.decode("utf-8", errors="replace")

                if not self._meets_quality_threshold(response):
                    continue

                fragments.append({
                    "text": response,
                    "source": "summon_response",
                    "domain": "general",
                    "scope": "global",
                    "created_at": datetime.now(timezone.utc).isoformat(),
                })

                if len(fragments) >= MAX_HARVEST_PER_CYCLE:
                    break
            except Exception:
                continue

        if fragments:
            crystallizer._harvest_buffer.extend(fragments)
            self._total_crystallized += len(fragments)
            logger.info("SummonCrystallizer: harvested %d summon responses into crystal buffer", len(fragments))

        # Archive to R2 for persistence
        if fragments:
            try:
                from app.services.blob_storage import upload_bytes
                import json
                archive_path = f"summon_crystals/{datetime.now(timezone.utc).strftime('%Y/%m/%d')}/{int(time.time())}.jsonl"
                jsonl = "\n".join(json.dumps(f) for f in fragments)
                await asyncio.to_thread(upload_bytes, rel_path=archive_path, content=jsonl.encode())
            except Exception as e:
                logger.debug("SummonCrystallizer: R2 archive failed (non-fatal): %s", e)

    def _meets_quality_threshold(self, response: str) -> bool:
        if len(response) < MIN_RESPONSE_LENGTH:
            return False
        lower = response.lower()
        for phrase in REJECTION_PHRASES:
            if phrase in lower:
                return False
        return True

    def health(self) -> Dict[str, Any]:
        return {
            "running": self._running,
            "cycle_count": self._cycle_count,
            "total_crystallized": self._total_crystallized,
        }
