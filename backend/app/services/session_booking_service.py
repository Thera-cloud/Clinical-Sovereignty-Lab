"""
QUANTUM-CRYSTAL-ARCH: Callable session booking core (Agentic Phase 2).

Extracted pattern for bridge WS handler and nate_tool_executor book_session tool.
"""

from __future__ import annotations

import logging
import secrets
from datetime import datetime, timedelta, timezone
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
    duration_minutes: int = 50,
) -> Dict[str, Any]:
    """Validate inputs, persist pending_approval session, open negotiation when flagged."""
    if not client_hw_id or not str(client_hw_id).strip():
        return {"success": False, "error": "missing_client_id"}
    if not slot_start:
        return {"success": False, "error": "missing_slot_start"}

    try:
        start_dt = datetime.fromisoformat(str(slot_start).replace("Z", "+00:00"))
    except Exception:
        return {"success": False, "error": "invalid_slot_start"}

    if start_dt.tzinfo is None:
        start_dt = start_dt.replace(tzinfo=timezone.utc)

    if not db_pool:
        return {
            "success": False,
            "error": "database_unavailable",
            "detail": "booking requires database",
        }

    end_dt = start_dt + timedelta(minutes=max(5, int(duration_minutes or 50)))

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

            pd = client.get("profile_data") or {}
            if isinstance(pd, str):
                import json

                try:
                    pd = json.loads(pd)
                except Exception:
                    pd = {}

            resolved_coach = coach_id
            if not resolved_coach:
                resolved_coach = (
                    pd.get("coach_id")
                    or pd.get("assigned_coach_id")
                    or pd.get("assigned_coach")
                )
            if not resolved_coach:
                return {"success": False, "error": "no_assigned_coach"}

            # Resolve coach hardware_id when username was stored
            coach_row = await conn.fetchrow(
                """
                SELECT hardware_id, username, profile_data->>'name' AS name
                FROM users
                WHERE hardware_id = $1 OR username = $1
                LIMIT 1
                """,
                str(resolved_coach),
            )
            coach_hw = (
                (coach_row["hardware_id"] if coach_row else None)
                or str(resolved_coach)
            )
            client_hw = client["hardware_id"] or client_hw_id
            client_name = (
                (pd.get("name") if isinstance(pd, dict) else None)
                or client["username"]
                or "Client"
            )

        session_id = (
            f"SES_{datetime.now(timezone.utc).strftime('%Y%m%d')}_"
            f"{secrets.token_hex(3).upper()}"
        )
        new_session = {
            "session_id": session_id,
            "client_id": client_hw,
            "coach_id": coach_hw,
            "family_id": (pd.get("family_id") if isinstance(pd, dict) else "") or "",
            "client_name": client_name,
            "session_type": session_type or "individual",
            "status": "pending_approval",
            "scheduled_start": start_dt.isoformat(),
            "scheduled_end": end_dt.isoformat(),
            "actual_start": None,
            "actual_end": None,
            "duration_minutes": int(duration_minutes or 50),
            "zoom_link": "",
            "zoom_meeting_id": "",
            "zoom_host_url": "",
            "notes": (notes or "")[:2000],
            "coach_notes": "",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "booked_by": "NATE_TOOL",
        }

        from app.services.pg_data_helpers import upsert_session_pg

        await upsert_session_pg(db_pool, new_session)

        # Nate-mediated negotiation when flag on (WS notify optional — tool path has no sockets)
        try:
            from app.services.session_negotiation_service import (
                negotiation_enabled,
                open_from_pending_session,
            )

            if negotiation_enabled():
                await open_from_pending_session(db_pool, new_session)
        except Exception as neg_err:
            logger.warning("session_booking: negotiation open skipped: %s", neg_err)

        return {
            "success": True,
            "status": "pending_approval",
            "session_id": session_id,
            "client_hw_id": client_hw,
            "coach_id": coach_hw,
            "slot_start": start_dt.isoformat(),
            "session_type": session_type or "individual",
            "notes": (notes or "")[:2000],
            "message": "Session request sent to your coach for approval.",
        }
    except Exception as e:
        logger.warning("session_booking_service: book_session failed: %s", e)
        return {"success": False, "error": "booking_failed", "detail": str(e)[:200]}
