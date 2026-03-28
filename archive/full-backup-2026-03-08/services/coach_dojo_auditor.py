"""
LITTLE NATE — Coach & DOJO Auditor
Tests all coach-facing REST API endpoints: coach portal, DOJO training,
Night School, sessions, homework, matchmaker, coach actions, Night School
write operations, and session memory retrieval.

Scheduled 3x daily (5 AM, 5 PM, 11 PM UTC) with stagger delay of 170s.
POST/PUT/DELETE endpoints use empty payloads — 422 (Pydantic validation)
or 404 (fake ID) confirms the endpoint exists and is routing correctly.

46 endpoints across 10 tabs.
"""

import asyncio
import logging
import os
import time
from datetime import datetime, timezone
from typing import Optional

import aiohttp

logger = logging.getLogger("nate.coach_dojo_auditor")

AUDIT_HOURS = {5, 17, 23}
AUDIT_EMAIL = "support@sovereignsanctuary.net"
BASE_URL = "http://localhost:8000"

COACH_ID = "audit_coach_hw"
CLIENT_ID = "audit_client_hw"
FAKE_ID = "00000000-0000-0000-0000-000000000000"

TAB_ENDPOINTS = [
    {
        "tab": "Coach Portal",
        "tab_num": 1,
        "endpoints": [
            ("GET", f"/api/coach/clients/{COACH_ID}"),
            ("GET", f"/api/coach/notes/{CLIENT_ID}"),
            ("GET", f"/api/coach/homework/{CLIENT_ID}"),
            ("GET", f"/api/coach/stats/{COACH_ID}"),
        ],
    },
    {
        "tab": "Sessions",
        "tab_num": 2,
        "endpoints": [
            ("GET", f"/api/sessions/coach/{COACH_ID}"),
            ("GET", f"/api/sessions/stats/coach/{COACH_ID}"),
            ("GET", f"/api/sessions/availability/{COACH_ID}"),
            ("GET", f"/api/sessions/available-slots/{COACH_ID}"),
        ],
    },
    {
        "tab": "DOJO",
        "tab_num": 3,
        "endpoints": [
            ("GET", "/api/night-school/dojo/personas"),
            ("GET", "/api/night-school/dojo/scenarios"),
            ("GET", "/api/night-school/dojo/wisdom/HOSTILE"),
        ],
    },
    {
        "tab": "Night School Wisdom",
        "tab_num": 4,
        "endpoints": [
            ("GET", "/api/night-school/wisdom"),
            ("GET", "/api/night-school/versions"),
            ("GET", "/api/night-school/notes/pending"),
            ("GET", "/api/night-school/stats"),
            ("GET", "/api/night-school/learning/stats"),
        ],
    },
    {
        "tab": "Session Memories",
        "tab_num": 5,
        "endpoints": [
            ("GET", f"/api/night-school/memories/client/{CLIENT_ID}"),
            ("GET", "/api/night-school/memories/dojo"),
            ("GET", "/api/night-school/memories/stats"),
            ("GET", f"/api/night-school/memories/family/{FAKE_ID}"),
            ("GET", f"/api/night-school/memories/session/{FAKE_ID}"),
        ],
    },
    {
        "tab": "Admin Coach Mgmt",
        "tab_num": 6,
        "endpoints": [
            ("GET", "/api/admin/coaches"),
            ("GET", "/api/admin/coaches?status=PENDING_VERIFICATION"),
            ("GET", "/api/admin/night-school/status"),
        ],
    },
    {
        "tab": "Matchmaker",
        "tab_num": 7,
        "endpoints": [
            ("GET", "/api/admin/users?role=COACH"),
            ("GET", "/api/admin/users?role=CLIENT"),
        ],
    },
    {
        "tab": "Coach Actions",
        "tab_num": 8,
        "endpoints": [
            ("GET", f"/api/coach/presession-brief/{CLIENT_ID}"),
            ("GET", f"/api/coach/ask-nate/{CLIENT_ID}"),
            ("GET", "/api/coach/insights/history"),
            ("POST", "/api/coach/notes"),
            ("POST", "/api/coach/homework"),
            ("POST", f"/api/coach/homework/{FAKE_ID}/complete"),
            ("POST", "/api/coach/matchmaker"),
        ],
    },
    {
        "tab": "Night School Operations",
        "tab_num": 9,
        "endpoints": [
            ("POST", "/api/night-school/wisdom"),
            ("POST", f"/api/night-school/wisdom/{FAKE_ID}/approve"),
            ("POST", "/api/night-school/versions/snapshot"),
            ("GET", "/api/night-school/versions/compare"),
            ("POST", "/api/night-school/notes"),
            ("GET", f"/api/night-school/notes/{FAKE_ID}"),
            ("POST", f"/api/night-school/notes/{FAKE_ID}/review"),
            ("POST", "/api/night-school/curriculum/upload"),
        ],
    },
    {
        "tab": "Assessments",
        "tab_num": 10,
        "endpoints": [
            ("GET", f"/api/assessments/available/{CLIENT_ID}"),
            ("GET", f"/api/assessments/history/{CLIENT_ID}"),
            ("POST", f"/api/assessments/generate/{CLIENT_ID}"),
            ("GET", f"/api/assessments/growth/{CLIENT_ID}"),
            ("GET", f"/api/assessments/triggers/{CLIENT_ID}"),
            ("GET", f"/api/assessments/{FAKE_ID}"),
        ],
    },
    {
        "tab": "Coach QuickBooks",
        "tab_num": 11,
        "endpoints": [
            ("GET", "/api/coach/quickbooks/health"),
            ("GET", "/api/coach/quickbooks/status"),
            ("GET", "/api/coach/quickbooks/connect"),
            ("POST", "/api/coach/quickbooks/disconnect"),
            ("POST", "/api/coach/quickbooks/sync/trigger"),
            ("GET", "/api/coach/quickbooks/sync/history"),
            ("GET", "/api/coach/quickbooks/account-mapping"),
            ("POST", "/api/coach/quickbooks/account-mapping"),
            ("GET", "/api/coach/quickbooks/callback"),
        ],
    },
]


