"""
LITTLE NATE — Database Maintenance Agent
Runs daily data hygiene: prunes stale rows from skyeye_activity and
skyeye_content_queue, records row counts and DB size to activity log,
and tracks backup freshness.

Actual pg_dump backups run via host-level cron (not inside Docker).
This agent focuses on data pruning and size monitoring.

Loop interval: 24 hours
Stagger delay: 90 seconds
"""

import asyncio
import logging
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger("skyeye.db_maintenance")

ACTIVITY_RETENTION_DAYS = 90
CONTENT_RETENTION_DAYS = 60
# Public Trial Funnel retention (security-trial-retention-purge) — see
# .cursor/plans/public_trial_funnel_4200095c.plan.md P1 section. Raw IP is
# never stored for trial rows; these purges only trim stale conversation
# content and PII that has already served its one-time purpose.
TRIAL_HISTORY_RETENTION_DAYS = 30
TRIAL_FLAGGED_TEXT_RETENTION_DAYS = 30
TRIAL_LEAD_EMAIL_RETENTION_DAYS = 45
IMMUTABLE_TYPES = (
    "audit_log",
    "factual_grounding_redirect",
    "nate_accuracy_warning",
    # Sensitive Clinical Bridge v1.3 Phase 6 — clinician-authored sensitive
    # disclosures retained 7 years per migration 202 (sensitive_bridge_log
    # retained_until default). Protect mirrored skyeye_activity rows so the
    # daily prune cannot evict the audit trail before its retention window.
    "sensitive_bridge_log_event",
)


