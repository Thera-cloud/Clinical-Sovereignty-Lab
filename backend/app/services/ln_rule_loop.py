"""
L4 scaffold — draft → sandbox → promote → rollback for versioned rules.

Disabled by default (ENABLE_LN_RULE_LOOP=false). Live chat does not read
active rules until L3a is proven in prod and this flag is explicitly enabled.

# QUANTUM-CRYSTAL-ARCH — L4 self-adaptive rule loop (scaffold)
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any, Dict, List, Optional

logger = logging.getLogger("ln_rule_loop")


def rule_loop_enabled() -> bool:
    return os.getenv("ENABLE_LN_RULE_LOOP", "false").strip().lower() in (
        "1", "true", "yes", "on",
    )


async def list_active_rules(db_pool: Any) -> List[Dict[str, Any]]:
    if not rule_loop_enabled() or not db_pool:
        return []
    try:
        async with db_pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT DISTINCT ON (rule_key)
                    id, rule_key, version, status, condition_json, action_json
                FROM ln_rule_store
                WHERE status = 'active'
                ORDER BY rule_key, version DESC
                """
            )
        out = []
        for r in rows:
            cond = r["condition_json"]
            act = r["action_json"]
            if isinstance(cond, str):
                cond = json.loads(cond)
            if isinstance(act, str):
                act = json.loads(act)
            out.append(
                {
                    "id": r["id"],
                    "rule_key": r["rule_key"],
                    "version": r["version"],
                    "condition": cond or {},
                    "action": act or {},
                }
            )
        return out
    except Exception as e:
        logger.warning("list_active_rules: %s", e)
        return []


async def draft_rule(
    db_pool: Any,
    *,
    rule_key: str,
    condition: Dict[str, Any],
    action: Dict[str, Any],
    created_by: str = "system",
    notes: str = "",
) -> Optional[int]:
    if not rule_loop_enabled() or not db_pool:
        return None
    try:
        async with db_pool.acquire() as conn:
            ver = await conn.fetchval(
                "SELECT COALESCE(MAX(version), 0) + 1 FROM ln_rule_store WHERE rule_key = $1",
                rule_key,
            )
            rid = await conn.fetchval(
                """
                INSERT INTO ln_rule_store
                    (rule_key, version, status, condition_json, action_json, created_by, notes)
                VALUES ($1, $2, 'draft', $3::jsonb, $4::jsonb, $5, $6)
                RETURNING id
                """,
                rule_key,
                int(ver),
                json.dumps(condition),
                json.dumps(action),
                created_by,
                notes[:500],
            )
            await conn.execute(
                """
                INSERT INTO ln_rule_audit (rule_key, version, action, detail)
                VALUES ($1, $2, 'draft', $3)
                """,
                rule_key,
                int(ver),
                notes[:300],
            )
        return int(rid) if rid is not None else None
    except Exception as e:
        logger.warning("draft_rule: %s", e)
        return None


async def promote_rule(
    db_pool: Any,
    *,
    rule_key: str,
    version: int,
) -> bool:
    """Promote sandbox→active; prior active for same key → rolled_back."""
    if not rule_loop_enabled() or not db_pool:
        return False
    try:
        async with db_pool.acquire() as conn:
            async with conn.transaction():
                await conn.execute(
                    """
                    UPDATE ln_rule_store
                    SET status = 'rolled_back', rolled_back_at = NOW()
                    WHERE rule_key = $1 AND status = 'active'
                    """,
                    rule_key,
                )
                updated = await conn.fetchval(
                    """
                    UPDATE ln_rule_store
                    SET status = 'active', promoted_at = NOW()
                    WHERE rule_key = $1 AND version = $2
                      AND status IN ('draft', 'sandbox')
                    RETURNING id
                    """,
                    rule_key,
                    version,
                )
                if not updated:
                    return False
                await conn.execute(
                    """
                    INSERT INTO ln_rule_audit (rule_key, version, action, detail)
                    VALUES ($1, $2, 'promote', 'promoted to active')
                    """,
                    rule_key,
                    version,
                )
        return True
    except Exception as e:
        logger.warning("promote_rule: %s", e)
        return False


async def rollback_rule(db_pool: Any, *, rule_key: str, version: int) -> bool:
    if not rule_loop_enabled() or not db_pool:
        return False
    try:
        async with db_pool.acquire() as conn:
            n = await conn.fetchval(
                """
                UPDATE ln_rule_store
                SET status = 'rolled_back', rolled_back_at = NOW()
                WHERE rule_key = $1 AND version = $2 AND status = 'active'
                RETURNING id
                """,
                rule_key,
                version,
            )
            if n:
                await conn.execute(
                    """
                    INSERT INTO ln_rule_audit (rule_key, version, action, detail)
                    VALUES ($1, $2, 'rollback', 'manual rollback')
                    """,
                    rule_key,
                    version,
                )
            return bool(n)
    except Exception as e:
        logger.warning("rollback_rule: %s", e)
        return False
