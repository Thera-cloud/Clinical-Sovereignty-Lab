"""
LITTLE NATE — Login Auditor
Blind WebSocket login tests for client and coach accounts.
Scheduled 3x daily (5 AM, 5 PM, 11 PM UTC) with stagger delay of 150s.

Performs actual WebSocket handshake → login_request → verifies login_success
response for both a client test account and a coach test account.

Hardened to stay GREEN under load:
- unique hardware_id per attempt (avoids Sentinel/device collision with WS Flow)
- drain intermediate messages until login_success / login_failed
- one automatic retry on non-TRUSTED
- JSON activity payload for Trust Enforcer + diagnostics
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
        # Email silenced — Trust Enforcer sends consolidated report

        passed = sum(1 for r in results if r["status"] == "TRUSTED")
        total = len(results)
        payload = {
            "trusted": passed,
            "total": total,
            "results": results,
            "at": now.isoformat(),
        }
        await self._log_activity(
            "system", "login_audit_sent",
            json.dumps(payload, default=str),
            "success" if passed == total else "warning",
        )
        logger.info(
            "LoginAuditor: scorecard sent — %d/%d TRUSTED detail=%s",
            passed,
            total,
            json.dumps(
                [{"label": r["label"], "status": r["status"], "detail": r["detail"]}
                 for r in results],
                default=str,
            )[:500],
        )

    async def _test_all_logins(self) -> list:
        results = []
        for account in TEST_ACCOUNTS:
            result = await self._test_login(account)
            if result["status"] != "TRUSTED":
                logger.warning(
                    "LoginAuditor: %s %s — retrying once (%s)",
                    account["label"], result["status"], result.get("detail"),
                )
                await asyncio.sleep(2.0)
                retry = await self._test_login(account)
                if retry["status"] == "TRUSTED":
                    retry["detail"] = f"OK after retry ({retry.get('detail', '')})"
                    retry["retried"] = True
                    result = retry
                else:
                    result["retried"] = True
                    result["retry_detail"] = retry.get("detail")
            results.append(result)
            # Brief pause so bridge can release the prior audit socket
            await asyncio.sleep(1.0)
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
        # Unique HW id — shared fixed ids collide with WS Flow auditor / Sentinel
        nonce = f"{int(time.time() * 1000) % 1000000}"
        hardware_id = (
            f"login_audit_{account['expected_role'].lower()}_hw_{nonce}"
        )

        try:
            ssl_context = None
            ws_url = WS_URL
            if ws_url.startswith("wss://"):
                ssl_context = ssl.create_default_context()
                ssl_context.check_hostname = False
                ssl_context.verify_mode = ssl.CERT_NONE

            async with websockets.connect(
                ws_url, ssl=ssl_context, open_timeout=15, close_timeout=5
            ) as ws:
                steps["connect"] = "OK"

                raw = await asyncio.wait_for(ws.recv(), timeout=8)
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
                    "hardware_id": hardware_id,
                })
                await ws.send(login_msg)
                steps["login_sent"] = "OK"

                # Wait for login_success / login_failed — skip intermediate frames
                resp = None
                login_deadline = time.monotonic() + 20
                while time.monotonic() < login_deadline:
                    remaining = max(0.5, login_deadline - time.monotonic())
                    raw = await asyncio.wait_for(ws.recv(), timeout=remaining)
                    candidate = json.loads(raw)
                    ctype = candidate.get("type")
                    if ctype == "login_success":
                        resp = candidate
                        break
                    if ctype in ("login_failed", "error"):
                        reason = (
                            candidate.get("reason")
                            or candidate.get("message")
                            or ctype
                        )
                        steps["login_response"] = f"REJECTED: {reason}"
                        elapsed = int((time.monotonic() - t0) * 1000)
                        return {
                            "label": label, "status": "WARNING",
                            "detail": f"Login rejected: {reason}", "ms": elapsed,
                            "steps": steps,
                        }
                    # Intermediate (metrics, stats, etc.) — keep waiting

                if not resp:
                    steps["login_response"] = "TIMEOUT"
                    elapsed = int((time.monotonic() - t0) * 1000)
                    return {
                        "label": label, "status": "FAILED",
                        "detail": "Timeout waiting for login_success", "ms": elapsed,
                        "steps": steps,
                    }

                steps["login_response"] = "OK"
                profile = resp.get("profile") or {}
                got_role = (
                    profile.get("role")
                    or resp.get("role")
                    or ""
                )
                if str(got_role).upper() == account["expected_role"]:
                    steps["role_match"] = "OK"
                else:
                    steps["role_match"] = (
                        f"Got {got_role!r} expected {account['expected_role']}"
                    )

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
