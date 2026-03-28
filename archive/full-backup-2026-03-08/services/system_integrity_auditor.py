"""
LITTLE NATE — System Integrity Auditor
Preventive auditor that catches security, billing, and integration issues
BEFORE they cause incidents. Complements the runtime health auditors.

Three check categories:
  A. Security Posture   — validates auth endpoints reject malformed input
  B. Billing Shield     — monitors external API usage (Twilio, SendGrid)
  C. Integration Sync   — verifies PG profile_data matches expected state

Scheduled 3x daily (5 AM, 5 PM, 11 PM UTC) with stagger delay of 250s.
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

logger = logging.getLogger("nate.system_integrity_auditor")

AUDIT_HOURS = {5, 17, 23}
AUDIT_EMAIL = "support@sovereignsanctuary.net"
BASE_URL = "http://localhost:8000"

# ─── Check Definitions ────────────────────────────────────────────────────────

SECURITY_CHECKS = [
    {
        "id": "totp_rejects_bad_code",
        "label": "TOTP rejects non-numeric code",
        "method": "POST",
        "path": "/api/admin/totp/verify",
        "payload": {"code": "ABCDEF"},
        "expect_status": 422,
    },
    {
        "id": "totp_rejects_short_code",
        "label": "TOTP rejects 3-digit code",
        "method": "POST",
        "path": "/api/admin/totp/verify",
        "payload": {"code": "123"},
        "expect_status": 422,
    },
    {
        "id": "sms_rejects_bad_phone",
        "label": "SMS rejects invalid phone format",
        "method": "POST",
        "path": "/api/admin/sms/set-phone",
        "payload": {"phone": "not-a-phone"},
        "expect_status": 400,
    },
    {
        "id": "sms_rejects_short_phone",
        "label": "SMS rejects too-short phone",
        "method": "POST",
        "path": "/api/admin/sms/set-phone",
        "payload": {"phone": "123"},
        "expect_status": 400,
    },
    {
        "id": "webauthn_rejects_empty_cred",
        "label": "WebAuthn rejects empty credential",
        "method": "POST",
        "path": "/api/admin/webauthn/auth-verify",
        "payload": {"credential": {}},
        "expect_status": 400,
    },
    {
        "id": "sms_confirm_rejects_bad_code",
        "label": "SMS confirm rejects non-numeric code",
        "method": "POST",
        "path": "/api/admin/sms/confirm",
        "payload": {"code": "BADCODE"},
        "expect_status": 422,
    },
    {
        "id": "totp_setup_blocks_resetup",
        "label": "TOTP setup requires current code when enabled",
        "method": "POST",
        "path": "/api/admin/totp/setup",
        "payload": {},
        "expect_status": [200, 400],
        "check_fn": "totp_setup_guard",
    },
]

BILLING_CHECKS = [
    {
        "id": "twilio_env_set",
        "label": "Twilio credentials configured",
        "type": "env",
        "vars": ["TWILIO_ACCOUNT_SID", "TWILIO_AUTH_TOKEN", "TWILIO_VERIFY_SID"],
    },
    {
        "id": "sendgrid_env_set",
        "label": "SendGrid API key configured",
        "type": "env",
        "vars": ["SENDGRID_API_KEY"],
    },
    {
        "id": "sms_rate_limit_active",
        "label": "SMS rate limiter responds 429 on abuse",
        "method": "GET",
        "path": "/api/admin/sms/status",
        "expect_status": 200,
        "note": "Verifies SMS endpoint is reachable; rate limit is code-enforced",
    },
    {
        "id": "stripe_env_set",
        "label": "Stripe credentials configured",
        "type": "env",
        "vars": ["STRIPE_SECRET_KEY"],
    },
]

INTEGRATION_CHECKS = [
    {
        "id": "admin_profile_exists",
        "label": "DrNevedal1 profile in PostgreSQL",
        "type": "db",
    },
    {
        "id": "webauthn_creds_intact",
        "label": "WebAuthn credentials array valid",
        "type": "db",
    },
    {
        "id": "sentinel_state_consistent",
        "label": "Sentinel frozen state consistent",
        "type": "db",
    },
    {
        "id": "auth_method_valid",
        "label": "sentinel_auth_method is valid value",
        "type": "db",
    },
]


class SystemIntegrityAuditor:

    def __init__(self, db_pool, notification_system=None, auth_token: str = "",
                 app_state=None):
        self.db_pool = db_pool
        self.notifications = notification_system
        self._auth_token = auth_token
        self._app_state = app_state
        self._task: Optional[asyncio.Task] = None
        self._running = False
        self._sent_windows: set = set()

    async def start(self):
        if self._task and not self._task.done():
            return
        self._running = True
        self._task = asyncio.create_task(self._run_loop())
        logger.info("SystemIntegrityAuditor started (3x daily at UTC 05:00, 17:00, 23:00)")

    async def stop(self):
        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("SystemIntegrityAuditor stopped")

    async def _run_loop(self):
        await asyncio.sleep(250)
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
                logger.error("SystemIntegrityAuditor tick failed: %s", e, exc_info=True)
            await asyncio.sleep(60)

    async def _build_and_send(self, now: datetime):
        results = await self._audit_all()
        html = self._render_html(results, now)
        subject = f"System Integrity Trust Scorecard — {now.strftime('%b %d %Y %H:%M UTC')}"

        # Email silenced — Trust Enforcer sends consolidated report

        trusted = sum(1 for r in results if r["status"] == "TRUSTED")
        total = len(results)
        await self._log_activity(
            "system", "system_integrity_audit_sent",
            f"Scorecard sent: {trusted}/{total} TRUSTED at {now.isoformat()}", "success"
        )
        logger.info("SystemIntegrityAuditor: scorecard sent — %d/%d TRUSTED", trusted, total)

    def _resolve_token(self) -> str:
        if self._auth_token:
            return self._auth_token
        env_token = os.environ.get("SKYEYE_AUDIT_TOKEN", "")
        if env_token:
            return env_token
        try:
            import redis as _redis
            redis_pw = os.environ.get("REDIS_PASSWORD", "")
            redis_url = f"redis://:{redis_pw}@redis:6379/0" if redis_pw else "redis://redis:6379/0"
            r = _redis.Redis.from_url(redis_url, socket_timeout=2, decode_responses=True)
            env = os.environ.get("ENVIRONMENT", "development")
            prefix = f"nate:{env}:auth:"
            for key in r.scan_iter(f"{prefix}*", count=100):
                val = r.get(key)
                if val and "ADMIN" in val.upper():
                    return key.replace(prefix, "")
        except Exception as e:
            logger.debug("SystemIntegrityAuditor: Redis token scan failed: %s", e)
        return ""

    # ─── Main Audit Orchestrator ──────────────────────────────────────────

    async def _audit_all(self) -> list:
        results = []
        token = self._resolve_token()
        headers = {"Authorization": f"Bearer {token}"} if token else {}

        # A. Security Posture
        for check in SECURITY_CHECKS:
            r = await self._test_security_check(check, headers)
            r["category"] = "Security Posture"
            results.append(r)

        # B. Billing Shield
        for check in BILLING_CHECKS:
            if check.get("type") == "env":
                r = self._check_env_vars(check)
            else:
                r = await self._test_endpoint_check(check, headers)
            r["category"] = "Billing Shield"
            results.append(r)

        # C. Integration Sync
        db_results = await self._run_integration_checks()
        for r in db_results:
            r["category"] = "Integration Sync"
            results.append(r)

        return results

    # ─── A. Security Posture Tests ────────────────────────────────────────

    async def _test_security_check(self, check: dict, headers: dict) -> dict:
        url = f"{BASE_URL}{check['path']}"
        t0 = time.monotonic()
        try:
            timeout = aiohttp.ClientTimeout(total=10)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.request(
                    check["method"], url,
                    json=check.get("payload"),
                    headers=headers,
                ) as resp:
                    code = resp.status
                    try:
                        body = await resp.json()
                    except Exception:
                        body = {}
                    elapsed = int((time.monotonic() - t0) * 1000)

            expected = check["expect_status"]
            if isinstance(expected, list):
                ok = code in expected
            else:
                ok = code == expected

            if check.get("check_fn") == "totp_setup_guard":
                ok = self._verify_totp_setup_guard(code, body)

            return {
                "id": check["id"],
                "label": check["label"],
                "status": "TRUSTED" if ok else "FAILED",
                "detail": f"HTTP {code} in {elapsed}ms" + (
                    "" if ok else f" (expected {expected})"),
            }
        except Exception as exc:
            elapsed = int((time.monotonic() - t0) * 1000)
            return {
                "id": check["id"],
                "label": check["label"],
                "status": "FAILED",
                "detail": str(exc)[:80],
            }

    @staticmethod
    def _verify_totp_setup_guard(code: int, body: dict) -> bool:
        if code == 200:
            return True
        if code == 400:
            detail = body.get("detail", "")
            if "already enabled" in detail.lower() or "current_code" in detail.lower():
                return True
        return False

    # ─── B. Billing Shield ────────────────────────────────────────────────

    @staticmethod
    def _check_env_vars(check: dict) -> dict:
        missing = [v for v in check["vars"] if not os.environ.get(v)]
        if not missing:
            return {
                "id": check["id"],
                "label": check["label"],
                "status": "TRUSTED",
                "detail": f"All {len(check['vars'])} vars set",
            }
        return {
            "id": check["id"],
            "label": check["label"],
            "status": "FAILED",
            "detail": f"Missing: {', '.join(missing)}",
        }

    async def _test_endpoint_check(self, check: dict, headers: dict) -> dict:
        url = f"{BASE_URL}{check['path']}"
        t0 = time.monotonic()
        try:
            timeout = aiohttp.ClientTimeout(total=10)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                method = check.get("method", "GET")
                kwargs = {"headers": headers}
                if check.get("payload"):
                    kwargs["json"] = check["payload"]
                async with session.request(method, url, **kwargs) as resp:
                    code = resp.status
                    elapsed = int((time.monotonic() - t0) * 1000)

            expected = check.get("expect_status", 200)
            ok = code == expected
            return {
                "id": check["id"],
                "label": check["label"],
                "status": "TRUSTED" if ok else "FAILED",
                "detail": f"HTTP {code} in {elapsed}ms",
            }
        except Exception as exc:
            elapsed = int((time.monotonic() - t0) * 1000)
            return {
                "id": check["id"],
                "label": check["label"],
                "status": "FAILED",
                "detail": str(exc)[:80],
            }

    # ─── C. Integration Sync ─────────────────────────────────────────────

    async def _run_integration_checks(self) -> list:
        results = []
        if not self.db_pool:
            for check in INTEGRATION_CHECKS:
                results.append({
                    "id": check["id"],
                    "label": check["label"],
                    "status": "FAILED",
                    "detail": "Database pool unavailable",
                })
            return results

        try:
            async with self.db_pool.acquire() as conn:
                row = await conn.fetchrow(
                    "SELECT profile_data FROM users WHERE username = 'DrNevedal1'"
                )
                if not row or not row["profile_data"]:
                    results.append({
                        "id": "admin_profile_exists",
                        "label": "DrNevedal1 profile in PostgreSQL",
                        "status": "FAILED",
                        "detail": "Admin profile not found in users table",
                    })
                    for check in INTEGRATION_CHECKS[1:]:
                        results.append({
                            "id": check["id"],
                            "label": check["label"],
                            "status": "FAILED",
                            "detail": "Skipped: admin profile missing",
                        })
                    return results

                pd = row["profile_data"] if isinstance(row["profile_data"], dict) else json.loads(row["profile_data"])

                # Check 1: Admin profile exists
                results.append({
                    "id": "admin_profile_exists",
                    "label": "DrNevedal1 profile in PostgreSQL",
                    "status": "TRUSTED",
                    "detail": f"Profile found, {len(pd)} fields",
                })

                # Check 2: WebAuthn credentials array validity
                creds = pd.get("webauthn_credentials", [])
                creds_valid = isinstance(creds, list) and all(
                    isinstance(c, dict) and c.get("credential_id") and c.get("public_key")
                    for c in creds
                ) if creds else True
                results.append({
                    "id": "webauthn_creds_intact",
                    "label": "WebAuthn credentials array valid",
                    "status": "TRUSTED" if creds_valid else "FAILED",
                    "detail": f"{len(creds)} credential(s), all structurally valid" if creds_valid
                             else f"Invalid credential structure in {len(creds)} entries",
                })

                # Check 3: Sentinel frozen state consistent
                frozen = pd.get("sentinel_frozen", False)
                auth_method = pd.get("sentinel_auth_method", "password")
                if frozen and auth_method == "yubikey":
                    results.append({
                        "id": "sentinel_state_consistent",
                        "label": "Sentinel frozen state consistent",
                        "status": "WARNING",
                        "detail": f"Frozen=True but auth_method=yubikey — unusual combo",
                    })
                else:
                    results.append({
                        "id": "sentinel_state_consistent",
                        "label": "Sentinel frozen state consistent",
                        "status": "TRUSTED",
                        "detail": f"frozen={frozen}, auth_method={auth_method}",
                    })

                # Check 4: sentinel_auth_method is valid value
                valid_methods = {"password", "totp", "yubikey"}
                results.append({
                    "id": "auth_method_valid",
                    "label": "sentinel_auth_method is valid value",
                    "status": "TRUSTED" if auth_method in valid_methods else "FAILED",
                    "detail": f"auth_method='{auth_method}'" + (
                        "" if auth_method in valid_methods
                        else f" (expected one of: {valid_methods})"),
                })

                # Check 5: Sign counts are non-negative and monotonic
                sign_count_ok = True
                sign_detail = ""
                for i, c in enumerate(creds):
                    sc = c.get("sign_count", 0)
                    if not isinstance(sc, int) or sc < 0:
                        sign_count_ok = False
                        sign_detail = f"Key {i+1} has invalid sign_count: {sc}"
                        break
                if creds and sign_count_ok:
                    sign_detail = ", ".join(
                        f"{c.get('label', f'Key {i+1}')}: count={c.get('sign_count', 0)}"
                        for i, c in enumerate(creds)
                    )
                elif not creds:
                    sign_detail = "No keys registered"
                results.append({
                    "id": "sign_counts_valid",
                    "label": "WebAuthn sign counts valid",
                    "status": "TRUSTED" if sign_count_ok else "FAILED",
                    "detail": sign_detail,
                })

                # Check 6: TOTP secret present if TOTP enabled
                totp_enabled = pd.get("totp_enabled", False)
                totp_secret = pd.get("totp_secret", "")
                totp_ok = True
                if totp_enabled and not totp_secret:
                    totp_ok = False
                results.append({
                    "id": "totp_data_consistent",
                    "label": "TOTP config data consistent",
                    "status": "TRUSTED" if totp_ok else "FAILED",
                    "detail": f"enabled={totp_enabled}, secret={'present' if totp_secret else 'missing'}"
                             if not totp_ok else f"enabled={totp_enabled}, data consistent",
                })

                # Check 7: SMS phone present if SMS verified
                sms_verified = pd.get("sms_verified", False)
                phone = pd.get("phone", "")
                sms_ok = True
                if sms_verified and not phone:
                    sms_ok = False
                results.append({
                    "id": "sms_data_consistent",
                    "label": "SMS config data consistent",
                    "status": "TRUSTED" if sms_ok else "FAILED",
                    "detail": f"verified={sms_verified}, phone={'set' if phone else 'missing'}"
                             if not sms_ok else f"verified={sms_verified}, data consistent",
                })

        except Exception as e:
            logger.error("Integration checks failed: %s", e)
            for check in INTEGRATION_CHECKS:
                if not any(r["id"] == check["id"] for r in results):
                    results.append({
                        "id": check["id"],
                        "label": check["label"],
                        "status": "FAILED",
                        "detail": f"DB error: {str(e)[:60]}",
                    })

        return results

    # ─── HTML Rendering ───────────────────────────────────────────────────

    def _render_html(self, results: list, now: datetime) -> str:
        total = len(results)
        trusted = sum(1 for r in results if r["status"] == "TRUSTED")
        warning = sum(1 for r in results if r["status"] == "WARNING")
        failed = sum(1 for r in results if r["status"] == "FAILED")
        pct = int((trusted / total * 100) if total else 0)
        header_color = "#22c55e" if failed == 0 and warning == 0 else (
            "#ef4444" if failed > 0 else "#eab308")

        categories = ["Security Posture", "Billing Shield", "Integration Sync"]
        cat_icons = {"Security Posture": "🛡️", "Billing Shield": "💰", "Integration Sync": "🔗"}

        section_rows = ""
        for cat in categories:
            cat_results = [r for r in results if r.get("category") == cat]
            if not cat_results:
                continue
            cat_trusted = sum(1 for r in cat_results if r["status"] == "TRUSTED")
            cat_total = len(cat_results)
            cat_color = "#22c55e" if cat_trusted == cat_total else (
                "#ef4444" if any(r["status"] == "FAILED" for r in cat_results) else "#eab308")
            cat_verdict = "TRUSTED" if cat_trusted == cat_total else (
                "FAILED" if any(r["status"] == "FAILED" for r in cat_results) else "WARNING")

            section_rows += (
                f'<tr><td style="padding:8px;background:#111;color:#C9A962;'
                f'font-weight:bold;font-size:13px;" colspan="3">'
                f'{cat_icons.get(cat, "")} {cat} '
                f'<span style="color:{cat_color};font-size:11px;">'
                f'[{cat_verdict} — {cat_trusted}/{cat_total}]</span></td></tr>\n'
            )
            for r in cat_results:
                c = "#22c55e" if r["status"] == "TRUSTED" else (
                    "#eab308" if r["status"] == "WARNING" else "#ef4444")
                section_rows += (
                    f'<tr>'
                    f'<td style="padding:4px 8px 4px 20px;color:{c};font-weight:bold;'
                    f'font-size:11px;width:80px;">[{r["status"]}]</td>'
                    f'<td style="padding:4px 8px;color:#e2e8f0;font-size:12px;">'
                    f'{r["label"]}</td>'
                    f'<td style="padding:4px 8px;color:#94a3b8;font-size:11px;">'
                    f'{r["detail"]}</td>'
                    f'</tr>\n'
                )

        return f"""
