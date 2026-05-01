"""
LITTLE NATE — Trust Enforcer
Meta-agent that aggregates results from all tab/DB auditors, compares against
the governed trust baseline, enforces solutions when trust drops below 100%,
and gates parameter changes through admin approval.

Scheduled 3x daily at 5:10 AM, 5:10 PM, 11:10 PM UTC (10-min stagger
after all auditors have completed).

Email model (2 emails max per window):
  Email #1 — Sovereign Trust Report (ALWAYS sent)
    Full breakdown: pre-flight, auditor scorecards, enforcement actions,
    pending proposals. Goes out every audit window.
  Email #2 — Trust Alert (ONLY sent when NOT 100% GREEN)
    Concise alert: only failing pre-flights, failing auditors, enforcement
    actions. Omitted entirely when everything is green.

Individual auditors no longer send their own emails. All notification
goes through this enforcer to keep the inbox to 1-2 emails per window.

Responsibilities:
  0. Pre-flight checks (audit token, test accounts, admin MFA, Azure env)
  1. Aggregate auditor results from skyeye_activity
  2. Compare against trust_baseline expectations
  3. Log enforcement actions with remediation categories
  4. Guard baseline parameter changes via proposal/approval flow
  5. Send consolidated trust emails (full report + conditional alert)
"""

import asyncio
import json
import logging
import os
import re
import time
from datetime import datetime, timezone
from typing import Optional

import aiohttp

logger = logging.getLogger("nate.trust_enforcer")

AUDIT_HOURS = {5, 17, 23}
AUDIT_EMAIL = "support@sovereignsanctuary.net"

_REDIS_URL_EARLY = os.environ.get("REDIS_URL", "")
_REDIS_PW_EARLY = os.environ.get("REDIS_PASSWORD", "")
_REDIS_HOST_EARLY = os.environ.get("REDIS_HOST", "redis")
_REDIS_KEY_PREFIX = os.environ.get("REDIS_KEY_PREFIX", "nate")
_REDIS_KEY_ENV = os.environ.get("ENVIRONMENT", "production")

AUDITOR_ACTIVITY_TYPES = [
    "skyeye_tab_audit_sent",
    "command_tab_audit_sent",
    "eye_tab_audit_sent",
    "login_audit_sent",
    "client_app_audit_sent",
    "coach_dojo_audit_sent",
    "billing_audit_sent",
    "defense_audit_sent",
    "ai_pipeline_audit_sent",
    "ws_flow_audit_sent",
    "tier_gating_audit_sent",
    "nevedal_lab_audit_sent",
    "hardware_security_audit_sent",
    "system_integrity_audit_sent",
    "dojo_session_audit_sent",
    "wisdom_pipeline_audit_sent",
    "settings_tab_audit_sent",
    "coach_hierarchy_audit_sent",
    "liminal_presence_audit_sent",
    "pmb_command_center_audit_sent",
    "data_uniformity_audit_sent",
    "token_lab_audit_sent",
    "gkm_audit_sent",
    "nate_checkin_audit_sent",
    "quickbooks_audit_sent",
    "corporate_command_audit_sent",
    "voice_infra_audit_sent",
    "classroom_learning_audit_sent",
]

AUDITOR_LABELS = {
    "skyeye_tab_audit_sent": "SkyEye Dashboard",
    "command_tab_audit_sent": "Sovereign Command",
    "eye_tab_audit_sent": "The Eye",
    "login_audit_sent": "Login Tests",
    "client_app_audit_sent": "Client App",
    "coach_dojo_audit_sent": "Coach & DOJO",
    "billing_audit_sent": "Billing Pipeline",
    "defense_audit_sent": "Defense Health",
    "ai_pipeline_audit_sent": "AI Pipeline",
    "ws_flow_audit_sent": "WebSocket Flows",
    "tier_gating_audit_sent": "Tier Gating",
    "nevedal_lab_audit_sent": "Nevedal Research Lab",
    "hardware_security_audit_sent": "Hardware Security",
    "system_integrity_audit_sent": "System Integrity",
    "dojo_session_audit_sent": "DOJO & Zoom Sessions",
    "wisdom_pipeline_audit_sent": "Wisdom Pipeline",
    "settings_tab_audit_sent": "Settings Tab",
    "coach_hierarchy_audit_sent": "Coach Hierarchy & Mesh",
    "liminal_presence_audit_sent": "Liminal Presence",
    "pmb_command_center_audit_sent": "PMB Command Center",
    "data_uniformity_audit_sent": "Data Uniformity",
    "token_lab_audit_sent": "Token Lab",
    "gkm_audit_sent": "GKM Ministry",
    "nate_checkin_audit_sent": "Nate Check-In",
    "quickbooks_audit_sent": "QuickBooks Sync",
    "corporate_command_audit_sent": "Corporate Command",
    "voice_infra_audit_sent": "Voice Infrastructure",
    "classroom_learning_audit_sent": "Classroom Learning",
}

