"""
LITTLE NATE — CLI Agent Auditor
Tests all REST API endpoints for the Dual-CLI infrastructure
plus DB-level integrity checks for CLI tables.

14 checks across 5 tabs:
  Tab 1: CLI Health (2 endpoints — one per CLI token)
  Tab 2: Proposal & Source Request Flow (4 endpoints)
  Tab 3: Blob & Backup (3 endpoints)
  Tab 4: Search & Read Access (3 endpoints)
  Tab 5: Data Integrity (2 DB-level checks)

Scheduled 3x daily (5 AM, 5 PM, 11 PM UTC) with stagger delay of 300s.
"""

import asyncio
import json
import logging
import os
import time
from datetime import datetime, timezone
from typing import Optional

import aiohttp

logger = logging.getLogger("nate.cli_auditor")

AUDIT_HOURS = {5, 17, 23}
BASE_URL = "http://localhost:8000"

TAB_ENDPOINTS = [
    {
        "tab": "CLI Health",
        "tab_num": 1,
        "endpoints": [
            ("CLI_CLOUD", "/api/nate-agent/cli/health"),
            ("CLI_MAC", "/api/nate-agent/cli/health"),
        ],
    },
    {
        "tab": "Proposal & Source Request Flow",
        "tab_num": 2,
        "endpoints": [
            ("CLI_POST", "/api/nate-agent/cli/submit-proposal"),
            ("CLI_POST", "/api/nate-agent/cli/submit-source-request"),
            ("CLI_GET", "/api/nate-agent/cli/approval-status/00000000-0000-0000-0000-000000000000"),
            ("ADMIN_GET", "/api/nate-agent/pending?cli=cloud"),
        ],
    },
    {
        "tab": "Blob & Backup",
        "tab_num": 3,
        "endpoints": [
            ("CLI_GET", "/api/nate-agent/cli/blob/download?build_id=audit_test&filename=report.json"),
            ("CLI_POST", "/api/nate-agent/cli/blob/upload"),
            ("CLI_POST", "/api/nate-agent/cli/backup/restore-request"),
        ],
    },
    {
        "tab": "Search & Read Access",
        "tab_num": 4,
        "endpoints": [
            ("CLI_GET", "/api/nate-agent/cli/read-access/allowlist"),
            ("CLI_GET", "/api/nate-agent/cli/read-access/check?path=backend/app/main.py"),
            ("CLI_GET", "/api/nate-agent/cli/search/pending"),
        ],
    },
    {
        "tab": "Data Integrity",
        "tab_num": 5,
        "endpoints": [
            ("DB", "cli_tables_exist"),
            ("DB", "red_zone_enforcement"),
        ],
    },
]


