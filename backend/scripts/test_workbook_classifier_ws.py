"""
Ad-hoc smoke: log in as audit_client, send 3 chat_message turns that exercise
the workbook_intent_classifier + ln_response_stance path, and print Nate's
final response text for each turn.

Run inside nate_backend:
  docker exec -e WS_URL=ws://bridge:8765 nate_backend \
    python /app/scripts/test_workbook_classifier_ws.py

Watch classifier logs in another shell:
  docker logs -f nate_bridge 2>&1 | grep -E 'COACHING-INTENT|WORKBOOK|nate_response'
"""
import asyncio
import json
import os
import ssl
import time

import websockets

WS_URL = os.environ.get("WS_URL", "ws://bridge:8765")
USERNAME = "audit_client"
PASSWORD = "AuditClient2026!"
EXPECTED_ROLE = "CLIENT"

TURNS = [
    (
        "frame_control_expected_observe",
        "Stop asking me about my feelings. Just give me actionable strategies. "
        "We fight the same fight every night — I pursue and she withdraws.",
    ),
    (
        "gestalt_expected_offer",
        "There's unfinished business with my dad. I keep imagining what I'd say "
        "if he were sitting across from me. It just eats at me.",
    ),
    (
        "emotional_no_method_expected_defer_or_observe",
        "I just feel heavy today. Nothing in particular. Just heavy.",
    ),
]


async def _wait_for(ws, wanted_types, timeout=45):
    deadline = time.monotonic() + timeout
    collected = []
    while time.monotonic() < deadline:
        remaining = max(0.5, deadline - time.monotonic())
        raw = await asyncio.wait_for(ws.recv(), timeout=remaining)
        try:
            msg = json.loads(raw)
        except Exception:
            continue
        collected.append(msg)
        if msg.get("type") in wanted_types:
            return msg, collected
    return None, collected


async def main():
    ssl_ctx = None
    if WS_URL.startswith("wss://"):
        ssl_ctx = ssl.create_default_context()
        ssl_ctx.check_hostname = False
        ssl_ctx.verify_mode = ssl.CERT_NONE

    nonce = int(time.time() * 1000) % 1_000_000
    hardware_id = f"workbook_smoke_{nonce}"

    async with websockets.connect(WS_URL, ssl=ssl_ctx, open_timeout=15) as ws:
        hs = json.loads(await asyncio.wait_for(ws.recv(), timeout=10))
        assert hs.get("type") == "connected", f"bad handshake: {hs}"

        await ws.send(json.dumps({
            "type": "login_request",
            "username": USERNAME,
            "password": PASSWORD,
            "expected_role": EXPECTED_ROLE,
            "hardware_id": hardware_id,
        }))
        resp, _ = await _wait_for(ws, {"login_success", "login_failed", "error"}, timeout=20)
        assert resp and resp.get("type") == "login_success", f"login failed: {resp}"
        print(f"[login] OK role={resp.get('profile', {}).get('role')} hw={hardware_id}")

        for label, text in TURNS:
            print(f"\n===== TURN: {label} =====")
            print(f"[user] {text}")
            await ws.send(json.dumps({
                "type": "chat_message",
                "text": text,
            }))
            resp, all_msgs = await _wait_for(
                ws,
                {"nate_response", "ai_response", "error"},
                timeout=60,
            )
            if not resp:
                print("[nate] <timeout / no response>")
                print(f"[debug] {len(all_msgs)} intermediate messages")
                continue
            if resp.get("type") == "error":
                print(f"[nate] ERROR: {resp}")
                continue
            reply = (
                resp.get("nate_response")
                or resp.get("text")
                or resp.get("message")
                or resp.get("ai_response")
                or json.dumps(resp)[:400]
            )
            print(f"[nate] {reply}")
            # brief pause so classifier log lands in its own window
            await asyncio.sleep(1.5)


if __name__ == "__main__":
    asyncio.run(main())
