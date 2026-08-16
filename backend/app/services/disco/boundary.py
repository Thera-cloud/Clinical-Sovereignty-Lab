"""Live BuildBoundary — four read-only v1.5 contracts. Never crash on miss."""

from __future__ import annotations

import logging
from typing import Any, Optional

from app.services.disco.pipeline import BuildBoundary

logger = logging.getLogger("disco.boundary")


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
        checks = {
            "credentials": """
                SELECT 1 FROM information_schema.columns
                WHERE table_name = 'users' AND column_name = 'relationship_class'
                LIMIT 1
            """,
            "engagements": """
                SELECT 1 FROM information_schema.tables
                WHERE table_name = 'campaign_engagements' LIMIT 1
            """,
            "content_topics": """
                SELECT 1 FROM information_schema.tables
                WHERE table_name IN ('content_topics', 'disco_content_topics') LIMIT 1
            """,
            "authoring": """
                SELECT 1 FROM information_schema.tables
                WHERE table_name = 'marketing_content' LIMIT 1
            """,
        }
        try:
            async with self.db_pool.acquire() as conn:
                for name, sql in checks.items():
                    row = await conn.fetchval(sql)
                    if row:
                        found.add(name)
        except Exception as exc:
            logger.warning("disco boundary refresh failed: %s", exc)
        self.available = found
        return self.readiness()

    async def credentials_for(self, username: str) -> dict:
        default = {"class": "coaching", "username": username}
        if "credentials" not in self.available or not self.db_pool:
            return self.get("credentials", default)
        try:
            async with self.db_pool.acquire() as conn:
                row = await conn.fetchrow(
                    """
                    SELECT username, role,
                           COALESCE(relationship_class, 'coaching') AS relationship_class,
                           COALESCE(client_jurisdiction, '') AS jurisdiction,
                           COALESCE(vault_sync, false) AS vault_sync
                    FROM users
                    WHERE username = $1
                    LIMIT 1
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
                    rows = await conn.fetch(
                        "SELECT * FROM campaign_engagements ORDER BY created_at DESC LIMIT 50"
                    )
                    return {"degraded": False, "value": [dict(r) for r in rows]}
                if contract == "authoring":
                    rows = await conn.fetch(
                        """
                        SELECT id, content_type, status, slug, coach_id
                        FROM marketing_content
                        WHERE status IN ('approved', 'published', 'live')
                        ORDER BY id DESC LIMIT 50
                        """
                    )
                    return {"degraded": False, "value": [dict(r) for r in rows]}
                if contract == "content_topics":
                    rows = await conn.fetch(
                        "SELECT * FROM disco_content_topics ORDER BY flagged_at DESC LIMIT 50"
                    )
                    return {"degraded": False, "value": [dict(r) for r in rows]}
        except Exception as exc:
            logger.warning("%s contract degraded: %s", contract, exc)
            return {"degraded": True, "reason": str(exc), "value": default}
        return self.get(contract, default)
