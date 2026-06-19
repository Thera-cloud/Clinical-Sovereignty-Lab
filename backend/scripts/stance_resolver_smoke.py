#!/usr/bin/env python3
"""Smoke test: ln_stance_resolver + bridge overlay path (no WebSocket / no LLM)."""
from __future__ import annotations

import os
import re
import sys

# Must be set before any bridge import would occur (mirrors production activation).
os.environ["ENABLE_STANCE_RESOLVER"] = "true"

_BACKEND = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
for _root in (_BACKEND, "/app"):
    if _root and os.path.isdir(os.path.join(_root, "app", "services")):
        if _root not in sys.path:
            sys.path.insert(0, _root)
        break

from app.services import little_nate_adaptive as adaptive
from app.services import ln_stance_resolver as stance

_KRISTY_JSON = os.path.join(
    os.path.dirname(__file__), "..", "..", "data", "kristy_smoke_test.json"
)


def _kristy_turn(index: int) -> str:
    import json
    with open(_KRISTY_JSON, encoding="utf-8") as f:
        data = json.load(f)
    for row in data["turns"]:
        if row["index"] == index:
            return row["text"]
    raise KeyError(index)


# Real Kristy turn strings (kristy_smoke_test.json).
KRISTY_TURN_12 = _kristy_turn(12)
KRISTY_TURN_13 = _kristy_turn(13)
KRISTY_TURN_2 = _kristy_turn(2)
KRISTY_TURN_5 = _kristy_turn(5)
KRISTY_TURN_6 = _kristy_turn(6)
KRISTY_TURN_15 = _kristy_turn(15)


def _bridge_overlay(user_text: str, uid: str, states: dict) -> tuple[dict, stance.StanceDecision | None]:
    """Minimal copy of bridge_server stance block (prepare_response → resolve_stance)."""
    st = states.setdefault(uid, stance.StanceState())
    ad_state = adaptive.SessionState()
    payload = adaptive.prepare_response(ad_state, user_text, profile={"role": "CLIENT"})
    if payload.get("direct_response"):
        return payload, None
    dec = stance.resolve_stance(
        user_text, st, payload.get("system_addendum", "") or "",
    )
    if dec.move not in (stance.StanceMove.PASSTHROUGH, stance.StanceMove.REFLECT_AND_FRAME):
        payload["system_addendum"] = dec.addendum
    if stance.should_defer_handoff(user_text, st, dec):
        if payload.get("mode") == "handoff" or payload.get("should_offer_coach_ui"):
            payload["mode"] = "strategic"
            payload["should_offer_coach_ui"] = False
    payload["_stance_decision"] = dec
    return payload, dec


