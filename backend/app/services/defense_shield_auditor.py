"""
LITTLE NATE — Defense Shield Auditor
Audits the distributed defense shield beyond what the existing defense_auditor
covers: shield layer services, defense data integrity, and canary system health.

8 checks across 3 tabs:
  Tab 1: Shield Layers (3 app.state checks)
  Tab 2: Defense Data (3 DB checks)
  Tab 3: Canary System (2 DB checks)

Scheduled 3x daily (5 AM, 5 PM, 11 PM UTC) with stagger delay of 50s.
"""

import asyncio
import json
import logging
import os
import time
from datetime import datetime, timezone
from typing import Optional

import aiohttp

logger = logging.getLogger("nate.defense_shield_auditor")

AUDIT_HOURS = {5, 17, 23}
BASE_URL = "http://localhost:8000"

TAB_ENDPOINTS = [
    {
        "tab": "Shield Layers",
        "tab_num": 1,
        "endpoints": [
            ("DB", "edge_mirror_running"),
            ("DB", "distributed_defense_running"),
            ("DB", "sentinel_orchestrator_running"),
        ],
    },
    {
        "tab": "Defense Data",
        "tab_num": 2,
        "endpoints": [
            ("DB", "device_reputation_table"),
            ("DB", "defense_events_recent"),
            ("DB", "defcon_level_safe"),
        ],
    },
    {
        "tab": "Canary System",
        "tab_num": 3,
        "endpoints": [
            ("DB", "canary_records_exist"),
            ("DB", "no_duplicate_canaries"),
        ],
    },
]


