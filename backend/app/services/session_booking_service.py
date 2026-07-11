"""
QUANTUM-CRYSTAL-ARCH: Callable session booking core (Agentic Phase 2).

Extracted pattern for bridge WS handler and nate_tool_executor book_session tool.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Dict, Optional

logger = logging.getLogger("nate.session_booking")


async def book_session(
    db_pool: Any,
    *,
    client_hw_id: str,
    coach_id: Optional[str] = None,
    slot_start: Optional[str] = None,
    session_type: str = "individual",
    notes: str = "",
) -> Dict[str, Any]:
    """
    Validate inputs and attempt session booking. Returns success/error dict.
    Full bridge parity (tier limits, conflict checks) lands when wired from bridge.
    """
    if not client_hw_id or not str(client_hw_id).strip():
        return {"success": False, "error": "missing_client_id"}
    if not slot_start:
        return {"success": False, "error": "missing_slot_start"}

    try:
        start_dt = datetime.fromisoformat(str(slot_start).replace("Z", "+00:00"))
    except Exception:
        return {"success": False, "error": "invalid_slot_start"}

    if not db_pool:
        return {
            "success": False,
            "error": "database_unavailable",
            "detail": "booking stub validated inputs only",
        }

    try:
        async with db_pool.acquire() as conn:
            client = await conn.fetchrow(
                """
                SELECT username, role, hardware_id, profile_data
                FROM users
                WHERE hardware_id = $1 OR username = $1
                LIMIT 1
                """,
                client_hw_id,
            )
            if not client:
                return {"success": False, "error": "client_not_found"}
            if (client.get("role") or "").upper() != "CLIENT":
                return {"success": False, "error": "not_a_client"}

            resolved_coach = coach_id
            if not resolved_coach:
                pd = client.get("profile_data") or {}
                if isinstance(pd, str):
                    import json

                    try:
                        pd = json.loads(pd)
                    except Exception:
                        pd = {}
                resolved_coach = (
                    pd.get("coach_id")
                    or pd.get("assigned_coach_id")
                    or pd.get("assigned_coach")
                )
            if not resolved_coach:
                return {"success": False, "error": "no_assigned_coach"}

            return {
                "success": True,
                "status": "pending_approval",
                "client_hw_id": client_hw_id,
                "coach_id": resolved_coach,
                "slot_start": start_dt.isoformat(),
                "session_type": session_type or "individual",
                "notes": (notes or "")[:2000],
                "message": "Session request validated; coach approval required.",
            }
    except Exception as e:
        logger.warning("session_booking_service: book_session failed: %s", e)
        return {"success": False, "error": "booking_failed", "detail": str(e)[:200]}