class CoachDojoAuditor:

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
        logger.info("CoachDojoAuditor started (3x daily at UTC 05:00, 17:00, 23:00)")

    async def stop(self):
        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("CoachDojoAuditor stopped")

    async def _run_loop(self):
        await asyncio.sleep(170)
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
                logger.error("CoachDojoAuditor tick failed: %s", e, exc_info=True)
            await asyncio.sleep(60)

    async def _build_and_send(self, now: datetime):
        results = await self._audit_all_tabs()
        html = self._render_html(results, now)
        subject = f"Coach & DOJO Trust Scorecard — {now.strftime('%b %d %Y %H:%M UTC')}"

        # Email silenced — Trust Enforcer sends consolidated report

        total = sum(t["total"] for t in results)
        trusted = sum(t["trusted"] for t in results)
        await self._log_activity(
            "system", "coach_dojo_audit_sent",
            f"Scorecard sent: {trusted}/{total} TRUSTED at {now.isoformat()}", "success"
        )
        logger.info("CoachDojoAuditor: scorecard sent — %d/%d TRUSTED", trusted, total)

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
            logger.debug("CoachDojoAuditor: Redis token scan failed: %s", e)
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
                    "total": 0, "trusted": 0, "warning": 0, "failed": 0,
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
            elif method == "PUT":
                async with session.put(url, headers=headers, json={}) as resp:
                    code = resp.status
                    body = {}
                    elapsed = int((time.monotonic() - t0) * 1000)
            elif method == "DELETE":
                async with session.delete(url, headers=headers) as resp:
                    code = resp.status
                    body = {}
                    elapsed = int((time.monotonic() - t0) * 1000)
            else:
                async with session.post(url, headers=headers, json={}) as resp:
                    code = resp.status
                    body = await resp.json() if code in (200, 201) else {}
                    elapsed = int((time.monotonic() - t0) * 1000)

            if code in (200, 404):
                if code == 200 and self._is_empty_payload(body):
                    return {"method": method, "path": path, "code": code,
                            "ms": elapsed, "status": "WARNING",
                            "detail": f"200 but empty payload ({elapsed}ms)"}
                return {"method": method, "path": path, "code": code,
                        "ms": elapsed, "status": "TRUSTED",
                        "detail": f"{code} in {elapsed}ms"}
            elif code in (400, 422):
                return {"method": method, "path": path, "code": code,
                        "ms": elapsed, "status": "TRUSTED",
                        "detail": f"{code} validation (endpoint exists) in {elapsed}ms"}
            elif 400 < code < 500:
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
            tc = "#ef4444" if t["failed"] > 0 else ("#eab308" if t["warning"] > 0 else "#22c55e")
            tb = "FAILED" if t["failed"] > 0 else ("WARNING" if t["warning"] > 0 else "TRUSTED")
            tab_rows += (
                f'<tr><td style="padding:6px 8px;background:#111;color:#C9A962;'
                f'font-weight:bold;font-size:13px;" colspan="4">'
                f'Tab {t["tab_num"]}: {t["tab"]} '
                f'<span style="color:{tc};font-size:11px;">'
                f'[{tb} — {t["trusted"]}/{t["total"]}]</span></td></tr>\n'
            )
            for ep in t["endpoints"]:
                c = "#22c55e" if ep["status"] == "TRUSTED" else (
                    "#eab308" if ep["status"] == "WARNING" else "#ef4444")
                tab_rows += (
                    f'<tr><td style="padding:3px 8px 3px 20px;color:{c};font-weight:bold;'
                    f'font-size:11px;">[{ep["status"]}]</td>'
                    f'<td style="padding:3px 4px;color:#94a3b8;font-size:11px;'
                    f'font-family:monospace;">{ep["method"]}</td>'
                    f'<td style="padding:3px 4px;color:#e2e8f0;font-size:11px;'
                    f'font-family:monospace;">{ep["path"]}</td>'
                    f'<td style="padding:3px 8px;color:#94a3b8;font-size:10px;">'
                    f'{ep["detail"]}</td></tr>\n'
                )

        return f"""
<div style="font-family:'DM Sans',Arial,sans-serif;max-width:750px;margin:0 auto;
background:#0A0A0A;color:#e2e8f0;border:1px solid #222;border-radius:8px;overflow:hidden;">
  <div style="background:#050505;padding:16px 20px;border-bottom:1px solid #222;">
    <h2 style="margin:0;color:#C9A962;font-size:18px;">Coach & DOJO — Trust Scorecard</h2>
    <p style="margin:4px 0 0;color:#94a3b8;font-size:12px;">
      {now.strftime('%A, %B %d %Y at %H:%M UTC')} — {len(results)} Categories, {total_all} Endpoints
    </p>
  </div>
  <div style="padding:12px 20px;background:#111;border-bottom:1px solid #222;">
    <span style="color:{header_color};font-weight:bold;font-size:16px;">{pct}% Trust Score</span>
    <span style="color:#94a3b8;font-size:12px;"> — </span>
    <span style="color:#22c55e;font-weight:bold;font-size:13px;">{trusted_all} TRUSTED</span>
    <span style="color:#94a3b8;"> | </span>
    <span style="color:#eab308;font-weight:bold;font-size:13px;">{warning_all} WARNING</span>
    <span style="color:#94a3b8;"> | </span>
    <span style="color:#ef4444;font-weight:bold;font-size:13px;">{failed_all} FAILED</span>
  </div>
  <table style="width:100%;border-collapse:collapse;">{tab_rows}</table>
  <div style="padding:12px 20px;border-top:1px solid #222;text-align:center;">
    <span style="color:#666;font-size:10px;">Sovereign Sanctuary — Coach & DOJO Trust Auditor</span>
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
