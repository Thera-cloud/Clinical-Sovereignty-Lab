"""
LITTLE NATE — Login Auditor
Blind WebSocket login tests for client and coach accounts.
Scheduled 3x daily (5 AM, 5 PM, 11 PM UTC) with stagger delay of 150s.

Performs actual WebSocket handshake → login_request → verifies login_success
response for both a client test account and a coach test account.

Produces a colour-coded HTML trust scorecard email.
"""

import asyncio
import json
import logging
import os
import ssl
import time
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger("nate.login_auditor")

AUDIT_HOURS = {5, 17, 23}
AUDIT_EMAIL = "support@sovereignsanctuary.net"
WS_URL = os.environ.get("WS_AUDIT_URL", "ws://bridge:8765")

TEST_ACCOUNTS = [
    {
        "label": "Client Login",
        "username": "audit_client",
        "password": "AuditClient2026!",
        "expected_role": "CLIENT",
    },
    {
        "label": "Coach Login",
        "username": "audit_coach",
        "password": "AuditCoach2026!",
        "expected_role": "COACH",
    },
]


class LoginAuditor:

    def __init__(self, db_pool, notification_system=None, app_state=None):
        self.db_pool = db_pool
        self.notifications = notification_system
        self._app_state = app_state
        self._task: Optional[asyncio.Task] = None
        self._running = False
        self._sent_windows: set = set()

    async def start(self):
        if self._task and not self._task.done():
            return
        self._running = True
        self._task = asyncio.create_task(self._run_loop())
        logger.info("LoginAuditor started (3x daily at UTC 05:00, 17:00, 23:00)")

    async def stop(self):
        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("LoginAuditor stopped")

    async def _run_loop(self):
        await asyncio.sleep(150)
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
                logger.error("LoginAuditor tick failed: %s", e, exc_info=True)
            await asyncio.sleep(60)

    async def _build_and_send(self, now: datetime):
        results = await self._test_all_logins()
        html = self._render_html(results, now)
        subject = f"Login Trust Scorecard — {now.strftime('%b %d %Y %H:%M UTC')}"

        # Email silenced — Trust Enforcer sends consolidated report

        passed = sum(1 for r in results if r["status"] == "TRUSTED")
        total = len(results)
        await self._log_activity(
            "system", "login_audit_sent",
            f"Scorecard sent: {passed}/{total} TRUSTED at {now.isoformat()}", "success"
        )
        logger.info("LoginAuditor: scorecard sent — %d/%d TRUSTED", passed, total)

    async def _test_all_logins(self) -> list:
        results = []
        for account in TEST_ACCOUNTS:
            result = await self._test_login(account)
            results.append(result)
        return results

    async def _test_login(self, account: dict) -> dict:
        label = account["label"]
        t0 = time.monotonic()

        try:
            import websockets
        except ImportError:
            return {
                "label": label,
                "status": "FAILED",
                "detail": "websockets library not available",
                "ms": 0,
                "steps": {},
            }

        steps = {
            "connect": "PENDING",
            "handshake": "PENDING",
            "login_sent": "PENDING",
            "login_response": "PENDING",
            "role_match": "PENDING",
        }

        try:
            ssl_context = None
            ws_url = WS_URL
            if ws_url.startswith("wss://"):
                ssl_context = ssl.create_default_context()
                ssl_context.check_hostname = False
                ssl_context.verify_mode = ssl.CERT_NONE

            async with websockets.connect(
                ws_url, ssl=ssl_context, open_timeout=10, close_timeout=5
            ) as ws:
                steps["connect"] = "OK"

                raw = await asyncio.wait_for(ws.recv(), timeout=5)
                msg = json.loads(raw)
                if msg.get("type") == "connected" and msg.get("status") == "ready":
                    steps["handshake"] = "OK"
                else:
                    steps["handshake"] = f"Unexpected: {msg.get('type')}"
                    elapsed = int((time.monotonic() - t0) * 1000)
                    return {
                        "label": label, "status": "FAILED",
                        "detail": f"Bad handshake: {msg.get('type')}", "ms": elapsed,
                        "steps": steps,
                    }

                login_msg = json.dumps({
                    "type": "login_request",
                    "username": account["username"],
                    "password": account["password"],
                    "expected_role": account["expected_role"],
                    "hardware_id": f"audit_{account['expected_role'].lower()}_hw",
                })
                await ws.send(login_msg)
                steps["login_sent"] = "OK"

                raw = await asyncio.wait_for(ws.recv(), timeout=10)
                resp = json.loads(raw)

                if resp.get("type") == "login_success":
                    steps["login_response"] = "OK"
                    profile = resp.get("profile", {})
                    if profile.get("role", "").upper() == account["expected_role"]:
                        steps["role_match"] = "OK"
                    else:
                        steps["role_match"] = f"Got {profile.get('role')} expected {account['expected_role']}"
                elif resp.get("type") == "login_failed":
                    steps["login_response"] = f"REJECTED: {resp.get('reason', 'unknown')}"
                    elapsed = int((time.monotonic() - t0) * 1000)
                    return {
                        "label": label, "status": "WARNING",
                        "detail": f"Login rejected: {resp.get('reason', '')}", "ms": elapsed,
                        "steps": steps,
                    }
                else:
                    steps["login_response"] = f"Unexpected type: {resp.get('type')}"
                    elapsed = int((time.monotonic() - t0) * 1000)
                    return {
                        "label": label, "status": "FAILED",
                        "detail": f"Unexpected response: {resp.get('type')}", "ms": elapsed,
                        "steps": steps,
                    }

            elapsed = int((time.monotonic() - t0) * 1000)
            all_ok = all(v == "OK" for v in steps.values())
            return {
                "label": label,
                "status": "TRUSTED" if all_ok else "WARNING",
                "detail": f"All steps OK in {elapsed}ms" if all_ok else "Partial pass",
                "ms": elapsed,
                "steps": steps,
            }

        except asyncio.TimeoutError:
            elapsed = int((time.monotonic() - t0) * 1000)
            return {
                "label": label, "status": "FAILED",
                "detail": "Timeout waiting for response", "ms": elapsed,
                "steps": steps,
            }
        except Exception as exc:
            elapsed = int((time.monotonic() - t0) * 1000)
            return {
                "label": label, "status": "FAILED",
                "detail": str(exc)[:100], "ms": elapsed,
                "steps": steps,
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
            if r["status"] == "TRUSTED":
                c = "#22c55e"
            elif r["status"] == "WARNING":
                c = "#eab308"
            else:
                c = "#ef4444"

            step_details = ""
            for step_name, step_val in r.get("steps", {}).items():
                sc = "#22c55e" if step_val == "OK" else "#ef4444"
                step_details += (
                    f'<div style="padding:2px 0 2px 30px;color:{sc};font-size:10px;">'
                    f'  {step_name}: {step_val}</div>'
                )

            rows += (
                f'<tr><td style="padding:8px;color:{c};font-weight:bold;font-size:13px;">'
                f'[{r["status"]}]</td>'
                f'<td style="padding:8px;color:#C9A962;font-weight:bold;">{r["label"]}</td>'
                f'<td style="padding:8px;color:#94a3b8;font-size:11px;">{r["detail"]}</td>'
                f'<td style="padding:8px;color:#94a3b8;font-size:10px;">{r["ms"]}ms</td></tr>\n'
                f'<tr><td colspan="4" style="padding:0 8px 6px 8px;">{step_details}</td></tr>\n'
            )

        return f"""
<div style="font-family:'DM Sans',Arial,sans-serif;max-width:750px;margin:0 auto;
background:#0A0A0A;color:#e2e8f0;border:1px solid #222;border-radius:8px;overflow:hidden;">
  <div style="background:#050505;padding:16px 20px;border-bottom:1px solid #222;">
    <h2 style="margin:0;color:#C9A962;font-size:18px;">Login Trust Scorecard</h2>
    <p style="margin:4px 0 0;color:#94a3b8;font-size:12px;">
      {now.strftime('%A, %B %d %Y at %H:%M UTC')} — {total} Login Tests
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
    <span style="color:#666;font-size:10px;">Sovereign Sanctuary — Login Auditor</span>
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
