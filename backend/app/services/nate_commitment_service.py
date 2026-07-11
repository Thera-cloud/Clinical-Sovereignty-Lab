"""
QUANTUM-CRYSTAL-ARCH: Bridge-facing commitment + consent handlers (Agentic Phase 1).
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

logger = logging.getLogger("nate.commitment_service")


def _profile_data(raw: Any) -> Dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str):
        try:
            parsed = json.loads(raw)
            return parsed if isinstance(parsed, dict) else {}
        except Exception:
            return {}
    return {}


async def update_proactive_consent(
    db_pool: Any,
    *,
    hardware_id: str,
    enabled: bool,
    save_registry_fn=None,
    registry_cache=None,
) -> Dict[str, Any]:
    if not db_pool or not hardware_id:
        return {"ok": False, "error": "missing_identity"}
    try:
        async with db_pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT username, profile_data FROM users WHERE hardware_id = $1 LIMIT 1",
                hardware_id,
            )
            if not row:
                return {"ok": False, "error": "user_not_found"}
            pd = _profile_data(row["profile_data"])
            pd["proactive_presence_consent"] = bool(enabled)
            await conn.execute(
                "UPDATE users SET profile_data = $1::jsonb, updated_at = NOW() WHERE hardware_id = $2",
                json.dumps(pd),
                hardware_id,
            )
        if registry_cache is not None and save_registry_fn is not None:
            for key, entry in registry_cache.items():
                if entry.get("hardware_id") == hardware_id:
                    entry.setdefault("profile_data", {})["proactive_presence_consent"] = bool(enabled)
                    save_registry_fn(registry_cache)
                    break
        return {"ok": True, "proactive_presence_consent": bool(enabled)}
    except Exception as e:
        logger.warning("commitment_service: consent update failed: %s", e)
        return {"ok": False, "error": "persist_failed"}


async def list_commitments(db_pool: Any, hardware_id: str) -> List[Dict[str, Any]]:
    if not db_pool:
        return []
    try:
        async with db_pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT id, commitment_text, commitment_type, target_date, recurrence,
                       status, sensitivity, source, touch_count, last_touched_at, created_at
                FROM nate_commitments
                WHERE user_id = $1 AND status = 'active'
                ORDER BY target_date NULLS LAST, created_at DESC
                LIMIT 50
                """,
                hardware_id,
            )
        return [
            {
                "id": str(r["id"]),
                "text": r["commitment_text"],
                "type": r["commitment_type"],
                "target_date": r["target_date"].isoformat() if r["target_date"] else None,
                "recurrence": r["recurrence"],
                "sensitivity": r["sensitivity"],
                "source": r["source"],
                "touch_count": r["touch_count"],
            }
            for r in rows
        ]
    except Exception as e:
        logger.warning("commitment_service: list failed: %s", e)
        return []


async def dismiss_commitment(db_pool: Any, hardware_id: str, commitment_id: str) -> bool:
    if not db_pool:
        return False
    try:
        async with db_pool.acquire() as conn:
            result = await conn.execute(
                """
                UPDATE nate_commitments SET status = 'dismissed', updated_at = NOW()
                WHERE id = $1::uuid AND user_id = $2 AND status = 'active'
                """,
                commitment_id,
                hardware_id,
            )
        return result.endswith("1")
    except Exception as e:
        logger.warning("commitment_service: dismiss failed: %s", e)
        return False


async def edit_commitment(
    db_pool: Any,
    hardware_id: str,
    commitment_id: str,
    *,
    text: Optional[str] = None,
    target_date_iso: Optional[str] = None,
) -> bool:
    if not db_pool:
        return False
    target_dt = None
    if target_date_iso:
        try:
            target_dt = datetime.fromisoformat(target_date_iso.replace("Z", "+00:00"))
        except Exception:
            target_dt = None
    try:
        async with db_pool.acquire() as conn:
            result = await conn.execute(
                """
                UPDATE nate_commitments
                SET commitment_text = COALESCE($3, commitment_text),
                    target_date = COALESCE($4, target_date),
                    source = 'client_entered',
                    updated_at = NOW()
                WHERE id = $1::uuid AND user_id = $2 AND status = 'active'
                """,
                commitment_id,
                hardware_id,
                text,
                target_dt,
            )
        return result.endswith("1")
    except Exception as e:
        logger.warning("commitment_service: edit failed: %s", e)
        return False
