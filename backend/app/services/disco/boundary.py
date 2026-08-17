"""Live BuildBoundary — four read-only v1.5 contracts. Never crash on miss."""

from __future__ import annotations

import logging
from typing import Any

from app.services.disco.pipeline import BuildBoundary
from app.services.disco.schema_keys import FORBIDDEN_TABLES, SCHEMA_KEYS

logger = logging.getLogger("disco.boundary")


def _tbl(contract: str, key: str) -> str:
    return SCHEMA_KEYS[contract][key][0]


def _col(contract: str, key: str) -> str:
    return SCHEMA_KEYS[contract][key][1]


class LiveBuildBoundary(BuildBoundary):
    """Probes live PG for contract presence; degrades per §18.2."""

    def __init__(self, db_pool=None, available=()):
        super().__init__(available=available)
        self.db_pool = db_pool

    async def refresh(self) -> dict:
        found = set()
        if not self.db_pool:
            self.available = found
            return self.readiness()
        users = _tbl("credentials", "class")
        rel_col = _col("credentials", "class")
        cred_tbl = _tbl("credentials", "credential_rows")
        eng_tbl = _tbl("engagements", "table")
        topics_tbl = _tbl("content_topics", "v15")
        auth_tbl = _tbl("authoring", "table")
        checks = {
            "credentials": f"""
                SELECT 1 FROM information_schema.columns
                WHERE table_name = '{users}' AND column_name = '{rel_col}'
                AND EXISTS (
                    SELECT 1 FROM information_schema.tables
                    WHERE table_name = '{cred_tbl}'
                )
                LIMIT 1
            """,
            "engagements": f"""
                SELECT 1 FROM information_schema.tables
                WHERE table_name = '{eng_tbl}' LIMIT 1
            """,
            "content_topics": f"""
                SELECT 1 FROM information_schema.tables
                WHERE table_name = '{topics_tbl}' LIMIT 1
            """,
            "authoring": f"""
                SELECT 1 FROM information_schema.tables
                WHERE table_name = '{auth_tbl}' LIMIT 1
            """,
        }
        try:
            async with self.db_pool.acquire() as conn:
                for name, sql in checks.items():
                    if any(bad in sql for bad in FORBIDDEN_TABLES):
                        raise KeyError(f"forbidden table in {name} probe")
                    row = await conn.fetchval(sql)
                    if row:
                        found.add(name)
        except Exception as exc:
            logger.warning("disco boundary refresh failed: %s", exc)
        self.available = found
        return self.readiness()

    async def credentials_for(self, username: str) -> dict:
        default = {"class": "coaching", "username": username, "credentials": []}
        if "credentials" not in self.available or not self.db_pool:
            return self.get("credentials", default)
        users = _tbl("credentials", "identity")
        ident = _col("credentials", "identity")
        rel = _col("credentials", "class")
        jur = _col("credentials", "jurisdiction")
        vault = _col("credentials", "vault_sync")
        cred_tbl = _tbl("credentials", "credential_rows")
        cred_fk = _col("credentials", "credential_rows")
        try:
            async with self.db_pool.acquire() as conn:
                row = await conn.fetchrow(
                    f"""
                    SELECT u.{ident} AS username, u.role,
                           COALESCE(u.{rel}, 'coaching') AS relationship_class,
                           COALESCE(u.{jur}, '') AS jurisdiction,
                           COALESCE(u.{vault}, false) AS vault_sync
                    FROM {users} u
                    WHERE u.{ident} = $1
                    LIMIT 1
                    """,
                    username,
                )
                creds = await conn.fetch(
                    f"""
                    SELECT credential_type, expires_at, document_ref
                    FROM {cred_tbl}
                    WHERE {cred_fk} = $1
                    """,
                    username,
                )
            if not row:
                return self.get("credentials", default)
            return {
                "degraded": False,
                "value": {
                    "username": row["username"],
                    "class": row["relationship_class"] or "coaching",
                    "jurisdiction": row["jurisdiction"],
                    "vault_sync": bool(row["vault_sync"]),
                    "role": row["role"],
                    "credentials": [dict(c) for c in creds],
                },
            }
        except Exception as exc:
            logger.warning("credentials contract degraded: %s", exc)
            return {"degraded": True, "reason": str(exc), "value": default}

    async def load_value(self, contract: str, default: Any = None) -> dict:
        if contract not in self.CONTRACTS:
            raise KeyError(f"undeclared contract: {contract}")
        if contract not in self.available or not self.db_pool:
            return self.get(contract, default)
        try:
            async with self.db_pool.acquire() as conn:
                if contract == "engagements":
                    tbl = _tbl("engagements", "table")
                    rows = await conn.fetch(
                        f"SELECT * FROM {tbl} ORDER BY created_at DESC LIMIT 50"
                    )
                    return {"degraded": False, "value": [dict(r) for r in rows]}
                if contract == "authoring":
                    tbl = _tbl("authoring", "table")
                    rows = await conn.fetch(
                        f"""
                        SELECT id, content_type, status, slug, coach_id
                        FROM {tbl}
                        WHERE status IN ('approved', 'published', 'live')
                        ORDER BY id DESC LIMIT 50
                        """
                    )
                    return {"degraded": False, "value": [dict(r) for r in rows]}
                if contract == "content_topics":
                    v15 = _tbl("content_topics", "v15")
                    flagged = _tbl("content_topics", "coach_flagged")
                    v15_rows = await conn.fetch(
                        f"SELECT * FROM {v15} ORDER BY created_at DESC LIMIT 50"
                    )
                    try:
                        flag_rows = await conn.fetch(
                            f"SELECT * FROM {flagged} ORDER BY flagged_at DESC LIMIT 50"
                        )
                    except Exception:
                        flag_rows = []
                    return {
                        "degraded": False,
                        "value": {
                            "topics": [dict(r) for r in v15_rows],
                            "coach_flagged": [dict(r) for r in flag_rows],
                        },
                    }
        except Exception as exc:
            logger.warning("%s contract degraded: %s", contract, exc)
            return {"degraded": True, "reason": str(exc), "value": default}
        return self.get(contract, default)
