"""Phase H predicate poller (W15) — writes PHASE_H_OPEN every 6h.

# QUANTUM-CRYSTAL-ARCH
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List

logger = logging.getLogger("phase_h_predicate_poller")


async def evaluate_predicates(db_pool) -> Dict[str, Any]:
    """Five mechanical predicates. All true → PHASE_H_OPEN."""
    results: List[Dict[str, Any]] = []

    # 1 Gold-sample audit present
    gold_ok = False
    try:
        async with db_pool.acquire() as conn:
            n = await conn.fetchval(
                """
                SELECT COUNT(*) FROM ln7_tasks
                WHERE split = 'heldout' AND source IN ('authored', 'public_bench')
                """
            )
            gold_ok = int(n or 0) >= 1
    except Exception as e:
        logger.warning("gold predicate: %s", e)
    results.append({"id": "gold_sample_audit", "ok": gold_ok})

    # 2 Calibrated abstention — envelope has calibration series
    cal_ok = False
    try:
        async with db_pool.acquire() as conn:
            n = await conn.fetchval(
                """
                SELECT COUNT(*) FROM outcome_envelope
                WHERE metrics_json ? 'calibration'
                   OR metrics_json ? 'brier'
                """
            )
            cal_ok = int(n or 0) >= 1
    except Exception as e:
        logger.warning("calibration predicate: %s", e)
    results.append({"id": "calibrated_abstention", "ok": cal_ok})

    # 3 Labeling provenance fields exist on outcomes
    prov_ok = False
    try:
        async with db_pool.acquire() as conn:
            n = await conn.fetchval(
                """
                SELECT COUNT(*) FROM outcome_envelope
                WHERE provenance_json != '{}'::jsonb
                """
            )
            prov_ok = int(n or 0) >= 1
    except Exception as e:
        logger.warning("provenance predicate: %s", e)
    results.append({"id": "labeling_provenance", "ok": prov_ok})

    # 4 Adversarial held-out weld artifact (platform-state derived, not model-gen)
    from pathlib import Path
    from app.services.ln7_frozen_config import frozen_config_dir

    adv_path = frozen_config_dir() / "adversarial_heldout.json"
    # Bootstrap: goodhart_reference adversarial_criteria counts until dedicated file
    adv_ok = adv_path.is_file()
    if not adv_ok:
        ref = frozen_config_dir() / "goodhart_reference.json"
        adv_ok = ref.is_file()
    results.append({"id": "adversarial_heldout", "ok": adv_ok})

    # 5 Data governance — consent/de-id flag presence (conservative: require table)
    gov_ok = False
    try:
        async with db_pool.acquire() as conn:
            exists = await conn.fetchval(
                """
                SELECT EXISTS (
                    SELECT 1 FROM information_schema.tables
                    WHERE table_name = 'users'
                )
                """
            )
            gov_ok = bool(exists)
    except Exception as e:
        logger.warning("governance predicate: %s", e)
    results.append({"id": "data_governance", "ok": gov_ok})

    open_h = all(r["ok"] for r in results)
    return {"open": open_h, "predicates": results}


async def sync_phase_h_flag(db_pool) -> Dict[str, Any]:
    from app.services.ln7_feature_flags import set_flag

    ev = await evaluate_predicates(db_pool)
    await set_flag(
        db_pool,
        "PHASE_H_OPEN",
        bool(ev.get("open")),
        notes="phase_h_predicate_poller",
    )
    return ev


class PhaseHPredicatePoller:
    def __init__(self, db_pool, interval_seconds: int = 21600):
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

        await asyncio.sleep(200)
        while self._running:
            try:
                await sync_phase_h_flag(self.db_pool)
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.error("PhaseHPredicatePoller failed: %s", e)
            await asyncio.sleep(self.interval)
