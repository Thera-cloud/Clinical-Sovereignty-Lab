"""Phase-aware thrive recall section for crystal_recall_bridge — QUANTUM-CRYSTAL-ARCH."""

from __future__ import annotations

from typing import Any, Optional


async def thrive_recall_section(db_pool: Any, user_id: str, source: str = "bridge_chat") -> Optional[str]:
    """Extra thrive/coaching slot when the client is in a coaching phase."""
    from app.services.thrive.phase_resolver import ENABLE_GROWTH_PHASE, get_phase
    from app.services.thrive.strengths_interview import thrive_memory
    from app.services.thrive.growth_phase import is_coaching_phase, is_consolidating

    if not ENABLE_GROWTH_PHASE or db_pool is None or not user_id:
        return None
    state = await get_phase(db_pool, user_id)
    if not (is_coaching_phase(state.phase, state.sub_state) or is_consolidating(state.phase)):
        return None
    mem = await thrive_memory(db_pool, user_id, limit=4)
    if not mem:
        return None
    lines = [
        "GROWTH MEMORY (goals, practices, strengths — reference naturally, never recite):",
        *[f"- {m}" for m in mem if m],
    ]
    return "\n".join(lines)
