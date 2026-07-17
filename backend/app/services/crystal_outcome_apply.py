"""
Gated crystal confidence apply — GREEN/YELLOW domains only.

Clinical + defense stay RED (CEO-Nathan): never auto-applied here.
Shadow proposals remain in crystal_confidence_shadow; this module applies
eligible deltas to live confidence and logs the write.

Kept OUT of db_maintenance_agent.py so the shadow-only source invariant holds.

# QUANTUM-CRYSTAL-ARCH — Dual-COO outcome loop
"""

from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime, timezone
from typing import Any, Dict, Optional

logger = logging.getLogger("crystal_outcome_apply")

# Match shadow caps (WIRE_WHAT_EXISTS Commit 4)
APPLY_MAX_ABS_DELTA = 0.02
APPLY_MIN_SAMPLE = 5
APPLY_INTERVAL_HOURS = int(os.getenv("CRYSTAL_OUTCOME_APPLY_INTERVAL_H", "24"))
RED_DOMAINS = frozenset({"clinical", "defense"})
# Non-clinical domains eligible for GREEN auto-apply
GREEN_DOMAINS = frozenset({
    "coding", "marketing", "research", "culture", "general",
    "coherence", "coaching", "patent", "biochem", "predictive_intelligence",
})


def apply_enabled() -> bool:
    return os.getenv("CRYSTAL_OUTCOME_APPLY_ENABLED", "true").strip().lower() in (
        "1", "true", "yes", "on",
    )


