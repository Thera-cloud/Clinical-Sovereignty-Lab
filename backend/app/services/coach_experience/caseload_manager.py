"""
SOVEREIGN SWARM — Coach Caseload Manager
Tracks coach caseloads, scheduling, and capacity.

Operational Specifications §2.3 — Caseload Management.
"""

import asyncio
import logging
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

logger = logging.getLogger("coach_experience.caseload_manager")


class CaseloadManager:
    """
    Manages coach caseloads, scheduling constraints, and capacity.
    Ensures even distribution and prevents burnout.
    """

    def __init__(self, db_pool=None, notifications=None):
        self._db = db_pool
        self._notifications = notifications

    async def get_caseload(self, coach_id: str) -> Dict[str, Any]:
        """Get the current caseload summary for a coach."""
        if not self._db:
            return {"coach_id": coach_id, "active_clients": 0, "sessions_this_week": 0}

        try:
            async with self._db.acquire() as conn:
                # Active clients
                client_count = await conn.fetchval(
                    "SELECT COUNT(*) FROM users WHERE assigned_coach_id = $1 AND active = true",
                    coach_id,
                )

                # Sessions this week
                week_start = datetime.utcnow() - timedelta(days=datetime.utcnow().weekday())
                session_count = await conn.fetchval(
                    """
                    SELECT COUNT(*) FROM sessions
                    WHERE coach_id = $1 AND started_at >= $2
                    """,
                    coach_id, week_start,
                )

                # Upcoming sessions
                upcoming = await conn.fetch(
                    """
                    SELECT s.id, s.client_id, u.name AS client_name,
                           s.scheduled_at, s.session_type
                    FROM sessions s
                    JOIN users u ON u.id = s.client_id
                    WHERE s.coach_id = $1
                      AND s.scheduled_at > NOW()
                      AND s.status = 'scheduled'
                    ORDER BY s.scheduled_at ASC
                    LIMIT 10
                    """,
                    coach_id,
                )

                # Clients needing attention (low c_emo or silent)
                at_risk = await conn.fetch(
                    """
                    SELECT sa.member_id, u.name, sa.alert_level, sa.hours_silent
                    FROM silent_alerts sa
                    JOIN users u ON u.id = sa.member_id
                    WHERE u.assigned_coach_id = $1
                      AND sa.resolved_at IS NULL
                    ORDER BY sa.created_at DESC
                    LIMIT 5
                    """,
                    coach_id,
                )

                return {
                    "coach_id": coach_id,
                    "active_clients": client_count or 0,
                    "sessions_this_week": session_count or 0,
                    "upcoming_sessions": [
                        {
                            "session_id": r["id"],
                            "client_name": r["client_name"],
                            "scheduled_at": r["scheduled_at"].isoformat() if r["scheduled_at"] else None,
                            "type": r.get("session_type", "individual"),
                        }
                        for r in upcoming
                    ],
                    "at_risk_clients": [
                        {
                            "member_id": r["member_id"],
                            "name": r["name"],
                            "alert_level": r["alert_level"],
                            "hours_silent": r["hours_silent"],
                        }
                        for r in at_risk
                    ],
                }
        except Exception as e:
            logger.error("Caseload query failed: %s", e)
            return {"coach_id": coach_id, "active_clients": 0, "error": str(e)}

    async def check_capacity(self, coach_id: str, max_caseload: int = 30) -> Dict[str, Any]:
        """Check if a coach has capacity for new clients."""
        caseload = await self.get_caseload(coach_id)
        current = caseload.get("active_clients", 0)
        return {
            "coach_id": coach_id,
            "current_caseload": current,
            "max_caseload": max_caseload,
            "has_capacity": current < max_caseload,
            "utilization": current / max(max_caseload, 1),
        }

    async def reassign_client(
        self,
        client_id: str,
        from_coach_id: str,
        to_coach_id: str,
        reason: str = "",
    ) -> bool:
        """Reassign a client from one coach to another."""
        if not self._db:
            return False

        try:
            async with self._db.acquire() as conn:
                await conn.execute(
                    "UPDATE users SET assigned_coach_id = $1 WHERE id = $2",
                    to_coach_id, client_id,
                )
                # Log the reassignment
                await conn.execute(
                    """
                    INSERT INTO coach_notes (coach_id, client_id, note_type, content)
                    VALUES ($1, $2, 'reassignment', $3)
                    """,
                    from_coach_id, client_id,
                    f"Reassigned to {to_coach_id}. Reason: {reason}",
                )
                logger.info(
                    "Client %s reassigned: %s → %s (reason: %s)",
                    client_id, from_coach_id, to_coach_id, reason,
                )
                return True
        except Exception as e:
            logger.error("Client reassignment failed: %s", e)
            return False