REMEDIATION_CATEGORIES = {
    "L2_ISSUE": "L2 validation mismatch — response structure may have changed",
    "ENDPOINT_DOWN": "Endpoint returned 5xx or timed out",
    "AUTH_FAILURE": "Authentication rejected (token expired or account missing)",
    "DATA_PIPELINE": "Endpoint returned empty when data is expected",
    "AI_UNREACHABLE": "Azure OpenAI or TTS service unreachable",
    "DEFENSE_DEGRADED": "Defense subsystem offline or degraded",
    "GATE_BYPASS": "Tier feature gate not enforcing correctly",
    "WS_TIMEOUT": "WebSocket flow timed out or failed handshake",
    "PREFLIGHT_FAIL": "Pre-flight infrastructure check failed — auditors will be unreliable",
}

ADMIN_MFA_FIELDS = ["totp_enabled", "sms_verified", "webauthn_enabled"]
AZURE_REQUIRED_VARS = [
    "AZURE_API_KEY",
    "AZURE_OPENAI_ENDPOINT",
    "AZURE_OPENAI_CHAT_DEPLOYMENT",
    "AZURE_OPENAI_DEPLOYMENT",
    "AZURE_OPENAI_MINI_TTS_DEPLOYMENT",
]

_SCORE_RE = re.compile(r"(\d+)/(\d+)\s+TRUSTED")


