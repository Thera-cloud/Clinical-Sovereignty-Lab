"""LN7 continuous gated self-improvement agent (GREEN orchestration only).

Cycle: claim ready train job → mark for off-box worker → evaluate canaries.
Weight training never runs on GREEN (worker_host = BLUE/CUDA).

Product name: continuous gated self-improvement (coder-domain). Not AGI.

# QUANTUM-CRYSTAL-ARCH
"""
from __future__ import annotations

import asyncio
import logging
import os
from typing import Any, Optional

logger = logging.getLogger("ln7_continuous_agent")


class Ln7ContinuousAgent:
    def __init__(self, db_pool, *, interval_s: int = 300):
        self._db = db_pool
        self._interval = max(60, interval_s)
        self._task: Optional[asyncio.Task] = None
        self._stop = asyncio.Event()

    async def start(self) -> None:
        if self._task and not self._task.done():
            return
        self._stop.clear()
        self._task = asyncio.create_task(self._run_loop(), name="ln7_continuous_agent")
        logger.info("Ln7ContinuousAgent started (interval=%ss)", self._interval)

    async def stop(self) -> None:
        self._stop.set()
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

    async def _run_loop(self) -> None:
        from app.services.ln7_train_queue import continuous_enabled
        while not self._stop.is_set():
            try:
                if continuous_enabled() and self._db:
                    await self._cycle()
            except Exception as exc:
                logger.warning("Ln7ContinuousAgent cycle: %s", exc)
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=self._interval)
            except asyncio.TimeoutError:
                pass

    async def _cycle(self) -> None:
        from app.services.ln7_train_queue import claim_ready_job, update_job
        from app.services.ln7_canary_promoter import evaluate_canary

        job = await claim_ready_job(self._db)
        if job:
            jid = int(job["id"])
            # GREEN only stages — worker pulls via API / SSH
            await update_job(
                self._db,
                jid,
                status="training",
                worker_host=os.getenv("LN7_TRAIN_WORKER_HOST", "blue_or_cuda"),
                gate_json={"staged": True, "hint": "Drain via ln7_micro_qlora_worker.py"},
            )
            logger.info("LN7 continuous: staged job %s for off-box QLoRA", jid)

        # Evaluate active canaries
        try:
            async with self._db.acquire() as conn:
                rows = await conn.fetch(
                    "SELECT revision_id FROM ln7_canary_state WHERE status = 'active'"
                )
            for r in rows:
                result = await evaluate_canary(self._db, r["revision_id"])
                logger.info(
                    "LN7 canary %s → %s",
                    r["revision_id"],
                    result.get("action") or result.get("error"),
                )
                if result.get("action") == "await_ceo" and result.get("ok"):
                    try:
                        from app.services.ln7_revision import notify_revision_candidate

                        await notify_revision_candidate(
                            self._db, r["revision_id"], force_ready=True
                        )
                    except Exception as nexc:
                        logger.warning("LN7 READY renotify: %s", nexc)
        except Exception as exc:
            logger.warning("LN7 canary sweep: %s", exc)


async def maybe_start_continuous_agent(app_state, db_pool) -> Any:
    """Feature-flagged start; returns agent or None."""
    from app.services.ln7_train_queue import continuous_enabled
    if not continuous_enabled():
        return None
    agent = Ln7ContinuousAgent(
        db_pool,
        interval_s=int(os.getenv("LN7_CONTINUOUS_INTERVAL_S", "300") or 300),
    )
    await agent.start()
    app_state.ln7_continuous_agent = agent
    return agent
