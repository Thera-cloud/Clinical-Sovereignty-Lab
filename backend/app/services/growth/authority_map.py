"""Authority map: MarketingBrain (social) vs marketing_policies (factory/outreach).

Plan lock:
  (1) day-to-day social = MarketingBrain playbook + marketing_actions
  (2) factory/outreach prompt versions = GREEN marketing_policies + Dual-COO
  (3) BWAS stage weights = growth_config admin-only (RED)

# QUANTUM-CRYSTAL-ARCH
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger("nate.growth.authority_map")

POLICY_FACTORY_SYSTEM = "factory_system_prompt"
POLICY_OUTREACH_SYSTEM = "outreach_system_prompt"


async def list_policies(
    db_pool, *, stance: Optional[str] = None
) -> List[Dict[str, Any]]:
    if not db_pool:
        return []
    try:
        async with db_pool.acquire() as conn:
            if stance:
                rows = await conn.fetch(
                    "SELECT policy_key, stance, body, updated_at FROM marketing_policies "
                    "WHERE stance = $1 ORDER BY policy_key",
                    stance.upper(),
                )
            else:
                rows = await conn.fetch(
                    "SELECT policy_key, stance, body, updated_at FROM marketing_policies "
                    "ORDER BY stance, policy_key"
                )
        out = []
        for r in rows:
            d = dict(r)
            if hasattr(d.get("updated_at"), "isoformat"):
                d["updated_at"] = d["updated_at"].isoformat()
            out.append(d)
        return out
    except Exception as e:
        logger.warning("authority_map list_policies: %s", e)
        return []


async def get_green_policy(db_pool, policy_key: str) -> Optional[str]:
    """Factory/outreach may only consume GREEN stance bodies."""
    if not db_pool or not policy_key:
        return None
    try:
        async with db_pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT body FROM marketing_policies "
                "WHERE policy_key = $1 AND stance = 'GREEN' LIMIT 1",
                policy_key,
            )
        if row and (row["body"] or "").strip():
            return str(row["body"]).strip()
    except Exception as e:
        logger.warning("authority_map get_green_policy: %s", e)
    return None


async def get_factory_system_prompt(db_pool, default: str) -> str:
    body = await get_green_policy(db_pool, POLICY_FACTORY_SYSTEM)
    return body if body else default


async def upsert_policy(
    db_pool,
    *,
    policy_key: str,
    body: str,
    stance: str = "YELLOW",
) -> Dict[str, Any]:
    """Write/update policy. New drafts default YELLOW — GREEN only via CEO activate."""
    stance_u = (stance or "YELLOW").strip().upper()
    if stance_u not in ("GREEN", "YELLOW", "RED"):
        stance_u = "YELLOW"
    async with db_pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO marketing_policies (policy_key, stance, body, updated_at)
            VALUES ($1, $2, $3, NOW())
            ON CONFLICT (policy_key) DO UPDATE SET
                body = EXCLUDED.body,
                stance = CASE
                    WHEN marketing_policies.stance = 'GREEN'
                         AND EXCLUDED.stance = 'YELLOW'
                    THEN marketing_policies.stance
                    ELSE EXCLUDED.stance
                END,
                updated_at = NOW()
            RETURNING policy_key, stance, body
            """,
            policy_key,
            stance_u,
            (body or "")[:20000],
        )
    return dict(row) if row else {"policy_key": policy_key, "stance": stance_u}


async def activate_policy_green(
    db_pool, policy_key: str, *, peer_pass: bool, ceo_approved: bool
) -> Dict[str, Any]:
    """GREEN only when peer Queen passed review AND CEO APPROVE."""
    if not peer_pass:
        return {"ok": False, "error": "peer_pass_required"}
    if not ceo_approved:
        return {"ok": False, "error": "ceo_approve_required"}
    async with db_pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            UPDATE marketing_policies
            SET stance = 'GREEN', updated_at = NOW()
            WHERE policy_key = $1
            RETURNING policy_key, stance
            """,
            policy_key,
        )
    if not row:
        return {"ok": False, "error": "policy_not_found"}
    return {"ok": True, "policy_key": row["policy_key"], "stance": row["stance"]}


def social_strategy_owner() -> str:
    """Documented constant — MarketingBrain owns social day-to-day."""
    return "MarketingBrain"
