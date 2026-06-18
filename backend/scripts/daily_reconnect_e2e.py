#!/usr/bin/env python3
"""Production E2E: Daily Reconnect consent → escalation → OFFER_FS → ENTER_FS.

Keeps BOTH family members connected simultaneously and drives the escalation
ladder by turn order until the engine pauses and auto-offers Family Sanctuary,
then accepts the offer and verifies the ENTER_FS group-coaching handoff.

Usage:
    SPOUSE_PW='...' python3 backend/scripts/daily_reconnect_e2e.py [wss://host/ws]
"""

from __future__ import annotations

import asyncio
import json
import os
import ssl
import sys
import time

try:
    import websockets
except ImportError:
    print("FAIL: pip install websockets")
    sys.exit(1)

WS_URI = sys.argv[1] if len(sys.argv) > 1 else "wss://api.sovereignsanctuary.net/ws"
DEADLINE_S = 180.0

USER_A = {"username": "client1", "password": os.environ.get("CLIENT1_PW", "test123"), "expected_role": "CLIENT"}
USER_B = {"username": "sweet2noend@yahoo.com", "password": os.environ.get("SPOUSE_PW", "test123"), "expected_role": "CLIENT"}

# Escalating, esc-keyword-rich, but NOT crisis distress phrases (no "i feel hopeless/alone",
# no self-harm lexicon) → climbs temperature into SOFT_DEESCALATION → PAUSED → OFFER_FS.
ESCALATION = [
    "I'm so frustrated and upset, this money thing really hurt me.",
    "I'm overwhelmed and anxious, and honestly pretty angry about it too.",
    "I'm furious and frustrated, this whole thing makes me feel like a burden.",
    "I'm still upset and overwhelmed, frustrated and angry every time we argue.",
    "Angry and frustrated again, overwhelmed and anxious and it keeps hurting.",
    "Furious, upset, frustrated, overwhelmed — this argument is a burden.",
]


def _log(tag: str, msg: str) -> None:
    print(f"[{tag}] {msg}", file=sys.stderr, flush=True)


class Driver:
    def __init__(self) -> None:
        self.session_id: str | None = None
        self.state: str | None = None
        self.current_turn: str | None = None
        self.sanctuary_id: str | None = None
        self.esc_idx = 0
        self.offer_sent = False
        self.fs_response: dict | None = None
        self.done = asyncio.Event()
        self.lock = asyncio.Lock()
        self.start = time.monotonic()

    async def run_user(self, creds: dict, is_a: bool) -> None:
        ctx = ssl.create_default_context()
        async with websockets.connect(WS_URI, ssl=ctx, ping_interval=20, ping_timeout=60) as ws:
            # login
            await self._wait(ws, {"connected"})
            await ws.send(json.dumps({"type": "login_request", **creds}))
            await self._wait(ws, {"login_success"})
            _log(creds["username"], "login_success")
            # join
            await ws.send(json.dumps({"type": "reconnect_get_or_create"}))
            consumer = asyncio.create_task(self._consume(ws, creds, is_a))
            try:
                await asyncio.wait_for(self.done.wait(), timeout=self._remaining())
            except asyncio.TimeoutError:
                pass
            finally:
                consumer.cancel()

    def _remaining(self) -> float:
        return max(1.0, DEADLINE_S - (time.monotonic() - self.start))

    async def _wait(self, ws, want: set[str]) -> dict:
        while True:
            raw = await asyncio.wait_for(ws.recv(), timeout=self._remaining())
            msg = json.loads(raw)
            if msg.get("type") in want:
                return msg

    async def _consume(self, ws, creds: dict, is_a: bool) -> None:
        me = creds["username"]
        consented = False
        while not self.done.is_set():
            raw = await ws.recv()
            msg = json.loads(raw)
            t = msg.get("type", "")
            if t in ("reconnect_state", "reconnect_turn_ack", "reconnect_consent_result",
                     "reconnect_crisis_bypass", "reconnect_fs_response"):
                if msg.get("session_id"):
                    self.session_id = msg["session_id"]
                if msg.get("state"):
                    self.state = msg["state"]
                if msg.get("current_turn_user_id") is not None:
                    self.current_turn = msg.get("current_turn_user_id")
                if msg.get("sanctuary_id"):
                    self.sanctuary_id = msg["sanctuary_id"]

            if t == "reconnect_error":
                _log(me, f"reconnect_error: {msg.get('message')}")
                continue

            # consent once
            if not consented and self.session_id and (
                msg.get("consent_required") or t in ("reconnect_state", "reconnect_turn_ack")
            ):
                await ws.send(json.dumps({
                    "type": "reconnect_consent_ack",
                    "session_id": self.session_id,
                    "accepted": True,
                }))
                consented = True
                _log(me, "consent sent")
                continue

            if t == "reconnect_crisis_bypass":
                _log(me, "CRISIS_BYPASS reached (unexpected for soft escalation)")
                self.done.set()
                return

            if t == "reconnect_fs_response":
                self.fs_response = msg
                _log(me, f"reconnect_fs_response state={msg.get('state')} sanctuary={msg.get('sanctuary_id')}")
                self.done.set()
                return

            # OFFER_FS → A accepts
            if self.state == "OFFER_FS" and is_a and not self.offer_sent and self.session_id:
                async with self.lock:
                    if not self.offer_sent:
                        self.offer_sent = True
                        await ws.send(json.dumps({
                            "type": "reconnect_fs_offer_response",
                            "session_id": self.session_id,
                            "accepted": True,
                        }))
                        _log(me, "OFFER_FS accepted")
                continue

            # escalation turn: send when it's my turn in an active/soft state
            if (self.state in ("ACTIVE", "SOFT_DEESCALATION")
                    and self.current_turn == me and self.session_id):
                async with self.lock:
                    if self.esc_idx < len(ESCALATION) and self.current_turn == me:
                        text = ESCALATION[self.esc_idx]
                        self.esc_idx += 1
                        await ws.send(json.dumps({
                            "type": "reconnect_turn",
                            "session_id": self.session_id,
                            "content": text,
                        }))
                        _log(me, f"turn#{self.esc_idx} state={self.state}: {text[:40]}...")


async def main() -> int:
    d = Driver()
    await asyncio.gather(
        d.run_user(USER_A, is_a=True),
        d.run_user(USER_B, is_a=False),
    )
    ok = bool(d.fs_response) and d.fs_response.get("state") == "ENTER_FS" and bool(d.fs_response.get("sanctuary_id"))
    result = {
        "final_state": d.state,
        "sanctuary_id": d.sanctuary_id,
        "fs_response_type": (d.fs_response or {}).get("type"),
        "turns_sent": d.esc_idx,
    }
    print("PASS" if ok else "FAIL")
    print(json.dumps(result, indent=2))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
