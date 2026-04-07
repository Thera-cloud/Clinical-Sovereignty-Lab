"""SSE Stage 5 — Layer 0 Orchestrator.

AsyncIOScheduler-based runtime that reads sse_cron_schedules and
registers APScheduler jobs for daily panels, weekly clips, and monthly recaps.
Follows the DripScheduler pattern exactly.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

logger = logging.getLogger(__name__)


class SSEOrchestrator:
    """Background scheduler for SSE delivery pipeline."""

    def __init__(self, db_pool):
        self.db_pool = db_pool
        self.scheduler = AsyncIOScheduler()
        self._semaphore = asyncio.Semaphore(1)

    async def start(self):
        """Load enabled cron schedules from DB and register APScheduler jobs."""
        schedules = []
        try:
            async with self.db_pool.acquire() as conn:
                schedules = await conn.fetch(
                    "SELECT schedule_id, storyboard_id, schedule_type, cron_expression "
                    "FROM sse_cron_schedules WHERE enabled = true"
                )
        except Exception as e:
            logger.warning("SSEOrchestrator: failed to load schedules: %s", e)

        dispatch = {
            "daily_panel": self._run_daily_panels,
            "weekly_clip": self._run_weekly_clips,
            "monthly_recap": self._run_monthly_recap,
        }

        for row in schedules:
            stype = row["schedule_type"]
            handler = dispatch.get(stype)
            if not handler:
                continue
            parts = row["cron_expression"].split()
            if len(parts) < 5:
                continue
            trigger = CronTrigger(
                minute=parts[0], hour=parts[1], day=parts[2],
                month=parts[3], day_of_week=parts[4],
            )
            job_id = f"sse_{stype}_{row['storyboard_id']}"
            self.scheduler.add_job(
                handler, trigger, args=[row["storyboard_id"]],
                id=job_id, name=f"SSE {stype} for {row['storyboard_id']}",
                replace_existing=True,
            )

        self.scheduler.add_job(
            self._heartbeat_check,
            IntervalTrigger(minutes=30),
            id="sse_heartbeat", name="SSE delivery heartbeat",
            replace_existing=True,
        )

        self.scheduler.add_job(
            self._run_journey_panels,
            CronTrigger(minute="15", hour="3"),
            id="sse_journey_panels", name="SSE Thera-World journey panels",
            replace_existing=True,
        )

        self.scheduler.add_job(
            self._run_age_up_check,
            CronTrigger(minute="30", hour="4"),
            id="sse_age_up_check", name="SSE age-up transition check",
            replace_existing=True,
        )

        if not self.scheduler.running:
            self.scheduler.start()
        logger.info("SSEOrchestrator: started with %d schedule(s) + heartbeat", len(schedules))

    async def reload(self):
        """Re-read schedules without restarting the scheduler."""
        self.scheduler.remove_all_jobs()
        await self.start()

    def shutdown(self):
        self.scheduler.shutdown(wait=False)
        logger.info("SSEOrchestrator: shut down")

    async def stop(self):
        self.shutdown()

    async def _run_daily_panels(self, storyboard_id: str):
        async with self._semaphore:
            try:
                from app.sse.foundation import delivery_runtime as dr
                result = await dr.generate_daily_panels(storyboard_id, self.db_pool)
                logger.info("SSE daily_panel %s: %d generated, %d failed",
                            storyboard_id, result.get("panels_generated", 0),
                            result.get("panels_failed", 0))
            except Exception as e:
                logger.error("SSE daily_panel %s error: %s", storyboard_id, e)

    async def _run_weekly_clips(self, storyboard_id: str):
        # TODO Phase 5: Select best 3 journey panels from week → Grok Video Extend from
        #   Frame → chain clips → upload to Cloudflare Stream → push notification to user.
        #   Include quest/mission panels if active. Family recap aggregates member panels.
        async with self._semaphore:
            try:
                from app.sse.foundation import delivery_runtime as dr
                result = await dr.generate_weekly_clips(storyboard_id, self.db_pool)
                logger.info("SSE weekly_clip %s: %d generated, %d failed",
                            storyboard_id, result.get("clips_generated", 0),
                            result.get("clips_failed", 0))
            except Exception as e:
                logger.error("SSE weekly_clip %s error: %s", storyboard_id, e)

    async def _run_monthly_recap(self, storyboard_id: str):
        # TODO Phase 5: Select best panels + weekly clips → narrative voiceover via Grok TTS →
        #   compose 3-min video → upload to Cloudflare Stream + R2 + IPFS hash.
        #   Family recap: aggregate family member panels into shared video.
        async with self._semaphore:
            try:
                from app.sse.foundation import delivery_runtime as dr
                result = await dr.generate_monthly_recap(storyboard_id, self.db_pool)
                logger.info("SSE monthly_recap %s: %d generated, %d fallback(s)",
                            storyboard_id, result.get("recaps_generated", 0),
                            result.get("fallbacks", 0))
            except Exception as e:
                logger.error("SSE monthly_recap %s error: %s", storyboard_id, e)

    async def _run_journey_panels(self):
        """Generate Thera-World journey panels for all active clients."""
        async with self._semaphore:
            ok = fail = 0
            try:
                from app.sse.thera_world_engine import generate_journey_panel
                async with self.db_pool.acquire() as conn:
                    rows = await conn.fetch(
                        "SELECT hardware_id FROM users "
                        "WHERE role='CLIENT' AND subscription_status IN ('ACTIVE','TRIAL_ACTIVE') "
                        "AND hardware_id IS NOT NULL AND hardware_id != ''")
                for r in rows:
                    try:
                        async with self.db_pool.acquire() as c2:
                            exists = await c2.fetchval(
                                "SELECT 1 FROM sse_panel_log WHERE user_id=$1 AND generated_at::date = CURRENT_DATE LIMIT 1",
                                r["hardware_id"])
                        if exists:
                            logger.info("Skipping %s — panel already exists today", r["hardware_id"])
                            continue
                        await generate_journey_panel(r["hardware_id"], self.db_pool)
                        ok += 1
                    except Exception as e:
                        fail += 1
                        logger.warning("Journey panel failed for %s: %s", r["hardware_id"], e)
                    await asyncio.sleep(8)
                logger.info("SSE journey panels: %d generated, %d failed", ok, fail)
            except Exception as e:
                logger.error("SSE journey panels batch error: %s", e)

    async def _run_age_up_check(self):
        """Detect family members turning 18 today — lift age gate, generate transition panel."""
        try:
            from app.sse.family_engine import generate_shared_event
            from app.sse.thera_world_engine import generate_age_transition_panel
            async with self.db_pool.acquire() as conn:
                turning_18 = await conn.fetch(
                    "SELECT user_id, family_id FROM family_members "
                    "WHERE age_gated = true AND date_of_birth IS NOT NULL "
                    "AND date_of_birth = CURRENT_DATE - INTERVAL '18 years'")
                for row in turning_18:
                    await conn.execute(
                        "UPDATE family_members SET age_gated = false, "
                        "age_transitioned_at = NOW() WHERE user_id = $1", row["user_id"])
                    await generate_age_transition_panel(row["user_id"], self.db_pool)
                    await generate_shared_event(row["family_id"], "age_transition",
                        {"user_id": row["user_id"], "age": 18}, self.db_pool)
                    logger.info("SSE age-up: %s turned 18, gate lifted", row["user_id"])
        except Exception as e:
            logger.warning("SSE age-up check error: %s", e)

    async def _heartbeat_check(self):
        """Check for generation gaps and write heartbeat record."""
        import uuid
        try:
            async with self.db_pool.acquire() as conn:
                gaps = await conn.fetch(
                    "SELECT eu.storyboard_id, "
                    "EXTRACT(EPOCH FROM NOW() - MAX(gl.generated_at)) / 3600 AS hours_since "
                    "FROM sse_enrolled_users eu "
                    "LEFT JOIN sse_delivery_generation_log gl "
                    "  ON gl.storyboard_id = eu.storyboard_id AND gl.user_id = eu.user_id "
                    "WHERE eu.status = 'active' "
                    "GROUP BY eu.storyboard_id "
                    "HAVING MAX(gl.generated_at) IS NULL "
                    "   OR EXTRACT(EPOCH FROM NOW() - MAX(gl.generated_at)) / 3600 > 25"
                )
                for g in gaps:
                    logger.warning("SSE heartbeat: storyboard %s has %d-hour gap",
                                   g["storyboard_id"], int(g["hours_since"] or 0))

                await conn.execute(
                    "INSERT INTO sse_delivery_heartbeat "
                    "(heartbeat_id, storyboards_checked, gaps_found, status) "
                    "VALUES ($1, $2, $3, $4)",
                    str(uuid.uuid4()),
                    len(gaps) + 1,
                    len(gaps),
                    "ok" if not gaps else "gaps_detected",
                )
        except Exception as e:
            logger.error("SSE heartbeat error: %s", e)
