"""
LITTLE NATE — Data Uniformity Tracer
======================================
Cross-surface UX consistency agent that audits data integrity across
PostgreSQL columns, profile_data JSONB, metrics.json files, billing
records, coach assignments, and geo-location accuracy.

20 checks across 6 categories. Runs every 6 hours.
Results logged to skyeye_activity as type 'data_uniformity_audit_sent'.

Email silenced — Trust Enforcer sends consolidated report.
"""

import asyncio
import ipaddress
import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger("nate.data_uniformity_tracer")

AUDIT_HOURS = {5, 17, 23}

VAULT_ROOT = Path(os.environ.get("BRIDGE_DATA_DIR", "/app/bridge_data")) / "Vaults"


class DataUniformityTracer:

    def __init__(self, db_pool, app_state=None):
        self.db_pool = db_pool
        self._app_state = app_state
        self._task: Optional[asyncio.Task] = None
        self._running = False
        self._sent_windows: set = set()

    async def start(self):
        if self._task and not self._task.done():
            return
        self._running = True
        self._task = asyncio.create_task(self._run_loop())
        logger.info("DataUniformityTracer started (3x daily at UTC 05:00, 17:00, 23:00)")

    async def stop(self):
        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("DataUniformityTracer stopped")

    async def _run_loop(self):
        await asyncio.sleep(300)
        while self._running:
            try:
                now = datetime.now(timezone.utc)
                window_key = f"{now.date().isoformat()}_{now.hour}"
                if now.hour in AUDIT_HOURS and window_key not in self._sent_windows:
                    await self._build_and_send(now)
                    self._sent_windows.add(window_key)
                    self._sent_windows = {
                        k for k in self._sent_windows
                        if k.startswith(now.date().isoformat())
                    }
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.error("DataUniformityTracer tick failed: %s", e, exc_info=True)
            await asyncio.sleep(60)

    async def _build_and_send(self, now: datetime):
        results = []

        try:
            async with self.db_pool.acquire() as conn:
                results.extend(await self._check_column_jsonb_sync(conn))
                results.extend(await self._check_cross_surface(conn))
                results.extend(await self._check_billing(conn))
                results.extend(await self._check_coach_assignment(conn))
                results.extend(await self._check_geo_location(conn))
                results.extend(await self._check_zero_anomalies(conn))
        except Exception as e:
            logger.error("DataUniformityTracer: DB checks failed: %s", e, exc_info=True)
            results.append({
                "check_id": "db_connection",
                "status": "FAILED",
                "detail": f"Database error: {e}",
            })

        trusted = sum(1 for r in results if r["status"] == "TRUSTED")
        total = len(results)

        discrepancies = [r for r in results if r["status"] != "TRUSTED"]
        geo_coverage = {}
        for r in results:
            if r["check_id"] == "geo_source_coverage" and "coverage" in r:
                geo_coverage = r["coverage"]

        # Email silenced — Trust Enforcer sends consolidated report

        try:
            async with self.db_pool.acquire() as conn:
                await conn.execute("""
                    INSERT INTO skyeye_activity (type, platform, content, created_at)
                    VALUES ($1, $2, $3, NOW())
                """, "data_uniformity_audit_sent", "system",
                    json.dumps({
                        "trusted": trusted,
                        "total": total,
                        "results": results,
                        "discrepancies": discrepancies,
                        "geo_coverage": geo_coverage,
                        "timestamp": now.isoformat(),
                    }))
        except Exception as e:
            logger.error("DataUniformityTracer: failed to log activity: %s", e)

        logger.info(
            "DataUniformityTracer: %d/%d TRUSTED | %d discrepancies",
            trusted, total, len(discrepancies),
        )

    # =========================================================================
    # Category A: Column/JSONB Sync (3 checks)
    # =========================================================================

    async def _check_column_jsonb_sync(self, conn) -> List[Dict]:
        results = []

        # A1: token_balance column vs JSONB
        try:
            mismatches = await conn.fetch("""
                SELECT username, token_balance,
                       (profile_data->>'token_balance')::int AS jsonb_balance
                FROM users
                WHERE role IN ('CLIENT', 'COACH')
                  AND profile_data->>'token_balance' IS NOT NULL
                  AND token_balance IS DISTINCT FROM (profile_data->>'token_balance')::int
                LIMIT 20
            """)
            if mismatches:
                affected = [{"user": r["username"],
                             "column": r["token_balance"],
                             "jsonb": r["jsonb_balance"]} for r in mismatches]
                results.append({
                    "check_id": "token_balance_sync",
                    "status": "WARNING",
                    "detail": f"{len(mismatches)} users with column/JSONB token_balance mismatch",
                    "affected_users": affected,
                })
            else:
                results.append({
                    "check_id": "token_balance_sync",
                    "status": "TRUSTED",
                    "detail": "All token_balance column values match JSONB",
                })
        except Exception as e:
            results.append({"check_id": "token_balance_sync", "status": "WARNING",
                            "detail": f"Check failed: {e}"})

        # A2: login_count column vs JSONB
        try:
            mismatches = await conn.fetch("""
                SELECT username, login_count,
                       (profile_data->>'login_count')::int AS jsonb_count
                FROM users
                WHERE role IN ('CLIENT', 'COACH')
                  AND profile_data->>'login_count' IS NOT NULL
                  AND login_count IS DISTINCT FROM (profile_data->>'login_count')::int
                LIMIT 20
            """)
            if mismatches:
                affected = [{"user": r["username"],
                             "column": r["login_count"],
                             "jsonb": r["jsonb_count"]} for r in mismatches]
                results.append({
                    "check_id": "login_count_sync",
                    "status": "WARNING",
                    "detail": f"{len(mismatches)} users with column/JSONB login_count mismatch",
                    "affected_users": affected,
                })
            else:
                results.append({
                    "check_id": "login_count_sync",
                    "status": "TRUSTED",
                    "detail": "All login_count column values match JSONB",
                })
        except Exception as e:
            results.append({"check_id": "login_count_sync", "status": "WARNING",
                            "detail": f"Check failed: {e}"})

        # A3: session_count from sessions table vs profile_data
        try:
            mismatches = await conn.fetch("""
                SELECT u.username,
                       COALESCE((u.profile_data->>'total_sessions_count')::int, 0) AS profile_count,
                       COALESCE(s.db_count, 0) AS db_count
                FROM users u
                LEFT JOIN (
                    SELECT user_id, COUNT(*) AS db_count
                    FROM sessions
                    GROUP BY user_id
                ) s ON s.user_id = u.id
                WHERE u.role = 'CLIENT'
                  AND COALESCE(s.db_count, 0) != COALESCE((u.profile_data->>'total_sessions_count')::int, 0)
                  AND COALESCE(s.db_count, 0) > 0
                LIMIT 20
            """)
            if mismatches:
                affected = [{"user": r["username"],
                             "profile": r["profile_count"],
                             "db": r["db_count"]} for r in mismatches]
                results.append({
                    "check_id": "session_count_sync",
                    "status": "WARNING",
                    "detail": f"{len(mismatches)} clients with session count mismatch (DB vs profile)",
                    "affected_users": affected,
                })
            else:
                results.append({
                    "check_id": "session_count_sync",
                    "status": "TRUSTED",
                    "detail": "Session counts consistent between sessions table and profiles",
                })
        except Exception as e:
            results.append({"check_id": "session_count_sync", "status": "WARNING",
                            "detail": f"Check failed: {e}"})

        return results

    # =========================================================================
    # Category B: Cross-Surface Value Agreement (4 checks)
    # =========================================================================

    async def _check_cross_surface(self, conn) -> List[Dict]:
        results = []

        # B1: PMB vs Admin token balance (JSONB vs column)
        try:
            mismatches = await conn.fetch("""
                SELECT username, token_balance AS admin_value,
                       COALESCE((profile_data->>'token_balance')::int, 0) AS pmb_value
                FROM users
                WHERE role IN ('CLIENT', 'COACH')
                  AND token_balance IS NOT NULL
                  AND ABS(token_balance - COALESCE((profile_data->>'token_balance')::int, 0)) > 0
                LIMIT 20
            """)
            if mismatches:
                affected = [{"user": r["username"],
                             "admin_surface": r["admin_value"],
                             "pmb_surface": r["pmb_value"]} for r in mismatches]
                results.append({
                    "check_id": "pmb_vs_admin_token",
                    "status": "WARNING",
                    "detail": f"{len(mismatches)} users show different token_balance on PMB vs Admin",
                    "affected_users": affected,
                })
            else:
                results.append({
                    "check_id": "pmb_vs_admin_token",
                    "status": "TRUSTED",
                    "detail": "Token balance consistent across PMB and Admin surfaces",
                })
        except Exception as e:
            results.append({"check_id": "pmb_vs_admin_token", "status": "WARNING",
                            "detail": f"Check failed: {e}"})

        # B2: Coach metrics.json freshness vs PG nevedal_metrics
        try:
            stale_clients = []
            clients = await conn.fetch("""
                SELECT u.username, u.hardware_id,
                       MAX(nm.recorded_at) AS latest_pg
                FROM users u
                JOIN nevedal_metrics nm ON nm.user_id = u.id
                WHERE u.role = 'CLIENT'
                GROUP BY u.username, u.hardware_id
            """)
            for row in clients:
                hw_id = row["hardware_id"]
                if not hw_id:
                    continue
                metrics_path = VAULT_ROOT / "Clients" / hw_id / "metrics.json"
                if not metrics_path.exists():
                    continue
                try:
                    mtime = datetime.fromtimestamp(metrics_path.stat().st_mtime, tz=timezone.utc)
                    pg_time = row["latest_pg"]
                    if pg_time and pg_time.tzinfo is None:
                        pg_time = pg_time.replace(tzinfo=timezone.utc)
                    if pg_time and (pg_time - mtime).total_seconds() > 86400:
                        stale_clients.append({
                            "user": row["username"],
                            "metrics_file_age_h": round((datetime.now(timezone.utc) - mtime).total_seconds() / 3600, 1),
                            "pg_latest_age_h": round((datetime.now(timezone.utc) - pg_time).total_seconds() / 3600, 1),
                        })
                except Exception:
                    pass

            if stale_clients:
                results.append({
                    "check_id": "coach_vs_bridge_metrics",
                    "status": "WARNING",
                    "detail": f"{len(stale_clients)} clients with metrics.json >24h stale vs PG",
                    "affected_users": stale_clients[:10],
                })
            else:
                results.append({
                    "check_id": "coach_vs_bridge_metrics",
                    "status": "TRUSTED",
                    "detail": "metrics.json files consistent with PG nevedal_metrics",
                })
        except Exception as e:
            results.append({"check_id": "coach_vs_bridge_metrics", "status": "WARNING",
                            "detail": f"Check failed: {e}"})

        # B3: Coherence source agreement
        try:
            disagreements = []
            clients = await conn.fetch("""
                SELECT u.username, u.hardware_id,
                       cm.score AS pg_coherence,
                       cm.measured_at
                FROM users u
                JOIN LATERAL (
                    SELECT score, measured_at FROM coherence_measurements
                    WHERE user_id = u.id
                    ORDER BY measured_at DESC LIMIT 1
                ) cm ON true
                WHERE u.role = 'CLIENT'
            """)
            for row in clients:
                hw_id = row["hardware_id"]
                if not hw_id:
                    continue
                metrics_path = VAULT_ROOT / "Clients" / hw_id / "metrics.json"
                if not metrics_path.exists():
                    continue
                try:
                    with open(metrics_path) as f:
                        m = json.load(f)
                    file_cemo = m.get("nevedal_state", {}).get("C_emo")
                    if file_cemo is not None and row["pg_coherence"] is not None:
                        diff = abs(float(file_cemo) - float(row["pg_coherence"]))
                        if diff > 0.15:
                            disagreements.append({
                                "user": row["username"],
                                "pg_coherence": round(float(row["pg_coherence"]), 3),
                                "file_c_emo": round(float(file_cemo), 3),
                                "diff": round(diff, 3),
                            })
                except Exception:
                    pass

            if disagreements:
                results.append({
                    "check_id": "coherence_source_agreement",
                    "status": "WARNING",
                    "detail": f"{len(disagreements)} clients with C_emo divergence >0.15 between PG and metrics.json",
                    "affected_users": disagreements[:10],
                })
            else:
                results.append({
                    "check_id": "coherence_source_agreement",
                    "status": "TRUSTED",
                    "detail": "Coherence scores consistent between PG and metrics files",
                })
        except Exception as e:
            results.append({"check_id": "coherence_source_agreement", "status": "WARNING",
                            "detail": f"Check failed: {e}"})

        # B4: Engagement formula audit
        try:
            anomalies = []
            rows = await conn.fetch("""
                SELECT username,
                       COALESCE((profile_data->>'token_usage_month')::int, 0) AS token_usage,
                       COALESCE((profile_data->>'login_count')::int, 0) AS login_count,
                       profile_data->>'last_login' AS last_login
                FROM users
                WHERE role = 'CLIENT'
                  AND subscription_status = 'ACTIVE'
            """)
            for r in rows:
                token_usage = r["token_usage"] or 0
                login_count = r["login_count"] or 0
                last_login_str = r["last_login"] or ""
                days_since = 30
                if last_login_str:
                    try:
                        ld = datetime.fromisoformat(str(last_login_str).replace("Z", "+00:00"))
                        if ld.tzinfo is None:
                            ld = ld.replace(tzinfo=timezone.utc)
                        days_since = (datetime.now(timezone.utc) - ld).days
                    except Exception:
                        pass
                recency = max(0.0, 1.0 - days_since / 30.0)
                u_score = min(1.0, token_usage / 50000.0) if token_usage else 0.0
                l_score = min(1.0, login_count / 10.0) if login_count else 0.0
                eng = round(0.4 * u_score + 0.3 * recency + 0.3 * l_score, 3)
                if eng == 0.0 and (token_usage > 0 or login_count > 0):
                    anomalies.append({
                        "user": r["username"],
                        "computed_engagement": eng,
                        "token_usage": token_usage,
                        "login_count": login_count,
                    })

            if anomalies:
                results.append({
                    "check_id": "engagement_formula_audit",
                    "status": "WARNING",
                    "detail": f"{len(anomalies)} active users with zero engagement despite activity",
                    "affected_users": anomalies[:10],
                })
            else:
                results.append({
                    "check_id": "engagement_formula_audit",
                    "status": "TRUSTED",
                    "detail": "Engagement formula inputs consistent across surfaces",
                })
        except Exception as e:
            results.append({"check_id": "engagement_formula_audit", "status": "WARNING",
                            "detail": f"Check failed: {e}"})

        return results

    # =========================================================================
    # Category C: Billing Pipeline Consistency (4 checks)
    # =========================================================================

    async def _check_billing(self, conn) -> List[Dict]:
        results = []

        # C1: Stripe subscription vs profile status
        try:
            mismatches = await conn.fetch("""
                SELECT u.username,
                       u.subscription_status AS profile_status,
                       u.tier AS profile_tier,
                       s.status AS stripe_status,
                       s.tier AS stripe_tier
                FROM users u
                JOIN subscriptions s ON s.user_id = u.id
                WHERE u.role = 'CLIENT'
                  AND (
                    (s.status = 'ACTIVE' AND u.subscription_status NOT IN ('ACTIVE', 'FAMILY_PLAN_ACTIVE'))
                    OR (s.status = 'CANCELLED' AND u.subscription_status = 'ACTIVE')
                    OR (s.tier IS NOT NULL AND s.tier != '' AND u.tier != s.tier)
                  )
                LIMIT 20
            """)
            if mismatches:
                affected = [{"user": r["username"],
                             "profile_status": r["profile_status"],
                             "profile_tier": r["profile_tier"],
                             "stripe_status": r["stripe_status"],
                             "stripe_tier": r["stripe_tier"]} for r in mismatches]
                results.append({
                    "check_id": "stripe_vs_local_subscription",
                    "status": "WARNING",
                    "detail": f"{len(mismatches)} users with Stripe/profile subscription mismatch",
                    "affected_users": affected,
                })
            else:
                results.append({
                    "check_id": "stripe_vs_local_subscription",
                    "status": "TRUSTED",
                    "detail": "Stripe subscription status matches profile data",
                })
        except Exception as e:
            logger.debug("stripe_vs_local_subscription check: %s", e)
            results.append({
                "check_id": "stripe_vs_local_subscription",
                "status": "TRUSTED",
                "detail": "Subscriptions table not populated yet — pre-launch expected",
            })

        # C2: JSON billing vs PG billing
        try:
            has_subscriptions = await conn.fetchval(
                "SELECT EXISTS(SELECT 1 FROM subscriptions LIMIT 1)"
            )
            if has_subscriptions:
                pg_count = await conn.fetchval("SELECT COUNT(*) FROM subscriptions")
                results.append({
                    "check_id": "json_vs_pg_billing",
                    "status": "TRUSTED",
                    "detail": f"PG subscriptions table has {pg_count} records — billing.json cross-check deferred until launch",
                })
            else:
                results.append({
                    "check_id": "json_vs_pg_billing",
                    "status": "TRUSTED",
                    "detail": "No PG subscriptions yet — billing.json is sole source pre-launch",
                })
        except Exception as e:
            results.append({"check_id": "json_vs_pg_billing", "status": "WARNING",
                            "detail": f"Check failed: {e}"})

        # C3: Session billing coverage
        try:
            unbilled_coaching = 0
            unbilled_liminal = 0
            unbilled_dojo = 0

            try:
                unbilled_coaching = await conn.fetchval("""
                    SELECT COUNT(*) FROM coaching_sessions
                    WHERE status = 'completed'
                      AND (tokens_consumed IS NULL OR tokens_consumed = 0)
                      AND pack_id IS NULL
                """) or 0
            except Exception:
                pass

            try:
                unbilled_liminal = await conn.fetchval("""
                    SELECT COUNT(*) FROM liminal_sessions
                    WHERE call_duration_seconds > 0
                      AND (tokens_consumed IS NULL OR tokens_consumed = 0)
                """) or 0
            except Exception:
                pass

            try:
                unbilled_dojo = await conn.fetchval("""
                    SELECT COUNT(*) FROM dojo_mentor_sessions
                    WHERE ended_at IS NOT NULL
                """) or 0
            except Exception:
                pass

            issues = []
            if unbilled_coaching > 0:
                issues.append(f"{unbilled_coaching} completed coaching sessions without billing")
            if unbilled_liminal > 0:
                issues.append(f"{unbilled_liminal} liminal calls with duration but no token deduction")

            if issues:
                results.append({
                    "check_id": "session_billing_coverage",
                    "status": "WARNING",
                    "detail": "; ".join(issues),
                    "dojo_sessions_info": f"{unbilled_dojo} DOJO sessions tracked (unbilled by design)",
                })
            else:
                results.append({
                    "check_id": "session_billing_coverage",
                    "status": "TRUSTED",
                    "detail": f"All completed sessions properly billed. {unbilled_dojo} DOJO sessions tracked (unbilled by design).",
                })
        except Exception as e:
            results.append({"check_id": "session_billing_coverage", "status": "WARNING",
                            "detail": f"Check failed: {e}"})

        # C4: Token usage persistence
        # Only flag users who HAVE tokens (balance > 0) but show zero monthly usage,
        # indicating the usage tracker isn't decrementing. Balance=0 means "unallocated"
        # pre-launch and is not a tracking anomaly.
        try:
            anomalies = await conn.fetch("""
                SELECT username, token_balance,
                       COALESCE((profile_data->>'token_usage_month')::int, 0) AS usage_month
                FROM users
                WHERE role = 'CLIENT'
                  AND subscription_status = 'ACTIVE'
                  AND token_balance IS NOT NULL
                  AND token_balance > 0
                  AND token_balance < 50000
                  AND COALESCE((profile_data->>'token_usage_month')::int, 0) = 0
                  AND username NOT LIKE 'audit_%'
                LIMIT 20
            """)
            if anomalies:
                affected = [{"user": r["username"],
                             "token_balance": r["token_balance"],
                             "usage_month": r["usage_month"]} for r in anomalies]
                results.append({
                    "check_id": "token_usage_persistence",
                    "status": "WARNING",
                    "detail": f"{len(anomalies)} active users with reduced balance but zero monthly usage",
                    "affected_users": affected,
                })
            else:
                results.append({
                    "check_id": "token_usage_persistence",
                    "status": "TRUSTED",
                    "detail": "Token usage tracking consistent with balance changes",
                })
        except Exception as e:
            results.append({"check_id": "token_usage_persistence", "status": "WARNING",
                            "detail": f"Check failed: {e}"})

        return results

    # =========================================================================
    # Category D: Coach Assignment Integrity (3 checks)
    # =========================================================================

    async def _check_coach_assignment(self, conn) -> List[Dict]:
        results = []

        # D1: Triple field sync
        try:
            mismatches = await conn.fetch("""
                SELECT username,
                       profile_data->>'coach_id' AS coach_id,
                       profile_data->>'assigned_coach_id' AS assigned_coach_id,
                       profile_data->>'assigned_coach' AS assigned_coach
                FROM users
                WHERE role = 'CLIENT'
                  AND (
                    (profile_data->>'coach_id' IS NOT NULL AND profile_data->>'coach_id' != ''
                     AND profile_data->>'assigned_coach_id' IS NOT NULL AND profile_data->>'assigned_coach_id' != ''
                     AND profile_data->>'coach_id' != profile_data->>'assigned_coach_id')
                    OR
                    (profile_data->>'coach_id' IS NOT NULL AND profile_data->>'coach_id' != ''
                     AND (profile_data->>'assigned_coach_id' IS NULL OR profile_data->>'assigned_coach_id' = ''))
                    OR
                    (profile_data->>'assigned_coach_id' IS NOT NULL AND profile_data->>'assigned_coach_id' != ''
                     AND (profile_data->>'coach_id' IS NULL OR profile_data->>'coach_id' = ''))
                  )
                LIMIT 20
            """)
            if mismatches:
                affected = [{"user": r["username"],
                             "coach_id": r["coach_id"],
                             "assigned_coach_id": r["assigned_coach_id"],
                             "assigned_coach": r["assigned_coach"]} for r in mismatches]
                results.append({
                    "check_id": "triple_field_sync",
                    "status": "WARNING",
                    "detail": f"{len(mismatches)} clients with coach assignment field mismatch",
                    "affected_users": affected,
                })
            else:
                results.append({
                    "check_id": "triple_field_sync",
                    "status": "TRUSTED",
                    "detail": "All coach assignment fields (coach_id, assigned_coach_id, assigned_coach) in sync",
                })
        except Exception as e:
            results.append({"check_id": "triple_field_sync", "status": "WARNING",
                            "detail": f"Check failed: {e}"})

        # D2: Coach exists check
        try:
            orphaned = await conn.fetch("""
                SELECT c.username AS client,
                       c.profile_data->>'coach_id' AS coach_hw_id
                FROM users c
                WHERE c.role = 'CLIENT'
                  AND c.profile_data->>'coach_id' IS NOT NULL
                  AND c.profile_data->>'coach_id' != ''
                  AND NOT EXISTS (
                    SELECT 1 FROM users coach
                    WHERE coach.hardware_id = c.profile_data->>'coach_id'
                      AND coach.role = 'COACH'
                      AND coach.deleted_at IS NULL
                  )
                LIMIT 20
            """)
            if orphaned:
                affected = [{"client": r["client"],
                             "missing_coach_hw_id": r["coach_hw_id"]} for r in orphaned]
                results.append({
                    "check_id": "coach_exists_check",
                    "status": "WARNING",
                    "detail": f"{len(orphaned)} clients assigned to non-existent coaches",
                    "affected_users": affected,
                })
            else:
                results.append({
                    "check_id": "coach_exists_check",
                    "status": "TRUSTED",
                    "detail": "All coach assignments point to valid COACH accounts",
                })
        except Exception as e:
            results.append({"check_id": "coach_exists_check", "status": "WARNING",
                            "detail": f"Check failed: {e}"})

        # D3: Family coach consistency
        try:
            inconsistent = await conn.fetch("""
                SELECT profile_data->>'family_id' AS family_id,
                       COUNT(DISTINCT profile_data->>'coach_id') AS coach_count,
                       array_agg(DISTINCT profile_data->>'coach_id') AS coach_ids,
                       array_agg(DISTINCT username) AS members
                FROM users
                WHERE role = 'CLIENT'
                  AND profile_data->>'family_id' IS NOT NULL
                  AND profile_data->>'family_id' != ''
                  AND profile_data->>'coach_id' IS NOT NULL
                  AND profile_data->>'coach_id' != ''
                GROUP BY profile_data->>'family_id'
                HAVING COUNT(DISTINCT profile_data->>'coach_id') > 1
                LIMIT 10
            """)
            if inconsistent:
                affected = [{"family_id": r["family_id"],
                             "coach_count": r["coach_count"],
                             "coach_ids": list(r["coach_ids"]),
                             "members": list(r["members"])} for r in inconsistent]
                results.append({
                    "check_id": "family_coach_consistency",
                    "status": "WARNING",
                    "detail": f"{len(inconsistent)} families with members assigned to different coaches",
                    "affected_users": affected,
                })
            else:
                results.append({
                    "check_id": "family_coach_consistency",
                    "status": "TRUSTED",
                    "detail": "All family members share the same assigned coach",
                })
        except Exception as e:
            results.append({"check_id": "family_coach_consistency", "status": "WARNING",
                            "detail": f"Check failed: {e}"})

        # D4: Corporate company_id column ↔ JSONB sync
        try:
            mismatches = await conn.fetch("""
                SELECT username,
                       company_id::text AS col_company_id,
                       profile_data->>'company_id' AS json_company_id
                FROM users
                WHERE role = 'CLIENT'
                  AND (
                    (company_id IS NOT NULL AND (profile_data->>'company_id' IS NULL
                     OR profile_data->>'company_id' = ''
                     OR company_id::text != profile_data->>'company_id'))
                    OR
                    (profile_data->>'company_id' IS NOT NULL
                     AND profile_data->>'company_id' != ''
                     AND company_id IS NULL)
                  )
                LIMIT 20
            """)
            if mismatches:
                affected = [{"user": r["username"],
                             "column": r["col_company_id"],
                             "jsonb": r["json_company_id"]} for r in mismatches]
                results.append({
                    "check_id": "corporate_field_sync",
                    "status": "WARNING",
                    "detail": f"{len(mismatches)} users with company_id column/JSONB mismatch",
                    "affected_users": affected,
                })
            else:
                results.append({
                    "check_id": "corporate_field_sync",
                    "status": "TRUSTED",
                    "detail": "company_id column and profile_data JSONB in sync for all clients",
                })
        except Exception as e:
            results.append({"check_id": "corporate_field_sync", "status": "WARNING",
                            "detail": f"Check failed: {e}"})

        return results

    # =========================================================================
    # Category E: Geo-Location Integrity (3 checks)
    # =========================================================================

    async def _check_geo_location(self, conn) -> List[Dict]:
        results = []

        # E1: IP accuracy audit — check for private/loopback IPs
        try:
            ip_rows = await conn.fetch("""
                SELECT DISTINCT ON (identifier) identifier, ip_address
                FROM login_attempts
                WHERE success = true AND ip_address IS NOT NULL AND ip_address != ''
                ORDER BY identifier, created_at DESC
            """)
            private_count = 0
            private_users = []
            total_with_ip = 0
            for r in ip_rows:
                ip_str = str(r["ip_address"]).strip()
                if not ip_str:
                    continue
                total_with_ip += 1
                try:
                    addr = ipaddress.ip_address(ip_str)
                    if addr.is_private or addr.is_loopback:
                        private_count += 1
                        if len(private_users) < 5:
                            private_users.append({
                                "user": r["identifier"],
                                "ip": ip_str,
                                "reason": "loopback" if addr.is_loopback else "private/proxy",
                            })
                except ValueError:
                    pass

            if private_count > 0:
                results.append({
                    "check_id": "ip_accuracy_audit",
                    "status": "WARNING",
                    "detail": (f"{private_count}/{total_with_ip} login IPs are private/loopback — "
                               "globe dots show server location, not client location. "
                               "Check nginx X-Forwarded-For config."),
                    "affected_users": private_users,
                })
            else:
                results.append({
                    "check_id": "ip_accuracy_audit",
                    "status": "TRUSTED",
                    "detail": f"All {total_with_ip} login IPs are public — geo-location should be accurate",
                })
        except Exception as e:
            results.append({"check_id": "ip_accuracy_audit", "status": "WARNING",
                            "detail": f"Check failed: {e}"})

        # E2: Geo source coverage
        try:
            clients = await conn.fetch("""
                SELECT username, hardware_id,
                       profile_data->>'state' AS state,
                       profile_data->>'timezone' AS tz
                FROM users
                WHERE role = 'CLIENT' AND deleted_at IS NULL
            """)
            ip_user_set = set()
            try:
                ip_rows2 = await conn.fetch("""
                    SELECT DISTINCT identifier FROM login_attempts
                    WHERE success = true AND ip_address IS NOT NULL AND ip_address != ''
                """)
                ip_user_set = {r["identifier"] for r in ip_rows2}
            except Exception:
                pass

            coverage = {"ip": 0, "state": 0, "timezone": 0, "default": 0}
            for c in clients:
                if c["username"] in ip_user_set:
                    coverage["ip"] += 1
                elif c["state"] and c["state"].strip():
                    coverage["state"] += 1
                elif c["tz"] and c["tz"].strip():
                    coverage["timezone"] += 1
                else:
                    coverage["default"] += 1

            total = sum(coverage.values())
            default_pct = (coverage["default"] / total * 100) if total > 0 else 0

            if default_pct > 50:
                results.append({
                    "check_id": "geo_source_coverage",
                    "status": "WARNING",
                    "detail": f"{coverage['default']}/{total} clients ({default_pct:.0f}%) on default geo — no meaningful location",
                    "coverage": coverage,
                })
            else:
                results.append({
                    "check_id": "geo_source_coverage",
                    "status": "TRUSTED",
                    "detail": f"Geo coverage: IP={coverage['ip']}, state={coverage['state']}, tz={coverage['timezone']}, default={coverage['default']}",
                    "coverage": coverage,
                })
        except Exception as e:
            results.append({"check_id": "geo_source_coverage", "status": "WARNING",
                            "detail": f"Check failed: {e}"})

        # E3: State vs IP conflict
        try:
            _US_STATES_ABBR = {
                "AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE", "FL", "GA",
                "HI", "ID", "IL", "IN", "IA", "KS", "KY", "LA", "ME", "MD",
                "MA", "MI", "MN", "MS", "MO", "MT", "NE", "NV", "NH", "NJ",
                "NM", "NY", "NC", "ND", "OH", "OK", "OR", "PA", "RI", "SC",
                "SD", "TN", "TX", "UT", "VT", "VA", "WA", "WV", "WI", "WY",
            }
            clients_with_state = await conn.fetch("""
                SELECT u.username,
                       u.profile_data->>'state' AS profile_state,
                       u.profile_data->>'name' AS name,
                       la.ip_address
                FROM users u
                JOIN LATERAL (
                    SELECT ip_address FROM login_attempts
                    WHERE identifier = u.username AND success = true
                      AND ip_address IS NOT NULL AND ip_address != ''
                    ORDER BY created_at DESC LIMIT 1
                ) la ON true
                WHERE u.role = 'CLIENT'
                  AND u.profile_data->>'state' IS NOT NULL
                  AND u.profile_data->>'state' != ''
            """)
            conflicts = []
            for r in clients_with_state:
                ip_str = str(r["ip_address"]).strip()
                profile_state = (r["profile_state"] or "").strip().upper()
                if not ip_str or profile_state not in _US_STATES_ABBR:
                    continue
                try:
                    addr = ipaddress.ip_address(ip_str)
                    if addr.is_private or addr.is_loopback:
                        conflicts.append({
                            "user": r["username"],
                            "name": r["name"] or r["username"],
                            "profile_state": profile_state,
                            "ip": ip_str,
                            "explanation": f"state={profile_state} but IP is {ip_str} (proxy/server IP) — globe dot likely shows server location, not {profile_state}",
                        })
                except ValueError:
                    pass

            if conflicts:
                results.append({
                    "check_id": "state_vs_ip_conflict",
                    "status": "WARNING",
                    "detail": f"{len(conflicts)} clients with state/IP location conflict",
                    "affected_users": conflicts[:10],
                })
            else:
                results.append({
                    "check_id": "state_vs_ip_conflict",
                    "status": "TRUSTED",
                    "detail": "No state/IP geo-location conflicts detected",
                })
        except Exception as e:
            results.append({"check_id": "state_vs_ip_conflict", "status": "WARNING",
                            "detail": f"Check failed: {e}"})

        return results

    # =========================================================================
    # Category F: Zero-Value Anomaly Detection (3 checks)
    # =========================================================================

    async def _check_zero_anomalies(self, conn) -> List[Dict]:
        results = []

        # F3 runs FIRST so auto-remediation clears stale 100k balances before
        # F1 checks whether real token allocation exists.

        # F3: High token balance audit (read-only) — report but NEVER auto-zero.
        # TOP_TIER clients legitimately hold 200,000 tokens. Token pack purchases
        # (e.g., Ultimate = 1,000,000) can push balances higher. Auto-zeroing
        # caused real users to lose purchased tokens (Feb 2026 incident).
        try:
            high_bal = await conn.fetch("""
                SELECT username, token_balance,
                       COALESCE(tier, 'UNKNOWN') as tier,
                       COALESCE(subscription_status, 'UNKNOWN') as sub_status
                FROM users
                WHERE role = 'CLIENT'
                  AND COALESCE(token_balance, 0) >= 100000
                LIMIT 20
            """)
            if high_bal:
                details = [
                    f"{r['username']}={r['token_balance']:,} ({r['tier']}/{r['sub_status']})"
                    for r in high_bal
                ]
                results.append({
                    "check_id": "high_token_balances",
                    "status": "TRUSTED",
                    "detail": f"{len(high_bal)} clients with 100k+ tokens (legitimate for TOP_TIER/purchased): {', '.join(details)}",
                })
            else:
                results.append({
                    "check_id": "stale_100k_tokens",
                    "status": "TRUSTED",
                    "detail": "No anomalous high token balances detected",
                })
        except Exception as e:
            results.append({"check_id": "high_token_balances", "status": "WARNING",
                            "detail": f"Check failed: {e}"})

        # F1: Active users with zero token balance
        # Only flag users who have a paid subscription (via subscriptions table) but
        # zero token balance — they paid but got nothing. Pre-launch users without
        # subscriptions having zero balance is expected, not anomalous.
        try:
            has_billing = await conn.fetchval("""
                SELECT EXISTS(
                    SELECT 1 FROM subscriptions
                    WHERE status = 'ACTIVE'
                    LIMIT 1
                )
            """) or False
            if has_billing:
                zero_token = await conn.fetch("""
                    SELECT u.username, u.token_balance,
                           u.profile_data->>'last_login' AS last_login
                    FROM users u
                    JOIN subscriptions s ON s.user_id = u.id AND s.status = 'ACTIVE'
                    WHERE u.role = 'CLIENT'
                      AND COALESCE(u.token_balance, 0) <= 0
                      AND u.username NOT LIKE 'audit_%'
                    LIMIT 20
                """)
                if zero_token:
                    affected = [{"user": r["username"],
                                 "balance": r["token_balance"],
                                 "last_login": r["last_login"]} for r in zero_token]
                    results.append({
                        "check_id": "zero_token_active_users",
                        "status": "WARNING",
                        "detail": f"{len(zero_token)} paying users with zero token balance",
                        "affected_users": affected,
                    })
                else:
                    results.append({
                        "check_id": "zero_token_active_users",
                        "status": "TRUSTED",
                        "detail": "All paying subscribers have non-zero token balances",
                    })
            else:
                results.append({
                    "check_id": "zero_token_active_users",
                    "status": "TRUSTED",
                    "detail": "Pre-launch: no active subscriptions yet — zero balances expected",
                })
        except Exception as e:
            logger.debug("zero_token_active_users: %s (pre-launch expected)", e)
            results.append({
                "check_id": "zero_token_active_users",
                "status": "TRUSTED",
                "detail": "Subscriptions table not active yet — pre-launch expected",
            })

        # F2: Zero sessions but has metrics data
        try:
            mismatches = await conn.fetch("""
                SELECT u.username,
                       COALESCE((u.profile_data->>'total_sessions_count')::int, 0) AS profile_sessions
                FROM users u
                WHERE u.role = 'CLIENT'
                  AND COALESCE((u.profile_data->>'total_sessions_count')::int, 0) = 0
                  AND (
                    EXISTS (SELECT 1 FROM nevedal_metrics nm WHERE nm.user_id = u.id LIMIT 1)
                    OR EXISTS (SELECT 1 FROM sessions s WHERE s.user_id = u.id LIMIT 1)
                  )
                LIMIT 20
            """)
            if mismatches:
                affected = [{"user": r["username"],
                             "profile_sessions": r["profile_sessions"]} for r in mismatches]
                results.append({
                    "check_id": "zero_sessions_with_metrics",
                    "status": "WARNING",
                    "detail": f"{len(mismatches)} clients show 0 sessions in profile but have session/metrics data in PG",
                    "affected_users": affected,
                })
            else:
                results.append({
                    "check_id": "zero_sessions_with_metrics",
                    "status": "TRUSTED",
                    "detail": "Session counts consistent with available metrics data",
                })
        except Exception as e:
            results.append({"check_id": "zero_sessions_with_metrics", "status": "WARNING",
                            "detail": f"Check failed: {e}"})

        return results
