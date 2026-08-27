"""
LITTLE NATE — Database Maintenance Agent
Runs daily data hygiene: prunes stale rows from skyeye_activity and
skyeye_content_queue, records row counts and DB size to activity log,
and tracks backup freshness.

Also runs a weekly (gated) shadow confidence-weighting pass over
crystal_outcome_view — see _shadow_weighting_pass(). That pass only ever
INSERTs into crystal_confidence_shadow; it never UPDATEs
nate_intelligence_crystals.confidence (WIRE_WHAT_EXISTS Commit 4).

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
    # Thera-World research index cases (architecture / patent / Nate accuracy).
    "thera_world_index_case",
)

# QUANTUM-CRYSTAL-ARCH: WIRE_WHAT_EXISTS Commit 4 STEP 4 — shadow confidence
# weighting. This pass NEVER writes to nate_intelligence_crystals.confidence;
# it only INSERTs proposed deltas into crystal_confidence_shadow (migration
# 236) for review. Gated to run at most once per SHADOW_WEIGHTING_INTERVAL_DAYS
# using the table's own MAX(computed_at) — not in-memory state — so a process
# restart cannot cause it to run more often than intended.
SHADOW_WEIGHTING_INTERVAL_DAYS = 7
SHADOW_MIN_SAMPLE_SIZE = 5           # minimum outcome-linked recalls before proposing anything
SHADOW_MAX_ABS_DELTA = 0.02          # hard cap per WIRE_WHAT_EXISTS Commit 4 spec
SHADOW_DELTA_SCALE = 0.04            # avg_c_emo=0.5 -> 0 delta; 0.0/1.0 -> +/-0.02 (still clamped below)
# clinical/safety crystals are forced to 0 delta regardless of outcome signal.
# Domain taxonomy is the 7 canonical values from crystal-intelligence-integrity.mdc;
# 'clinical' and 'defense' are the two that carry clinical/safety weight.
SHADOW_FORCED_ZERO_DOMAINS = ("clinical", "defense")

# QUANTUM-CRYSTAL-ARCH: Agentic Phase 0 — proactive touch adaptation (restraint direct,
# assertiveness shadow-only). Gated by ENABLE_PROACTIVE_TOUCH_POLICY.
TOUCH_ADAPTATION_INTERVAL_DAYS = 1
TOUCH_IGNORE_STRETCH_THRESHOLD = 2
TOUCH_IGNORE_PAUSE_THRESHOLD = 3
TOUCH_INTERVAL_MULTIPLIER_CAP = 4.0


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
        shadow_proposals = await self._shadow_weighting_pass()
        touch_adaptations = await self._touch_adaptation_pass()
        retention_stats = await self._enforce_retention_policy()
        stats = await self._collect_stats()

        summary = (
            f"Pruned {pruned_activity} old activity rows ({ACTIVITY_RETENTION_DAYS}d retention), "
            f"{pruned_content} old content rows ({CONTENT_RETENTION_DAYS}d retention), "
            f"{expired_signups} expired pending signups, "
            f"{purged_trial_history} trial_history rows cleared ({TRIAL_HISTORY_RETENTION_DAYS}d), "
            f"{purged_flagged_text} flagged-turn texts purged ({TRIAL_FLAGGED_TEXT_RETENTION_DAYS}d), "
            f"{purged_lead_emails} trial lead emails purged ({TRIAL_LEAD_EMAIL_RETENTION_DAYS}d), "
            f"{sent_followups} trial follow-up emails sent, "
            f"{shadow_proposals} crystal confidence shadow proposals recorded "
            f"({SHADOW_WEIGHTING_INTERVAL_DAYS}d cadence, never applied). "
            f"{touch_adaptations} proactive touch adaptation proposals/shadow rows. "
            f"Retention: {retention_stats.get('summary', 'disabled')}. "
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

    async def _shadow_weighting_pass(self) -> int:
        """WIRE_WHAT_EXISTS Commit 4 STEP 4 — restraint-only shadow confidence
        weighting. Reads crystal_outcome_view (migration 236, STEP 3) and
        INSERTs proposed deltas into crystal_confidence_shadow. This method
        NEVER issues an UPDATE against nate_intelligence_crystals — that
        invariant is what backend/tests/test_shadow_weighting_no_update.py
        asserts by scanning this file's source.

        Gated to run at most once per SHADOW_WEIGHTING_INTERVAL_DAYS using
        MAX(computed_at) already stored in crystal_confidence_shadow, so the
        gate survives process restarts (no in-memory "last run" flag).

        Returns the number of shadow rows inserted this pass (0 if skipped
        by the weekly gate, if there is no outcome data yet, or on error).
        """
        try:
            async with self.db_pool.acquire() as conn:
                last_run = await conn.fetchval(
                    "SELECT MAX(computed_at) FROM crystal_confidence_shadow"
                )
                if last_run is not None:
                    age_days = (
                        datetime.now(timezone.utc) - last_run.replace(tzinfo=timezone.utc)
                    ).total_seconds() / 86400
                    if age_days < SHADOW_WEIGHTING_INTERVAL_DAYS:
                        return 0

                rows = await conn.fetch(f"""
                    SELECT
                        crystal_id,
                        MAX(crystal_domain) AS domain,
                        MAX(crystal_confidence) AS current_confidence,
                        COUNT(*) FILTER (WHERE c_emo IS NOT NULL) AS sample_size,
                        AVG(c_emo) FILTER (WHERE c_emo IS NOT NULL) AS avg_c_emo
                    FROM crystal_outcome_view
                    WHERE crystal_id IS NOT NULL
                    GROUP BY crystal_id
                    HAVING COUNT(*) FILTER (WHERE c_emo IS NOT NULL) >= {SHADOW_MIN_SAMPLE_SIZE}
                """)

                inserted = 0
                for row in rows:
                    domain = (row["domain"] or "general").lower()
                    avg_c_emo = float(row["avg_c_emo"]) if row["avg_c_emo"] is not None else None
                    sample_size = int(row["sample_size"])

                    if domain in SHADOW_FORCED_ZERO_DOMAINS:
                        delta = 0.0
                        reasoning = (
                            f"forced 0 delta — domain='{domain}' is clinical/safety "
                            f"(sample_size={sample_size}, avg_c_emo={avg_c_emo})"
                        )
                    elif avg_c_emo is None:
                        continue  # no outcome signal at all — nothing to propose
                    else:
                        raw_delta = (avg_c_emo - 0.5) * SHADOW_DELTA_SCALE
                        delta = max(-SHADOW_MAX_ABS_DELTA, min(SHADOW_MAX_ABS_DELTA, raw_delta))
                        reasoning = (
                            f"avg_c_emo={avg_c_emo:.4f} over {sample_size} outcome-linked "
                            f"recalls -> proposed delta {delta:+.4f} (cap +/-{SHADOW_MAX_ABS_DELTA})"
                        )

                    await conn.execute("""
                        INSERT INTO crystal_confidence_shadow
                            (crystal_id, domain, current_confidence, proposed_delta,
                             sample_size, avg_c_emo, reasoning, computed_at)
                        VALUES ($1, $2, $3, $4, $5, $6, $7, NOW())
                    """, row["crystal_id"], domain, row["current_confidence"], delta,
                        sample_size, avg_c_emo, reasoning)
                    inserted += 1

                return inserted
        except Exception as e:
            logger.warning("DatabaseMaintenanceAgent: shadow weighting pass failed: %s", e)
            return 0

    async def _touch_adaptation_pass(self) -> int:
        """Agentic Phase 0 — restraint applies to profile_data; assertiveness shadow-only."""
        import os

        if os.getenv("ENABLE_PROACTIVE_TOUCH_POLICY", "false").strip().lower() not in (
            "1",
            "true",
            "yes",
        ):
            return 0
        try:
            import json

            async with self.db_pool.acquire() as conn:
                last_run = await conn.fetchval(
                    "SELECT MAX(computed_at) FROM proactive_touch_adaptation_shadow"
                )
                if last_run is not None:
                    age_days = (
                        datetime.now(timezone.utc) - last_run.replace(tzinfo=timezone.utc)
                    ).total_seconds() / 86400
                    if age_days < TOUCH_ADAPTATION_INTERVAL_DAYS:
                        return 0

                rows = await conn.fetch("""
                    SELECT username, source_agent, outcome_class, COUNT(*) AS cnt
                    FROM proactive_touch_outcome_view
                    WHERE outcome_class IN ('responded', 'ignored', 'snoozed')
                    GROUP BY username, source_agent, outcome_class
                """)

                user_outcomes: dict = {}
                for row in rows:
                    uname = row["username"]
                    if not uname:
                        continue
                    key = (uname, row["source_agent"])
                    user_outcomes.setdefault(key, {"ignored": 0, "responded": 0})
                    user_outcomes[key][row["outcome_class"]] = int(row["cnt"])

                applied = 0
                for (uname, source), counts in user_outcomes.items():
                    ignored = counts.get("ignored", 0)
                    responded = counts.get("responded", 0)
                    urow = await conn.fetchrow(
                        "SELECT profile_data FROM users WHERE username = $1",
                        uname,
                    )
                    if not urow:
                        continue
                    pd = urow["profile_data"] or {}
                    if isinstance(pd, str):
                        try:
                            pd = json.loads(pd)
                        except Exception:
                            pd = {}
                    adaptation = dict(pd.get("proactive_touch_adaptation") or {})
                    changed = False

                    if ignored >= TOUCH_IGNORE_PAUSE_THRESHOLD:
                        from datetime import timedelta

                        adaptation["paused_until"] = (
                            datetime.now(timezone.utc) + timedelta(days=7)
                        ).isoformat()
                        changed = True
                    elif ignored >= TOUCH_IGNORE_STRETCH_THRESHOLD:
                        mult = float(adaptation.get("interval_multiplier") or 1.0)
                        mult = min(TOUCH_INTERVAL_MULTIPLIER_CAP, mult * 2.0)
                        adaptation["interval_multiplier"] = mult
                        adaptation["channel_ceiling"] = "in_app"
                        changed = True
                    elif responded > 0 and ignored == 0:
                        await conn.execute(
                            """
                            INSERT INTO proactive_touch_adaptation_shadow
                                (user_id, source, signal_type, proposed_change,
                                 sample_size, reasoning, computed_at)
                            VALUES ($1, $2, 'fast_response', $3::jsonb, $4, $5, NOW())
                            """,
                            uname,
                            source,
                            json.dumps({"suggest": "increase_cadence"}),
                            responded,
                            "Positive engagement — proposal only, never auto-applied",
                        )
                        applied += 1

                    if changed:
                        pd["proactive_touch_adaptation"] = adaptation
                        await conn.execute(
                            "UPDATE users SET profile_data = $2::jsonb WHERE username = $1",
                            uname,
                            json.dumps(pd),
                        )
                        applied += 1

                return applied
        except Exception as e:
            logger.warning("DatabaseMaintenanceAgent: touch adaptation pass failed: %s", e)
            return 0

    async def _enforce_retention_policy(self) -> dict:
        """Enforce the admin-configured `memory_retention_policy` on
        user-owned conversation data and write tombstones so Flutter
        clients can prune their local caches.

        Slice 1 of the Bee HIV+ privacy plan. Gated behind
        `ENABLE_RETENTION_ENFORCEMENT` so we can ship the code path in
        a disabled state and flip it on later.

        Slice B adds a cohort-aware DRY-RUN branch gated on
        ``ENABLE_RETENTION_DRYRUN`` which reports per-(table, cohort)
        deletion counts without touching data. When both flags are set,
        dry-run wins (safety-first).

        Currently prunes rows from `conversation_history` and
        `nevedal_metrics` older than the configured window. Rows are
        deleted in a single transaction with matching tombstone inserts
        so the operation is all-or-nothing. Uses a hard LIMIT per pass
        so a very old dataset can't monopolise the daily cycle.
        """
        try:
            from app.services.retention_policy import (
                get_retention_days,
                is_retention_dryrun_enabled,
                is_retention_enforcement_enabled,
            )
        except Exception as exc:
            logger.warning("retention: helper import failed: %s", exc)
            return {"summary": "disabled (import error)", "deleted": 0}

        dryrun = is_retention_dryrun_enabled()
        enforcement = is_retention_enforcement_enabled()

        # Slice B: dry-run wins when both are set. Safety-first.
        if dryrun:
            return await self._retention_dry_run_report()

        if not enforcement:
            return {"summary": "disabled (flag off)", "deleted": 0}

        # Cohort-scoped: Bee HIV+ uses 30d; non-cohort uses global policy.
        # Global "forever" (None) ⇒ non-cohort rows are never deleted.
        global_days = get_retention_days()
        STRICT_DAYS = 30
        deleted_total = 0
        per_table: dict[str, int] = {}
        targets = [
            ("conversation_history", "id::text", "user_id", "created_at"),
            ("nevedal_metrics", "id::text", "user_id", "created_at"),
        ]

        try:
            async with self.db_pool.acquire() as conn:
                cohort_ids = await self._retention_cohort_identifiers(
                    conn, "bee_hiv_plus"
                )
                for table, id_expr, user_col, ts_col in targets:
                    n_c = 0
                    n_n = 0
                    if cohort_ids:
                        n_c = await self._retention_delete_batch(
                            conn, table, id_expr, user_col, ts_col,
                            STRICT_DAYS, cohort_ids, invert=False,
                        )
                    if global_days is not None:
                        n_n = await self._retention_delete_batch(
                            conn, table, id_expr, user_col, ts_col,
                            global_days, cohort_ids, invert=True,
                        )
                    if n_c < 0 or n_n < 0:
                        per_table[table] = -1
                    else:
                        per_table[table] = n_c + n_n
                        deleted_total += n_c + n_n
        except Exception as exc:
            logger.warning("retention: enforcement pass failed: %s", exc)
            return {"summary": f"error: {exc}", "deleted": deleted_total}

        global_label = "forever" if global_days is None else f"{global_days}d"
        detail = ", ".join(f"{t}={n}" for t, n in per_table.items())
        return {
            "summary": (
                f"enforced cohort=30d global={global_label} — {detail}"
            ),
            "deleted": deleted_total,
            "per_table": per_table,
        }

    async def _retention_delete_batch(
        self, conn, table: str, id_expr: str, user_col: str, ts_col: str,
        days: int, cohort_ids: list, invert: bool,
    ) -> int:
        """Delete one (table × cohort-or-noncohort) batch + tombstones.

        ``invert=False``: only ``user_id`` in ``cohort_ids`` (strict 30d).
        ``invert=True``: everyone else, using the global window. Empty
        ``cohort_ids`` + invert means the whole table (all users non-cohort).
        ``invert=False`` + empty ids is a no-op.
        """
        if not days:
            return 0
        if not invert and not cohort_ids:
            return 0
        BATCH_LIMIT = 5000
        try:
            async with conn.transaction():
                if invert and cohort_ids:
                    rows = await conn.fetch(
                        f"""
                        SELECT {id_expr} AS row_id, {user_col} AS user_id
                        FROM {table}
                        WHERE {ts_col} < NOW() - ($1 || ' days')::interval
                          AND NOT ({user_col}::text = ANY($2::text[]))
                        LIMIT {BATCH_LIMIT}
                        """,
                        str(days),
                        cohort_ids,
                    )
                elif invert:
                    rows = await conn.fetch(
                        f"""
                        SELECT {id_expr} AS row_id, {user_col} AS user_id
                        FROM {table}
                        WHERE {ts_col} < NOW() - ($1 || ' days')::interval
                        LIMIT {BATCH_LIMIT}
                        """,
                        str(days),
                    )
                else:
                    rows = await conn.fetch(
                        f"""
                        SELECT {id_expr} AS row_id, {user_col} AS user_id
                        FROM {table}
                        WHERE {ts_col} < NOW() - ($1 || ' days')::interval
                          AND {user_col}::text = ANY($2::text[])
                        LIMIT {BATCH_LIMIT}
                        """,
                        str(days),
                        cohort_ids,
                    )
                if not rows:
                    return 0
                row_ids = [r["row_id"] for r in rows]
                await conn.execute(
                    f"DELETE FROM {table} WHERE {id_expr} = ANY($1::text[])",
                    row_ids,
                )
                await conn.executemany(
                    """
                    INSERT INTO data_tombstones
                        (user_id, table_name, row_id, reason)
                    VALUES ($1, $2, $3, 'retention_policy')
                    """,
                    [
                        (str(r["user_id"] or ""), table, str(r["row_id"]))
                        for r in rows
                    ],
                )
                return len(rows)
        except Exception as exc:
            logger.warning(
                "retention: table=%s invert=%s failed: %s", table, invert, exc
            )
            return -1

    # ------------------------------------------------------------------ #
    # Slice B: cohort-aware DRY-RUN report.                              #
    # ------------------------------------------------------------------ #
    async def _retention_dry_run_report(self) -> dict:
        """Cohort-aware retention dry-run.

        Reports what WOULD be deleted per (table × cohort) without
        touching data or emitting tombstones. Bee HIV+ cohort uses the
        strict 30-day window (retention_policy._STRICT_DEFAULT_DAYS).
        Non-cohort users use the admin-configured global policy; when
        global is "forever" they contribute 0 to the count.

        Never DELETEs. Never inserts into ``data_tombstones``. Safe to
        run on live production data before enforcement is flipped on.
        """
        try:
            from app.services.retention_policy import get_retention_days
        except Exception as exc:
            logger.warning("retention dry-run: helper import failed: %s", exc)
            return {"summary": f"dry-run error: {exc}", "would_delete": 0}

        global_days = get_retention_days()
        STRICT_DAYS = 30

        total_would_delete = 0
        per_table: dict[str, dict] = {}
        # (table, user_col, ts_col) — conversation_history.user_id is
        # text; nevedal_metrics.user_id is uuid. Always compare
        # user_col::text to ANY($::text[]).
        targets = [
            ("conversation_history", "user_id", "created_at"),
            ("nevedal_metrics", "user_id", "created_at"),
        ]

        try:
            async with self.db_pool.acquire() as conn:
                cohort_ids = await self._retention_cohort_identifiers(
                    conn, "bee_hiv_plus"
                )
                for table, user_col, ts_col in targets:
                    try:
                        row = await self._retention_count_would_delete(
                            conn, table, user_col, ts_col,
                            cohort_ids, global_days, STRICT_DAYS,
                        )
                        per_table[table] = row
                        total_would_delete += row["would_delete"]
                    except Exception as exc:
                        logger.warning(
                            "retention dry-run: table=%s failed: %s", table, exc
                        )
                        per_table[table] = {"error": str(exc), "would_delete": 0}
        except Exception as exc:
            logger.warning("retention dry-run: pass failed: %s", exc)
            return {
                "summary": f"dry-run error: {exc}",
                "would_delete": total_would_delete,
                "per_table": per_table,
            }

        detail = ", ".join(
            f"{t}(c={p.get('cohort_would', 0)},n={p.get('noncohort_would', 0)})"
            for t, p in per_table.items()
        )
        global_label = "forever" if global_days is None else f"{global_days}d"
        summary = (
            f"DRY-RUN (global={global_label}, cohort=30d) — "
            f"would_delete={total_would_delete} — {detail}"
        )
        return {
            "summary": summary,
            "dryrun": True,
            "would_delete": total_would_delete,
            "deleted": 0,
            "per_table": per_table,
            "policy_global_days": global_days,
            "policy_strict_days": STRICT_DAYS,
            "cohort_id_count": len(cohort_ids),
        }

    async def _retention_cohort_identifiers(
        self, conn, program_id: str
    ) -> list:
        """Return usernames, hardware_ids, and stringified UUIDs of
        users in the given cohort. Empty list if the ``program_id``
        column is missing (pre-414 schema) or no users match.

        ``conversation_history.user_id`` is text (username / hardware_id).
        ``nevedal_metrics.user_id`` is uuid. Callers resolve all three
        identifier shapes; SQL compares ``user_col::text = ANY($::text[])``.
        """
        try:
            rows = await conn.fetch(
                """
                SELECT username, hardware_id, id::text AS uid
                FROM users
                WHERE program_id = $1
                """,
                program_id,
            )
        except Exception as exc:
            logger.warning(
                "retention dry-run: cohort lookup failed (pre-414?): %s", exc
            )
            return []
        ids: set = set()
        for r in rows:
            for key in ("username", "hardware_id", "uid"):
                v = r[key]
                if v:
                    ids.add(str(v))
        return list(ids)

    async def _retention_count_would_delete(
        self, conn, table: str, user_col: str, ts_col: str,
        cohort_ids: list, global_days, strict_days: int,
    ) -> dict:
        """COUNT-only helper — never mutates."""
        cohort_would = 0
        if cohort_ids:
            row = await conn.fetchrow(
                f"""
                SELECT COUNT(*) AS c
                FROM {table}
                WHERE {ts_col} < NOW() - ($1 || ' days')::interval
                  AND {user_col}::text = ANY($2::text[])
                """,
                str(strict_days),
                cohort_ids,
            )
            cohort_would = int(row["c"] or 0) if row else 0

        noncohort_would = 0
        if global_days is not None:
            if cohort_ids:
                row = await conn.fetchrow(
                    f"""
                    SELECT COUNT(*) AS c
                    FROM {table}
                    WHERE {ts_col} < NOW() - ($1 || ' days')::interval
                      AND NOT ({user_col}::text = ANY($2::text[]))
                    """,
                    str(global_days),
                    cohort_ids,
                )
            else:
                row = await conn.fetchrow(
                    f"""
                    SELECT COUNT(*) AS c
                    FROM {table}
                    WHERE {ts_col} < NOW() - ($1 || ' days')::interval
                    """,
                    str(global_days),
                )
            noncohort_would = int(row["c"] or 0) if row else 0

        return {
            "would_delete": cohort_would + noncohort_would,
            "cohort_would": cohort_would,
            "noncohort_would": noncohort_would,
        }

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
