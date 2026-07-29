"""
LITTLE NATE — Agent Status Digest
System-wide health reporter that sends an HTML email digest 3x daily
(5 AM, 5 PM, 11 PM UTC) to support@sovereignsanctuary.net.

Covers EVERY agent and background worker in the system (17 sections):
  - Token Management (3), SkyEye / Social (3), Content Ops (1),
    Token Lifecycle (1), Intelligence / Wisdom (3), Clinical Safety (3),
    Billing / Accounts (3), Trust Auditors (29), Trust Enforcer (1),
    Coaching Subsystem (5), Liminal Presence (3), Data Integrity (2),
    Hive Defense Workers (16), Application Workers (23),
    Database Maintenance (2 — incl. crystal_confidence_shadow proposals,
    WIRE_WHAT_EXISTS Commit 5), Infrastructure (3), Hive Defense Services (27)

Each agent gets a trust status: TRUSTED, WARNING, or FAILED with explanation.

Stagger delay: 110 seconds
Tick interval: 60 seconds (time-of-day check)
"""

import asyncio
import logging
import os
from datetime import datetime, timezone, timedelta
from typing import Optional

logger = logging.getLogger("skyeye.agent_status_digest")

DIGEST_HOURS = {5, 17, 23}
DIGEST_EMAIL = "support@sovereignsanctuary.net"


