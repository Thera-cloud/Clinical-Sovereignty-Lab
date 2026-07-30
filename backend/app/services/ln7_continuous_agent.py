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

_MIN_PACK_OUTCOMES_DEFAULT = 3


class Ln7ContinuousAgent:
    def __init__(self, db_pool, *, interval_s: int = 300):
        self._db = db_pool
        self._interval = max(60, interval_s)
        self._task: Optional[asyncio.Task] = None
        self._stop = asyncio.Event()
        # G2 fix: revisions currently running an auto-triggered private-pack
        # bakeoff, so we never double-fire concurrent bakeoffs for the same
        # revision across cycles (bakeoffs can run longer than the 300s tick).
        self._bakeoff_inflight: set[str] = set()

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
                rid = r["revision_id"]
                await self._ensure_pack_outcomes(rid)
                result = await evaluate_canary(self._db, rid)
                logger.info(
                    "LN7 canary %s → %s",
                    rid,
                    result.get("action") or result.get("error"),
                )
                if result.get("action") == "await_ceo" and result.get("ok"):
                    try:
                        from app.services.ln7_revision import notify_revision_candidate

                        await notify_revision_candidate(
                            self._db, rid, force_ready=True
                        )
                    except Exception as nexc:
                        logger.warning("LN7 READY renotify: %s", nexc)
        except Exception as exc:
            logger.warning("LN7 canary sweep: %s", exc)

    async def _ensure_pack_outcomes(self, revision_id: str) -> None:
        """G2 fix: without this, a freshly-registered shadow revision sits in
        ln7_canary_state with zero ln7_coding_outcomes rows forever — nothing
        ever ran run_private_pack_bakeoff() for it, so evaluate_canary() keeps
        returning insufficient_tasks (0/3) until a human manually triggers a
        bakeoff via the API. Auto-fire the bakeoff here instead.
        """
        if not revision_id or revision_id in self._bakeoff_inflight:
            return
        min_n = int(
            os.getenv("LN7_CANARY_MIN_PACK_OUTCOMES", str(_MIN_PACK_OUTCOMES_DEFAULT))
            or _MIN_PACK_OUTCOMES_DEFAULT
        )
        try:
            async with self._db.acquire() as conn:
                n = await conn.fetchval(
                    """
                    SELECT COUNT(*) FROM ln7_coding_outcomes
                    WHERE revision_id = $1 AND generator = 'ln7'
                      AND (metrics_json->>'pack') IS NOT NULL
                    """,
                    revision_id,
                )
        except Exception as exc:
            logger.warning("LN7 pack-outcome count %s: %s", revision_id, exc)
            return
        if int(n or 0) >= min_n:
            return
        self._bakeoff_inflight.add(revision_id)
        logger.info(
            "LN7 continuous: auto-triggering private-pack bakeoff for %s (have=%s, need=%s)",
            revision_id, n, min_n,
        )
        asyncio.create_task(self._run_auto_bakeoff(revision_id))

    async def _run_auto_bakeoff(self, revision_id: str) -> None:
        try:
            from app.services.ln7_bakeoff_engine import run_private_pack_bakeoff

            result = await run_private_pack_bakeoff(
                self._db, revision_id=revision_id, mode="max",
            )
            pass_rate = (result.get("pass_rate") or {}) if isinstance(result, dict) else {}
            logger.info(
                "LN7 auto-bakeoff %s: ok=%s n=%s mean=%.2f",
                revision_id,
                result.get("ok") if isinstance(result, dict) else None,
                pass_rate.get("n"),
                float(pass_rate.get("mean") or 0.0),
            )
        except Exception as exc:
            logger.warning("LN7 auto-bakeoff %s failed: %s", revision_id, exc)
        finally:
            self._bakeoff_inflight.discard(revision_id)


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