class DatabaseMaintenanceAgent:

    def __init__(self, db_pool, interval_seconds: int = 86400):
        self.db_pool = db_pool
        self.interval = interval_seconds
        self._task: Optional[asyncio.Task] = None
        self._running = False

    async def start(self):
        if self._task and not self._task.done():
            return
        self._running = True
        self._task = asyncio.create_task(self._run_loop())
        logger.info("DatabaseMaintenanceAgent started (interval=%ds)", self.interval)

    async def stop(self):
        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("DatabaseMaintenanceAgent stopped")

    async def _run_loop(self):
        await asyncio.sleep(90)
        while self._running:
            try:
                await self._cycle()
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.error("DatabaseMaintenanceAgent cycle failed: %s", e, exc_info=True)
            await asyncio.sleep(self.interval)

    async def _cycle(self):
        pruned_activity = await self._prune_activity()
        pruned_content = await self._prune_content()
        expired_signups = await self._expire_pending_signups()
        purged_trial_history = await self._purge_trial_history()
        purged_flagged_text = await self._purge_flagged_turn_text()
        purged_lead_emails = await self._purge_trial_lead_emails()
        sent_followups = await self._send_trial_followups()
        stats = await self._collect_stats()

        summary = (
            f"Pruned {pruned_activity} old activity rows ({ACTIVITY_RETENTION_DAYS}d retention), "
            f"{pruned_content} old content rows ({CONTENT_RETENTION_DAYS}d retention), "
            f"{expired_signups} expired pending signups, "
            f"{purged_trial_history} trial_history rows cleared ({TRIAL_HISTORY_RETENTION_DAYS}d), "
            f"{purged_flagged_text} flagged-turn texts purged ({TRIAL_FLAGGED_TEXT_RETENTION_DAYS}d), "
            f"{purged_lead_emails} trial lead emails purged ({TRIAL_LEAD_EMAIL_RETENTION_DAYS}d), "
            f"{sent_followups} trial follow-up emails sent. "
            f"DB size: {stats.get('db_size', 'unknown')}. "
            f"Tables: activity={stats.get('activity_rows', '?')}, "
            f"content_queue={stats.get('content_rows', '?')}, "
            f"tokens={stats.get('token_rows', '?')}, "
            f"users={stats.get('user_rows', '?')}."
        )

        await self._log_activity("system", "db_maintenance_cycle", summary, "success")
        logger.info("DatabaseMaintenanceAgent: %s", summary)

    async def _prune_activity(self) -> int:
        try:
            async with self.db_pool.acquire() as conn:
                immutable_clause = " AND ".join(
                    f"type != '{t}'" for t in IMMUTABLE_TYPES
                )
                result = await conn.execute(f"""
                    DELETE FROM skyeye_activity
                    WHERE created_at < NOW() - INTERVAL '{ACTIVITY_RETENTION_DAYS} days'
                      AND {immutable_clause}
                """)
            return int(result.split()[-1]) if result else 0
        except Exception as e:
            logger.error("DatabaseMaintenanceAgent: activity prune failed: %s", e)
            return 0

    async def _prune_content(self) -> int:
        try:
            async with self.db_pool.acquire() as conn:
                result = await conn.execute(f"""
                    DELETE FROM skyeye_content_queue
                    WHERE status IN ('archived', 'posted')
                      AND updated_at < NOW() - INTERVAL '{CONTENT_RETENTION_DAYS} days'
                """)
            return int(result.split()[-1]) if result else 0
        except Exception as e:
            logger.error("DatabaseMaintenanceAgent: content prune failed: %s", e)
            return 0

    async def _expire_pending_signups(self) -> int:
        try:
            async with self.db_pool.acquire() as conn:
                result = await conn.execute(
                    "UPDATE pending_signups SET status='expired' "
                    "WHERE status='pending' AND expires_at < NOW()"
                )
            return int(result.split()[-1]) if result else 0
        except Exception as e:
            logger.warning("DatabaseMaintenanceAgent: pending_signups expire failed: %s", e)
            return 0

    async def _purge_trial_history(self) -> int:
        """security-trial-retention-purge (1/3): clear stale trial conversation
        content for fingerprints that never converted. Only trims
        `trial_history` — `converted`, `trial_started_at`, `converted_at`,
        and `device_uuid_hash` are kept for funnel analytics."""
        try:
            async with self.db_pool.acquire() as conn:
                result = await conn.execute(f"""
                    UPDATE public_summon_usage
                    SET trial_history = '[]'::jsonb
                    WHERE converted = FALSE
                      AND trial_started_at IS NOT NULL
                      AND trial_started_at < NOW() - INTERVAL '{TRIAL_HISTORY_RETENTION_DAYS} days'
                      AND trial_history IS DISTINCT FROM '[]'::jsonb
                """)
            return int(result.split()[-1]) if result else 0
        except Exception as e:
            logger.warning("DatabaseMaintenanceAgent: trial_history purge failed: %s", e)
            return 0

    async def _purge_flagged_turn_text(self) -> int:
        """security-trial-retention-purge (2/3): drop raw flagged-turn text
        (may contain crisis content, P0.1) after 30 days. fp_hash, direction,
        reason, and created_at survive indefinitely for jailbreak-regression
        baselines and admin review trends."""
        try:
            async with self.db_pool.acquire() as conn:
                result = await conn.execute(f"""
                    UPDATE public_trial_flagged_turns
                    SET text = NULL
                    WHERE created_at < NOW() - INTERVAL '{TRIAL_FLAGGED_TEXT_RETENTION_DAYS} days'
                      AND text IS NOT NULL
                """)
            return int(result.split()[-1]) if result else 0
        except Exception as e:
            logger.warning("DatabaseMaintenanceAgent: flagged-turn text purge failed: %s", e)
            return 0

    async def _purge_trial_lead_emails(self) -> int:
        """security-trial-retention-purge (3/3): purge the raw inbox address
        from public_trial_leads after 45 days regardless of converted status
        — a converted lead's email already lives on the users row, and an
        unconverted lead has had its one signup + one follow-up email by
        then. fp_hash/device_uuid_hash/token_hash/timestamps survive for
        Phase 4 funnel analytics."""
        try:
            async with self.db_pool.acquire() as conn:
                result = await conn.execute(f"""
                    UPDATE public_trial_leads
                    SET email = NULL
                    WHERE created_at < NOW() - INTERVAL '{TRIAL_LEAD_EMAIL_RETENTION_DAYS} days'
                      AND email IS NOT NULL
                """)
            return int(result.split()[-1]) if result else 0
        except Exception as e:
            logger.warning("DatabaseMaintenanceAgent: trial lead email purge failed: %s", e)
            return 0

    async def _send_trial_followups(self) -> int:
        """trial-email-reengagement: exactly one re-engagement email per
        unconverted, non-unsubscribed lead. Logic lives in
        public_trial_gate.py alongside the rest of the lead/token handling;
        this is just the daily-cycle trigger point."""
        try:
            from app.services.public_trial_gate import run_trial_followup_cycle
            return await run_trial_followup_cycle()
        except Exception as e:
            logger.warning("DatabaseMaintenanceAgent: trial follow-up cycle failed: %s", e)
            return 0

    async def _collect_stats(self) -> dict:
        stats = {}
        try:
            async with self.db_pool.acquire() as conn:
                row = await conn.fetchrow(
                    "SELECT pg_size_pretty(pg_database_size(current_database())) AS s"
                )
                stats["db_size"] = row["s"] if row else "unknown"

                for table, key in [
                    ("skyeye_activity", "activity_rows"),
                    ("skyeye_content_queue", "content_rows"),
                    ("skyeye_platform_tokens", "token_rows"),
                    ("users", "user_rows"),
                ]:
                    try:
                        row = await conn.fetchrow(f"SELECT COUNT(*) AS c FROM {table}")
                        stats[key] = row["c"] if row else 0
                    except Exception:
                        stats[key] = "?"
        except Exception as e:
            logger.error("DatabaseMaintenanceAgent: stats collection failed: %s", e)
        return stats

    async def _log_activity(self, platform: str, activity_type: str,
                            content: str, severity: str = "info"):
        try:
            async with self.db_pool.acquire() as conn:
                await conn.execute("""
                    INSERT INTO skyeye_activity (platform, type, content, severity, created_at)
                    VALUES ($1, $2, $3, $4, NOW())
                """, platform, activity_type, content, severity)
        except Exception:
            pass
