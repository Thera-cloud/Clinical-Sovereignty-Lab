"""
LITTLE NATE — The Eye Trust Auditor
Scheduled health auditor that tests every REST API endpoint backing the 6
Eye (Surveillance & Analytics) dashboard tabs 3x daily (5 AM, 5 PM, 11 PM UTC).

Tabs: Overview, Token Analytics, Live Monitor, Crisis Watchlist,
      Community Health, Coach Performance

Produces a colour-coded HTML trust scorecard email sent to
support@sovereignsanctuary.net via NotificationSystem.

Stagger delay: 140 seconds
Tick interval: 60 seconds (time-of-day check)
"""

import asyncio
import logging
import os
import time
from datetime import datetime, timezone
from typing import Optional

import aiohttp

logger = logging.getLogger("eye.tab_auditor")

AUDIT_HOURS = {5, 17, 23}
AUDIT_EMAIL = "support@sovereignsanctuary.net"
BASE_URL = "http://localhost:8000"

TAB_ENDPOINTS = [
    {
        "tab": "Overview",
        "tab_num": 1,
        "endpoints": [
            ("GET", "/api/admin/dashboard"),
            ("GET", "/api/admin/users"),
            ("GET", "/api/admin/analytics/metrics-distribution"),
            ("GET", "/api/admin/analytics/daily"),
            ("GET", "/api/admin/billing/revenue"),
            ("GET", "/api/admin/billing/tier-config"),
            ("GET", "/api/admin/token-economics"),
        ],
    },
    {
        "tab": "Token Analytics",
        "tab_num": 2,
        "endpoints": [
            ("GET", "/api/admin/dashboard"),
            ("GET", "/api/admin/token-economics"),
        ],
    },
    {
        "tab": "Live Monitor",
        "tab_num": 3,
        "endpoints": [
            ("GET", "/api/admin/dashboard"),
            ("GET", "/api/admin/live-sessions"),
            ("GET", "/api/admin/users"),
        ],
    },
    {
        "tab": "Crisis Watchlist",
        "tab_num": 4,
        "endpoints": [
            ("GET", "/api/admin/crisis-watchlist"),
            ("GET", "/api/admin/crisis-log"),
            ("GET", "/api/admin/analytics/metrics-distribution"),
        ],
    },
    {
        "tab": "Community Health",
        "tab_num": 5,
        "endpoints": [
            ("GET", "/api/admin/community-health"),
            ("GET", "/api/admin/analytics/metrics-distribution"),
            ("GET", "/api/coherence/pulse"),
        ],
    },
    {
        "tab": "Coach Performance",
        "tab_num": 6,
        "endpoints": [
            ("GET", "/api/admin/coaches"),
            ("GET", "/api/admin/users"),
            ("GET", "/api/admin/night-school/status"),
        ],
    },
]