class CrystalOutcomeApplyAgent:
    """Periodic apply of non-RED shadow confidence deltas."""

    def __init__(self, db_pool, app_state=None):
        self.db_pool = db_pool
        self._app_state = app_state
        self._running = False
        self._task: Optional[asyncio.Task] = None
        self._cycles = 0
        self._applied = 0

    async def start(self):
        self._running = True
        self._task = asyncio.create_task(self._run_loop())
        logger.info(
            "CrystalOutcomeApplyAgent started (enabled=%s interval_h=%s)",
            apply_enabled(),
            APPLY_INTERVAL_HOURS,
        )

    async def stop(self):
        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info(
            "CrystalOutcomeApplyAgent stopped (cycles=%s applied=%s)",
            self._cycles,
            self._applied,
        )

    async def _run_loop(self):
        await asyncio.sleep(120)
        while self._running:
            try:
                n = await self.apply_once()
                if n:
                    logger.info("CrystalOutcomeApplyAgent applied %s deltas", n)
            except Exception as e:
                logger.error("CrystalOutcomeApplyAgent cycle error: %s", e)
            await asyncio.sleep(max(3600, APPLY_INTERVAL_HOURS * 3600 // 4))

    async def apply_once(self) -> int:
        """Apply latest eligible shadow rows. Returns count applied."""
        self._cycles += 1
        if not apply_enabled() or not self.db_pool:
            return 0
        async with self.db_pool.acquire() as conn:
            # Gate: skip if we applied recently
            last = await conn.fetchval(
                "SELECT MAX(applied_at) FROM crystal_confidence_apply_log"
            )
            if last is not None:
                age_h = (
                    datetime.now(timezone.utc) - last.replace(tzinfo=timezone.utc)
                ).total_seconds() / 3600
                if age_h < APPLY_INTERVAL_HOURS:
                    return 0

            rows = await conn.fetch(
                """
                SELECT DISTINCT ON (s.crystal_id)
                    s.id AS shadow_id,
                    s.crystal_id,
                    s.domain,
                    s.current_confidence,
                    s.proposed_delta,
                    s.sample_size,
                    s.avg_c_emo,
                    s.reasoning
                FROM crystal_confidence_shadow s
                WHERE s.sample_size >= $1
                  AND ABS(s.proposed_delta) > 0.0001
                  AND LOWER(COALESCE(s.domain, 'general')) = ANY($2::text[])
                  AND NOT EXISTS (
                      SELECT 1 FROM crystal_confidence_apply_log a
                      WHERE a.shadow_id = s.id
                  )
                ORDER BY s.crystal_id, s.computed_at DESC
                LIMIT 200
                """,
                APPLY_MIN_SAMPLE,
                list(GREEN_DOMAINS),
            )

            applied = 0
            for row in rows:
                domain = (row["domain"] or "general").lower()
                if domain in RED_DOMAINS:
                    continue  # belt-and-suspenders — CEO only
                delta = float(row["proposed_delta"])
                delta = max(-APPLY_MAX_ABS_DELTA, min(APPLY_MAX_ABS_DELTA, delta))
                if abs(delta) < 0.0001:
                    continue
                cur = float(row["current_confidence"] or 0.5)
                new_c = max(0.15, min(0.95, cur + delta))

                await conn.execute(
                    """
                    UPDATE nate_intelligence_crystals
                    SET confidence = $1
                    WHERE id = $2
                      AND LOWER(COALESCE(domain, '')) <> ALL($3::text[])
                    """,
                    new_c,
                    row["crystal_id"],
                    list(RED_DOMAINS),
                )
                await conn.execute(
                    """
                    INSERT INTO crystal_confidence_apply_log
                        (shadow_id, crystal_id, domain, old_confidence, new_confidence,
                         delta, sample_size, risk_class, applied_at, reasoning)
                    VALUES ($1, $2, $3, $4, $5, $6, $7, 'GREEN', NOW(), $8)
                    """,
                    row["shadow_id"],
                    row["crystal_id"],
                    domain,
                    cur,
                    new_c,
                    delta,
                    int(row["sample_size"]),
                    (row["reasoning"] or "")[:500],
                )
                applied += 1

            self._applied += applied
            return applied


async def propose_red_clinical_to_ceo(db_pool) -> Dict[str, Any]:
    """Surface clinical/defense shadow proposals to CEO inbox (never auto-apply)."""
    if not db_pool:
        return {"status": "skipped"}
    try:
        from app.websocket.cli_dual_coo import RISK_RED, enqueue_ceo

        async with db_pool.acquire() as conn:
            n = await conn.fetchval(
                """
                SELECT COUNT(*) FROM crystal_confidence_shadow
                WHERE computed_at > NOW() - INTERVAL '8 days'
                  AND LOWER(COALESCE(domain, '')) = ANY($1::text[])
                  AND ABS(proposed_delta) > 0.0001
                """,
                list(RED_DOMAINS),
            )
        if int(n or 0) > 0:
            enqueue_ceo(
                risk=RISK_RED,
                title=f"{n} clinical/defense crystal confidence proposals (CEO only)",
                detail=(
                    "Shadow table has non-zero clinical/defense proposals. "
                    "Auto-apply blocked. Review crystal_confidence_shadow."
                ),
                origin="cloud",
                payload={"count": int(n)},
            )
        return {"status": "ok", "red_proposals": int(n or 0)}
    except Exception as e:
        logger.warning("propose_red_clinical_to_ceo: %s", e)
        return {"status": "error", "error": str(e)[:200]}


async def ceo_apply_clinical_shadows(
    db_pool,
    shadow_ids: list,
    *,
    approved_by: str = "DrNevedal1",
) -> Dict[str, Any]:
    """CEO-RED explicit apply of clinical/defense shadow deltas (forensic log)."""
    if not db_pool or not shadow_ids:
        return {"status": "error", "error": "missing_args"}
    applied = 0
    try:
        async with db_pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT s.id AS shadow_id, s.crystal_id, s.domain,
                       s.current_confidence, s.proposed_delta, s.sample_size, s.reasoning
                FROM crystal_confidence_shadow s
                WHERE s.id = ANY($1::bigint[])
                  AND LOWER(COALESCE(s.domain, '')) = ANY($2::text[])
                  AND s.sample_size >= $3
                """,
                list(shadow_ids),
                list(RED_DOMAINS),
                APPLY_MIN_SAMPLE,
            )
            for row in rows:
                delta = float(row["proposed_delta"])
                delta = max(-APPLY_MAX_ABS_DELTA, min(APPLY_MAX_ABS_DELTA, delta))
                cur = float(row["current_confidence"] or 0.5)
                new_c = max(0.15, min(0.95, cur + delta))
                domain = (row["domain"] or "clinical").lower()
                await conn.execute(
                    """
                    UPDATE nate_intelligence_crystals
                    SET confidence = $1
                    WHERE id = $2
                      AND LOWER(COALESCE(domain, '')) = ANY($3::text[])
                    """,
                    new_c,
                    row["crystal_id"],
                    list(RED_DOMAINS),
                )
                await conn.execute(
                    """
                    INSERT INTO crystal_confidence_apply_log
                        (shadow_id, crystal_id, domain, old_confidence, new_confidence,
                         delta, sample_size, risk_class, applied_at, reasoning)
                    VALUES ($1, $2, $3, $4, $5, $6, $7, 'RED', NOW(), $8)
                    """,
                    row["shadow_id"],
                    row["crystal_id"],
                    domain,
                    cur,
                    new_c,
                    delta,
                    int(row["sample_size"] or 0),
                    f"CEO:{approved_by} {(row['reasoning'] or '')}"[:500],
                )
                await conn.execute(
                    """
                    INSERT INTO ceo_clinical_apply_approvals
                        (shadow_id, crystal_id, domain, old_confidence, new_confidence,
                         delta, approved_by)
                    VALUES ($1, $2, $3, $4, $5, $6, $7)
                    """,
                    row["shadow_id"],
                    row["crystal_id"],
                    domain,
                    cur,
                    new_c,
                    delta,
                    approved_by[:80],
                )
                applied += 1
        return {"status": "ok", "applied": applied}
    except Exception as e:
        logger.warning("ceo_apply_clinical_shadows: %s", e)
        return {"status": "error", "error": str(e)[:300]}
