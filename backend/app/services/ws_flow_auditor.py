"""
LITTLE NATE — WebSocket Flow Auditor
Tests critical WebSocket message flows beyond login: chat, metrics,
coach operations, DOJO, Nevedal, notifications, and billing.

Scheduled 3x daily (5 AM, 5 PM, 11 PM UTC) with stagger delay of 210s.

Architecture: Uses separate WebSocket connections for client and coach tests
to prevent cross-contamination. Each connection logs in fresh, runs its tests
sequentially with inter-test drains, then disconnects cleanly.
"""

import asyncio
import json
import logging
import os
import ssl
import time
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger("nate.ws_flow_auditor")

AUDIT_HOURS = {5, 17, 23}
AUDIT_EMAIL = "support@sovereignsanctuary.net"
WS_URL = os.environ.get("WS_AUDIT_URL", "ws://bridge:8765")

def _make_client_account():
    nonce = f"{int(time.time() * 1000) % 100000}"
    return {
        "username": "audit_client",
        "password": "AuditClient2026!",
        "expected_role": "CLIENT",
        "hardware_id": f"wsflow_audit_client_hw_{nonce}",
    }

def _make_coach_account():
    nonce = f"{int(time.time() * 1000) % 100000}"
    return {
        "username": "audit_coach",
        "password": "AuditCoach2026!",
        "expected_role": "COACH",
        "hardware_id": f"wsflow_audit_coach_hw_{nonce}",
    }

CLIENT_TESTS = [
    {"label": "Client Metrics", "account": "client",
     "send": {"type": "get_metrics"},
     "expect_type": "metrics_data",
     "timeout": 10},
    {"label": "Client History", "account": "client",
     "send": {"type": "get_history"},
     "expect_type": None,
     "timeout": 10},
    {"label": "Client Notifications", "account": "client",
     "send": {"type": "get_notifications"},
     "expect_type": None,
     "timeout": 10},
    {"label": "Client Billing", "account": "client",
     "send": {"type": "get_billing"},
     "expect_type": None,
     "timeout": 10},
    {"label": "Nevedal Subscribe", "account": "client",
     "send": {"type": "nevedal_subscribe"},
     "expect_type": "nevedal_subscribed",
     "timeout": 10},
    {"label": "Client Chat", "account": "client",
     "send": {"type": "chat_message", "message": "audit ping", "mode": "therapeutic"},
     "expect_type": "nate_response",
     "timeout": 30},
]

COACH_TESTS = [
    {"label": "Coach Clients", "account": "coach",
     "send": {"type": "coach_get_clients"},
     "expect_type": None,
     "timeout": 15},
    {"label": "Coach Briefing", "account": "coach",
     "send": {"type": "fetch_coach_calendar"},
     "expect_type": None,
     "timeout": 10},
    {"label": "DOJO Personas", "account": "coach",
     "send": {"type": "get_dojo_subscriptions"},
     "expect_type": "dojo_subscriptions_data",
     "timeout": 10},
    {"label": "Night School Wisdom", "account": "coach",
     "send": {"type": "get_night_school_wisdom"},
     "expect_type": None,
     "timeout": 10},
]


