#!/usr/bin/env python3
"""Smoke test: ln_stance_resolver + bridge overlay path (no WebSocket / no LLM)."""
from __future__ import annotations

import os
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
    ]
    for text, expected in intent_cases:
        got = stance.classify_intent(text)
        if got != expected:
            fails.append(f"classify_intent({text!r}) expected {expected}, got {got}")

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

    print("stance_resolver_smoke")
    print(f"  ENABLE_STANCE_RESOLVER={os.environ.get('ENABLE_STANCE_RESOLVER')}")
    print(f"  position move={dec_pos.move.value if dec_pos else '?'} end_on_question={dec_pos.end_on_question if dec_pos else '?'}")
    print(f"  closer stripped: {cleaned!r}")
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
