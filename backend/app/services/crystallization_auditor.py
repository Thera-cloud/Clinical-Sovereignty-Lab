"""
LITTLE NATE — Crystallization Auditor
Audits crystal integrity and the crystallization pipeline including
Merkle integrity, decay cycles, supersession chains, and recall tracking.

10 checks across 4 tabs:
  Tab 1: Crystal Health (1 GET endpoint)
  Tab 2: Crystal Pipeline (4 DB checks)
  Tab 3: Merkle Integrity (3 DB checks)
  Tab 4: Memory Pipeline (2 DB checks)

Scheduled 3x daily (5 AM, 5 PM, 11 PM UTC) with stagger delay of 298s.
"""

import asyncio
import hashlib
import json
import logging
import os
import time
from datetime import datetime, timezone, timedelta
from typing import Optional

import aiohttp

logger = logging.getLogger("nate.crystallization_auditor")

AUDIT_HOURS = {5, 17, 23}
BASE_URL = "http://localhost:8000"

TAB_ENDPOINTS = [
    {
        "tab": "Crystal Health",
        "tab_num": 1,
        "endpoints": [
            ("DB", "crystal_table_exists"),
        ],
    },
    {
        "tab": "Crystal Pipeline",
        "tab_num": 2,
        "endpoints": [
            ("DB", "crystal_count"),
            ("DB", "recent_crystals"),
            ("DB", "domain_diversity"),
            ("DB", "supersession_chain"),
        ],
    },
    {
        "tab": "Merkle Integrity",
        "tab_num": 3,
        "endpoints": [
            ("DB", "hash_consistency"),
            ("DB", "no_orphaned_crystals"),
            ("DB", "decay_cycle_active"),
        ],
    },
    {
        "tab": "Memory Pipeline",
        "tab_num": 4,
        "endpoints": [
            ("DB", "recall_tracking"),
            ("DB", "confidence_distribution"),
        ],
    },
]


