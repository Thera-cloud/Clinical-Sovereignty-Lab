"""Shared growth-phase turn injector — QUANTUM-CRYSTAL-ARCH.

One owner for note_turn + practice harvest + persona addendum so chat,
sanctuary, group, private coaching, and voice stay in lockstep without
duplicating the bridge block.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

_CRISIS = ("suicid", "kill myself", "end my life", "not want to be alive")


def _first_name(profile: Optional[Dict[str, Any]]) -> Optional[str]:
    if not isinstance(profile, dict):
        return None
    name = (profile.get("name") or "").strip()
    return name.split(" ")[0] if name else None


def _uid(profile: Optional[Dict[str, Any]], fallback: str = "") -> str:
    if not isinstance(profile, dict):
        return fallback
    return (profile.get("hardware_id") or profile.get("username") or fallback or "").strip()


async def apply_growth_phase_turn(
    db_pool: Any,
    user_id: str,
    user_text: str,
    profile: Optional[Dict[str, Any]],
    system_prompt: Optional[str],
    *,
    role: str = "CLIENT",
    dojo_type: Optional[str] = None,
    source: str = "chat",
    inject: bool = True,
    record: bool = True,
) -> Tuple[Optional[str], Any]:
    """Apply turn-time phase rules. Returns (system_prompt, PhaseState|None)."""
    from app.services.thrive.phase_resolver import ENABLE_GROWTH_PHASE, get_phase, note_turn

    if not ENABLE_GROWTH_PHASE or db_pool is None or not user_id:
        return system_prompt, None
    if (role or "").upper() != "CLIENT" or dojo_type:
        return system_prompt, None

    from app.services.thrive import practice_tracker as pt
    from app.services.thrive.persona import build_phase_addendum

    if record:
        crisis = any(w in (user_text or "").lower() for w in _CRISIS)
        state = await note_turn(db_pool, user_id, user_text or "", crisis=crisis)
        focus = await pt.focus_state(db_pool, user_id)
        done = pt.detect_completion(
            user_text or "",
            [a.get("practice_key") for a in (focus.get("areas") or []) if a.get("practice_key")],
        )
        if done:
            asyncio.create_task(pt.log_completion(db_pool, user_id, done, source=source, harvest=user_text or ""))
    else:
        state = await get_phase(db_pool, user_id)
        focus = await pt.focus_state(db_pool, user_id)

    if isinstance(profile, dict):
        profile["growth_phase"] = {"phase": state.phase, "sub_state": state.sub_state}

    if inject:
        addendum = build_phase_addendum(
            state.phase, state.sub_state, focus, display_name=_first_name(profile),
        )
        if addendum:
            system_prompt = (system_prompt or "") + "\n\n---\n" + addendum
            print(f">>> [GROWTH PHASE] {state.phase}/{state.sub_state or '-'} addendum {len(addendum)} chars src={source} uid={user_id}")
    return system_prompt, state


async def apply_growth_phase_family(
    db_pool: Any,
    family_profiles: List[Dict[str, Any]],
    conversation: str,
    system_prompt: Optional[str],
    *,
    source: str = "family_sanctuary",
) -> Optional[str]:
    """Per-member addenda for Family Sanctuary (privacy wall: own phase only)."""
    from app.services.thrive.phase_resolver import ENABLE_GROWTH_PHASE

    if not ENABLE_GROWTH_PHASE or db_pool is None:
        return system_prompt
    parts: List[str] = []
    last = (conversation or "").strip().splitlines()
    last_text = last[-1] if last else conversation or ""
    for fp in family_profiles or []:
        if (fp.get("role") or "").upper() == "ADMIN":
            continue
        uid = _uid(fp)
        if not uid:
            continue
        try:
            prompt, _ = await apply_growth_phase_turn(
                db_pool, uid, last_text, fp, "",
                role="CLIENT", source=source, inject=True, record=False,
            )
            extra = (prompt or "").strip()
            if extra:
                name = _first_name(fp) or uid
                parts.append(f"[{name}'s growth phase]\n{extra.lstrip('-').strip()}")
        except Exception as e:
            logger.debug("turn_inject: family member %s skipped: %s", uid, e)
    if parts:
        system_prompt = (system_prompt or "") + "\n\n---\n" + "\n\n".join(parts[:8])
    return system_prompt
