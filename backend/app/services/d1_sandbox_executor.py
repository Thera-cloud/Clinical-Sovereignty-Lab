"""
D1 Sandbox Executor — Manages SQL operations on cli-chamberofsecrets.

Nate's creative workspace. All table names must start with nate_ext_.
Uses the same D1 REST API pattern as d1_sync_agent.py.
"""

import asyncio
import json
import logging
import os
import re
from typing import Any, Dict, List, Optional

import aiohttp

logger = logging.getLogger("d1_sandbox")

_CF_ACCOUNT_ID = os.getenv("CLOUDFLARE_ACCOUNT_ID", "").strip()
_CF_API_TOKEN = os.getenv("CLOUDFLARE_API_TOKEN", "").strip()
_D1_SANDBOX_ID = os.getenv("D1_SANDBOX_DATABASE_ID", "bedabdd5-ab9d-4a56-b2").strip()

D1_API_URL = "https://api.cloudflare.com/client/v4/accounts/{account_id}/d1/database/{db_id}/query"

_MAX_TABLES = 100
_STORAGE_WARN_GB = 8.0
_STORAGE_STOP_GB = 9.5
_NATE_EXT_PREFIX = "nate_ext_"

_TABLE_NAME_RE = re.compile(r"^nate_ext_[a-z][a-z0-9_]{0,60}$")

RED_ZONE_TABLES = frozenset({
    "users", "webauthn", "totp", "password_hash", "profile_data",
    "login_attempts", "password_reset_tokens",
})