class TrustEnforcer:

    def __init__(self, db_pool, notification_system=None, app_state=None,
                 redis_url: str = "", redis_password: str = ""):
        self.db_pool = db_pool
        self.notifications = notification_system
        self._app_state = app_state
        self._redis_url = redis_url
        self._redis_password = redis_password
        self._task: Optional[asyncio.Task] = None
        self._running = False
        self._sent_windows: set = set()
        self._redis = None

    async def start(self):
        if self._task and not self._task.done():
            return
        self._running = True
        self._task = asyncio.create_task(self._run_loop())
        logger.info("TrustEnforcer started (3x daily at UTC 05:10, 17:10, 23:10)")

    async def stop(self):
        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("TrustEnforcer stopped")

    async def _run_loop(self):
        await asyncio.sleep(600)
        while self._running:
            try:
                now = datetime.now(timezone.utc)
                window_key = f"{now.date().isoformat()}_{now.hour}"
                if (now.hour in AUDIT_HOURS and now.minute >= 10
                        and window_key not in self._sent_windows):
                    await self._enforce_and_report(now)
                    self._sent_windows.add(window_key)
                    self._sent_windows = {
                        k for k in self._sent_windows
                        if k.startswith(now.date().isoformat())
                    }
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.error("TrustEnforcer tick failed: %s", e, exc_info=True)
            await asyncio.sleep(60)

    async def trigger(self):
        """Manually trigger an enforcement cycle (admin-only)."""
        now = datetime.now(timezone.utc)
        await self._enforce_and_report(now)

    async def _enforce_and_report(self, now: datetime):
        try:
            async with self.db_pool.acquire() as conn:
                already = await conn.fetchval(
                    "SELECT 1 FROM skyeye_activity WHERE type='trust_enforcer_sent' "
                    "AND created_at > NOW() - INTERVAL '30 minutes' LIMIT 1")
            if already:
                logger.info("TrustEnforcer: skipping — already sent this window")
                return
        except Exception:
            pass

        preflight = await self._pre_flight_checks()
        auditor_results = await self._read_latest_results()
        baseline = await self._load_baseline()
        enforcement_actions = []

        for activity_type, result in auditor_results.items():
            if result is None:
                enforcement_actions.append({
                    "auditor": AUDITOR_LABELS.get(activity_type, activity_type),
                    "category": "ENDPOINT_DOWN",
                    "detail": "No audit result found — auditor may not have run",
                })
                continue

            trusted, total = result["trusted"], result["total"]
            if trusted < total:
                category = self._classify_failure(activity_type)
                enforcement_actions.append({
                    "auditor": AUDITOR_LABELS.get(activity_type, activity_type),
                    "category": category,
                    "detail": f"{trusted}/{total} TRUSTED — {total - trusted} endpoint(s) need attention",
                    "trusted": trusted,
                    "total": total,
                })

            baseline_key = self._baseline_key_for(activity_type)
            if baseline_key and baseline_key in baseline:
                expected = baseline[baseline_key].get("expected", 0)
                if total != expected:
                    enforcement_actions.append({
                        "auditor": AUDITOR_LABELS.get(activity_type, activity_type),
                        "category": "DATA_PIPELINE",
                        "detail": f"Baseline expects {expected} tests but auditor reported {total}",
                    })

        pending_proposals = await self._get_pending_proposals()

        total_trusted = sum(r["trusted"] for r in auditor_results.values() if r)
        total_tests = sum(r["total"] for r in auditor_results.values() if r)
        pct = int((total_trusted / total_tests * 100) if total_tests else 0)
        pf_passed = sum(1 for c in preflight if c["pass"])
        pf_total = len(preflight)
        level = "GREEN" if pct == 100 and not enforcement_actions and pf_passed == pf_total else (
            "RED" if any(a["category"] in ("ENDPOINT_DOWN", "AI_UNREACHABLE", "PREFLIGHT_FAIL")
                        for a in enforcement_actions)
            else "YELLOW")

        # ── Email #1: Full Sovereign Trust Report (always sent) ──────────
        full_html = self._render_html(auditor_results, enforcement_actions,
                                      pending_proposals, preflight, now)
        full_subject = (
            f"Sovereign Trust Report — {total_trusted}/{total_tests} "
            f"({pct}%) {level} — {now.strftime('%b %d %H:%M UTC')}"
        )
        if self.notifications:
            try:
                await self.notifications._send_email(
                    AUDIT_EMAIL, full_subject, full_html, "trust_enforcement"
                )
            except Exception as e:
                logger.error("TrustEnforcer: full report email failed: %s", e)

        # ── Email #2: Trust Alert (only when NOT 100% GREEN) ─────────────
        if level != "GREEN" and self.notifications:
            alert_html = self._render_alert_html(
                auditor_results, enforcement_actions, preflight, now,
                total_trusted, total_tests, pct, pf_passed, pf_total, level
            )
            alert_subject = (
                f"TRUST ALERT — {level} — "
                f"{len(enforcement_actions)} issue(s) — "
                f"{now.strftime('%b %d %H:%M UTC')}"
            )
            try:
                await self.notifications._send_email(
                    AUDIT_EMAIL, alert_subject, alert_html, "trust_alert"
                )
            except Exception as e:
                logger.error("TrustEnforcer: alert email failed: %s", e)

        for action in enforcement_actions:
            await self._log_activity(
                "system", "trust_enforcement",
                json.dumps(action, default=str), "warning"
            )

        await self._log_activity(
            "system", "trust_enforcer_sent",
            f"Enforcement report sent: {total_trusted}/{total_tests} TRUSTED "
            f"({pct}%) — Pre-flight {pf_passed}/{pf_total} — {level} — "
            f"{len(enforcement_actions)} actions at {now.isoformat()}",
            "success" if level == "GREEN" else "warning"
        )
        logger.info("TrustEnforcer: report sent — %d/%d (%d%%) preflight %d/%d %s, %d actions",
                     total_trusted, total_tests, pct, pf_passed, pf_total,
                     level, len(enforcement_actions))

    # ── Pre-flight checks ────────────────────────────────────────────────
    async def _pre_flight_checks(self) -> list:
        """Validate infrastructure prerequisites before evaluating auditor
        results. Returns a list of check dicts: {id, label, pass, detail}."""
        checks = []

        checks.append(await self._pf_audit_token())
        checks.append(await self._pf_test_accounts())
        checks.append(await self._pf_admin_mfa())
        checks.append(self._pf_azure_env())
        checks.append(await self._pf_redis_alive())

        for c in checks:
            if not c["pass"]:
                logger.warning("Pre-flight FAIL: %s — %s", c["id"], c["detail"])

        return checks

    async def _pf_audit_token(self) -> dict:
        """SKYEYE_AUDIT_TOKEN must be set in env AND exist in Redis."""
        token = os.environ.get("SKYEYE_AUDIT_TOKEN", "")
        if not token:
            return {"id": "audit_token", "label": "Audit Token",
                    "pass": False, "detail": "SKYEYE_AUDIT_TOKEN env var not set"}
        try:
            r = await self._get_redis()
            if r is None:
                return {"id": "audit_token", "label": "Audit Token",
                        "pass": False, "detail": "Redis unavailable — cannot verify token"}
            key = f"{_REDIS_KEY_PREFIX}:{_REDIS_KEY_ENV}:auth:{token}"
            exists = await r.exists(key)
            if exists:
                return {"id": "audit_token", "label": "Audit Token",
                        "pass": True, "detail": "Token set and registered in Redis"}
            return {"id": "audit_token", "label": "Audit Token",
                    "pass": False, "detail": "Token set in env but NOT found in Redis"}
        except Exception as e:
            return {"id": "audit_token", "label": "Audit Token",
                    "pass": False, "detail": f"Redis check failed: {str(e)[:60]}"}

    async def _pf_test_accounts(self) -> dict:
        """audit_client and audit_coach must exist in the users table."""
        try:
            async with self.db_pool.acquire() as conn:
                rows = await conn.fetch(
                    "SELECT username FROM users WHERE username IN ('audit_client', 'audit_coach')"
                )
                found = {r["username"] for r in rows}
                missing = {"audit_client", "audit_coach"} - found
                if not missing:
                    return {"id": "test_accounts", "label": "Test Accounts",
                            "pass": True, "detail": "audit_client + audit_coach exist"}
                return {"id": "test_accounts", "label": "Test Accounts",
                        "pass": False,
                        "detail": f"Missing: {', '.join(sorted(missing))}"}
        except Exception as e:
            return {"id": "test_accounts", "label": "Test Accounts",
                    "pass": False, "detail": f"DB query failed: {str(e)[:60]}"}

    async def _pf_admin_mfa(self) -> dict:
        """DrNevedal1 must have totp_enabled, sms_verified, webauthn_enabled
        all true, plus at least 2 webauthn credentials."""
        try:
            async with self.db_pool.acquire() as conn:
                row = await conn.fetchrow(
                    "SELECT profile_data FROM users WHERE username = 'DrNevedal1'"
                )
                if not row or not row["profile_data"]:
                    return {"id": "admin_mfa", "label": "Admin MFA Posture",
                            "pass": False, "detail": "DrNevedal1 profile not found"}
                pd = row["profile_data"] if isinstance(row["profile_data"], dict) \
                    else json.loads(row["profile_data"])

                failures = []
                for field in ADMIN_MFA_FIELDS:
                    if pd.get(field) is not True:
                        failures.append(field)

                creds = pd.get("webauthn_credentials", [])
                if len(creds) < 2:
                    failures.append(f"yubikeys ({len(creds)}/2)")

                if not failures:
                    return {"id": "admin_mfa", "label": "Admin MFA Posture",
                            "pass": True,
                            "detail": "TOTP + SMS + WebAuthn + 2 YubiKeys verified"}
                return {"id": "admin_mfa", "label": "Admin MFA Posture",
                        "pass": False,
                        "detail": f"Missing: {', '.join(failures)}"}
        except Exception as e:
            return {"id": "admin_mfa", "label": "Admin MFA Posture",
                    "pass": False, "detail": f"DB query failed: {str(e)[:60]}"}

    @staticmethod
    def _pf_azure_env() -> dict:
        """All required Azure OpenAI env vars must be set."""
        missing = [v for v in AZURE_REQUIRED_VARS if not os.environ.get(v)]
        if not missing:
            return {"id": "azure_env", "label": "Azure Env Vars",
                    "pass": True, "detail": f"All {len(AZURE_REQUIRED_VARS)} vars set"}
        return {"id": "azure_env", "label": "Azure Env Vars",
                "pass": False, "detail": f"Missing: {', '.join(missing)}"}

    async def _pf_redis_alive(self) -> dict:
        """Redis must respond to PING."""
        try:
            r = await self._get_redis()
            if r is None:
                return {"id": "redis", "label": "Redis Connection",
                        "pass": False, "detail": "Could not connect to Redis"}
            pong = await r.ping()
            if pong:
                return {"id": "redis", "label": "Redis Connection",
                        "pass": True, "detail": "Redis PONG"}
            return {"id": "redis", "label": "Redis Connection",
                    "pass": False, "detail": "Redis did not respond to PING"}
        except Exception as e:
            return {"id": "redis", "label": "Redis Connection",
                    "pass": False, "detail": f"Redis error: {str(e)[:60]}"}

    async def _get_redis(self):
        """Lazy-connect async Redis client for pre-flight checks.
        Uses redis_url passed from main.py (captured before load_dotenv
        clobbers Docker env vars)."""
        if self._redis is not None:
            try:
                await self._redis.ping()
                return self._redis
            except Exception:
                self._redis = None
        try:
            import redis.asyncio as aioredis
            if self._redis_url:
                self._redis = aioredis.from_url(
                    self._redis_url, decode_responses=True,
                    socket_connect_timeout=5)
            else:
                self._redis = aioredis.Redis(
                    host=_REDIS_HOST_EARLY,
                    port=int(os.environ.get("REDIS_PORT", "6379")),
                    password=self._redis_password or _REDIS_PW_EARLY or None,
                    decode_responses=True, socket_connect_timeout=5)
            await self._redis.ping()
            return self._redis
        except Exception:
            self._redis = None
            return None

    async def _read_latest_results(self) -> dict:
        results = {}
        try:
            async with self.db_pool.acquire() as conn:
                for atype in AUDITOR_ACTIVITY_TYPES:
                    row = await conn.fetchrow("""
                        SELECT content, created_at FROM skyeye_activity
                        WHERE type = $1
                        ORDER BY created_at DESC LIMIT 1
                    """, atype)
                    if row:
                        content = row["content"]
                        m = _SCORE_RE.search(content)
                        if m:
                            results[atype] = {
                                "trusted": int(m.group(1)),
                                "total": int(m.group(2)),
                                "timestamp": row["created_at"],
                            }
                        else:
                            try:
                                parsed = json.loads(content) if isinstance(content, str) else content
                                if isinstance(parsed, dict) and "trusted" in parsed and "total" in parsed:
                                    results[atype] = {
                                        "trusted": int(parsed["trusted"]),
                                        "total": int(parsed["total"]),
                                        "timestamp": row["created_at"],
                                    }
                                else:
                                    results[atype] = None
                            except (json.JSONDecodeError, TypeError, ValueError):
                                results[atype] = None
                    else:
                        results[atype] = None
        except Exception as e:
            logger.error("TrustEnforcer: failed reading audit results: %s", e)
            for atype in AUDITOR_ACTIVITY_TYPES:
                results.setdefault(atype, None)
        return results

    async def _load_baseline(self) -> dict:
        baseline = {}
        try:
            async with self.db_pool.acquire() as conn:
                rows = await conn.fetch("SELECT parameter_key, parameter_value FROM trust_baseline")
                for r in rows:
                    baseline[r["parameter_key"]] = (
                        json.loads(r["parameter_value"])
                        if isinstance(r["parameter_value"], str)
                        else r["parameter_value"]
                    )
        except Exception as e:
            logger.debug("TrustEnforcer: baseline load failed: %s", e)
        return baseline

    async def _get_pending_proposals(self) -> list:
        try:
            async with self.db_pool.acquire() as conn:
                rows = await conn.fetch(
                    "SELECT id, parameter_key, reason, proposed_by, created_at "
                    "FROM trust_baseline_proposals WHERE status = 'PENDING' "
                    "ORDER BY created_at DESC LIMIT 10"
                )
                return [dict(r) for r in rows]
        except Exception:
            return []

    def _classify_failure(self, activity_type: str) -> str:
        mapping = {
            "ai_pipeline_audit_sent": "AI_UNREACHABLE",
            "defense_audit_sent": "DEFENSE_DEGRADED",
            "tier_gating_audit_sent": "GATE_BYPASS",
            "ws_flow_audit_sent": "WS_TIMEOUT",
            "login_audit_sent": "AUTH_FAILURE",
        }
        return mapping.get(activity_type, "ENDPOINT_DOWN")

    def _baseline_key_for(self, activity_type: str) -> str:
        mapping = {
            "skyeye_tab_audit_sent": "skyeye_endpoint_count",
            "command_tab_audit_sent": "command_endpoint_count",
            "eye_tab_audit_sent": "eye_endpoint_count",
            "client_app_audit_sent": "client_app_endpoint_count",
            "login_audit_sent": "login_test_accounts",
            "coach_dojo_audit_sent": "coach_dojo_endpoint_count",
            "billing_audit_sent": "billing_endpoint_count",
            "defense_audit_sent": "defense_subsystem_count",
            "ai_pipeline_audit_sent": "ai_pipeline_check_count",
            "ws_flow_audit_sent": "ws_flow_test_count",
            "tier_gating_audit_sent": "tier_gate_test_count",
            "nevedal_lab_audit_sent": "nevedal_lab_endpoint_count",
            "hardware_security_audit_sent": "hardware_security_check_count",
            "system_integrity_audit_sent": "system_integrity_check_count",
            "dojo_session_audit_sent": "dojo_session_endpoint_count",
            "wisdom_pipeline_audit_sent": "wisdom_pipeline_check_count",
            "settings_tab_audit_sent": "settings_tab_check_count",
            "coach_hierarchy_audit_sent": "coach_hierarchy_check_count",
            "liminal_presence_audit_sent": "liminal_presence_check_count",
            "pmb_command_center_audit_sent": "pmb_command_center_check_count",
            "data_uniformity_audit_sent": "data_uniformity_check_count",
            "token_lab_audit_sent": "token_lab_check_count",
            "gkm_audit_sent": "gkm_check_count",
            "nate_checkin_audit_sent": "nate_checkin_check_count",
            "quickbooks_audit_sent": "quickbooks_check_count",
            "corporate_command_audit_sent": "corporate_command_check_count",
            "voice_infra_audit_sent": "voice_infra_check_count",
            "classroom_learning_audit_sent": "classroom_learning_check_count",
        }
        return mapping.get(activity_type, "")

    def _render_html(self, auditor_results: dict, enforcement_actions: list,
                     pending_proposals: list, preflight: list,
                     now: datetime) -> str:
        total_trusted = sum(r["trusted"] for r in auditor_results.values() if r)
        total_tests = sum(r["total"] for r in auditor_results.values() if r)
        pct = int((total_trusted / total_tests * 100) if total_tests else 0)
        pf_passed = sum(1 for c in preflight if c["pass"])
        pf_total = len(preflight)

        has_failed = any(
            a["category"] in ("ENDPOINT_DOWN", "AI_UNREACHABLE", "AUTH_FAILURE")
            for a in enforcement_actions
        )
        pf_clean = pf_passed == pf_total
        if pct == 100 and not enforcement_actions and pf_clean:
            level, level_color = "GREEN", "#22c55e"
        elif has_failed or not pf_clean:
            level, level_color = "RED", "#ef4444"
        else:
            level, level_color = "YELLOW", "#eab308"

        # Pre-flight rows
        pf_color = "#22c55e" if pf_clean else "#ef4444"
        preflight_rows = ""
        for c in preflight:
            ic = "#22c55e" if c["pass"] else "#ef4444"
            icon = "PASS" if c["pass"] else "FAIL"
            preflight_rows += (
                f'<tr>'
                f'<td style="padding:4px 8px;color:{ic};font-weight:bold;font-size:11px;">'
                f'{icon}</td>'
                f'<td style="padding:4px 8px;color:#C9A962;font-size:11px;">'
                f'{c["label"]}</td>'
                f'<td style="padding:4px 8px;color:#94a3b8;font-size:10px;">'
                f'{c["detail"]}</td></tr>\n'
            )

        # Auditor rows
        auditor_rows = ""
        for atype in AUDITOR_ACTIVITY_TYPES:
            label = AUDITOR_LABELS.get(atype, atype)
            r = auditor_results.get(atype)
            if r:
                t, tot = r["trusted"], r["total"]
                apct = int((t / tot * 100) if tot else 0)
                c = "#22c55e" if t == tot else ("#eab308" if t > 0 else "#ef4444")
                bar_width = apct
                ts = r.get("timestamp", "")
                ts_str = ts.strftime("%H:%M UTC") if hasattr(ts, "strftime") else str(ts)[:16]
                auditor_rows += (
                    f'<tr>'
                    f'<td style="padding:6px 8px;color:#C9A962;font-weight:bold;font-size:12px;">'
                    f'{label}</td>'
                    f'<td style="padding:6px 8px;color:{c};font-weight:bold;font-size:12px;">'
                    f'{t}/{tot}</td>'
                    f'<td style="padding:6px 8px;"><div style="background:#1a1a1a;border-radius:4px;'
                    f'height:14px;width:120px;position:relative;">'
                    f'<div style="background:{c};height:14px;border-radius:4px;'
                    f'width:{bar_width}%;"></div></div></td>'
                    f'<td style="padding:6px 8px;color:{c};font-weight:bold;font-size:12px;">'
                    f'{apct}%</td>'
                    f'<td style="padding:6px 8px;color:#666;font-size:10px;">{ts_str}</td>'
                    f'</tr>\n'
                )
            else:
                auditor_rows += (
                    f'<tr>'
                    f'<td style="padding:6px 8px;color:#C9A962;font-weight:bold;font-size:12px;">'
                    f'{label}</td>'
                    f'<td colspan="4" style="padding:6px 8px;color:#ef4444;font-size:11px;">'
                    f'NO DATA — auditor has not reported</td></tr>\n'
                )

        # Enforcement action rows
        action_rows = ""
        if enforcement_actions:
            for a in enforcement_actions:
                action_rows += (
                    f'<tr>'
                    f'<td style="padding:4px 8px;color:#ef4444;font-weight:bold;font-size:11px;">'
                    f'{a["category"]}</td>'
                    f'<td style="padding:4px 8px;color:#C9A962;font-size:11px;">'
                    f'{a["auditor"]}</td>'
                    f'<td style="padding:4px 8px;color:#94a3b8;font-size:10px;">'
                    f'{a["detail"]}</td></tr>\n'
                )
        else:
            action_rows = (
                '<tr><td colspan="3" style="padding:8px;color:#22c55e;text-align:center;'
                'font-size:12px;">No enforcement actions needed — all systems nominal</td></tr>\n'
            )

        # Proposal rows
        proposal_rows = ""
        if pending_proposals:
            for p in pending_proposals:
                proposal_rows += (
                    f'<tr><td style="padding:4px 8px;color:#eab308;font-size:11px;">'
                    f'#{p.get("id")} — {p.get("parameter_key")}</td>'
                    f'<td style="padding:4px 8px;color:#94a3b8;font-size:10px;">'
                    f'{p.get("reason", "No reason given")}</td>'
                    f'<td style="padding:4px 8px;color:#666;font-size:10px;">'
                    f'{p.get("proposed_by")}</td></tr>\n'
                )
        else:
            proposal_rows = (
                '<tr><td colspan="3" style="padding:8px;color:#666;text-align:center;'
                'font-size:11px;">No pending baseline proposals</td></tr>\n'
            )

        return f"""
<div style="font-family:'DM Sans',Arial,sans-serif;max-width:800px;margin:0 auto;
background:#0A0A0A;color:#e2e8f0;border:1px solid #222;border-radius:8px;overflow:hidden;">
  <div style="background:#050505;padding:16px 20px;border-bottom:1px solid #222;">
    <h2 style="margin:0;color:#C9A962;font-size:20px;">Trust Enforcement Report</h2>
    <p style="margin:4px 0 0;color:#94a3b8;font-size:12px;">
      {now.strftime('%A, %B %d %Y at %H:%M UTC')} — 17 Auditors, {total_tests} Total Tests
    </p>
  </div>
  <div style="padding:16px 20px;background:#111;border-bottom:1px solid #222;">
    <span style="color:{level_color};font-weight:bold;font-size:22px;">{pct}%</span>
    <span style="color:#94a3b8;font-size:14px;"> Overall Trust — </span>
    <span style="background:{level_color};color:#000;padding:2px 10px;border-radius:4px;
    font-weight:bold;font-size:12px;">{level}</span>
    <span style="color:#94a3b8;font-size:12px;margin-left:10px;">
    {total_trusted}/{total_tests} TRUSTED</span>
    <span style="color:#94a3b8;font-size:12px;margin-left:10px;">|</span>
    <span style="color:{pf_color};font-size:12px;margin-left:10px;">
    Pre-flight {pf_passed}/{pf_total}</span>
  </div>

  <div style="padding:8px 20px;border-bottom:1px solid #222;">
    <h3 style="margin:8px 0 4px;color:#C9A962;font-size:14px;">
    Pre-flight Checks ({pf_passed}/{pf_total})</h3>
  </div>
  <table style="width:100%;border-collapse:collapse;">{preflight_rows}</table>

  <div style="padding:8px 20px;border-bottom:1px solid #222;border-top:1px solid #222;">
    <h3 style="margin:8px 0 4px;color:#C9A962;font-size:14px;">Auditor Breakdown</h3>
  </div>
  <table style="width:100%;border-collapse:collapse;">{auditor_rows}</table>

  <div style="padding:8px 20px;border-bottom:1px solid #222;border-top:1px solid #222;">
    <h3 style="margin:8px 0 4px;color:#C9A962;font-size:14px;">
    Enforcement Actions ({len(enforcement_actions)})</h3>
  </div>
  <table style="width:100%;border-collapse:collapse;">{action_rows}</table>

  <div style="padding:8px 20px;border-bottom:1px solid #222;border-top:1px solid #222;">
    <h3 style="margin:8px 0 4px;color:#C9A962;font-size:14px;">
    Pending Baseline Proposals ({len(pending_proposals)})</h3>
  </div>
  <table style="width:100%;border-collapse:collapse;">{proposal_rows}</table>

  <div style="padding:12px 20px;border-top:1px solid #222;text-align:center;">
    <span style="color:#666;font-size:10px;">Sovereign Sanctuary — Trust Enforcer v3</span>
  </div>
</div>"""

    def _render_alert_html(self, auditor_results: dict,
                           enforcement_actions: list, preflight: list,
                           now: datetime, total_trusted: int, total_tests: int,
                           pct: int, pf_passed: int, pf_total: int,
                           level: str) -> str:
        """Render a concise alert email showing ONLY items that need attention."""
        level_color = "#ef4444" if level == "RED" else "#eab308"

        # Failed pre-flights
        pf_rows = ""
        failed_pf = [c for c in preflight if not c["pass"]]
        for c in failed_pf:
            pf_rows += (
                f'<tr>'
                f'<td style="padding:4px 8px;color:#ef4444;font-weight:bold;font-size:11px;">'
                f'FAIL</td>'
                f'<td style="padding:4px 8px;color:#C9A962;font-size:11px;">'
                f'{c["label"]}</td>'
                f'<td style="padding:4px 8px;color:#94a3b8;font-size:10px;">'
                f'{c["detail"]}</td></tr>\n'
            )

        # Auditors that are not 100%
        bad_auditor_rows = ""
        for atype in AUDITOR_ACTIVITY_TYPES:
            label = AUDITOR_LABELS.get(atype, atype)
            r = auditor_results.get(atype)
            if r is None:
                bad_auditor_rows += (
                    f'<tr>'
                    f'<td style="padding:6px 8px;color:#C9A962;font-weight:bold;font-size:12px;">'
                    f'{label}</td>'
                    f'<td colspan="2" style="padding:6px 8px;color:#ef4444;font-size:11px;">'
                    f'NO DATA — auditor has not reported</td></tr>\n'
                )
            elif r["trusted"] < r["total"]:
                t, tot = r["trusted"], r["total"]
                deficit = tot - t
                c = "#eab308" if t > 0 else "#ef4444"
                bad_auditor_rows += (
                    f'<tr>'
                    f'<td style="padding:6px 8px;color:#C9A962;font-weight:bold;font-size:12px;">'
                    f'{label}</td>'
                    f'<td style="padding:6px 8px;color:{c};font-weight:bold;font-size:12px;">'
                    f'{t}/{tot}</td>'
                    f'<td style="padding:6px 8px;color:{c};font-size:11px;">'
                    f'{deficit} endpoint(s) failing</td></tr>\n'
                )

        # Enforcement action rows
        action_rows = ""
        for a in enforcement_actions:
            cat = a["category"]
            cat_color = "#ef4444" if cat in ("ENDPOINT_DOWN", "AI_UNREACHABLE",
                                              "PREFLIGHT_FAIL") else "#eab308"
            action_rows += (
                f'<tr>'
                f'<td style="padding:4px 8px;color:{cat_color};font-weight:bold;font-size:11px;">'
                f'{cat}</td>'
                f'<td style="padding:4px 8px;color:#C9A962;font-size:11px;">'
                f'{a["auditor"]}</td>'
                f'<td style="padding:4px 8px;color:#94a3b8;font-size:10px;">'
                f'{a["detail"]}</td></tr>\n'
            )

        pf_section = ""
        if failed_pf:
            pf_section = f"""
  <div style="padding:8px 20px;border-bottom:1px solid #333;">
    <h3 style="margin:8px 0 4px;color:#ef4444;font-size:14px;">
    Failed Pre-flight Checks ({len(failed_pf)})</h3>
  </div>
  <table style="width:100%;border-collapse:collapse;">{pf_rows}</table>"""

        return f"""
<div style="font-family:'DM Sans',Arial,sans-serif;max-width:700px;margin:0 auto;
background:#0A0A0A;color:#e2e8f0;border:2px solid {level_color};border-radius:8px;overflow:hidden;">
  <div style="background:{level_color};padding:16px 20px;">
    <h2 style="margin:0;color:#000;font-size:20px;font-weight:bold;">
    TRUST ALERT — {level}</h2>
    <p style="margin:4px 0 0;color:#000;font-size:12px;">
      {now.strftime('%A, %B %d %Y at %H:%M UTC')} —
      {total_trusted}/{total_tests} TRUSTED ({pct}%) —
      Pre-flight {pf_passed}/{pf_total}
    </p>
  </div>
  <div style="padding:12px 20px;background:#111;border-bottom:1px solid #333;">
    <span style="color:#94a3b8;font-size:13px;">
      {len(enforcement_actions)} enforcement action(s) detected.
      The full Sovereign Trust Report has been sent separately.
    </span>
  </div>{pf_section}
  <div style="padding:8px 20px;border-bottom:1px solid #333;border-top:1px solid #333;">
    <h3 style="margin:8px 0 4px;color:#C9A962;font-size:14px;">
    Failing Auditors</h3>
  </div>
  <table style="width:100%;border-collapse:collapse;">{bad_auditor_rows}</table>

  <div style="padding:8px 20px;border-bottom:1px solid #333;border-top:1px solid #333;">
    <h3 style="margin:8px 0 4px;color:#C9A962;font-size:14px;">
    Enforcement Actions ({len(enforcement_actions)})</h3>
  </div>
  <table style="width:100%;border-collapse:collapse;">{action_rows}</table>

  <div style="padding:12px 20px;border-top:1px solid #333;text-align:center;">
    <span style="color:#666;font-size:10px;">
    Sovereign Sanctuary — Trust Alert — investigate immediately</span>
  </div>
</div>"""

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
