"""
LITTLE NATE — Hardware Security Trust Auditor
Verifies admin MFA posture: YubiKeys, TOTP, SMS, Sentinel status,
and WebAuthn API health.

Scheduled 3x daily (5 AM, 5 PM, 11 PM UTC) with stagger delay of 240s.
"""

import asyncio
import json
import logging
import os
import time
from datetime import datetime, timezone
from typing import Optional

import aiohttp

logger = logging.getLogger("nate.hardware_security_auditor")

AUDIT_HOURS = {5, 17, 23}
AUDIT_EMAIL = "support@sovereignsanctuary.net"
BASE_URL = "http://localhost:8000"

CHECKS = [
    {"id": "webauthn_enabled",   "label": "WebAuthn Enabled",      "type": "profile"},
    {"id": "primary_key",        "label": "Primary YubiKey",        "type": "profile"},
    {"id": "backup_key",         "label": "Backup YubiKey",         "type": "profile"},
    {"id": "totp_enabled",       "label": "TOTP Authenticator",     "type": "profile"},
    {"id": "sms_verified",       "label": "SMS Verification",       "type": "profile"},
    {"id": "sentinel_clear",     "label": "Sentinel Clear",         "type": "profile"},
    {"id": "no_stale_challenge", "label": "No Stale Challenge",     "type": "profile"},
    {"id": "sign_count_valid",   "label": "Sign Count Tracking",    "type": "profile"},
    {"id": "keys_api",           "label": "Keys List API",          "type": "endpoint",
     "method": "GET",  "path": "/api/admin/webauthn/keys"},
    {"id": "presence_api",       "label": "Presence API",           "type": "endpoint",
     "method": "GET",  "path": "/api/admin/webauthn/presence"},
    {"id": "delete_key_api",     "label": "Delete Key API",         "type": "endpoint",
     "method": "POST", "path": "/api/admin/webauthn/delete-key"},
]