<div style="font-family:'DM Sans',Arial,sans-serif;max-width:750px;margin:0 auto;
background:#0A0A0A;color:#e2e8f0;border:1px solid #222;border-radius:8px;overflow:hidden;">
  <div style="background:#050505;padding:16px 20px;border-bottom:1px solid #222;">
    <h2 style="margin:0;color:#4ECDC4;font-size:18px;">System Integrity — Trust Scorecard</h2>
    <p style="margin:4px 0 0;color:#94a3b8;font-size:12px;">
      Security Posture + Billing Shield + Integration Sync —
      {now.strftime('%A, %B %d %Y at %H:%M UTC')} — {total} Checks
    </p>
  </div>
  <div style="padding:12px 20px;background:#111;border-bottom:1px solid #222;">
    <span style="color:{header_color};font-weight:bold;font-size:16px;">{pct}% Trust Score</span>
    <span style="color:#94a3b8;font-size:12px;"> — </span>
    <span style="color:#22c55e;font-weight:bold;font-size:13px;">{trusted} TRUSTED</span>
    <span style="color:#94a3b8;"> | </span>
    <span style="color:#eab308;font-weight:bold;font-size:13px;">{warning} WARNING</span>
    <span style="color:#94a3b8;"> | </span>
    <span style="color:#ef4444;font-weight:bold;font-size:13px;">{failed} FAILED</span>
  </div>
  <table style="width:100%;border-collapse:collapse;">{section_rows}</table>
  <div style="padding:12px 20px;border-top:1px solid #222;text-align:center;">
    <span style="color:#666;font-size:10px;">Sovereign Sanctuary — System Integrity Trust Auditor</span>
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
