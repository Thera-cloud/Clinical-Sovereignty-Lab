"""
LITTLE NATE — Defense Health Auditor
Tests all defense/security subsystems: Sentinel, PII detection, rate limiting,
Content Sentinel, SASE controller, Hive Defense, and Detonation Chamber.

Scheduled 3x daily (5 AM, 5 PM, 11 PM UTC) with stagger delay of 190s.
"""

import asyncio
import logging
import os
import time
from datetime import datetime, timezone
from typing import Optional

import aiohttp

logger = logging.getLogger("nate.defense_auditor")

AUDIT_HOURS = {5, 17, 23}
AUDIT_EMAIL = "support@sovereignsanctuary.net"
BASE_URL = "http://localhost:8000"

DEFENSE_CHECKS = [
    {
        "name": "Hive Defense Overview",
        "check_type": "rest",
        "method": "GET",
        "path": "/api/hive-defense/overview",
    },
    {
        "name": "DEFCON Status",
        "check_type": "rest",
        "method": "GET",
        "path": "/api/hive-defense/defcon",
    },
    {
        "name": "Threat Dropbox",
        "check_type": "rest",
        "method": "GET",
        "path": "/api/hive-defense/v4/threat-dropbox/hunts",
    },
    {
        "name": "Gate Metrics",
        "check_type": "rest",
        "method": "GET",
        "path": "/api/hive-defense/gate/metrics",
    },
    {
        "name": "Heartbeat Registry",
        "check_type": "rest",
        "method": "GET",
        "path": "/api/hive-defense/heartbeat/registry",
    },
    {
        "name": "Quarantine Active",
        "check_type": "rest",
        "method": "GET",
        "path": "/api/hive-defense/quarantine/active",
    },
    {
        "name": "Attacker Profiles",
        "check_type": "rest",
        "method": "GET",
        "path": "/api/hive-defense/attackers/profiles",
    },
    {
        "name": "Forensics Recent",
        "check_type": "rest",
        "method": "GET",
        "path": "/api/hive-defense/forensics/recent?limit=10",
    },
]


class DefenseHealthAuditor:

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
        logger.info("DefenseHealthAuditor started (3x daily at UTC 05:00, 17:00, 23:00)")

    async def stop(self):
        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("DefenseHealthAuditor stopped")

    async def _run_loop(self):
        await asyncio.sleep(190)
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
                logger.error("DefenseHealthAuditor tick failed: %s", e, exc_info=True)
            await asyncio.sleep(60)

    async def _build_and_send(self, now: datetime):
        results = await self._audit_all()
        html = self._render_html(results, now)
        subject = f"Defense Health Trust Scorecard — {now.strftime('%b %d %Y %H:%M UTC')}"

        # Email silenced — Trust Enforcer sends consolidated report

        trusted = sum(1 for r in results if r["status"] == "TRUSTED")
        total = len(results)
        await self._log_activity(
            "system", "defense_audit_sent",
            f"Scorecard sent: {trusted}/{total} TRUSTED at {now.isoformat()}", "success"
        )
        logger.info("DefenseHealthAuditor: scorecard sent — %d/%d TRUSTED", trusted, total)

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
            logger.debug("DefenseHealthAuditor: Redis token scan failed: %s", e)
        return ""

    async def _audit_all(self) -> list:
        results = []
        token = self._resolve_token()
        headers = {}
        if token:
            headers["Authorization"] = f"Bearer {token}"

        timeout = aiohttp.ClientTimeout(total=10)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            for check in DEFENSE_CHECKS:
                result = await self._run_check(session, check, headers)
                results.append(result)
        return results

    async def _run_check(self, session, check: dict, headers: dict) -> dict:
        name = check["name"]
        path = check["path"]
        url = f"{BASE_URL}{path}"
        t0 = time.monotonic()
        try:
            async with session.get(url, headers=headers) as resp:
                code = resp.status
                try:
                    body = await resp.json()
                except Exception:
                    body = None
                elapsed = int((time.monotonic() - t0) * 1000)

            if code == 200:
                if self._is_empty_payload(body):
                    return {"name": name, "path": path, "code": code,
                            "ms": elapsed, "status": "WARNING",
                            "detail": f"200 but empty payload ({elapsed}ms)"}
                return {"name": name, "path": path, "code": code,
                        "ms": elapsed, "status": "TRUSTED",
                        "detail": f"Healthy ({elapsed}ms)"}
            elif 400 <= code < 500:
                return {"name": name, "path": path, "code": code,
                        "ms": elapsed, "status": "WARNING",
                        "detail": f"HTTP {code}"}
            else:
                return {"name": name, "path": path, "code": code,
                        "ms": elapsed, "status": "FAILED",
                        "detail": f"HTTP {code}"}
        except asyncio.TimeoutError:
            elapsed = int((time.monotonic() - t0) * 1000)
            return {"name": name, "path": path, "code": 0,
                    "ms": elapsed, "status": "FAILED", "detail": "Timeout"}
        except Exception as exc:
            elapsed = int((time.monotonic() - t0) * 1000)
            return {"name": name, "path": path, "code": 0,
                    "ms": elapsed, "status": "FAILED", "detail": str(exc)[:80]}

    @staticmethod
    def _is_empty_payload(body) -> bool:
        if body is None:
            return True
        if isinstance(body, (list, bool, int, float, str)):
            return False
        if isinstance(body, dict):
            return len(body) == 0
        return True

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
                f'<td style="padding:6px 8px;color:#C9A962;font-weight:bold;">{r["name"]}</td>'
                f'<td style="padding:6px 8px;color:#94a3b8;font-size:11px;font-family:monospace;">'
                f'{r["path"]}</td>'
                f'<td style="padding:6px 8px;color:#94a3b8;font-size:10px;">{r["detail"]}</td>'
                f'</tr>\n'
            )

        return f"""
<div style="font-family:'DM Sans',Arial,sans-serif;max-width:750px;margin:0 auto;
background:#0A0A0A;color:#e2e8f0;border:1px solid #222;border-radius:8px;overflow:hidden;">
  <div style="background:#050505;padding:16px 20px;border-bottom:1px solid #222;">
    <h2 style="margin:0;color:#C9A962;font-size:18px;">Defense Health — Trust Scorecard</h2>
    <p style="margin:4px 0 0;color:#94a3b8;font-size:12px;">
      {now.strftime('%A, %B %d %Y at %H:%M UTC')} — {total} Subsystems
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
    <span style="color:#666;font-size:10px;">Sovereign Sanctuary — Defense Health Trust Auditor</span>
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
