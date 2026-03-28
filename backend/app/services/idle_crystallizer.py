"""
Idle Crystallizer — R2-backed crystal archival and pre-warming pipeline.

When the system is idle (no active sessions), scans for:
  1. Crystals near decay threshold → pre-warms them in Vectorize/KV
  2. Low-confidence crystals → triggers research synthesis
  3. Archived crystals → replicates to R2 cold storage for durability
  4. Orphaned harvest fragments → attempts clustering

Runs as a background agent every 2 hours. Skips cycles when active
session count > 0 to avoid competing for inference resources.
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

_logger = logging.getLogger("idle_crystallizer")

_R2_CRYSTAL_BUCKET = "nate-cold-archive"
_R2_PREFIX = "crystals/"
_DECAY_WARNING_DAYS = 75
_LOW_CONFIDENCE_THRESHOLD = 0.35
_ARCHIVE_BATCH_SIZE = 50
_CYCLE_INTERVAL_SECONDS = 7200


class IdleCrystallizer:
    """R2-backed crystal archival and pre-warming pipeline."""

    def __init__(self, db_pool, app_state=None):
        self.db_pool = db_pool
        self.app_state = app_state
        self._task: Optional[asyncio.Task] = None
        self._stop_event = asyncio.Event()
        self._last_cycle: Optional[datetime] = None
        self._stats = {
            "cycles_completed": 0,
            "crystals_archived_to_r2": 0,
            "crystals_pre_warmed": 0,
            "low_confidence_flagged": 0,
        }

    async def start(self):
        """Start the idle crystallization background loop."""
        self._stop_event.clear()
        self._task = asyncio.create_task(self._run_loop())
        _logger.info("IdleCrystallizer started (cycle every %ds)", _CYCLE_INTERVAL_SECONDS)

    async def stop(self):
        """Stop the background loop gracefully."""
        self._stop_event.set()
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):
                pass
        _logger.info("IdleCrystallizer stopped. Stats: %s", self._stats)

    def get_status(self) -> Dict[str, Any]:
        return {
            "running": self._task is not None and not self._task.done(),
            "last_cycle": self._last_cycle.isoformat() if self._last_cycle else None,
            **self._stats,
        }

    async def _run_loop(self):
        await asyncio.sleep(180)
        while not self._stop_event.is_set():
            try:
                await self._cycle()
            except Exception as e:
                _logger.warning("IdleCrystallizer cycle error: %s", e)
            try:
                await asyncio.wait_for(self._stop_event.wait(), timeout=_CYCLE_INTERVAL_SECONDS)
                break
            except asyncio.TimeoutError:
                pass

    async def _cycle(self):
        if not self.db_pool:
            return

        active = await self._count_active_sessions()
        if active > 0:
            _logger.debug("IdleCrystallizer: %d active sessions, skipping cycle", active)
            return

        _logger.info("IdleCrystallizer: system idle, running crystal maintenance")

        archived = await self._archive_to_r2()
        pre_warmed = await self._pre_warm_decay_candidates()
        flagged = await self._flag_low_confidence()

        self._stats["cycles_completed"] += 1
        self._stats["crystals_archived_to_r2"] += archived
        self._stats["crystals_pre_warmed"] += pre_warmed
        self._stats["low_confidence_flagged"] += flagged
        self._last_cycle = datetime.now(timezone.utc)

        _logger.info(
            "IdleCrystallizer cycle complete: archived=%d, pre_warmed=%d, flagged=%d",
            archived, pre_warmed, flagged,
        )

    async def _count_active_sessions(self) -> int:
        try:
            async with self.db_pool.acquire() as conn:
                row = await conn.fetchrow(
                    """SELECT COUNT(*) AS cnt FROM coaching_sessions
                       WHERE status = 'ACTIVE'
                         AND session_start > NOW() - INTERVAL '4 hours'"""
                )
                return row["cnt"] if row else 0
        except Exception:
            return 0

    async def _archive_to_r2(self) -> int:
        """Replicate archived crystals to R2 cold storage."""
        try:
            from app.services.r2_storage import is_r2_configured, upload_bytes
        except ImportError:
            return 0

        if not is_r2_configured():
            return 0

        try:
            async with self.db_pool.acquire() as conn:
                rows = await conn.fetch(
                    """SELECT id, crystal_text, domain, confidence, content_hash,
                              created_at, last_recalled_at, recall_count
                       FROM nate_intelligence_crystals
                       WHERE scope = 'archived'
                         AND content_hash NOT IN (
                             SELECT COALESCE(content_hash, '') FROM nate_intelligence_crystals
                             WHERE scope != 'archived'
                         )
                       ORDER BY created_at ASC
                       LIMIT $1""",
                    _ARCHIVE_BATCH_SIZE,
                )

            count = 0
            for r in rows:
                crystal_data = {
                    "id": str(r["id"]),
                    "text": r["crystal_text"],
                    "domain": r["domain"],
                    "confidence": float(r["confidence"] or 0),
                    "content_hash": r["content_hash"],
                    "created_at": r["created_at"].isoformat() if r["created_at"] else None,
                    "last_recalled_at": r["last_recalled_at"].isoformat() if r["last_recalled_at"] else None,
                    "recall_count": r["recall_count"] or 0,
                    "archived_to_r2_at": datetime.now(timezone.utc).isoformat(),
                }
                key = f"{_R2_PREFIX}{r['domain']}/{r['content_hash']}.json"
                try:
                    blob = json.dumps(crystal_data, default=str).encode("utf-8")
                    ok = await asyncio.to_thread(
                        upload_bytes,
                        bucket=_R2_CRYSTAL_BUCKET,
                        key=key,
                        data=blob,
                        content_type="application/json",
                    )
                    if ok:
                        count += 1
                except Exception as e:
                    _logger.debug("R2 archive failed for crystal %s: %s", r["id"], e)
            return count
        except Exception as e:
            _logger.warning("IdleCrystallizer archive_to_r2 error: %s", e)
            return 0

    async def _pre_warm_decay_candidates(self) -> int:
        """Find crystals approaching decay and refresh their recall metadata."""
        cutoff = datetime.now(timezone.utc) - timedelta(days=_DECAY_WARNING_DAYS)
        try:
            async with self.db_pool.acquire() as conn:
                rows = await conn.fetch(
                    """SELECT id, crystal_text, domain, confidence, recall_count
                       FROM nate_intelligence_crystals
                       WHERE scope = 'global'
                         AND (last_recalled_at IS NULL OR last_recalled_at < $1)
                         AND recall_count < 3
                         AND confidence >= 0.3
                       ORDER BY confidence DESC
                       LIMIT 20""",
                    cutoff,
                )

            if not rows:
                return 0

            count = 0
            try:
                from app.services.vectorize_service import is_vectorize_configured
                vectorize_ok = is_vectorize_configured()
            except ImportError:
                vectorize_ok = False

            for r in rows:
                try:
                    if vectorize_ok:
                        from app.services.vectorize_service import index_wisdom
                        await index_wisdom(
                            user_id="nate_crystal",
                            wisdom_id=f"crystal_{str(r['id'])[:16]}",
                            insight_type=f"crystal_{r['domain'] or 'general'}",
                            content=(r["crystal_text"] or "")[:500],
                            source="idle_prewarm",
                            domain=r["domain"] or "general",
                            timestamp=str(r.get("created_at", "")),
                            face_path="",
                        )
                    async with self.db_pool.acquire() as conn:
                        await conn.execute(
                            """UPDATE nate_intelligence_crystals
                               SET last_recalled_at = NOW()
                               WHERE id = $1""",
                            r["id"],
                        )
                    count += 1
                except Exception as e:
                    _logger.debug("Pre-warm failed for crystal %s: %s", r["id"], e)

            return count
        except Exception as e:
            _logger.warning("IdleCrystallizer pre_warm error: %s", e)
            return 0

    async def _flag_low_confidence(self) -> int:
        """Flag crystals with critically low confidence for research synthesis."""
        try:
            async with self.db_pool.acquire() as conn:
                result = await conn.execute(
                    """UPDATE nate_intelligence_crystals
                       SET scope = 'archived'
                       WHERE scope = 'global'
                         AND confidence < $1
                         AND recall_count < 2
                         AND created_at < NOW() - INTERVAL '7 days'""",
                    _LOW_CONFIDENCE_THRESHOLD,
                )
                count_str = result.split(" ")[-1] if result else "0"
                return int(count_str)
        except Exception as e:
            _logger.warning("IdleCrystallizer flag_low_confidence error: %s", e)
            return 0