class AgentStatusDigest:

    def __init__(self, app_state, db_pool, notification_system=None):
        self.app = app_state
        self.db_pool = db_pool
        self.notifications = notification_system
        self._task: Optional[asyncio.Task] = None
        self._running = False
        self._sent_windows: set = set()

    async def start(self):
        if self._task and not self._task.done():
            return
        self._running = True
        self._task = asyncio.create_task(self._run_loop())
        logger.info("AgentStatusDigest started (3x daily at UTC 05:00, 17:00, 23:00)")

    async def stop(self):
        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("AgentStatusDigest stopped")

    async def _run_loop(self):
        await asyncio.sleep(110)
        while self._running:
            try:
                now = datetime.now(timezone.utc)
                window_key = f"{now.date().isoformat()}_{now.hour}"

                if now.hour in DIGEST_HOURS and window_key not in self._sent_windows:
                    await self._build_and_send(now)
                    self._sent_windows.add(window_key)
                    self._sent_windows = {
                        k for k in self._sent_windows
                        if k.startswith(now.date().isoformat())
                    }

            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.error("AgentStatusDigest tick failed: %s", e, exc_info=True)
            await asyncio.sleep(60)

    async def _build_and_send(self, now: datetime):
        try:
            async with self.db_pool.acquire() as conn:
                already = await conn.fetchval(
                    "SELECT 1 FROM skyeye_activity WHERE type='agent_digest_sent' "
                    "AND created_at > NOW() - INTERVAL '30 minutes' LIMIT 1")
            if already:
                logger.info("AgentStatusDigest: skipping — already sent this window")
                return
        except Exception:
            pass

        sections = []

        sections.append(await self._section_token_management())
        sections.append(await self._section_skyeye_social())
        sections.append(await self._section_content_ops())
        sections.append(await self._section_token_lifecycle())
        sections.append(await self._section_intelligence())
        sections.append(await self._section_clinical_safety())
        sections.append(await self._section_billing_accounts())
        sections.append(await self._section_trust_auditors())
        sections.append(await self._section_trust_enforcer())
        sections.append(await self._section_coaching_subsystem())
        sections.append(await self._section_liminal_presence())
        sections.append(await self._section_self_learning())
        sections.append(await self._section_data_integrity())
        sections.append(await self._section_hive_defense_workers())
        sections.append(await self._section_application_workers())
        sections.append(await self._section_db_maintenance())
        sections.append(await self._section_infrastructure())
        sections.append(await self._section_hive_defense_services())

        html = self._render_html(sections, now)
        subject = f"Little Nate Agent Digest — {now.strftime('%b %d %Y %H:%M UTC')}"

        if self.notifications:
            try:
                await self.notifications._send_email(DIGEST_EMAIL, subject, html, "agent_digest")
            except Exception as e:
                logger.error("AgentStatusDigest: email send failed: %s", e)

        await self._log_activity("system", "agent_digest_sent",
                                 f"Digest sent at {now.isoformat()}", "success")
        logger.info("AgentStatusDigest: email sent for %s", now.strftime("%H:%M UTC"))

    # ── Section builders ──────────────────────────────────────────────────

    async def _section_token_management(self) -> dict:
        rows = []
        for name, attr in [
            ("Token Guardian", "token_guardian"),
            ("Token Renewal Agent", "token_renewal_agent"),
            ("Token Audit Agent", "token_audit_agent"),
        ]:
            agent = getattr(self.app, attr, None)
            status, detail = self._check_agent(agent, name)
            extra = await self._recent_activity_summary("token_", limit=3)
            if extra:
                detail += f" | {extra}"
            rows.append((status, name, detail))
        return {"title": "Token Management", "rows": rows}

    async def _section_skyeye_social(self) -> dict:
        rows = []
        engine = getattr(self.app, "skyeye_engine", None)
        status, detail = self._check_agent(engine, "SkyEye Session Engine")
        rows.append((status, "SkyEye Session Engine", detail))

        mw = getattr(self.app, "marketing_worker", None)
        status, detail = self._check_agent(mw, "Marketing Automation Worker")
        rows.append((status, "Marketing Automation Worker", detail))

        no = getattr(self.app, "notification_observer", None)
        status, detail = self._check_agent(no, "Notification Observer")
        rows.append((status, "Notification Observer", detail))

        queue_stats = await self._content_queue_stats()
        if queue_stats:
            rows.append(("INFO", "Content Queue", queue_stats))
        return {"title": "SkyEye / Social Media", "rows": rows}

    async def _section_content_ops(self) -> dict:
        rows = []
        agent = getattr(self.app, "content_queue_janitor", None)
        status, detail = self._check_agent(agent, "ContentQueueJanitor")
        last_cycle = await self._last_activity_ago("janitor_cycle")
        if last_cycle:
            detail += f" | Last cycle: {last_cycle}"
        rows.append((status, "ContentQueueJanitor", detail))
        # QUANTUM-CRYSTAL-ARCH — Little Nate Dispatch
        nl = getattr(self.app, "newsletter_agent", None)
        status, detail = self._check_agent(nl, "NewsletterAgent")
        rows.append((status, "NewsletterAgent", detail))
        # QUANTUM-CRYSTAL-ARCH — Adaptive Growth scheduler + factory
        gs = getattr(self.app, "growth_scheduler", None)
        if gs == "disabled":
            rows.append(("INFO", "GrowthScheduler", "ENABLE_GROWTH_ENGINE=false"))
        elif gs == "init_failed":
            rows.append(("WARNING", "GrowthScheduler", "init_failed"))
        else:
            status, detail = self._check_agent(gs, "GrowthScheduler")
            rows.append((status, "GrowthScheduler", detail))
        cf = getattr(self.app, "content_factory", None)
        if cf == "disabled":
            rows.append(("INFO", "ContentFactory", "ENABLE_CONTENT_FACTORY=false"))
        elif cf == "init_failed":
            rows.append(("WARNING", "ContentFactory", "init_failed"))
        else:
            status, detail = self._check_agent(cf, "ContentFactory")
            rows.append((status, "ContentFactory", detail))
        ow = getattr(self.app, "outreach_worker", None)
        if ow == "disabled":
            rows.append(("INFO", "OutreachWorker", "ENABLE_OUTREACH_ENGINE=false"))
        elif ow == "init_failed":
            rows.append(("WARNING", "OutreachWorker", "init_failed"))
        elif ow is not None and getattr(ow, "last_health", None):
            lh = ow.last_health or {}
            rows.append(
                (
                    "WARNING" if lh.get("status") == "degraded" else "OK",
                    "OutreachWorker",
                    str(lh.get("status") or lh.get("error") or "ok")[:80],
                )
            )
        else:
            status, detail = self._check_agent(ow, "OutreachWorker")
            rows.append((status, "OutreachWorker", detail))
        return {"title": "Content Operations", "rows": rows}

    async def _section_token_lifecycle(self) -> dict:
        agent = getattr(self.app, "token_lifecycle_predictor", None)
        status, detail = self._check_agent(agent, "TokenLifecyclePredictor")
        warnings = await self._count_recent_activity("token_expiry_warning", hours=24)
        detail += f" | {warnings} expiry warning(s) in 24h"
        return {"title": "Token Lifecycle", "rows": [(status, "TokenLifecyclePredictor", detail)]}

    async def _section_intelligence(self) -> dict:
        rows = []
        for name, attr in [
            ("Insight Accumulator", "insight_accumulator"),
            ("Web Content Reader", "web_content_reader"),
            ("CLI Dual-COO Chief", "cli_task_bus_consumer"),  # QUANTUM-CRYSTAL-ARCH
            ("Crystal Outcome Apply", "crystal_outcome_apply"),  # QUANTUM-CRYSTAL-ARCH
            ("Dual-COO Loop Closer", "dual_coo_loop_closer"),  # QUANTUM-CRYSTAL-ARCH
            ("Six-Quotient Battery", "six_quotient_battery_agent"),  # QUANTUM-CRYSTAL-ARCH
            ("Six-Quotient Battery Auditor", "six_quotient_battery_auditor"),  # QUANTUM-CRYSTAL-ARCH
            ("Six-Quotient Standards Index", "six_quotient_standards_index"),  # QUANTUM-CRYSTAL-ARCH
            ("Six-Quotient Growth Engine", "six_quotient_growth_engine"),  # QUANTUM-CRYSTAL-ARCH
            ("Six-Quotient Self-Dev", "six_quotient_self_dev_agent"),  # QUANTUM-CRYSTAL-ARCH
            ("Nate Clinical Bakeoff", "nate_clinical_bakeoff_agent"),  # QUANTUM-CRYSTAL-ARCH
            ("LN Sandbox DOJO", "ln_sandbox_engine"),  # QUANTUM-CRYSTAL-ARCH
            ("LN Sandbox Auditor", "ln_sandbox_auditor"),  # QUANTUM-CRYSTAL-ARCH
            ("PGSD Heartbeat", "pgsd_heartbeat_agent"),  # QUANTUM-CRYSTAL-ARCH
        ]:
            agent = getattr(self.app, attr, None)
            status, detail = self._check_agent(agent, name)
            rows.append((status, name, detail))

        # QUANTUM-CRYSTAL-ARCH — CEO-Nathan morning inbox summary
        try:
            from app.websocket.cli_dual_coo import ceo_inbox_summary

            inbox = ceo_inbox_summary()
            rows.append((
                "INFO",
                "CEO Inbox (Nathan)",
                f"pending={inbox.get('pending')} yellow={inbox.get('yellow')} red={inbox.get('red')}",
            ))
        except Exception:
            pass

        ns = None
        for w in getattr(self.app, "_workers_list", []):
            if type(w).__name__ == "NightSchoolWorker":
                ns = w
                break
        status, detail = self._check_agent(ns, "Night School Worker")
        rows.append((status, "Night School Worker", detail))
        return {"title": "Intelligence / Wisdom", "rows": rows}

    async def _section_clinical_safety(self) -> dict:
        rows = []

        ti_task = getattr(self.app, "_therapeutic_integrity_task", None)
        status, detail = self._check_task(ti_task, "Therapeutic Integrity Monitor")
        rows.append((status, "Therapeutic Integrity Monitor", detail))

        ds_task = getattr(self.app, "_deadman_switch_task", None)
        status, detail = self._check_task(ds_task, "Deadman Switch")
        rows.append((status, "Deadman Switch", detail))

        sr = getattr(self.app, "session_recovery_agent", None)
        status, detail = self._check_agent(sr, "Session Recovery Agent")
        last_cycle = await self._last_activity_ago("session_recovery_cycle")
        if last_cycle:
            detail += f" | Last cycle: {last_cycle}"
        rows.append((status, "Session Recovery Agent", detail))

        cpa = getattr(self.app, "crystal_phi_auditor", None)
        status, detail = self._check_agent(cpa, "Crystal PHI Auditor")
        last_cycle = await self._last_activity_ago("crystal_phi_audit_cycle")
        if last_cycle:
            detail += f" | Last cycle: {last_cycle}"
        rows.append((status, "Crystal PHI Auditor", detail))
        return {"title": "Clinical Safety", "rows": rows}

    async def _section_billing_accounts(self) -> dict:
        rows = []
        billing = None
        for w in getattr(self.app, "_workers_list", []):
            if type(w).__name__ == "BillingWorker":
                billing = w
                break
        status, detail = self._check_agent(billing, "Billing Worker")
        rows.append((status, "Billing Worker", detail))

        purge = getattr(self.app, "_purge_task", None)
        status, detail = self._check_task(purge, "Account Purge Job")
        rows.append((status, "Account Purge Job", detail))

        drip = getattr(self.app, "drip_scheduler", None)
        status, detail = self._check_agent(drip, "Drip Scheduler")
        rows.append((status, "Drip Scheduler", detail))

        qb_sync = getattr(self.app, "quickbooks_sync_agent", None)
        status, detail = self._check_agent(qb_sync, "QuickBooks Sync Agent")
        rows.append((status, "QuickBooks Sync Agent", detail))

        account_recon = getattr(self.app, "account_event_reconciler", None)
        status, detail = self._check_agent(account_recon, "Account Event Reconciler")
        rows.append((status, "Account Event Reconciler", detail))

        return {"title": "Billing / Accounts", "rows": rows}

    async def _section_trust_auditors(self) -> dict:
        auditors = [
            ("SkyEye Tab Auditor", "skyeye_tab_auditor"),
            ("Command Tab Auditor", "command_tab_auditor"),
            ("The Eye Auditor", "the_eye_auditor"),
            ("Login Auditor", "login_auditor"),
            ("Client App Auditor", "client_app_auditor"),
            ("Coach & DOJO Auditor", "coach_dojo_auditor"),
            ("Billing Auditor", "billing_auditor"),
            ("Defense Auditor", "defense_auditor"),
            ("AI Pipeline Auditor", "ai_pipeline_auditor"),
            ("WS Flow Auditor", "ws_flow_auditor"),
            ("Tier Gating Auditor", "tier_gating_auditor"),
            ("Nevedal Lab Auditor", "nevedal_lab_auditor"),
            ("HW Security Auditor", "hw_security_auditor"),
            ("System Integrity Auditor", "system_integrity_auditor"),
            ("DOJO Session Auditor", "dojo_session_auditor"),
            ("Wisdom Pipeline Auditor", "wisdom_pipeline_auditor"),
            ("Settings Tab Auditor", "settings_tab_auditor"),
            ("Coach Hierarchy Auditor", "coach_hierarchy_auditor"),
            ("Classroom Learning Auditor", "classroom_learning_auditor"),
            ("Liminal Presence Auditor", "liminal_presence_auditor"),
            ("PMB Command Center Auditor", "pmb_command_center_auditor"),
            ("Token Lab Auditor", "token_lab_auditor"),
            ("Token Usage Agent", "token_usage_agent"),
            ("Data Uniformity Tracer", "data_uniformity_tracer"),
            ("GKM Auditor", "gkm_auditor"),
            ("Nate Check-In Auditor", "nate_checkin_auditor"),
            ("QuickBooks Auditor", "quickbooks_auditor"),
            ("Corporate Command Auditor", "corporate_command_auditor"),
            ("Voice Infrastructure Auditor", "voice_infra_auditor"),
            ("High-Risk Crisis Auditor", "high_risk_crisis_auditor"),  # QUANTUM-CRYSTAL-ARCH
            ("Newsletter Auditor", "newsletter_auditor"),  # QUANTUM-CRYSTAL-ARCH
        ]
        rows = []
        for name, attr in auditors:
            agent = getattr(self.app, attr, None)
            status, detail = self._check_agent(agent, name)
            rows.append((status, name, detail))
        return {"title": "Trust Auditors (30)", "rows": rows}

    async def _section_trust_enforcer(self) -> dict:
        agent = getattr(self.app, "trust_enforcer", None)
        status, detail = self._check_agent(agent, "Trust Enforcer")
        last_report = await self._last_activity_ago("trust_enforcer_sent")
        if last_report:
            detail += f" | Last report: {last_report}"
        return {"title": "Trust Enforcer", "rows": [(status, "Trust Enforcer", detail)]}

    async def _section_coaching_subsystem(self) -> dict:
        engines = [
            ("Community Mesh Engine", "community_mesh_engine"),
            ("Liminal Coaching Engine", "liminal_coaching_engine"),
            ("DOJO Mentor Engine", "dojo_mentor_engine"),
            ("DOJO Mentor Zoom", "dojo_mentor_zoom"),
            ("Coaching Mesh Engine", "coaching_mesh_engine"),
            ("Call Coaching Engine", "call_coaching_engine"),
            ("Assessment Engine", "assessment_engine"),
        ]
        rows = []
        for name, attr in engines:
            agent = getattr(self.app, attr, None)
            if agent is not None:
                status, detail = self._check_service(agent, name)
            else:
                status, detail = "FAILED", f"{name} not registered on app.state"
            rows.append((status, name, detail))
        return {"title": "Coaching Subsystem", "rows": rows}

    async def _section_liminal_presence(self) -> dict:
        agents = [
            ("Silence Sentinel", "silence_sentinel"),
            ("Language Drift Monitor", "language_drift_monitor"),
            ("Field Response Parser", "field_response_parser"),
        ]
        rows = []
        for name, attr in agents:
            agent = getattr(self.app, attr, None)
            status, detail = self._check_agent(agent, name)
            rows.append((status, name, detail))
        return {"title": "Liminal Presence", "rows": rows}

    async def _section_self_learning(self) -> dict:
        """Crystallizer loop + 6 domain agents (both flag-gated; see .env.template)."""
        rows = []
        cz = getattr(self.app, "nate_memory_crystallizer", None)
        if cz is None:
            rows.append(("FAILED", "Crystallizer", "Not registered on app.state"))
        elif not getattr(cz, "_running", False):
            rows.append(("WARNING", "Crystallizer Loop",
                         "Dormant (ENABLE_CRYSTALLIZER_LOOP off) — no harvest/cluster/decay"))
        else:
            rows.append(("TRUSTED", "Crystallizer Loop",
                         f"Running | cycles={getattr(cz, '_cycle_count', 0)} "
                         f"| buffer={len(getattr(cz, '_harvest_buffer', []) or [])}"))

        agents = getattr(self.app, "nate_domain_agents", None) or {}
        if not agents:
            rows.append(("WARNING", "Domain Agents",
                         "None started (ENABLE_DOMAIN_AGENTS off) — 0/6 self-learning agents"))
        else:
            for domain in sorted(agents):
                agent = agents[domain]
                status, detail = self._check_agent(agent, f"{domain} agent")
                detail += f" | cycles={getattr(agent, '_cycle_count', 0)}"
                rows.append((status, f"Domain Agent: {domain}", detail))
        return {"title": "Self-Learning (Crystallizer + Domain Agents)", "rows": rows}

    async def _section_data_integrity(self) -> dict:
        rows = []
        digest = getattr(self.app, "agent_status_digest", None)
        if digest is not None:
            rows.append(("TRUSTED", "Agent Status Digest", "Running (self)"))
        else:
            rows.append(("WARNING", "Agent Status Digest", "Not on app.state"))
        return {"title": "Data Integrity & Self", "rows": rows}

    async def _section_hive_defense_workers(self) -> dict:
        hive_worker_names = [
            "HeartbeatMonitorWorker", "CuriosityScannerWorker", "TrapMonitorWorker",
            "CdsComputationWorker", "DefconEvaluatorWorker", "CanaryMonitorWorker",
            "BackupAuditWorker", "BirthRateMonitorWorker", "QuarantineEvaluatorWorker",
            "SnapshotComparisonWorker", "CTMonitorWorker", "ConservationAuditWorker",
            "HelixRotationWorker", "TriangleMonitorWorker", "ProjectionMonitorWorker",
            "RecursiveLearningWorker",
        ]
        rows = []
        hive_workers = getattr(self.app, "_hive_workers_list", [])
        matched = set()
        for w in hive_workers:
            class_name = type(w).__name__
            status, detail = self._check_agent(w, class_name)
            rows.append((status, class_name, detail))
            matched.add(class_name)
        for name in hive_worker_names:
            if name not in matched:
                rows.append(("WARNING", name, "Not found in worker list"))
        return {"title": "Hive Defense Workers", "rows": rows}

    async def _section_application_workers(self) -> dict:
        app_worker_names = [
            "BLEAssemblyWorker", "CoherenceWorker", "ConvergenceWorker",
            "FibreLifecycleWorker", "ForesightWorker", "PatternWorker", "RingWorker",
            "TrailWorker", "OnboardingWorker", "SilentDetectorWorker",
            "AutonomyReviewWorker", "WeatherWorker", "BriefingWorker",
            "CommunityWarningWorker", "NightSchoolWorker", "BillingWorker",
            "ImprintAccumulatorWorker", "CrystalSynthesizerWorker",
            "GrowthEngineWorker", "MigrationWorker", "VaultIntegrityWorker",
            "IngestionSafetyWorker", "DependencyGuardian",
        ]
        rows = []
        workers = getattr(self.app, "_workers_list", [])
        matched = set()
        for w in workers:
            class_name = type(w).__name__
            status, detail = self._check_agent(w, class_name)
            rows.append((status, class_name, detail))
            matched.add(class_name)
        for name in app_worker_names:
            if name not in matched:
                rows.append(("WARNING", name, "Not found in worker list"))
        return {"title": "Application Workers", "rows": rows}

    async def _section_db_maintenance(self) -> dict:
        agent = getattr(self.app, "db_maintenance_agent", None)
        status, detail = self._check_agent(agent, "DatabaseMaintenanceAgent")
        last_cycle = await self._last_activity_ago("db_maintenance_cycle")
        if last_cycle:
            detail += f" | Last cycle: {last_cycle}"
        rows = [(status, "DatabaseMaintenanceAgent", detail)]
        rows.append(await self._row_crystal_confidence_shadow())
        return {"title": "Database Maintenance", "rows": rows}

    async def _row_crystal_confidence_shadow(self) -> tuple:
        """WIRE_WHAT_EXISTS Commit 5 — surface (never act on) the weekly
        crystal_confidence_shadow proposals from Commit 4 STEP 4. This is
        informational only: nothing here reads back into
        nate_intelligence_crystals.confidence.
        """
        try:
            async with self.db_pool.acquire() as conn:
                summary = await conn.fetchrow("""
                    SELECT
                        COUNT(*) AS proposal_count,
                        MAX(computed_at) AS last_computed_at,
                        COUNT(*) FILTER (WHERE proposed_delta != 0) AS nonzero_count,
                        MAX(ABS(proposed_delta)) AS max_abs_delta
                    FROM crystal_confidence_shadow
                    WHERE computed_at > NOW() - INTERVAL '8 days'
                """)
        except Exception as e:
            return ("WARNING", "Crystal Confidence Shadow (proposals only)",
                    f"Query failed: {e}")

        if not summary or not summary["proposal_count"]:
            return ("INFO", "Crystal Confidence Shadow (proposals only)",
                    "No proposals in the last 8 days (weekly gate not yet due, "
                    "or no outcome-linked crystal recalls met the minimum sample size)")

        last_ts = summary["last_computed_at"]
        last_str = last_ts.strftime("%b %d %H:%M UTC") if last_ts else "unknown"
        detail = (
            f"{summary['proposal_count']} crystal(s) evaluated in latest pass "
            f"({summary['nonzero_count']} with nonzero delta, max |delta|="
            f"{float(summary['max_abs_delta'] or 0):.4f}) at {last_str}. "
            f"Proposals are never applied — review crystal_confidence_shadow directly."
        )
        return ("INFO", "Crystal Confidence Shadow (proposals only)", detail)

    async def _section_infrastructure(self) -> dict:
        rows = []
        relay = getattr(self.app, "swarm_relay", None)
        status, detail = self._check_agent(relay, "Swarm Relay")
        rows.append((status, "Swarm Relay", detail))

        try:
            async with self.db_pool.acquire() as conn:
                await conn.fetchval("SELECT 1")
            rows.append(("TRUSTED", "PostgreSQL", "Connected"))
        except Exception as e:
            rows.append(("FAILED", "PostgreSQL", f"Connection error: {e}"))

        try:
            import redis
            redis_pw = os.environ.get("REDIS_PASSWORD", "")
            redis_url = f"redis://:{redis_pw}@redis:6379/0" if redis_pw else "redis://redis:6379/0"
            r = redis.Redis.from_url(redis_url, socket_timeout=2)
            r.ping()
            rows.append(("TRUSTED", "Redis", "PONG received"))
        except Exception:
            rows.append(("WARNING", "Redis", "Ping failed or unavailable"))

        return {"title": "Infrastructure", "rows": rows}

    async def _section_hive_defense_services(self) -> dict:
        hive_svc_names = [
            "webhook_fortress", "guardian_fibre", "sentinel_mesh", "pipeline_drum",
            "hepa_filter", "billing_monitor", "trial_guard", "usage_meter",
            "coach_financial_guard", "anonymization_proxy", "therapeutic_integrity",
            "model_stability", "transit_guardian", "infiltrator_trap",
            "family_data_guardian", "mirror_prediction", "coach_integrity_shield",
            "legal_compulsion", "sovereign_stripe_proxy", "family_session_guardian",
            "zero_knowledge_vault", "sovereign_keys", "succession_protocol",
            "recovery_drill", "heritage_vault", "upstream_canary", "deadman_switch",
        ]
        rows = []
        hv4 = getattr(self.app, "hive_v4", {})
        for name in hive_svc_names:
            svc = hv4.get(name)
            if svc is not None:
                rows.append(("TRUSTED", f"hive:{name}", "Initialized"))
            else:
                rows.append(("WARNING", f"hive:{name}", "Not initialized"))
        return {"title": "Hive Defense Services", "rows": rows}

    # ── Helpers ────────────────────────────────────────────────────────────

    def _check_agent(self, agent, name: str) -> tuple:
        if agent is None:
            return ("FAILED", f"{name} not registered on app.state")

        running = getattr(agent, "_running", None)
        task = getattr(agent, "_task", None)

        if running is True:
            if task and task.done():
                exc = task.exception() if not task.cancelled() else None
                reason = f"task exited: {exc}" if exc else "task exited unexpectedly"
                return ("FAILED", reason)
            return ("TRUSTED", "Running")

        if running is False:
            return ("FAILED", "Agent stopped (_running=False)")

        is_running = getattr(agent, "_is_running", None)
        if is_running is True:
            return ("TRUSTED", "Running")
        if is_running is False:
            return ("FAILED", "Agent stopped (_is_running=False)")

        scheduler = getattr(agent, "scheduler", None)
        if scheduler is not None and hasattr(scheduler, "running"):
            if scheduler.running:
                return ("TRUSTED", "Running (scheduler)")
            return ("WARNING", "Scheduler not running")

        listener = getattr(agent, "_listener_task", None)
        if listener is not None:
            if not listener.done():
                return ("TRUSTED", "Running (listener)")
            return ("FAILED", "Listener task exited")

        if hasattr(agent, "is_running"):
            if agent.is_running():
                return ("TRUSTED", "Running (is_running=True)")
            return ("FAILED", "is_running returned False")

        return ("WARNING", "No _running flag found, cannot verify")

    def _check_service(self, agent, name: str) -> tuple:
        """Check a request-response service (no _running flag expected)."""
        if agent is None:
            return ("FAILED", f"{name} not registered on app.state")
        running = getattr(agent, "_running", None)
        if running is True:
            task = getattr(agent, "_task", None)
            if task and task.done():
                exc = task.exception() if not task.cancelled() else None
                return ("FAILED", f"task exited: {exc}" if exc else "task exited")
            return ("TRUSTED", "Running")
        if running is False:
            return ("FAILED", "Service stopped (_running=False)")
        return ("TRUSTED", "Initialized")

    def _check_task(self, task, name: str) -> tuple:
        """Check an asyncio.Task (e.g. Account Purge, Deadman Switch)."""
        if task is None:
            return ("FAILED", f"{name} task not registered")
        if not task.done():
            return ("TRUSTED", "Running")
        if task.cancelled():
            return ("FAILED", "Task was cancelled")
        exc = task.exception() if not task.cancelled() else None
        if exc:
            return ("FAILED", f"Task exited with error: {exc}")
        return ("FAILED", "Task exited unexpectedly")

    async def _recent_activity_summary(self, type_prefix: str, limit: int = 3) -> str:
        try:
            async with self.db_pool.acquire() as conn:
                rows = await conn.fetch(f"""
                    SELECT type, platform, content
                    FROM skyeye_activity
                    WHERE type LIKE $1
                    ORDER BY created_at DESC
                    LIMIT $2
                """, f"{type_prefix}%", limit)
            if not rows:
                return ""
            return "; ".join(f"{r['platform']}: {r['content'][:60]}" for r in rows)
        except Exception:
            return ""

    async def _last_activity_ago(self, activity_type: str) -> str:
        try:
            async with self.db_pool.acquire() as conn:
                row = await conn.fetchrow("""
                    SELECT created_at FROM skyeye_activity
                    WHERE type = $1
                    ORDER BY created_at DESC LIMIT 1
                """, activity_type)
            if not row:
                return ""
            delta = datetime.now(timezone.utc) - row["created_at"].replace(tzinfo=timezone.utc)
            hours = delta.total_seconds() / 3600
            if hours < 1:
                return f"{delta.total_seconds() / 60:.0f} min ago"
            return f"{hours:.1f}h ago"
        except Exception:
            return ""

    async def _count_recent_activity(self, activity_type: str, hours: int = 24) -> int:
        try:
            async with self.db_pool.acquire() as conn:
                row = await conn.fetchrow("""
                    SELECT COUNT(*) AS c FROM skyeye_activity
                    WHERE type = $1 AND created_at > NOW() - INTERVAL '%s hours'
                """ % hours, activity_type)
            return row["c"] if row else 0
        except Exception:
            return 0

    async def _content_queue_stats(self) -> str:
        try:
            async with self.db_pool.acquire() as conn:
                rows = await conn.fetch("""
                    SELECT status, COUNT(*) AS cnt
                    FROM skyeye_content_queue GROUP BY status
                """)
            parts = [f"{r['status']}={r['cnt']}" for r in rows]
            return ", ".join(parts) if parts else ""
        except Exception:
            return ""

    def _render_html(self, sections: list, now: datetime) -> str:
        rows_html = ""
        trusted = 0
        warnings = 0
        failed = 0

        for section in sections:
            rows_html += f'<tr><td colspan="3" style="background:#111;color:#C9A962;'
            rows_html += f'font-weight:bold;padding:10px 8px;font-size:14px;">'
            rows_html += f'{section["title"]}</td></tr>\n'

            for status, name, detail in section["rows"]:
                if status == "TRUSTED":
                    color = "#22c55e"
                    trusted += 1
                elif status == "WARNING":
                    color = "#eab308"
                    warnings += 1
                elif status == "FAILED":
                    color = "#ef4444"
                    failed += 1
                else:
                    color = "#94a3b8"

                rows_html += (
                    f'<tr>'
                    f'<td style="padding:4px 8px;color:{color};font-weight:bold;'
                    f'font-size:12px;white-space:nowrap;">[{status}]</td>'
                    f'<td style="padding:4px 8px;color:#e2e8f0;font-size:12px;">{name}</td>'
                    f'<td style="padding:4px 8px;color:#94a3b8;font-size:11px;">{detail}</td>'
                    f'</tr>\n'
                )

        total = trusted + warnings + failed
        header_color = "#22c55e" if failed == 0 else "#ef4444"

        html = f"""
<div style="font-family:'DM Sans',Arial,sans-serif;max-width:700px;margin:0 auto;
background:#0A0A0A;color:#e2e8f0;border:1px solid #222;border-radius:8px;overflow:hidden;">
  <div style="background:#050505;padding:16px 20px;border-bottom:1px solid #222;">
    <h2 style="margin:0;color:#C9A962;font-size:18px;">Little Nate Agent Digest</h2>
    <p style="margin:4px 0 0;color:#94a3b8;font-size:12px;">
      {now.strftime('%A, %B %d %Y at %H:%M UTC')}
    </p>
  </div>
  <div style="padding:12px 20px;background:#111;border-bottom:1px solid #222;">
    <span style="color:{header_color};font-weight:bold;font-size:14px;">
      {trusted} TRUSTED</span>
    <span style="color:#94a3b8;"> | </span>
    <span style="color:#eab308;font-weight:bold;font-size:14px;">
      {warnings} WARNING</span>
    <span style="color:#94a3b8;"> | </span>
    <span style="color:#ef4444;font-weight:bold;font-size:14px;">
      {failed} FAILED</span>
    <span style="color:#94a3b8;font-size:12px;"> / {total} total agents</span>
  </div>
  <table style="width:100%;border-collapse:collapse;">
    {rows_html}
  </table>
  <div style="padding:12px 20px;border-top:1px solid #222;text-align:center;">
    <span style="color:#666;font-size:10px;">
      Sovereign Sanctuary — Autonomous Agent Health Monitor
    </span>
  </div>
</div>
"""
        return html

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
