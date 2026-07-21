#!/usr/bin/env python3
"""QUANTUM-CRYSTAL-ARCH: Phase 5c live WS smoke — forward reasoning on prod bridge.

Login as CLIENT (default client1 / test123 / CLIENT_001), send a distress turn,
assert flags FORWARD=true and bridge logged forward_reasoning constraints.

Usage (on GREEN host, not inside nate_backend):
  PROD_TEST_PASSWORD=test123 python3 backend/scripts/prod_phase5c_ws_smoke.py
"""
from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
import time

try:
    import aiohttp
except ImportError:
    print("FAIL: pip install aiohttp", file=sys.stderr)
    sys.exit(2)

WS_URL = os.getenv("PROD_BRIDGE_WS", "ws://127.0.0.1:8765")
USERNAME = os.getenv("PROD_TEST_USER", "client1")
PASSWORD = os.getenv("PROD_TEST_PASSWORD", "test123")
HARDWARE_ID = os.getenv("PROD_TEST_HW", "CLIENT_001")
_MARKER = os.getenv("PROD_5C_MARKER", f"phase5c_soak_{int(time.time())}")
QUERY = os.getenv(
    "PROD_TEST_QUERY",
    f"I feel overwhelmed and afraid today. {_MARKER}",
)


async def _recv_until(ws, wanted, timeout_s: float):
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        msg = await asyncio.wait_for(
            ws.receive(), timeout=max(0.1, deadline - time.monotonic())
        )
        if msg.type == aiohttp.WSMsgType.TEXT:
            data = json.loads(msg.data)
            mt = data.get("type", "")
            print(f"[<] {mt}: {json.dumps(data)[:240]}")
            if mt in wanted or mt in ("login_failed", "error", "auth_error"):
                return data
        elif msg.type in (aiohttp.WSMsgType.CLOSE, aiohttp.WSMsgType.ERROR):
            raise RuntimeError(f"WS closed during wait for {wanted}: {msg}")
    raise TimeoutError(f"timeout waiting for {wanted}")


async def run_ws() -> str:
    async with aiohttp.ClientSession() as session:
        print(f"[*] connect {WS_URL}")
        ws = await session.ws_connect(WS_URL, heartbeat=30, receive_timeout=180)
        await _recv_until(ws, {"connected"}, 15)
        await ws.send_str(
            json.dumps(
                {
                    "type": "login_request",
                    "username": USERNAME,
                    "password": PASSWORD,
                    "expected_role": "CLIENT",
                    "hardware_id": HARDWARE_ID,
                }
            )
        )
        login = await _recv_until(ws, {"login_success", "login_failed"}, 30)
        if login.get("type") != "login_success":
            raise RuntimeError(f"login failed: {login}")

        await asyncio.sleep(0.3)
        while True:
            try:
                msg = await asyncio.wait_for(ws.receive(), timeout=0.15)
                if msg.type in (aiohttp.WSMsgType.CLOSE, aiohttp.WSMsgType.ERROR):
                    break
            except asyncio.TimeoutError:
                break

        print(f"[>] nate_query: {QUERY}")
        await ws.send_str(
            json.dumps(
                {
                    "type": "nate_query",
                    "text": QUERY,
                    "nate_query": QUERY,
                }
            )
        )
        full = ""
        deadline = time.monotonic() + 120
        while time.monotonic() < deadline:
            msg = await asyncio.wait_for(
                ws.receive(), timeout=max(0.1, deadline - time.monotonic())
            )
            if msg.type != aiohttp.WSMsgType.TEXT:
                if msg.type in (aiohttp.WSMsgType.CLOSE, aiohttp.WSMsgType.ERROR):
                    break
                continue
            data = json.loads(msg.data)
            mt = data.get("type", "")
            chunk = data.get("text") or data.get("response") or data.get("message") or ""
            if mt in ("nate_response", "ai_response") and chunk:
                full = chunk if len(chunk) >= len(full) else full
                print(f"[<] {mt} len={len(chunk)}")
                break
            print(f"[<] {mt}: {json.dumps(data)[:160]}")
        await ws.close()
        if not full:
            raise RuntimeError("no nate/ai response text received")
        print(f"[=] response len={len(full)} preview={full[:200]!r}")
        return full


def _printenv_bridge(*keys: str) -> list[str]:
    out = subprocess.check_output(
        ["docker", "exec", "nate_bridge", "printenv", *keys],
        text=True,
    ).strip()
    return out.splitlines()


def verify(response_text: str) -> int:
    fail = 0
    print("[*] flags on bridge")
    lines = _printenv_bridge(
        "ENABLE_FORWARD_REASONING",
        "ENABLE_SYMBOLIC_VERIFIER",
        "ENABLE_SYMBOLIC_EXTRACTION",
    )
    print("\n".join(lines))
    if len(lines) < 3 or lines[0].lower() != "true":
        print("FAIL: ENABLE_FORWARD_REASONING must be true for 5c soak")
        fail = 1
    elif lines[1].lower() != "true" or lines[2].lower() != "true":
        print("FAIL: 5b flags must stay true during 5c")
        fail = 1
    else:
        print("OK: flags true/true/true (FORWARD/VERIFIER/EXTRACT)")

    if not (response_text or "").strip():
        print("FAIL: empty response")
        fail = 1
    else:
        print("OK: live reply received")

    print("[*] bridge logs forward_reasoning (last 3m)")
    logs = subprocess.check_output(
        ["docker", "logs", "nate_bridge", "--since", "3m"],
        text=True,
        stderr=subprocess.STDOUT,
    )
    hits = [
        ln
        for ln in logs.splitlines()
        if "forward_reasoning" in ln.lower()
        or "FORWARD REASONING" in ln
    ]
    for ln in hits[-8:]:
        print(ln[:220])
    if not any("forward_reasoning n=" in ln for ln in hits):
        print("FAIL: no therapeutic_controller forward_reasoning log")
        fail = 1
    else:
        print("OK: forward_reasoning constraints logged")

    return fail


async def main() -> int:
    try:
        text = await run_ws()
    except Exception as e:
        print(f"FAIL: WS path: {e}")
        return 1
    await asyncio.sleep(3)
    return verify(text)


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