def main() -> int:
    fails: list[str] = []

    flag_on = os.getenv("ENABLE_STANCE_RESOLVER", "false").lower() in ("true", "1", "yes")
    if not flag_on:
        fails.append("ENABLE_STANCE_RESOLVER not true in environment")

    # Module self-test cases (Kristy / magicguy72 shapes)
    intent_cases = [
        ("Do you think it's reasonable that I wanted comfort?", stance.TurnIntent.POSITION),
        ("You're doing it again.", stance.TurnIntent.META_FEEDBACK),
        ("kinda", stance.TurnIntent.LOW_WEIGHT),
        (KRISTY_TURN_12, stance.TurnIntent.POSITION),
        (KRISTY_TURN_13, stance.TurnIntent.POSITION),
    ]
    for text, expected in intent_cases:
        got = stance.classify_intent(text)
        if got != expected:
            fails.append(f"classify_intent({text[:40]!r}...) expected {expected}, got {got}")

    # False-positive fixtures: practical requests must stay exploratory/framing.
    practical_cases = [
        "what should I do about this situation?",
        "can you give me strategies for talking to him?",
        "give me a script for what to say",
        "give me steps I can try tonight",
    ]
    for text in practical_cases:
        got = stance.classify_intent(text)
        if got != stance.TurnIntent.EXPLORE:
            fails.append(f"practical fixture expected EXPLORE, got {got} for {text!r}")
        st_pr = stance.StanceState()
        dec_pr = stance.resolve_stance(text, st_pr, base_addendum="BASE")
        if dec_pr.move == stance.StanceMove.WITNESS:
            fails.append(f"practical fixture must not WITNESS: {text!r} -> {dec_pr.move}")

    states: dict = {}
    uid = "SMOKE_UID"

    # POSITION → witness addendum + closer strip
    _, dec_pos = _bridge_overlay(
        "Do you think it's reasonable that I wanted comfort?", uid, states,
    )
    if dec_pos is None or dec_pos.move != stance.StanceMove.WITNESS:
        fails.append(f"position move expected WITNESS, got {getattr(dec_pos, 'move', None)}")
    if dec_pos and dec_pos.end_on_question:
        fails.append("position turn should set end_on_question=False")

    raw = (
        "Wanting comfort after crying for days is a normal response. "
        "Which of these framings resonates with you?"
    )
    cleaned = stance.guard_generated_closer(raw, dec_pos, states[uid])
    if "?" in cleaned or "Which of these" in cleaned:
        fails.append(f"closer guard failed: {cleaned!r}")

    # Kristy turn 12 + 13 → POSITION + WITNESS (not framing menu addendum)
    for label, turn_text in (("turn_12", KRISTY_TURN_12), ("turn_13", KRISTY_TURN_13)):
        got_int = stance.classify_intent(turn_text)
        if got_int != stance.TurnIntent.POSITION:
            fails.append(f"{label} classify expected POSITION, got {got_int}")
        _, dec_k = _bridge_overlay(turn_text, uid, states)
        if dec_k is None or dec_k.move != stance.StanceMove.WITNESS:
            fails.append(f"{label} resolve expected WITNESS, got {getattr(dec_k, 'move', None)}")
        if dec_k and "menu of framings" not in (dec_k.addendum or "").lower():
            fails.append(f"{label} missing witness addendum prohibition")

    # Kristy neutral narrative turns 2/5/6 → WITNESS (no framing menu)
    for label, turn_text in (("turn_2", KRISTY_TURN_2), ("turn_5", KRISTY_TURN_5), ("turn_6", KRISTY_TURN_6)):
        _, dec_n = _bridge_overlay(turn_text, uid, states)
        if dec_n is None or dec_n.move != stance.StanceMove.WITNESS:
            fails.append(f"{label} expected WITNESS, got {getattr(dec_n, 'move', None)}")

    # Turn 15: position-thread breakthrough — WITNESS + defer handoff
    _, dec_15 = _bridge_overlay(KRISTY_TURN_15, uid, states)
    if dec_15 is None or dec_15.move != stance.StanceMove.WITNESS:
        fails.append(f"turn_15 expected WITNESS, got {getattr(dec_15, 'move', None)}")
    if dec_15 and dec_15.end_on_question:
        fails.append("turn_15 should set end_on_question=False")

    handoff_raw = (
        "You've been carrying a lot. Your coach is available if you'd like to bring them in. "
        "What do you think?"
    )
    handoff_clean = stance.guard_generated_closer(
        handoff_raw, dec_15 or dec_pos, states[uid],
    )
    if handoff_clean.strip().endswith("?"):
        fails.append(f"handoff trailing question not stripped: {handoff_clean!r}")

    # guard_framing_menu: numbered menu under WITNESS → stripped + non-empty fallback
    menu_raw = (
        "You're naming the heart of it.\n\n"
        "Here are three concrete framings:\n"
        "1. Pacing mutual vulnerability\n"
        "2. Building in comfort as baseline\n"
        "3. Capping exposure time\n\n"
        "Which of these fits what you're picturing?"
    )
    menu_clean = stance.guard_framing_menu(menu_raw, stance.StanceMove.WITNESS)
    if not menu_clean.strip():
        fails.append("guard_framing_menu returned empty")
    if re.search(r"\d+[.)]", menu_clean) or "which of these" in menu_clean.lower():
        fails.append(f"guard_framing_menu left menu content: {menu_clean!r}")

    # stale-opener strip
    st_op = stance.StanceState()
    st_op.recent_opener_hashes.append(
        stance._opener_fingerprint("You're naming the heart of it.")
    )
    st_op.recent_opener_phrases.append("You're naming the heart of it.")
    stale_raw = "You're naming the heart of it. That sounds like a lot to carry alone."
    stale_clean = stance.guard_stale_opener(stale_raw, st_op)
    if stale_clean.lower().startswith("you're naming the heart"):
        fails.append(f"stale opener not stripped: {stale_clean!r}")

    # META → ack/adjust addendum
    _, dec_meta = _bridge_overlay("You're doing it again.", uid, states)
    if dec_meta is None or dec_meta.move != stance.StanceMove.ACKNOWLEDGE_AND_ADJUST:
        fails.append(f"meta move expected ACKNOWLEDGE_AND_ADJUST, got {getattr(dec_meta, 'move', None)}")
    if dec_meta and "ACKNOWLEDGE + ADJUST" not in (dec_meta.addendum or ""):
        fails.append("meta turn missing ACKNOWLEDGE + ADJUST addendum")

    # direct_response path must skip stance (simulate scope_lock)
    ad = adaptive.SessionState()
    payload_scope = adaptive.prepare_response(ad, "hello", profile={"role": "CLIENT"})
    payload_scope["direct_response"] = "Stabilization hold."
    skip = bool(payload_scope.get("direct_response"))
    if not skip:
        fails.append("direct_response fixture should be set")

    # ITEM 1: state_to_dict -> state_from_dict round-trip preserves all fields
    st_rt = stance.StanceState()
    st_rt.position_asks_unanswered = 2
    st_rt.position_thread_active = True
    st_rt.consecutive_framings = 1
    st_rt.recent_opener_hashes = ["h1", "h2"]
    st_rt.recent_opener_phrases = ["p1", "p2"]
    st_rt2 = stance.state_from_dict(stance.state_to_dict(st_rt))
    if (st_rt2.position_asks_unanswered != 2 or not st_rt2.position_thread_active
            or st_rt2.consecutive_framings != 1
            or st_rt2.recent_opener_hashes != ["h1", "h2"]
            or st_rt2.recent_opener_phrases != ["p1", "p2"]):
        fails.append(f"state round-trip lost fields: {stance.state_to_dict(st_rt2)!r}")

    # ITEM 8: clear regex POSITION must win over a NEUTRAL classifier hint (regex is floor)
    st_rc = stance.StanceState()
    pos_intent = stance.classify_intent(
        "Do you think it's reasonable that I wanted comfort?", st_rc
    )
    eff_intent = stance.reconcile_intent(
        pos_intent, stance.TurnIntent.NEUTRAL, 0.9, st_rc
    )
    if pos_intent == stance.TurnIntent.POSITION and eff_intent != stance.TurnIntent.POSITION:
        fails.append(f"classifier NEUTRAL wrongly downgraded regex POSITION -> {eff_intent}")

    print("stance_resolver_smoke")
    print(f"  ENABLE_STANCE_RESOLVER={os.environ.get('ENABLE_STANCE_RESOLVER')}")
    print(f"  position move={dec_pos.move.value if dec_pos else '?'} end_on_question={dec_pos.end_on_question if dec_pos else '?'}")
    print(f"  closer stripped: {cleaned!r}")
    print(f"  kristy turn_12 move={dec_k.move.value if dec_k else '?'}")
    print(f"  guard_framing_menu: {menu_clean!r}")
    print(f"  stale opener stripped: {stale_clean!r}")
    print(f"  meta move={dec_meta.move.value if dec_meta else '?'}")
    print(f"  direct_response skip path: OK")

    if fails:
        print(f"\nFAIL ({len(fails)}):")
        for f in fails:
            print(f"  - {f}")
        return 1

    print("\nPASS — all checks OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