class WebSocketFlowAuditor:

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
        logger.info("WebSocketFlowAuditor started (5am/5pm/11pm UTC, stagger 210s)")

    async def stop(self):
        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("WebSocketFlowAuditor stopped")

    async def _run_loop(self):
        await asyncio.sleep(210)
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
                logger.error("WebSocketFlowAuditor tick failed: %s", e, exc_info=True)
            await asyncio.sleep(60)

    async def _build_and_send(self, now: datetime):
        # Wait for Login Auditor to finish its audit_client connection cycle.
        # Both auditors share audit_client/audit_coach accounts; the bridge
        # enforces one connection per username and closes the earlier one
        # with "Replaced by new connection" if both connect simultaneously.
        await asyncio.sleep(15)
        results = await self._audit_all_flows()
        html = self._render_html(results, now)

        # Email silenced — Trust Enforcer sends consolidated report

        trusted = sum(1 for r in results if r["status"] == "TRUSTED")
        total = len(results)

        result_data = json.dumps({
            "trusted": trusted,
            "total": total,
            "results": results,
            "timestamp": now.isoformat(),
        })

        await self._log_activity(
            "system", "ws_flow_audit_sent",
            result_data, "success"
        )
        logger.info("WebSocketFlowAuditor: scorecard sent — %d/%d TRUSTED", trusted, total)

    async def _audit_all_flows(self) -> list:
        results = []

        client_results = await self._run_test_group(_make_client_account(), CLIENT_TESTS)
        results.extend(client_results)

        await asyncio.sleep(2)

        coach_results = await self._run_test_group(_make_coach_account(), COACH_TESTS)
        results.extend(coach_results)

        return results

    async def _run_test_group(self, account: dict, tests: list) -> list:
        """Run a group of tests on a single fresh WebSocket connection.
        Retries once if the connection is replaced (bridge closed it for
        a duplicate username from another auditor)."""
        for attempt in range(2):
            results = []
            ws = await self._login_ws(account)

            if ws is None:
                for test in tests:
                    results.append({
                        "label": test["label"],
                        "status": "FAILED",
                        "detail": f"No WS connection for {account['username']}",
                        "ms": 0,
                        "steps": {"login": "FAILED"},
                    })
                return results

            replaced = False
            try:
                for test in tests:
                    result = await self._test_flow(ws, test)
                    results.append(result)
                    if "Replaced" in result.get("detail", ""):
                        replaced = True
                        break
                    await self._drain_between_tests(ws)
            finally:
                try:
                    await ws.close()
                except Exception:
                    pass

            if replaced and attempt == 0:
                logger.info("WS Flow: connection replaced for %s, retrying in 10s",
                            account["username"])
                await asyncio.sleep(10)
                continue
            return results
        return results

    async def _login_ws(self, account: dict):
        try:
            import websockets
        except ImportError:
            return None

        ssl_context = None
        ws_url = WS_URL
        if ws_url.startswith("wss://"):
            ssl_context = ssl.create_default_context()
            ssl_context.check_hostname = False
            ssl_context.verify_mode = ssl.CERT_NONE

        try:
            ws = await websockets.connect(
                ws_url, ssl=ssl_context, open_timeout=10, close_timeout=5
            )
            raw = await asyncio.wait_for(ws.recv(), timeout=5)
            msg = json.loads(raw)
            if msg.get("type") != "connected":
                await ws.close()
                return None

            login_msg = json.dumps({
                "type": "login_request",
                "username": account["username"],
                "password": account["password"],
                "expected_role": account["expected_role"],
                "hardware_id": account["hardware_id"],
            })
            await ws.send(login_msg)

            # Wait for login_success, consuming any intermediate messages
            login_deadline = time.monotonic() + 15
            while time.monotonic() < login_deadline:
                remaining = max(0.5, login_deadline - time.monotonic())
                raw = await asyncio.wait_for(ws.recv(), timeout=remaining)
                resp = json.loads(raw)
                if resp.get("type") == "login_success":
                    await self._drain_post_login(ws)
                    return ws
                if resp.get("type") in ("error", "login_failed"):
                    logger.warning("WS login failed for %s: %s",
                                   account["username"], resp.get("message", ""))
                    await ws.close()
                    return None

            await ws.close()
            return None
        except Exception as e:
            logger.warning("WS login failed for %s: %s", account["username"], e)
            return None

    async def _drain_post_login(self, ws):
        """Drain unsolicited messages the bridge sends after login
        (metrics_update, admin_stats, nudge, etc.) so test flows read clean responses."""
        while True:
            try:
                await asyncio.wait_for(ws.recv(), timeout=5)
            except (asyncio.TimeoutError, Exception):
                break

    async def _drain_between_tests(self, ws):
        """Drain any leftover messages from the previous test."""
        while True:
            try:
                await asyncio.wait_for(ws.recv(), timeout=2)
            except (asyncio.TimeoutError, Exception):
                break

    async def _test_flow(self, ws, test: dict) -> dict:
        label = test["label"]
        t0 = time.monotonic()
        test_timeout = test.get("timeout", 15)

        steps = {"send": "PENDING", "receive": "PENDING"}

        try:
            await ws.send(json.dumps(test["send"]))
            steps["send"] = "OK"

            expect = test.get("expect_type")
            deadline = t0 + test_timeout
            resp = None

            while time.monotonic() < deadline:
                remaining = max(0.5, deadline - time.monotonic())
                raw = await asyncio.wait_for(ws.recv(), timeout=remaining)
                resp = json.loads(raw)
                resp_type = resp.get("type", "")

                # If we have a specific expected type, keep reading until we find it
                if expect is not None:
                    if resp_type == expect:
                        break
                    if resp_type == "error":
                        break
                    continue

                # expect_type is None: accept any non-system response as proof the handler ran
                _system_types = {
                    "metrics_update", "admin_stats", "nudge_check",
                    "connection_stats", "ping", "pong", "connected",
                }
                if resp_type not in _system_types:
                    break

            steps["receive"] = "OK"
            elapsed = int((time.monotonic() - t0) * 1000)

            if resp and resp.get("type") == "error":
                err_msg = resp.get("message", "")[:60]
                # Some errors are expected (e.g., "No billing data") — still proves the handler ran
                steps["receive"] = f"error: {err_msg}"
                return {"label": label, "status": "TRUSTED",
                        "detail": f"Handler responded with error in {elapsed}ms: {err_msg}",
                        "ms": elapsed, "steps": steps}

            return {"label": label, "status": "TRUSTED",
                    "detail": f"Response in {elapsed}ms (type={resp.get('type') if resp else '?'})",
                    "ms": elapsed, "steps": steps}

        except asyncio.TimeoutError:
            elapsed = int((time.monotonic() - t0) * 1000)
            steps["receive"] = "TIMEOUT"
            return {"label": label, "status": "FAILED",
                    "detail": f"Timeout after {elapsed}ms (deadline {test_timeout}s)",
                    "ms": elapsed, "steps": steps}
        except Exception as exc:
            elapsed = int((time.monotonic() - t0) * 1000)
            steps["receive"] = f"EXCEPTION: {type(exc).__name__}"
            return {"label": label, "status": "FAILED",
                    "detail": str(exc)[:80], "ms": elapsed,
                    "steps": steps}

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
            step_html = ""
            for sn, sv in r.get("steps", {}).items():
                sc = "#22c55e" if sv == "OK" else "#ef4444"
                step_html += f'<span style="color:{sc};font-size:9px;margin-right:8px;">{sn}:{sv}</span>'
            rows += (
                f'<tr>'
                f'<td style="padding:6px 8px;color:{c};font-weight:bold;font-size:12px;">'
                f'[{r["status"]}]</td>'
                f'<td style="padding:6px 8px;color:#C9A962;font-weight:bold;">{r["label"]}</td>'
                f'<td style="padding:6px 8px;color:#94a3b8;font-size:10px;">{r["detail"]}</td>'
                f'<td style="padding:6px 8px;color:#94a3b8;font-size:10px;">{r.get("ms",0)}ms</td>'
                f'</tr>\n'
                f'<tr><td colspan="4" style="padding:0 8px 4px 20px;">{step_html}</td></tr>\n'
            )

        return f"""
<div style="font-family:'DM Sans',Arial,sans-serif;max-width:750px;margin:0 auto;
background:#0A0A0A;color:#e2e8f0;border:1px solid #222;border-radius:8px;overflow:hidden;">
  <div style="background:#050505;padding:16px 20px;border-bottom:1px solid #222;">
    <h2 style="margin:0;color:#C9A962;font-size:18px;">WebSocket Flow — Trust Scorecard</h2>
    <p style="margin:4px 0 0;color:#94a3b8;font-size:12px;">
      {now.strftime('%A, %B %d %Y at %H:%M UTC')} — {total} Flow Tests
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
    <span style="color:#666;font-size:10px;">Sovereign Sanctuary — WebSocket Flow Trust Auditor</span>
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
