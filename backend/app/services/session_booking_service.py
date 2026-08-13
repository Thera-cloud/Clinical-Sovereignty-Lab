"""
QUANTUM-CRYSTAL-ARCH: Nate booking lock.

Clients request times via `client_book_session` against published availability.
The coach approves or declines. Little Nate must never persist a session row.
"""

from __future__ import annotations

from typing import Any, Dict, Optional


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
    """Refuse persist. Coach decides; clients use availability UI."""
    del db_pool, client_hw_id, coach_id, slot_start, session_type, notes, duration_minutes
    return {
        "success": False,
        "error": "coach_decision_required",
        "message": (
            "Little Nate cannot book sessions. Clients request a time from "
            "coach availability; the coach approves."
        ),
    }