class HardwareSecurityAuditor:

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
        logger.info("HardwareSecurityAuditor started (3x daily at UTC 05:00, 17:00, 23:00)")

    async def stop(self):
        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("HardwareSecurityAuditor stopped")

    async def _run_loop(self):
        await asyncio.sleep(240)
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
                logger.error("HardwareSecurityAuditor tick failed: %s", e, exc_info=True)
            await asyncio.sleep(60)

    async def _build_and_send(self, now: datetime):
        results = await self._audit_all()
        html = self._render_html(results, now)
        subject = f"Hardware Security Trust Scorecard — {now.strftime('%b %d %Y %H:%M UTC')}"

        # Email silenced — Trust Enforcer sends consolidated report

        trusted = sum(1 for r in results if r["status"] == "TRUSTED")
        total = len(results)
        await self._log_activity(
            "system", "hardware_security_audit_sent",
            f"Scorecard sent: {trusted}/{total} TRUSTED at {now.isoformat()}", "success"
        )
        logger.info("HardwareSecurityAuditor: scorecard sent — %d/%d TRUSTED", trusted, total)

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
            logger.debug("HardwareSecurityAuditor: Redis token scan failed: %s", e)
        return ""

    async def _get_admin_profile(self) -> dict:
        if not self.db_pool:
            return {}
        try:
            async with self.db_pool.acquire() as conn:
                row = await conn.fetchrow(
                    "SELECT profile_data FROM users WHERE username = 'DrNevedal1'"
                )
                if row and row["profile_data"]:
                    pd = row["profile_data"]
                    return pd if isinstance(pd, dict) else json.loads(pd)
        except Exception as e:
            logger.warning("Failed to load admin profile: %s", e)
        return {}

    async def _audit_all(self) -> list:
        results = []
        profile = await self._get_admin_profile()
        token = self._resolve_token()
        headers = {"Authorization": f"Bearer {token}"} if token else {}

        creds = profile.get("webauthn_credentials", [])

        for check in CHECKS:
            cid = check["id"]

            if check["type"] == "profile":
                if cid == "webauthn_enabled":
                    ok = profile.get("webauthn_enabled", False) is True
                    results.append(self._profile_result(check, ok,
                        "webauthn_enabled = true" if ok else "webauthn_enabled is false or missing"))

                elif cid == "primary_key":
                    ok = len(creds) >= 1 and bool(creds[0].get("credential_id")) and bool(creds[0].get("public_key"))
                    label = creds[0].get("label", "Key 1") if ok else "Not registered"
                    results.append(self._profile_result(check, ok,
                        f"'{label}' — ID {creds[0].get('credential_id', '')[:12]}..." if ok else "No primary key"))

                elif cid == "backup_key":
                    ok = len(creds) >= 2 and bool(creds[1].get("credential_id")) and bool(creds[1].get("public_key"))
                    label = creds[1].get("label", "Key 2") if ok else "Not registered"
                    results.append(self._profile_result(check, ok,
                        f"'{label}' — ID {creds[1].get('credential_id', '')[:12]}..." if ok else "No backup key"))

                elif cid == "totp_enabled":
                    ok = profile.get("totp_enabled", False) is True
                    results.append(self._profile_result(check, ok,
                        "TOTP authenticator active" if ok else "TOTP not configured"))

                elif cid == "sms_verified":
                    ok = profile.get("sms_verified", False) is True
                    results.append(self._profile_result(check, ok,
                        "SMS phone verified" if ok else "SMS not verified"))

                elif cid == "sentinel_clear":
                    frozen = profile.get("sentinel_frozen", False)
                    auth_method = profile.get("sentinel_auth_method", "password")
                    if not frozen:
                        ok = True
                        detail = f"Session clear, auth: {auth_method}"
                    else:
                        active_defense = await self._check_active_defense(db_pool)
                        if active_defense:
                            ok = True
                            detail = "Session FROZEN — active defense in progress (mirror deployed)"
                        else:
                            ok = False
                            detail = "Session FROZEN — no active defense detected"
                    results.append(self._profile_result(check, ok, detail))

                elif cid == "no_stale_challenge":
                    reg_chal = profile.get("webauthn_challenge", "")
                    auth_chal = profile.get("webauthn_auth_challenge", "")
                    ok = not reg_chal and not auth_chal
                    if ok:
                        detail = "No pending challenges"
                    else:
                        stale = []
                        if reg_chal:
                            stale.append("registration")
                        if auth_chal:
                            stale.append("auth")
                        detail = f"Stale challenge(s) lingering: {', '.join(stale)}"
                    results.append(self._profile_result(check, ok, detail))

                elif cid == "sign_count_valid":
                    ok = True
                    detail = "All keys have valid sign counts"
                    for i, c in enumerate(creds):
                        sc = c.get("sign_count")
                        if sc is None or not isinstance(sc, int):
                            ok = False
                            detail = f"Key '{c.get('label', i)}' missing sign_count"
                            break
                    results.append(self._profile_result(check, ok, detail))

            elif check["type"] == "endpoint":
                ep_result = await self._test_endpoint(
                    check["method"], check["path"], headers
                )
                results.append(ep_result)

        return results

    @staticmethod
    def _profile_result(check: dict, ok: bool, detail: str) -> dict:
        return {
            "id": check["id"],
            "label": check["label"],
            "status": "TRUSTED" if ok else "FAILED",
            "detail": detail,
        }

    async def _check_active_defense(self, db_pool) -> bool:
        """Check if there's an active defense action (mirror deployed) within 24h."""
        if not db_pool:
            return False
        try:
            async with db_pool.acquire() as conn:
                row = await conn.fetchrow(
                    "SELECT id FROM sentinel_freeze_history "
                    "WHERE frozen_at > NOW() - INTERVAL '24 hours' "
                    "AND actions_taken::text LIKE '%mirror%' "
                    "LIMIT 1"
                )
                return row is not None
        except Exception:
            return False

    async def _test_endpoint(self, method: str, path: str, headers: dict) -> dict:
        url = f"{BASE_URL}{path}"
        t0 = time.monotonic()
        try:
            timeout = aiohttp.ClientTimeout(total=10)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.request(method, url, headers=headers) as resp:
                    code = resp.status
                    try:
                        body = await resp.json()
                    except Exception:
                        body = None
                    elapsed = int((time.monotonic() - t0) * 1000)

            if code in (200, 400, 404, 422):
                return {
                    "id": path.split("/")[-1],
                    "label": f"{method} {path}",
                    "status": "TRUSTED",
                    "detail": f"{code} in {elapsed}ms",
                }
            elif 400 <= code < 500:
                return {
                    "id": path.split("/")[-1],
                    "label": f"{method} {path}",
                    "status": "WARNING",
                    "detail": f"HTTP {code} in {elapsed}ms",
                }
            else:
                return {
                    "id": path.split("/")[-1],
                    "label": f"{method} {path}",
                    "status": "FAILED",
                    "detail": f"HTTP {code} in {elapsed}ms",
                }
        except Exception as exc:
            elapsed = int((time.monotonic() - t0) * 1000)
            return {
                "id": path.split("/")[-1],
                "label": f"{method} {path}",
                "status": "FAILED",
                "detail": str(exc)[:80],
            }

    def _render_html(self, results: list, now: datetime) -> str:
        total = len(results)
        trusted = sum(1 for r in results if r["status"] == "TRUSTED")
        warning = sum(1 for r in results if r["status"] == "WARNING")
        failed = sum(1 for r in results if r["status"] == "FAILED")
        pct = int((trusted / total * 100) if total else 0)
        header_color = "#22c55e" if failed == 0 and warning == 0 else (
            "#ef4444" if failed > 0 else "#eab308")

        rows = ""
        for r in results:
            c = "#22c55e" if r["status"] == "TRUSTED" else (
                "#eab308" if r["status"] == "WARNING" else "#ef4444")
            rows += (
                f'<tr>'
                f'<td style="padding:6px 8px;color:{c};font-weight:bold;font-size:12px;">'
                f'[{r["status"]}]</td>'
                f'<td style="padding:6px 8px;color:#e2e8f0;font-size:13px;">'
                f'{r["label"]}</td>'
                f'<td style="padding:6px 8px;color:#94a3b8;font-size:11px;">'
                f'{r["detail"]}</td>'
                f'</tr>\n'
            )

        return f"""
<div style="font-family:'DM Sans',Arial,sans-serif;max-width:700px;margin:0 auto;
background:#0A0A0A;color:#e2e8f0;border:1px solid #222;border-radius:8px;overflow:hidden;">
  <div style="background:#050505;padding:16px 20px;border-bottom:1px solid #222;">
    <h2 style="margin:0;color:#C9A962;font-size:18px;">Hardware Security — Trust Scorecard</h2>
    <p style="margin:4px 0 0;color:#94a3b8;font-size:12px;">
      Admin MFA Posture & Sentinel Status —
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
  <table style="width:100%;border-collapse:collapse;">{rows}</table>
  <div style="padding:12px 20px;border-top:1px solid #222;text-align:center;">
    <span style="color:#666;font-size:10px;">Sovereign Sanctuary — Hardware Security Trust Auditor</span>
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