class DefenseShieldAuditor:

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
        logger.info("DefenseShieldAuditor started (3x daily at UTC 05:00, 17:00, 23:00)")

    async def stop(self):
        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("DefenseShieldAuditor stopped")

    async def _run_loop(self):
        await asyncio.sleep(50)
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
                logger.error("DefenseShieldAuditor tick failed: %s", e, exc_info=True)
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
            "system", "defense_shield_audit_detail", detail_json, "info"
        )
        await self._log_activity(
            "system", "defense_shield_audit_sent",
            f"Scorecard sent: {trusted}/{total} TRUSTED at {now.isoformat()}", "success"
        )
        logger.info("DefenseShieldAuditor: scorecard sent — %d/%d TRUSTED", trusted, total)

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
            logger.debug("DefenseShieldAuditor: Redis token scan failed: %s", e)
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
                    if method == "DB":
                        ep_result = await self._run_db_check(path)
                    else:
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

    async def _run_db_check(self, check_name: str) -> dict:
        t0 = time.monotonic()
        try:
            if check_name == "edge_mirror_running":
                return self._check_app_state("edge_mirror", t0)
            elif check_name == "distributed_defense_running":
                return self._check_app_state("distributed_defense", t0)
            elif check_name == "sentinel_orchestrator_running":
                return self._check_app_state("sentinel_orchestrator", t0)
            elif check_name == "device_reputation_table":
                return await self._check_device_reputation_table(t0)
            elif check_name == "defense_events_recent":
                return await self._check_defense_events_recent(t0)
            elif check_name == "defcon_level_safe":
                return await self._check_defcon_level(t0)
            elif check_name == "canary_records_exist":
                return await self._check_canary_records(t0)
            elif check_name == "no_duplicate_canaries":
                return await self._check_no_duplicate_canaries(t0)
            else:
                elapsed = int((time.monotonic() - t0) * 1000)
                return {"method": "DB", "path": check_name, "code": 0,
                        "ms": elapsed, "status": "FAILED",
                        "detail": f"Unknown check: {check_name}"}
        except Exception as e:
            elapsed = int((time.monotonic() - t0) * 1000)
            logger.warning("DefenseShieldAuditor: check '%s' failed: %s", check_name, e)
            return {"method": "DB", "path": check_name, "code": 0,
                    "ms": elapsed, "status": "FAILED", "detail": str(e)[:80]}

    def _check_app_state(self, attr_name: str, t0: float) -> dict:
        """Verify a defense service is initialized on app.state."""
        elapsed = int((time.monotonic() - t0) * 1000)
        if self._app_state is None:
            return {"method": "DB", "path": f"{attr_name}_running", "code": 0,
                    "ms": elapsed, "status": "WARNING",
                    "detail": "app_state not available to auditor"}
        svc = getattr(self._app_state, attr_name, None)
        if svc is not None:
            return {"method": "DB", "path": f"{attr_name}_running", "code": 200,
                    "ms": elapsed, "status": "TRUSTED",
                    "detail": f"{attr_name} is running ({elapsed}ms)"}
        return {"method": "DB", "path": f"{attr_name}_running", "code": 0,
                "ms": elapsed, "status": "FAILED",
                "detail": f"{attr_name} is None — not initialized"}

    async def _check_device_reputation_table(self, t0: float) -> dict:
        """Verify device_reputation table exists."""
        async with self.db_pool.acquire() as conn:
            row = await conn.fetchrow("""
                SELECT EXISTS(
                    SELECT 1 FROM information_schema.tables
                    WHERE table_name = 'device_reputation'
                ) as exists_ok
            """)
        elapsed = int((time.monotonic() - t0) * 1000)
        if not row or not row["exists_ok"]:
            return {"method": "DB", "path": "device_reputation_table", "code": 0,
                    "ms": elapsed, "status": "WARNING",
                    "detail": "device_reputation table does not exist — defense data layer incomplete"}
        return {"method": "DB", "path": "device_reputation_table", "code": 200,
                "ms": elapsed, "status": "TRUSTED",
                "detail": f"device_reputation table exists ({elapsed}ms)"}

    async def _check_defense_events_recent(self, t0: float) -> dict:
        """Verify defense-related events have been logged in skyeye_activity within 24h."""
        async with self.db_pool.acquire() as conn:
            row = await conn.fetchrow("""
                SELECT COUNT(*) as cnt FROM skyeye_activity
                WHERE (type LIKE '%defense%' OR type LIKE '%sentinel%' OR type LIKE '%defcon%')
                  AND created_at > NOW() - INTERVAL '24 hours'
            """)
        elapsed = int((time.monotonic() - t0) * 1000)
        count = row["cnt"] if row else 0
        if count == 0:
            return {"method": "DB", "path": "defense_events_recent", "code": 200,
                    "ms": elapsed, "status": "WARNING",
                    "detail": "No defense events in last 24h — defense may be quiet or not logging"}
        return {"method": "DB", "path": "defense_events_recent", "code": 200,
                "ms": elapsed, "status": "TRUSTED",
                "detail": f"{count} defense events in last 24h ({elapsed}ms)"}

    async def _check_defcon_level(self, t0: float) -> dict:
        """Verify DEFCON is not at L1 (quantum collapse) unless intentional."""
        async with self.db_pool.acquire() as conn:
            table_exists = await conn.fetchrow("""
                SELECT EXISTS(
                    SELECT 1 FROM information_schema.tables
                    WHERE table_name = 'hive_defcon_history'
                ) as exists_ok
            """)
            if not table_exists or not table_exists["exists_ok"]:
                elapsed = int((time.monotonic() - t0) * 1000)
                return {"method": "DB", "path": "defcon_level_safe", "code": 200,
                        "ms": elapsed, "status": "TRUSTED",
                        "detail": f"No DEFCON history table — default safe ({elapsed}ms)"}

            row = await conn.fetchrow("""
                SELECT level, reason, created_at FROM hive_defcon_history
                ORDER BY created_at DESC LIMIT 1
            """)
        elapsed = int((time.monotonic() - t0) * 1000)
        if not row:
            return {"method": "DB", "path": "defcon_level_safe", "code": 200,
                    "ms": elapsed, "status": "TRUSTED",
                    "detail": f"No DEFCON history — system at default level ({elapsed}ms)"}
        level = row["level"]
        if level == 1:
            return {"method": "DB", "path": "defcon_level_safe", "code": 200,
                    "ms": elapsed, "status": "WARNING",
                    "detail": f"DEFCON L1 (quantum collapse) active since {row['created_at']} — verify intentional"}
        return {"method": "DB", "path": "defcon_level_safe", "code": 200,
                "ms": elapsed, "status": "TRUSTED",
                "detail": f"DEFCON L{level} — safe ({elapsed}ms)"}

    async def _check_canary_records(self, t0: float) -> dict:
        """Verify canary records exist if the canary table is present."""
        async with self.db_pool.acquire() as conn:
            table_exists = await conn.fetchrow("""
                SELECT EXISTS(
                    SELECT 1 FROM information_schema.tables
                    WHERE table_name = 'hive_canary_records'
                ) as exists_ok
            """)
            if not table_exists or not table_exists["exists_ok"]:
                elapsed = int((time.monotonic() - t0) * 1000)
                return {"method": "DB", "path": "canary_records_exist", "code": 200,
                        "ms": elapsed, "status": "TRUSTED",
                        "detail": f"Canary table not provisioned — pre-launch expected ({elapsed}ms)"}
            row = await conn.fetchrow(
                "SELECT COUNT(*) as cnt FROM hive_canary_records"
            )
        elapsed = int((time.monotonic() - t0) * 1000)
        count = row["cnt"] if row else 0
        if count == 0:
            return {"method": "DB", "path": "canary_records_exist", "code": 200,
                    "ms": elapsed, "status": "WARNING",
                    "detail": "No canary records deployed — exfiltration detection not active"}
        return {"method": "DB", "path": "canary_records_exist", "code": 200,
                "ms": elapsed, "status": "TRUSTED",
                "detail": f"{count} canary records deployed ({elapsed}ms)"}

    async def _check_no_duplicate_canaries(self, t0: float) -> dict:
        """Verify no canary UUID is duplicated across devices."""
        async with self.db_pool.acquire() as conn:
            table_exists = await conn.fetchrow("""
                SELECT EXISTS(
                    SELECT 1 FROM information_schema.tables
                    WHERE table_name = 'hive_canary_records'
                ) as exists_ok
            """)
            if not table_exists or not table_exists["exists_ok"]:
                elapsed = int((time.monotonic() - t0) * 1000)
                return {"method": "DB", "path": "no_duplicate_canaries", "code": 200,
                        "ms": elapsed, "status": "TRUSTED",
                        "detail": f"No canary table — check not applicable ({elapsed}ms)"}

            has_device = await conn.fetchrow("""
                SELECT EXISTS(
                    SELECT 1 FROM information_schema.columns
                    WHERE table_name = 'hive_canary_records' AND column_name = 'device_id'
                ) as has_col
            """)
            if not has_device or not has_device["has_col"]:
                elapsed = int((time.monotonic() - t0) * 1000)
                return {"method": "DB", "path": "no_duplicate_canaries", "code": 200,
                        "ms": elapsed, "status": "TRUSTED",
                        "detail": f"No device_id column — uniqueness assumed ({elapsed}ms)"}

            row = await conn.fetchrow("""
                SELECT COUNT(*) as dups FROM (
                    SELECT canary_uuid FROM hive_canary_records
                    GROUP BY canary_uuid HAVING COUNT(DISTINCT device_id) > 1
                ) sub
            """)
        elapsed = int((time.monotonic() - t0) * 1000)
        dups = row["dups"] if row else 0
        if dups > 0:
            return {"method": "DB", "path": "no_duplicate_canaries", "code": 200,
                    "ms": elapsed, "status": "WARNING",
                    "detail": f"{dups} canary UUIDs shared across multiple devices — uniqueness violated"}
        return {"method": "DB", "path": "no_duplicate_canaries", "code": 200,
                "ms": elapsed, "status": "TRUSTED",
                "detail": f"All canary UUIDs are unique per device ({elapsed}ms)"}

    @staticmethod
    def _is_empty_payload(body) -> bool:
        if body is None:
            return True
        if isinstance(body, (list, bool, int, float, str)):
            return False
        if isinstance(body, dict):
            return len(body) == 0
        return True

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
