"""Commitments, agenda gate, conjecture budget.

QUANTUM-CRYSTAL-ARCH — clinical. SOVEREIGN-STANDARD.
CEO: Nathaniel James Nevedal. Risk: RED.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from app.services.attunement import flags, store

_TTL = 60 * 60 * 6


def _steer_k(uid: str) -> str:
    return store.key("steeroff", uid)


def _sess_k(uid: str) -> str:
    return store.key("sess", uid)


def _commit_used_k(uid: str) -> str:
    return store.key("commitused", uid)


def session_turn_index(uid: str, bump: bool = False) -> int:
    n = int((store.get_json(_sess_k(uid)) or {}).get("n") or 0)
    if bump:
        n += 1
        store.set_json(_sess_k(uid), {"n": n}, _TTL)
    return n


def reset_session_index(uid: str) -> None:
    store.set_json(_sess_k(uid), {"n": 0}, _TTL)


def mark_steer_off(uid: str, turns: int = 3) -> None:
    store.set_json(_steer_k(uid), {"left": turns}, _TTL)


def steer_off_left(uid: str) -> int:
    return int((store.get_json(_steer_k(uid)) or {}).get("left") or 0)


def consume_steer_off(uid: str) -> bool:
    left = steer_off_left(uid)
    if left <= 0:
        return False
    store.set_json(_steer_k(uid), {"left": left - 1}, _TTL)
    return True


def agenda_suppressed(uid: str, hold_cover: float) -> bool:
    if not flags.agenda_gate():
        return False
    n = session_turn_index(uid)
    if n < 2:
        return True
    return hold_cover < 0.35


def faster_hold_first(depth: str, cold_recall: bool, uid: str) -> bool:
    if not flags.conjecture():
        return False
    if consume_steer_off(uid):
        return True
    d = (depth or "").lower()
    if d in ("fast", "faster", "quick", "light") and cold_recall:
        return True
    return False


def hold_first_directive() -> str:
    return (
        "[CHAT DEPTH: FASTER — HOLD FIRST]\n"
        "Stay with what they just said. One short steer only if they asked. "
        "Do not lecture quotient names. Do not open unfinished-story files."
    )


def commitment_used(uid: str) -> bool:
    return bool((store.get_json(_commit_used_k(uid)) or {}).get("used"))


def mark_commitment_used(uid: str) -> None:
    store.set_json(_commit_used_k(uid), {"used": True}, _TTL)


def format_commitment_steer(text: str) -> str:
    t = (text or "").strip()
    if not t:
        return ""
    return f"STEER CANDIDATE (one this session, only after hold): open commitment — {t[:160]}"


async def fetch_open_commitment(db_pool, username: str) -> str:
    if not flags.commitments() or not db_pool or not username:
        return ""
    try:
        async with db_pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT commitment_text FROM nate_commitments "
                "WHERE user_id = $1 AND status = 'active' "
                "ORDER BY updated_at DESC NULLS LAST LIMIT 1",
                username,
            )
        if not row:
            return ""
        return (row.get("commitment_text") or "").strip()
    except Exception:
        return ""


def apply_agency(
    uid: str,
    *,
    depth: str,
    cold_recall: bool,
    hold_cover: float,
    plan_block: str,
    stay: bool,
    commitment_text: str = "",
) -> Tuple[str, str, Dict[str, Any]]:
    """Returns (plan_block, extra_directive, meta)."""
    if stay:
        mark_steer_off(uid, 3)
    n = session_turn_index(uid)
    suppress = agenda_suppressed(uid, hold_cover)
    plan = "" if suppress else (plan_block or "")
    extras: List[str] = []
    if faster_hold_first(depth, cold_recall, uid):
        extras.append(hold_first_directive())
    if (
        flags.commitments()
        and commitment_text
        and not suppress
        and not commitment_used(uid)
        and n >= 2
    ):
        extras.append(format_commitment_steer(commitment_text))
        mark_commitment_used(uid)
    return plan, "\n\n".join(extras), {
        "agenda_suppressed": suppress,
        "session_turn": n,
        "steer_off": steer_off_left(uid),
    }