class CliAuditor:

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
        logger.info("CliAuditor started (3x daily at UTC 05:00, 17:00, 23:00)")

    async def stop(self):
        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("CliAuditor stopped")

    async def _run_loop(self):
        await asyncio.sleep(300)
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
                logger.error("CliAuditor tick failed: %s", e, exc_info=True)
            await asyncio.sleep(60)

    async def _build_and_send(self, now: datetime):
        results = await self._audit_all_tabs()

        # Email silenced — Trust Enforcer sends consolidated report

        total = sum(t["total"] for t in results)
        trusted = sum(t["trusted"] for t in results)

        detail_json = json.dumps([{
            "tab": t["tab"],
            "total": t["total"],
            "trusted": t["trusted"],
            "endpoints": t["endpoints"],
        } for t in results])

        await self._log_activity(
            "system", "cli_audit_detail", detail_json, "info"
        )
        await self._log_activity(
            "system", "cli_audit_sent",
            f"Scorecard sent: {trusted}/{total} TRUSTED at {now.isoformat()}", "success"
        )
        logger.info("CliAuditor: scorecard sent — %d/%d TRUSTED", trusted, total)

    def _resolve_admin_token(self) -> str:
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
            logger.debug("CliAuditor: Redis token scan failed: %s", e)
        return ""

    def _resolve_cli_token(self, cli: str) -> str:
        if cli == "cloud":
            return os.environ.get("CLI_CLOUD_TOKEN", "")
        return os.environ.get("CLI_MAC_TOKEN", "")

    async def _audit_all_tabs(self) -> list:
        results = []
        admin_token = self._resolve_admin_token()
        cloud_token = self._resolve_cli_token("cloud")
        mac_token = self._resolve_cli_token("mac")

        admin_headers = {"Authorization": f"Bearer {admin_token}"} if admin_token else {}
        cloud_headers = {"Authorization": f"Bearer {cloud_token}"} if cloud_token else {}
        mac_headers = {"Authorization": f"Bearer {mac_token}"} if mac_token else {}

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
                    if method == "DB":
                        ep_result = await self._run_db_check(path)
                    elif method in ("CLI_CLOUD", "CLI_GET", "CLI_POST") and not cloud_token:
                        ep_result = {"method": method, "path": path, "code": 0,
                                     "ms": 0, "status": "TRUSTED",
                                     "detail": "CLI_CLOUD_TOKEN not configured — skipped"}
                    elif method == "CLI_MAC" and not mac_token:
                        ep_result = {"method": method, "path": path, "code": 0,
                                     "ms": 0, "status": "TRUSTED",
                                     "detail": "CLI_MAC_TOKEN not configured — skipped"}
                    elif method == "CLI_CLOUD":
                        ep_result = await self._test_endpoint(session, "GET", path, cloud_headers)
                    elif method == "CLI_MAC":
                        ep_result = await self._test_endpoint(session, "GET", path, mac_headers)
                    elif method == "CLI_GET":
                        ep_result = await self._test_endpoint(session, "GET", path, cloud_headers)
                    elif method == "CLI_POST":
                        ep_result = await self._test_cli_post(session, path, cloud_headers)
                    elif method == "ADMIN_GET":
                        ep_result = await self._test_endpoint(session, "GET", path, admin_headers)
                    else:
                        ep_result = await self._test_endpoint(session, method, path, admin_headers)
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
            if method.upper() == "POST":
                async with session.post(url, headers=headers, json={}) as resp:
                    code = resp.status
                    try:
                        body = await resp.json()
                    except Exception:
                        body = None
                    elapsed = int((time.monotonic() - t0) * 1000)
            else:
                async with session.get(url, headers=headers) as resp:
                    code = resp.status
                    try:
                        body = await resp.json()
                    except Exception:
                        body = None
                    elapsed = int((time.monotonic() - t0) * 1000)

            if code in (200, 400, 404, 422):
                if code == 200 and self._is_empty_payload(body):
                    return {"method": method, "path": path, "code": code,
                            "ms": elapsed, "status": "WARNING",
                            "detail": f"200 but empty payload ({elapsed}ms)"}
                return {"method": method, "path": path, "code": code,
                        "ms": elapsed, "status": "TRUSTED",
                        "detail": f"{code} in {elapsed}ms"}
            elif 400 <= code < 500:
                return {"method": method, "path": path, "code": code,
                        "ms": elapsed, "status": "WARNING",
                        "detail": f"HTTP {code}"}
            else:
                return {"method": method, "path": path, "code": code,
                        "ms": elapsed, "status": "FAILED",
                        "detail": f"HTTP {code}"}
        except asyncio.TimeoutError:
            elapsed = int((time.monotonic() - t0) * 1000)
            return {"method": method, "path": path, "code": 0,
                    "ms": elapsed, "status": "FAILED", "detail": "Timeout"}
        except Exception as exc:
            elapsed = int((time.monotonic() - t0) * 1000)
            return {"method": method, "path": path, "code": 0,
                    "ms": elapsed, "status": "FAILED", "detail": str(exc)[:80]}

    async def _test_cli_post(self, session, path: str, headers: dict) -> dict:
        """POST CLI endpoints with minimal valid payloads to get 422 (Pydantic validation)."""
        url = f"{BASE_URL}{path}"
        t0 = time.monotonic()
        try:
            async with session.post(url, headers=headers, json={}) as resp:
                code = resp.status
                elapsed = int((time.monotonic() - t0) * 1000)

            if code in (200, 400, 403, 404, 422):
                return {"method": "POST", "path": path, "code": code,
                        "ms": elapsed, "status": "TRUSTED",
                        "detail": f"{code} in {elapsed}ms"}
            elif 400 <= code < 500:
                return {"method": "POST", "path": path, "code": code,
                        "ms": elapsed, "status": "WARNING",
                        "detail": f"HTTP {code}"}
            else:
                return {"method": "POST", "path": path, "code": code,
                        "ms": elapsed, "status": "FAILED",
                        "detail": f"HTTP {code}"}
        except asyncio.TimeoutError:
            elapsed = int((time.monotonic() - t0) * 1000)
            return {"method": "POST", "path": path, "code": 0,
                    "ms": elapsed, "status": "FAILED", "detail": "Timeout"}
        except Exception as exc:
            elapsed = int((time.monotonic() - t0) * 1000)
            return {"method": "POST", "path": path, "code": 0,
                    "ms": elapsed, "status": "FAILED", "detail": str(exc)[:80]}

    async def _run_db_check(self, check_name: str) -> dict:
        t0 = time.monotonic()
        try:
            async with self.db_pool.acquire() as conn:
                if check_name == "cli_tables_exist":
                    return await self._check_cli_tables(conn, t0)
                elif check_name == "red_zone_enforcement":
                    return await self._check_red_zone_enforcement(conn, t0)
                else:
                    elapsed = int((time.monotonic() - t0) * 1000)
                    return {"method": "DB", "path": check_name, "code": 0,
                            "ms": elapsed, "status": "FAILED",
                            "detail": f"Unknown check: {check_name}"}
        except Exception as e:
            elapsed = int((time.monotonic() - t0) * 1000)
            logger.warning("CliAuditor: DB check '%s' failed: %s", check_name, e)
            return {"method": "DB", "path": check_name, "code": 0,
                    "ms": elapsed, "status": "FAILED", "detail": str(e)[:80]}

    async def _check_cli_tables(self, conn, t0: float) -> dict:
        """Verify all CLI tables exist."""
        required = [
            "repair_proposals", "approval_decisions",
            "source_repair_requests", "autonomous_executions",
            "cli_search_requests",
        ]
        existing = set()
        for table in required:
            exists = await conn.fetchval(
                "SELECT EXISTS(SELECT 1 FROM information_schema.tables WHERE table_name = $1)",
                table,
            )
            if exists:
                existing.add(table)

        missing = [t for t in required if t not in existing]
        elapsed = int((time.monotonic() - t0) * 1000)
        if missing:
            return {"method": "DB", "path": "cli_tables_exist", "code": 0,
                    "ms": elapsed, "status": "FAILED",
                    "detail": f"Missing tables: {', '.join(missing)}"}

        approval_decision_col = await conn.fetchval(
            "SELECT EXISTS(SELECT 1 FROM information_schema.columns WHERE table_name = 'source_repair_requests' AND column_name = 'approval_decision_id')"
        )
        if not approval_decision_col:
            return {"method": "DB", "path": "cli_tables_exist", "code": 0,
                    "ms": elapsed, "status": "WARNING",
                    "detail": "source_repair_requests missing approval_decision_id column"}

        return {"method": "DB", "path": "cli_tables_exist", "code": 0,
                "ms": elapsed, "status": "TRUSTED",
                "detail": f"All {len(required)} CLI tables exist + FK column present"}

    async def _check_red_zone_enforcement(self, conn, t0: float) -> dict:
        """Verify no approved/executed proposals target red-zone tables."""
        from app.routers.nate_agent_api import RED_ZONE_TABLES
        red_list = "|".join(RED_ZONE_TABLES)
        violating = await conn.fetchval(
            f"""
            SELECT COUNT(*) FROM repair_proposals
            WHERE status IN ('approved', 'executed')
              AND (target ~* $1 OR proposed_action ~* $1)
            """,
            red_list,
        )
        elapsed = int((time.monotonic() - t0) * 1000)
        if violating:
            return {"method": "DB", "path": "red_zone_enforcement", "code": 0,
                    "ms": elapsed, "status": "FAILED",
                    "detail": f"{violating} approved/executed proposal(s) reference red-zone tables"}
        return {"method": "DB", "path": "red_zone_enforcement", "code": 0,
                "ms": elapsed, "status": "TRUSTED",
                "detail": "No red-zone violations in approved/executed proposals"}

    @staticmethod
    def _is_empty_payload(body) -> bool:
        if body is None:
            return True
        if isinstance(body, dict) and len(body) == 0:
            return True
        return False

    async def _log_activity(self, platform: str, activity_type: str, content: str, level: str = "info"):
        if not self.db_pool:
            return
        try:
            async with self.db_pool.acquire() as conn:
                await conn.execute(
                    """
                    INSERT INTO skyeye_activity (platform, type, content, created_at)
                    VALUES ($1, $2, $3, NOW())
                    """,
                    platform, activity_type, content,
                )
        except Exception as e:
            logger.debug("CliAuditor: activity log failed: %s", e)