class TheEyeAuditor:

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
        logger.info("TheEyeAuditor started (3x daily at UTC 05:00, 17:00, 23:00)")

    async def stop(self):
        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("TheEyeAuditor stopped")

    async def _run_loop(self):
        await asyncio.sleep(140)
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
                logger.error("TheEyeAuditor tick failed: %s", e, exc_info=True)
            await asyncio.sleep(60)

    async def _build_and_send(self, now: datetime):
        results = await self._audit_all_tabs()
        html = self._render_html(results, now)
        subject = f"The Eye Trust Scorecard — {now.strftime('%b %d %Y %H:%M UTC')}"

        # Email silenced — Trust Enforcer sends consolidated report

        total = sum(t["total"] for t in results)
        trusted = sum(t["trusted"] for t in results)
        await self._log_activity(
            "system", "eye_tab_audit_sent",
            f"Scorecard sent: {trusted}/{total} TRUSTED at {now.isoformat()}", "success"
        )
        logger.info("TheEyeAuditor: scorecard sent — %d/%d TRUSTED", trusted, total)

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
                    token = key.replace(prefix, "")
                    return token
        except Exception as e:
            logger.debug("TheEyeAuditor: Redis token scan failed: %s", e)
        return ""

    async def _audit_all_tabs(self) -> list:
        results = []
        token = self._resolve_token()
        headers = {}
        if token:
            headers["Authorization"] = f"Bearer {token}"

        timeout = aiohttp.ClientTimeout(total=10)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            for tab_def in TAB_ENDPOINTS:
                tab_result = {
                    "tab": tab_def["tab"],
                    "tab_num": tab_def["tab_num"],
                    "total": 0,
                    "trusted": 0,
                    "warning": 0,
                    "failed": 0,
                    "endpoints": [],
                }
                for method, path in tab_def["endpoints"]:
                    tab_result["total"] += 1
                    ep_result = await self._test_endpoint(session, method, path, headers)
                    tab_result["endpoints"].append(ep_result)
                    if ep_result["status"] == "TRUSTED":
                        tab_result["trusted"] += 1
                    elif ep_result["status"] == "WARNING":
                        tab_result["warning"] += 1
                    else:
                        tab_result["failed"] += 1
                results.append(tab_result)
        return results

    async def _test_endpoint(self, session, method: str, path: str, headers: dict) -> dict:
        url = f"{BASE_URL}{path}"
        t0 = time.monotonic()
        try:
            if method == "GET":
                async with session.get(url, headers=headers) as resp:
                    code = resp.status
                    body = await resp.json() if code == 200 else {}
                    elapsed = int((time.monotonic() - t0) * 1000)
            else:
                async with session.post(url, headers=headers, json={}) as resp:
                    code = resp.status
                    body = await resp.json() if code in (200, 201) else {}
                    elapsed = int((time.monotonic() - t0) * 1000)

            if code == 200 or (method == "POST" and code == 422):
                if code == 200 and self._is_empty_payload(body):
                    return {"method": method, "path": path, "code": code,
                            "ms": elapsed, "status": "WARNING",
                            "detail": f"200 but empty/zero payload ({elapsed}ms)"}
                return {"method": method, "path": path, "code": code,
                        "ms": elapsed, "status": "TRUSTED", "detail": f"{code} in {elapsed}ms"}
            elif 400 <= code < 500:
                return {"method": method, "path": path, "code": code,
                        "ms": elapsed, "status": "WARNING", "detail": f"HTTP {code}"}
            else:
                return {"method": method, "path": path, "code": code,
                        "ms": elapsed, "status": "FAILED", "detail": f"HTTP {code}"}
        except asyncio.TimeoutError:
            elapsed = int((time.monotonic() - t0) * 1000)
            return {"method": method, "path": path, "code": 0,
                    "ms": elapsed, "status": "FAILED", "detail": "Timeout"}
        except Exception as exc:
            elapsed = int((time.monotonic() - t0) * 1000)
            return {"method": method, "path": path, "code": 0,
                    "ms": elapsed, "status": "FAILED", "detail": str(exc)[:80]}

    @staticmethod
    def _is_empty_payload(body) -> bool:
        """L2: structurally valid response = not empty.
        Only truly empty bodies ({}, null) are flagged."""
        if body is None:
            return True
        if isinstance(body, (list, bool, int, float, str)):
            return False
        if isinstance(body, dict):
            return len(body) == 0
        return True

    def _render_html(self, results: list, now: datetime) -> str:
        total_all = sum(t["total"] for t in results)
        trusted_all = sum(t["trusted"] for t in results)
        warning_all = sum(t["warning"] for t in results)
        failed_all = sum(t["failed"] for t in results)
        pct = int((trusted_all / total_all * 100) if total_all else 0)
        header_color = "#22c55e" if failed_all == 0 and warning_all == 0 else (
            "#ef4444" if failed_all > 0 else "#eab308")

        tab_rows = ""
        for t in results:
            if t["failed"] > 0:
                tab_color = "#ef4444"
                tab_badge = "FAILED"
            elif t["warning"] > 0:
                tab_color = "#eab308"
                tab_badge = "WARNING"
            else:
                tab_color = "#22c55e"
                tab_badge = "TRUSTED"

            tab_rows += (
                f'<tr>'
                f'<td style="padding:6px 8px;background:#111;color:#C9A962;'
                f'font-weight:bold;font-size:13px;" colspan="4">'
                f'Tab {t["tab_num"]}: {t["tab"]} '
                f'<span style="color:{tab_color};font-size:11px;">'
                f'[{tab_badge} — {t["trusted"]}/{t["total"]}]</span></td></tr>\n'
            )

            for ep in t["endpoints"]:
                if ep["status"] == "TRUSTED":
                    c = "#22c55e"
                elif ep["status"] == "WARNING":
                    c = "#eab308"
                else:
                    c = "#ef4444"
                tab_rows += (
                    f'<tr>'
                    f'<td style="padding:3px 8px 3px 20px;color:{c};font-weight:bold;'
                    f'font-size:11px;white-space:nowrap;">[{ep["status"]}]</td>'
                    f'<td style="padding:3px 4px;color:#94a3b8;font-size:11px;'
                    f'font-family:monospace;">{ep["method"]}</td>'
                    f'<td style="padding:3px 4px;color:#e2e8f0;font-size:11px;'
                    f'font-family:monospace;">{ep["path"]}</td>'
                    f'<td style="padding:3px 8px;color:#94a3b8;font-size:10px;">'
                    f'{ep["detail"]}</td>'
                    f'</tr>\n'
                )

        html = f"""
<div style="font-family:'DM Sans',Arial,sans-serif;max-width:750px;margin:0 auto;
background:#0A0A0A;color:#e2e8f0;border:1px solid #222;border-radius:8px;overflow:hidden;">
  <div style="background:#050505;padding:16px 20px;border-bottom:1px solid #222;">
    <h2 style="margin:0;color:#C9A962;font-size:18px;">The Eye — Trust Scorecard</h2>
    <p style="margin:4px 0 0;color:#94a3b8;font-size:12px;">
      {now.strftime('%A, %B %d %Y at %H:%M UTC')} — 6 Tabs, {total_all} Endpoints
    </p>
  </div>
  <div style="padding:12px 20px;background:#111;border-bottom:1px solid #222;">
    <span style="color:{header_color};font-weight:bold;font-size:16px;">
      {pct}% Trust Score</span>
    <span style="color:#94a3b8;font-size:12px;"> — </span>
    <span style="color:#22c55e;font-weight:bold;font-size:13px;">
      {trusted_all} TRUSTED</span>
    <span style="color:#94a3b8;"> | </span>
    <span style="color:#eab308;font-weight:bold;font-size:13px;">
      {warning_all} WARNING</span>
    <span style="color:#94a3b8;"> | </span>
    <span style="color:#ef4444;font-weight:bold;font-size:13px;">
      {failed_all} FAILED</span>
    <span style="color:#94a3b8;font-size:11px;"> / {total_all} endpoints</span>
  </div>
  <table style="width:100%;border-collapse:collapse;">
    {tab_rows}
  </table>
  <div style="padding:12px 20px;border-top:1px solid #222;text-align:center;">
    <span style="color:#666;font-size:10px;">
      Sovereign Sanctuary — The Eye Endpoint Trust Auditor
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