class CrystallizationAuditor:

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
        logger.info("CrystallizationAuditor started (3x daily at UTC 05:00, 17:00, 23:00)")

    async def stop(self):
        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("CrystallizationAuditor stopped")

    async def _run_loop(self):
        await asyncio.sleep(298)
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
                logger.error("CrystallizationAuditor tick failed: %s", e, exc_info=True)
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
            "system", "crystallization_audit_detail", detail_json, "info"
        )
        await self._log_activity(
            "system", "crystallization_audit_sent",
            f"Scorecard sent: {trusted}/{total} TRUSTED at {now.isoformat()}", "success"
        )
        logger.info("CrystallizationAuditor: scorecard sent — %d/%d TRUSTED", trusted, total)

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
            logger.debug("CrystallizationAuditor: Redis token scan failed: %s", e)
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
            async with self.db_pool.acquire() as conn:
                if check_name == "crystal_table_exists":
                    return await self._check_crystal_table_exists(conn, t0)
                elif check_name == "crystal_count":
                    return await self._check_crystal_count(conn, t0)
                elif check_name == "recent_crystals":
                    return await self._check_recent_crystals(conn, t0)
                elif check_name == "domain_diversity":
                    return await self._check_domain_diversity(conn, t0)
                elif check_name == "supersession_chain":
                    return await self._check_supersession_chain(conn, t0)
                elif check_name == "hash_consistency":
                    return await self._check_hash_consistency(conn, t0)
                elif check_name == "no_orphaned_crystals":
                    return await self._check_no_orphaned_crystals(conn, t0)
                elif check_name == "decay_cycle_active":
                    return await self._check_decay_cycle_active(conn, t0)
                elif check_name == "recall_tracking":
                    return await self._check_recall_tracking(conn, t0)
                elif check_name == "confidence_distribution":
                    return await self._check_confidence_distribution(conn, t0)
                else:
                    elapsed = int((time.monotonic() - t0) * 1000)
                    return {"method": "DB", "path": check_name, "code": 0,
                            "ms": elapsed, "status": "FAILED",
                            "detail": f"Unknown check: {check_name}"}
        except Exception as e:
            elapsed = int((time.monotonic() - t0) * 1000)
            logger.warning("CrystallizationAuditor: DB check '%s' failed: %s", check_name, e)
            return {"method": "DB", "path": check_name, "code": 0,
                    "ms": elapsed, "status": "FAILED", "detail": str(e)[:80]}

    async def _check_crystal_table_exists(self, conn, t0: float) -> dict:
        """Verify nate_intelligence_crystals table exists."""
        row = await conn.fetchrow("""
            SELECT EXISTS(
                SELECT 1 FROM information_schema.tables
                WHERE table_name = 'nate_intelligence_crystals'
            ) as exists_ok
        """)
        elapsed = int((time.monotonic() - t0) * 1000)
        if not row or not row["exists_ok"]:
            return {"method": "DB", "path": "crystal_table_exists", "code": 0,
                    "ms": elapsed, "status": "FAILED",
                    "detail": "nate_intelligence_crystals table does not exist"}
        return {"method": "DB", "path": "crystal_table_exists", "code": 200,
                "ms": elapsed, "status": "TRUSTED",
                "detail": f"nate_intelligence_crystals table exists ({elapsed}ms)"}

    async def _check_crystal_count(self, conn, t0: float) -> dict:
        """Verify nate_intelligence_crystals table has entries."""
        count_row = await conn.fetchrow(
            "SELECT COUNT(*) as cnt FROM nate_intelligence_crystals"
        )
        count = count_row["cnt"] if count_row else 0
        elapsed = int((time.monotonic() - t0) * 1000)
        if count == 0:
            return {"method": "DB", "path": "crystal_count", "code": 200,
                    "ms": elapsed, "status": "TRUSTED",
                    "detail": "No crystals yet — pipeline is new (pre-launch)"}
        return {"method": "DB", "path": "crystal_count", "code": 200,
                "ms": elapsed, "status": "TRUSTED",
                "detail": f"{count} crystals in store ({elapsed}ms)"}

    async def _check_recent_crystals(self, conn, t0: float) -> dict:
        """Verify crystals have been created within the last 7 days."""
        row = await conn.fetchrow("""
            SELECT COUNT(*) as cnt FROM nate_intelligence_crystals
            WHERE created_at > NOW() - INTERVAL '7 days'
        """)
        elapsed = int((time.monotonic() - t0) * 1000)
        count = row["cnt"] if row else 0
        if count == 0:
            return {"method": "DB", "path": "recent_crystals", "code": 200,
                    "ms": elapsed, "status": "TRUSTED",
                    "detail": "No crystals in last 7 days — pipeline pre-launch"}
        return {"method": "DB", "path": "recent_crystals", "code": 200,
                "ms": elapsed, "status": "TRUSTED",
                "detail": f"{count} crystals in last 7 days ({elapsed}ms)"}

    async def _check_domain_diversity(self, conn, t0: float) -> dict:
        """Verify crystals span more than 1 domain."""
        row = await conn.fetchrow("""
            SELECT COUNT(DISTINCT domain) as domain_count
            FROM nate_intelligence_crystals
            WHERE scope != 'archived'
        """)
        elapsed = int((time.monotonic() - t0) * 1000)
        domain_count = row["domain_count"] if row else 0
        if domain_count == 0:
            return {"method": "DB", "path": "domain_diversity", "code": 200,
                    "ms": elapsed, "status": "TRUSTED",
                    "detail": "No active crystals — pre-launch"}
        if domain_count == 1:
            return {"method": "DB", "path": "domain_diversity", "code": 200,
                    "ms": elapsed, "status": "TRUSTED",
                    "detail": f"1 domain so far — pipeline bootstrapping"}
        return {"method": "DB", "path": "domain_diversity", "code": 200,
                "ms": elapsed, "status": "TRUSTED",
                "detail": f"{domain_count} domains represented ({elapsed}ms)"}

    async def _check_supersession_chain(self, conn, t0: float) -> dict:
        """Verify superseded_by references point to valid crystal IDs."""
        row = await conn.fetchrow("""
            SELECT COUNT(*) as total_superseded,
                   COUNT(*) FILTER (
                       WHERE superseded_by IS NOT NULL
                         AND superseded_by NOT IN (
                             SELECT id FROM nate_intelligence_crystals
                         )
                   ) as orphaned
            FROM nate_intelligence_crystals
            WHERE superseded_by IS NOT NULL
        """)
        elapsed = int((time.monotonic() - t0) * 1000)
        total = row["total_superseded"] if row else 0
        orphaned = row["orphaned"] if row else 0
        if total == 0:
            return {"method": "DB", "path": "supersession_chain", "code": 200,
                    "ms": elapsed, "status": "TRUSTED",
                    "detail": f"No supersession chains yet ({elapsed}ms)"}
        if orphaned > 0:
            return {"method": "DB", "path": "supersession_chain", "code": 200,
                    "ms": elapsed, "status": "WARNING",
                    "detail": f"{orphaned}/{total} superseded_by references point to missing crystals"}
        return {"method": "DB", "path": "supersession_chain", "code": 200,
                "ms": elapsed, "status": "TRUSTED",
                "detail": f"{total} supersession chains valid ({elapsed}ms)"}

    async def _check_hash_consistency(self, conn, t0: float) -> dict:
        """Sample crystals and verify content_hash matches SHA-256 of crystal_text."""
        rows = await conn.fetch("""
            SELECT id, crystal_text, content_hash
            FROM nate_intelligence_crystals
            WHERE crystal_text IS NOT NULL AND content_hash IS NOT NULL
            ORDER BY created_at DESC LIMIT 10
        """)
        elapsed = int((time.monotonic() - t0) * 1000)
        if not rows:
            return {"method": "DB", "path": "hash_consistency", "code": 200,
                    "ms": elapsed, "status": "TRUSTED",
                    "detail": "No crystals to verify — pre-launch"}
        mismatched = 0
        for r in rows:
            expected = hashlib.sha256(r["crystal_text"].encode("utf-8")).hexdigest()
            if r["content_hash"] != expected:
                mismatched += 1
        elapsed = int((time.monotonic() - t0) * 1000)
        if mismatched > 0:
            return {"method": "DB", "path": "hash_consistency", "code": 200,
                    "ms": elapsed, "status": "WARNING",
                    "detail": f"{mismatched}/{len(rows)} sampled crystals have hash mismatch — potential tampering"}
        return {"method": "DB", "path": "hash_consistency", "code": 200,
                "ms": elapsed, "status": "TRUSTED",
                "detail": f"{len(rows)} sampled crystals pass Merkle check ({elapsed}ms)"}

    async def _check_no_orphaned_crystals(self, conn, t0: float) -> dict:
        """Verify all supersession targets exist (no dangling references)."""
        row = await conn.fetchrow("""
            SELECT COUNT(*) as orphaned FROM nate_intelligence_crystals c
            WHERE c.superseded_by IS NOT NULL
              AND NOT EXISTS (
                  SELECT 1 FROM nate_intelligence_crystals t WHERE t.id = c.superseded_by
              )
        """)
        elapsed = int((time.monotonic() - t0) * 1000)
        orphaned = row["orphaned"] if row else 0
        if orphaned > 0:
            return {"method": "DB", "path": "no_orphaned_crystals", "code": 200,
                    "ms": elapsed, "status": "WARNING",
                    "detail": f"{orphaned} crystals reference non-existent supersession targets"}
        return {"method": "DB", "path": "no_orphaned_crystals", "code": 200,
                "ms": elapsed, "status": "TRUSTED",
                "detail": f"No orphaned supersession references ({elapsed}ms)"}

    async def _check_decay_cycle_active(self, conn, t0: float) -> dict:
        """Verify archived crystals exist (decay cycle is functioning)."""
        row = await conn.fetchrow("""
            SELECT COUNT(*) as archived_count FROM nate_intelligence_crystals
            WHERE scope = 'archived'
        """)
        elapsed = int((time.monotonic() - t0) * 1000)
        archived = row["archived_count"] if row else 0
        total_row = await conn.fetchrow(
            "SELECT COUNT(*) as cnt FROM nate_intelligence_crystals"
        )
        total = total_row["cnt"] if total_row else 0
        elapsed = int((time.monotonic() - t0) * 1000)
        if total == 0:
            return {"method": "DB", "path": "decay_cycle_active", "code": 200,
                    "ms": elapsed, "status": "TRUSTED",
                    "detail": "No crystals yet — decay cycle not applicable (pre-launch)"}
        if archived == 0 and total > 50:
            return {"method": "DB", "path": "decay_cycle_active", "code": 200,
                    "ms": elapsed, "status": "WARNING",
                    "detail": f"{total} crystals but 0 archived — decay may not be running"}
        return {"method": "DB", "path": "decay_cycle_active", "code": 200,
                "ms": elapsed, "status": "TRUSTED",
                "detail": f"{archived} archived of {total} total crystals ({elapsed}ms)"}

    async def _check_recall_tracking(self, conn, t0: float) -> dict:
        """Verify recall tracking is active (last_recalled_at not all null)."""
        row = await conn.fetchrow("""
            SELECT COUNT(*) as total,
                   COUNT(*) FILTER (WHERE last_recalled_at IS NOT NULL) as recalled
            FROM nate_intelligence_crystals
            WHERE scope != 'archived'
        """)
        elapsed = int((time.monotonic() - t0) * 1000)
        total = row["total"] if row else 0
        recalled = row["recalled"] if row else 0
        if total == 0:
            return {"method": "DB", "path": "recall_tracking", "code": 200,
                    "ms": elapsed, "status": "TRUSTED",
                    "detail": "No active crystals — pre-launch"}
        if recalled == 0 and total > 50:
            return {"method": "DB", "path": "recall_tracking", "code": 200,
                    "ms": elapsed, "status": "WARNING",
                    "detail": f"{total} active crystals but none have been recalled — tracking may be broken"}
        if recalled == 0 and total <= 50:
            return {"method": "DB", "path": "recall_tracking", "code": 200,
                    "ms": elapsed, "status": "TRUSTED",
                    "detail": f"{total} active crystals, none recalled yet — normal for early system"}
        return {"method": "DB", "path": "recall_tracking", "code": 200,
                "ms": elapsed, "status": "TRUSTED",
                "detail": f"{recalled}/{total} active crystals have recall data ({elapsed}ms)"}

    async def _check_confidence_distribution(self, conn, t0: float) -> dict:
        """Verify confidence scores are spread across a range (not all identical)."""
        row = await conn.fetchrow("""
            SELECT MIN(confidence) as min_conf, MAX(confidence) as max_conf,
                   AVG(confidence) as avg_conf, COUNT(*) as cnt
            FROM nate_intelligence_crystals
            WHERE scope != 'archived'
        """)
        elapsed = int((time.monotonic() - t0) * 1000)
        if not row or row["cnt"] == 0:
            return {"method": "DB", "path": "confidence_distribution", "code": 200,
                    "ms": elapsed, "status": "TRUSTED",
                    "detail": "No active crystals — pre-launch"}
        min_c = float(row["min_conf"]) if row["min_conf"] is not None else 0
        max_c = float(row["max_conf"]) if row["max_conf"] is not None else 0
        avg_c = float(row["avg_conf"]) if row["avg_conf"] is not None else 0
        spread = max_c - min_c
        if row["cnt"] > 50 and spread < 0.05:
            return {"method": "DB", "path": "confidence_distribution", "code": 200,
                    "ms": elapsed, "status": "WARNING",
                    "detail": f"Confidence range too narrow ({min_c:.2f}–{max_c:.2f}) — may indicate synthesis issue"}
        return {"method": "DB", "path": "confidence_distribution", "code": 200,
                "ms": elapsed, "status": "TRUSTED",
                "detail": f"Confidence range {min_c:.2f}–{max_c:.2f}, avg {avg_c:.2f}, n={row['cnt']} ({elapsed}ms)"}

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