class D1SandboxExecutor:
    def __init__(self):
        self._session: Optional[aiohttp.ClientSession] = None
        self._configured = bool(_CF_ACCOUNT_ID and _CF_API_TOKEN and _D1_SANDBOX_ID)

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(
                headers={
                    "Authorization": f"Bearer {_CF_API_TOKEN}",
                    "Content-Type": "application/json",
                },
                timeout=aiohttp.ClientTimeout(total=30),
            )
        return self._session

    async def _execute(self, sql: str, params: Optional[List] = None) -> Optional[List[Dict]]:
        if not self._configured:
            logger.debug("D1 sandbox not configured — skipping")
            return None
        url = D1_API_URL.format(account_id=_CF_ACCOUNT_ID, db_id=_D1_SANDBOX_ID)
        payload: Dict[str, Any] = {"sql": sql}
        if params:
            payload["params"] = params
        try:
            session = await self._get_session()
            async with session.post(url, json=payload) as resp:
                if resp.status != 200:
                    body = await resp.text()
                    logger.warning("D1 sandbox query failed (%d): %s", resp.status, body[:200])
                    return None
                data = await resp.json()
                results = data.get("result", [])
                if results and isinstance(results, list) and len(results) > 0:
                    return results[0].get("results", [])
                return []
        except Exception as e:
            logger.warning("D1 sandbox error: %s", e)
            return None

    def _validate_table_name(self, name: str) -> Optional[str]:
        if not name.startswith(_NATE_EXT_PREFIX):
            return f"Table name must start with '{_NATE_EXT_PREFIX}'"
        if not _TABLE_NAME_RE.match(name):
            return f"Invalid table name format: {name}"
        base = name.replace(_NATE_EXT_PREFIX, "").lower()
        if base in RED_ZONE_TABLES:
            return f"Red zone violation: table name shadows protected table"
        return None

    async def create_table(self, table_name: str, columns: List[Dict[str, str]],
                           extension_id: str, domain: str) -> Dict[str, Any]:
        err = self._validate_table_name(table_name)
        if err:
            return {"ok": False, "error": err}

        count = await self.get_table_count()
        if count >= _MAX_TABLES:
            return {"ok": False, "error": f"Table limit reached ({_MAX_TABLES})"}

        col_defs = []
        for col in columns:
            name = col.get("name", "")
            dtype = col.get("type", "TEXT")
            if not re.match(r"^[a-z][a-z0-9_]{0,60}$", name):
                return {"ok": False, "error": f"Invalid column name: {name}"}
            col_defs.append(f"{name} {dtype}")

        sql = f"CREATE TABLE IF NOT EXISTS {table_name} ({', '.join(col_defs)})"
        result = await self._execute(sql)
        if result is None:
            return {"ok": False, "error": "D1 execution failed"}

        await self._execute(
            "INSERT OR REPLACE INTO nate_ext_metadata (table_name, extension_id, domain, created_at) "
            "VALUES (?, ?, ?, datetime('now'))",
            [table_name, extension_id, domain],
        )
        return {"ok": True, "table": table_name}

    async def drop_table(self, table_name: str) -> Dict[str, Any]:
        err = self._validate_table_name(table_name)
        if err:
            return {"ok": False, "error": err}
        await self._execute(f"DROP TABLE IF EXISTS {table_name}")
        await self._execute("DELETE FROM nate_ext_metadata WHERE table_name = ?", [table_name])
        return {"ok": True}

    async def query(self, table_name: str, where: str = "", params: Optional[List] = None,
                    limit: int = 1000) -> Optional[List[Dict]]:
        err = self._validate_table_name(table_name)
        if err:
            return None
        sql = f"SELECT * FROM {table_name}"
        if where:
            sql += f" WHERE {where}"
        sql += f" LIMIT {min(limit, 5000)}"
        return await self._execute(sql, params)

    async def insert(self, table_name: str, rows: List[Dict[str, Any]]) -> Dict[str, Any]:
        err = self._validate_table_name(table_name)
        if err:
            return {"ok": False, "error": err}
        if not rows:
            return {"ok": True, "inserted": 0}

        inserted = 0
        for row in rows[:500]:
            cols = list(row.keys())
            placeholders = ", ".join(["?"] * len(cols))
            col_names = ", ".join(cols)
            vals = [row[c] for c in cols]
            result = await self._execute(
                f"INSERT INTO {table_name} ({col_names}) VALUES ({placeholders})", vals
            )
            if result is not None:
                inserted += 1
        return {"ok": True, "inserted": inserted}

    async def insert_formula_result(self, formula_name: str, domain: str,
                                    entanglement: float, tunneling: float,
                                    noise: float, load_val: float, time_val: float,
                                    coherence: float, metadata: str = "") -> bool:
        result = await self._execute(
            "INSERT INTO nate_ext_formula_results "
            "(formula_name, domain, entanglement, tunneling, noise, load_val, time_val, "
            "coherence_result, computed_at, metadata) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, datetime('now'), ?)",
            [formula_name, domain, entanglement, tunneling, noise,
             load_val, time_val, coherence, metadata],
        )
        return result is not None

    async def log_webhook(self, webhook_name: str, target_url: str,
                          status_code: int, response_body: str = "") -> bool:
        result = await self._execute(
            "INSERT INTO nate_ext_webhook_log "
            "(webhook_name, target_url, status_code, response_body, fired_at) "
            "VALUES (?, ?, ?, ?, datetime('now'))",
            [webhook_name, target_url, status_code, response_body[:2000]],
        )
        return result is not None

    async def get_table_count(self) -> int:
        result = await self._execute("SELECT COUNT(*) as cnt FROM nate_ext_metadata")
        if result and len(result) > 0:
            return result[0].get("cnt", 0)
        return 0

    async def list_tables(self) -> List[Dict]:
        result = await self._execute(
            "SELECT table_name, extension_id, domain, created_at, row_count "
            "FROM nate_ext_metadata ORDER BY created_at DESC"
        )
        return result or []

    async def prune_formula_results(self, days: int = 90) -> int:
        before = await self._execute("SELECT COUNT(*) as cnt FROM nate_ext_formula_results")
        await self._execute(
            f"DELETE FROM nate_ext_formula_results WHERE computed_at < date('now', '-{days} days')"
        )
        after = await self._execute("SELECT COUNT(*) as cnt FROM nate_ext_formula_results")
        if before and after:
            return max(0, int(before[0].get("cnt", 0)) - int(after[0].get("cnt", 0)))
        return 0

    async def prune_webhook_log(self, days: int = 60) -> int:
        before = await self._execute("SELECT COUNT(*) as cnt FROM nate_ext_webhook_log")
        await self._execute(
            f"DELETE FROM nate_ext_webhook_log WHERE fired_at < date('now', '-{days} days')"
        )
        after = await self._execute("SELECT COUNT(*) as cnt FROM nate_ext_webhook_log")
        if before and after:
            return max(0, int(before[0].get("cnt", 0)) - int(after[0].get("cnt", 0)))
        return 0

    def health(self) -> Dict[str, Any]:
        return {
            "configured": self._configured,
            "database_id": _D1_SANDBOX_ID[:12] + "..." if _D1_SANDBOX_ID else "none",
        }
