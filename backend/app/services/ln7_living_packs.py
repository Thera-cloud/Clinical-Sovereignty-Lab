"""Living CI packs from Queens merges (R2 / W8).

# QUANTUM-CRYSTAL-ARCH
"""
from __future__ import annotations

import logging
import random
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger("ln7_living_packs")


async def record_pack_candidate(
    db_pool,
    *,
    patch_hash: str,
    domain: str = "",
    evidence_uri: str = "",
) -> bool:
    if not db_pool or not patch_hash:
        return False
    try:
        async with db_pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO ln7_pack_candidates (patch_hash, domain, evidence_uri)
                VALUES ($1, $2, $3)
                ON CONFLICT (patch_hash) DO NOTHING
                """,
                patch_hash,
                domain or None,
                evidence_uri or None,
            )
        return True
    except Exception as e:
        logger.warning("record_pack_candidate failed: %s", e)
        return False


async def mark_revert(db_pool, patch_hash: str) -> bool:
    if not db_pool or not patch_hash:
        return False
    try:
        async with db_pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE ln7_pack_candidates
                SET revert_seen = TRUE
                WHERE patch_hash = $1
                """,
                patch_hash,
            )
        return True
    except Exception as e:
        logger.warning("mark_revert failed: %s", e)
        return False


async def distill_due_packs(
    db_pool,
    *,
    min_age_days: int = 7,
) -> Dict[str, Any]:
    """Daily job: distill packs aged ≥ N days with no revert."""
    if not db_pool:
        return {"ok": False, "distilled": 0}
    try:
        from app.services.ln7_frozen_config import load_json

        gov = load_json("governance.json", {}) or {}
        min_age_days = int(gov.get("living_pack_min_age_days", min_age_days))
    except Exception:
        pass

    cutoff = datetime.now(timezone.utc) - timedelta(days=min_age_days)
    distilled = 0
    try:
        async with db_pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT id, patch_hash, domain
                FROM ln7_pack_candidates
                WHERE distilled_at IS NULL
                  AND retired_at IS NULL
                  AND revert_seen = FALSE
                  AND merged_at <= $1
                LIMIT 20
                """,
                cutoff,
            )
            for row in rows:
                split = random.choice(["train", "heldout"])
                pack_name = f"living_{row['patch_hash'][:12]}"
                # Distill stub: mark distilled; full broken/+tests copy is deploy-time
                await conn.execute(
                    """
                    UPDATE ln7_pack_candidates
                    SET distilled_at = NOW(), pack_name = $2, split = $3
                    WHERE id = $1
                    """,
                    row["id"],
                    pack_name,
                    split,
                )
                distilled += 1
                logger.info(
                    "living pack candidate distilled: %s domain=%s split=%s",
                    pack_name,
                    row["domain"],
                    split,
                )
    except Exception as e:
        logger.warning("distill_due_packs failed: %s", e)
        return {"ok": False, "distilled": distilled, "error": str(e)}
    return {"ok": True, "distilled": distilled}


class LivingPackAgent:
    """Background daily distill."""

    def __init__(self, db_pool, interval_seconds: int = 86400):
        self.db_pool = db_pool
        self.interval = interval_seconds
        self._task = None
        self._running = False

    async def start(self):
        import asyncio

        if self._task and not self._task.done():
            return
        self._running = True
        self._task = asyncio.create_task(self._run_loop())

    async def stop(self):
        import asyncio

        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    async def _run_loop(self):
        import asyncio

        await asyncio.sleep(190)
        while self._running:
            try:
                await distill_due_packs(self.db_pool)
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.error("LivingPackAgent cycle failed: %s", e)
            await asyncio.sleep(self.interval)
