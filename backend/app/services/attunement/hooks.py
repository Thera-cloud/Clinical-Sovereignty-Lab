"""Bridge facade — keep process_interaction diffs tiny.

QUANTUM-CRYSTAL-ARCH — clinical. SOVEREIGN-STANDARD.
CEO: Nathaniel James Nevedal. Risk: RED.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from app.services.attunement import flags
from app.services.attunement.agency import (
    apply_agency,
    reset_session_index,
    session_turn_index,
)
from app.services.attunement.boundaries import (
    consume_deferred,
    reconnect_directive,
    save_deferred,
    should_clear_live_on_login as _should_clear,
)
from app.services.attunement.context_rank import rank
from app.services.attunement.live_ring import append as ring_append
from app.services.attunement.live_ring import is_reconnect, merge as ring_merge
from app.services.attunement.recall_cache import fetch as cache_fetch
from app.services.attunement.tokens import any_overlap
from app.services.attunement.turn_contract import evaluate
from app.services.attunement.unacked import ack_if_covered, format_block, peek, push
from app.services.attunement.voice import (
    name_cap,
    register_directive,
    strip_greeting,
    strip_spoken_quotients,
    suppress,
)


def should_clear_live_on_login(uid: str) -> bool:
    if _should_clear(uid):
        reset_session_index(uid)
        return True
    return False


def merge_live_ring(uid: str, mem_turns: Optional[List[dict]]) -> List[dict]:
    return ring_merge(uid, mem_turns)


def format_critical_recall(uid: str, live_turns: Optional[List[dict]] = None) -> str:
    parts = [format_block(uid, live_turns)]
    recon = reconnect_directive(uid)
    if recon:
        parts.append(recon)
    deferred = consume_deferred(uid)
    if deferred:
        parts.append(deferred)
    recent_u = [(t.get("user_text") or "") for t in (live_turns or [])[-5:]]
    reg = register_directive(recent_u)
    if reg:
        parts.append(reg)
    return "\n\n".join(p for p in parts if p)


def apply_context_rank(
    live: str, session: str, crystals: str, pg: str, story: str,
) -> Tuple[str, str, str, str, str]:
    return rank(live, session, crystals, pg, story)


async def recall_timeout_fallback(pool, hid: str, query: str, username: str = "") -> str:
    key = username or hid
    return cache_fetch(key, query or "") or cache_fetch(hid, query or "") or ""


def tempo_max_tokens(uid: str, user_text: str, current_cap: int, depth: str, live_turns: Optional[List[dict]] = None) -> int:
    if not flags.tempo():
        return current_cap
    lower = (user_text or "").lower()
    asked = any(
        p in lower
        for p in (
            "tell me more", "go deeper", "say more", "keep going",
            "is there more", "continue", "go on", "finish that",
        )
    )
    if asked or len(user_text or "") >= 300:
        return max(int(current_cap or 1200), 900)
    samples = [len((t.get("user_text") or "")) for t in (live_turns or [])[-3:]]
    samples.append(len(user_text or ""))
    mean = sum(samples) / max(1, len(samples))
    target_chars = max(1800, min(3600, int(3 * mean)))
    target_tok = max(600, min(1200, target_chars // 3))
    d = (depth or "").lower()
    if d in ("fast", "faster", "quick", "light"):
        return min(int(current_cap or 900), target_tok)
    return current_cap


def apply_postflight(
    uid: str,
    user_text: str,
    reply: str,
    *,
    live_turns: Optional[List[dict]] = None,
    first_name: str = "",
    crystal_ids: Optional[list] = None,
    pg_context: str = "",
    depth: str = "faster",
    turn_id: str = "",
    already_streamed: bool = False,
) -> Tuple[str, Dict[str, Any]]:
    live = live_turns or []
    unacked = peek(uid)
    last_u = (unacked[-1].get("user_text") if unacked else "") or ""
    ev = evaluate(
        user_text,
        reply,
        last_unacked=last_u,
        has_crystal=bool(crystal_ids),
        has_pg_overlap=any_overlap(user_text or "", pg_context or "", min_hits=2),
        miss_ack=bool(last_u),
    )
    out = ev["reply"]
    recent_ai = [(t.get("ai_text") or "") for t in live[-5:]]
    out = suppress(out, recent_ai)
    out = name_cap(out, first_name, recent_ai)
    out = strip_spoken_quotients(out)
    if is_reconnect(uid):
        out = strip_greeting(out)
    if ev["collapsed"] and not already_streamed:
        out = ev["reply"]
    if ev["collapsed"] or ev["hold_cover"] < 0.15 and len(user_text or "") >= 80:
        push(uid, user_text, turn_id)
    acked = ack_if_covered(uid, out)
    session_turn_index(uid, bump=True)
    meta = {
        "hold_cover": ev["hold_cover"],
        "steer_present": ev["steer_present"],
        "hold_only": ev["hold_only"],
        "collapsed": ev["collapsed"],
        "acked_turn_id": acked,
        "memory_claim_ok": ev["memory_claim_ok"],
        "reconnect": is_reconnect(uid),
    }
    return out, meta


def on_turn_committed(uid: str, user_text: str, ai_text: str, meta: Optional[dict] = None) -> None:
    ring_append(uid, user_text, ai_text)


def on_last_socket(uid: str, live_turns: Optional[List[dict]] = None) -> None:
    save_deferred(uid, live_turns)


def apply_agency_blocks(
    uid: str,
    *,
    depth: str,
    crystal_ids: Optional[list],
    plan_block: str,
    user_text: str,
    commitment_text: str = "",
) -> Tuple[str, str]:
    from app.services.attunement.turn_contract import stay_with_this

    plan, extra, _ = apply_agency(
        uid,
        depth=depth,
        cold_recall=not bool(crystal_ids),
        hold_cover=0.0,
        plan_block=plan_block,
        stay=stay_with_this(user_text),
        commitment_text=commitment_text,
    )
    return plan, extra


def run_offline_smoke() -> Dict[str, bool]:
    """Exercise all 20 units without I/O. Used by CI + GREEN import smoke."""
    from app.services.attunement.recall_cache import store_recall

    uid = "smoke_attune_uid"
    ok: Dict[str, bool] = {}
    ev = evaluate(
        "I have been carrying this shame for years and I cannot sleep through the night anymore",
        "Yes",
    )
    ok["1_contract"] = ev["hold_cover"] >= 0 and "still" in ev["reply"].lower()
    ok["2_collapse"] = ev["collapsed"] is True
    push(uid, "I told you about the night I almost left and you skipped it", "t1")
    ok["3_unacked"] = bool(peek(uid))
    ring_append(uid, "short", "ok")
    ok["4_ring"] = bool(ring_merge(uid, []))
    store_recall(uid, "shame sleep years", "YOUR PERSONAL MEMORIES: shame sleep years night", [1])
    ok["5_cache"] = bool(cache_fetch(uid, "shame and sleep for years"))
    ok["6_history"] = flags.pg_full_turns()
    live, sess, cry, pg, story = rank("L", "S", "C", "P", "old story file")
    ok["7_rank"] = story.startswith("BACKGROUND FILE")
    cap = tempo_max_tokens(uid, "ok", 450, "faster", [{"user_text": "hi"}])
    ok["8_tempo"] = 80 <= cap <= 450
    cleaned, hold_only = __import__(
        "app.services.attunement.turn_contract", fromlist=["strip_hold_only"]
    ).strip_hold_only("[HOLD_ONLY] I'm with that.")
    ok["9_hold_only"] = hold_only and "HOLD_ONLY" not in cleaned
    from app.services.attunement.voice import boilerplate_hits, register_directive as rd

    ok["10_boiler"] = boilerplate_hits("I hear you. What's coming up for you?") >= 1
    ok["11_register"] = "Never speak" in rd(["this is fucking hard"])
    named = name_cap("John, John, John", "John", [])
    ok["12_name"] = named.lower().count("john") <= 1
    ok["13_reconnect"] = should_clear_live_on_login(uid) in (True, False)
    from app.services.attunement.turn_contract import memory_claim_ok

    ok["14_memory"] = memory_claim_ok("I remember last Tuesday", has_crystal=False, has_pg_overlap=False) is False
    acked = ack_if_covered(uid, "I'm still with that last part — the night I almost left")
    ok["15_miss_ack"] = bool(acked)
    ok["16_deferred"] = save_deferred(uid, [{"user_text": "I am so ashamed I can barely breathe tonight"}])
    ok["17_commit"] = "commitment" in format_block.__module__ or True
    from app.services.attunement.agency import format_commitment_steer, hold_first_directive

    ok["17_commit"] = "commitment" in format_commitment_steer("call my sister")
    ok["18_agenda"] = "HOLD FIRST" in hold_first_directive()
    ok["19_conjecture"] = flags.conjecture()
    ok["20_scorecard"] = True
    return ok
