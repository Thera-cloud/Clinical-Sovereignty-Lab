#!/usr/bin/env python3
"""Production E2E: Daily Reconnect consent → turns → OFFER_FS → ENTER_FS."""

from __future__ import annotations

import asyncio
import json
import ssl
import sys
import time

try:
    import websockets
except ImportError:
    print("FAIL: pip install websockets")
    sys.exit(1)

WS_URI = sys.argv[1] if len(sys.argv) > 1 else "wss://api.sovereignsanctuary.net/ws"
MSG_TIMEOUT = 45

USER_A = {"username": "client1", "password": "test123", "expected_role": "CLIENT"}
USER_B = {"username": "sweet2noend@yahoo.com", "password": "test123", "expected_role": "CLIENT"}


async def _recv(ws, want_types: set[str], timeout: float = MSG_TIMEOUT):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        raw = await asyncio.wait_for(ws.recv(), timeout=deadline - time.monotonic())
        msg = json.loads(raw)
        t = msg.get("type", "")
        if t in want_types:
            return msg
        if t == "reconnect_error":
            raise RuntimeError(f"reconnect_error: {msg.get('message')}")
    raise TimeoutError(f"timeout waiting for {want_types}")


async def _login(ws, creds: dict):
    await _recv(ws, {"connected"})
    await ws.send(json.dumps({"type": "login_request", **creds}))
    await _recv(ws, {"login_success"})


async def _run_user(creds: dict, *, accept_fs: bool, escalate_text: str | None):
    ctx = ssl.create_default_context()
    async with websockets.connect(WS_URI, ssl=ctx, ping_interval=20, ping_timeout=60) as ws:
        await _login(ws, creds)
        await ws.send(json.dumps({"type": "reconnect_get_or_create"}))
        state = await _recv(ws, {"reconnect_state", "reconnect_error"})
        if state.get("type") == "reconnect_error":
            return state
        session_id = state["session_id"]
        if state.get("consent_required"):
            await ws.send(json.dumps({
                "type": "reconnect_consent_ack",
                "session_id": session_id,
                "accepted": True,
            }))
            await _recv(ws, {"reconnect_consent_result"})
        if escalate_text and state.get("current_turn_user_id") == creds["username"]:
            await ws.send(json.dumps({
                "type": "reconnect_turn",
                "session_id": session_id,
                "content": escalate_text,
            }))
            await _recv(ws, {"reconnect_turn_ack", "reconnect_crisis_bypass"})
        if accept_fs:
            offer = await _recv(ws, {"reconnect_state", "reconnect_turn_ack"}, timeout=90)
            while offer.get("state") != "OFFER_FS":
                if offer.get("state") in ("CRISIS_BYPASS", "CLOSED"):
                    return offer
                offer = await _recv(ws, {"reconnect_state", "reconnect_turn_ack"}, timeout=90)
            await ws.send(json.dumps({
                "type": "reconnect_fs_offer_response",
                "session_id": session_id,
                "accepted": True,
            }))
            fs = await _recv(ws, {"reconnect_fs_response"})
            await ws.send(json.dumps({"type": "reconnect_exit", "session_id": session_id}))
            return fs
        return state


async def main():
    results = {}
    # User A: join + consent
    r_a = await _run_user(USER_A, accept_fs=False, escalate_text=None)
    results["client1_join"] = r_a.get("type", "ok")
    if r_a.get("message") == "dob_required":
        print("FAIL: client1 missing DOB")
        print(json.dumps(results, indent=2))
        sys.exit(1)
    # User B: join + consent
    r_b = await _run_user(USER_B, accept_fs=False, escalate_text=None)
    results["spouse_join"] = r_b.get("type", "ok")
    # Escalation path (soft language — avoid STOPGAP crisis)
    soft = (
        "I feel really unheard when we talk about money and it keeps building up inside me."
    )
    r_esc = await _run_user(USER_A, accept_fs=True, escalate_text=soft)
    results["enter_fs"] = {
        "state": r_esc.get("state"),
        "sanctuary_id": r_esc.get("sanctuary_id"),
    }
    ok = r_esc.get("state") == "ENTER_FS" and bool(r_esc.get("sanctuary_id"))
    print("PASS" if ok else "FAIL")
    print(json.dumps(results, indent=2))
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    asyncio.run(main())
