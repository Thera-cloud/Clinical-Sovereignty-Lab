#!/usr/bin/env python3
"""QUANTUM-CRYSTAL-ARCH: Phase 5d live smoke after ENABLE_CRYSTAL_GRAPH=true.

Checks: flag on backend, CrystalGraph init log, client1 chat still works,
re-run isolation audit still clean for client1.

Usage on GREEN:
  PROD_TEST_PASSWORD=test123 python3 backend/scripts/prod_phase5d_ws_smoke.py
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
_MARKER = os.getenv("PROD_5D_MARKER", f"phase5d_soak_{int(time.time())}")
QUERY = os.getenv(
    "PROD_TEST_QUERY",
    f"What patterns have we talked about before? {_MARKER}",
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
            print(f"[<] {mt}: {json.dumps(data)[:200]}")
            if mt in wanted or mt in ("login_failed", "error", "auth_error"):
                return data
        elif msg.type in (aiohttp.WSMsgType.CLOSE, aiohttp.WSMsgType.ERROR):
            raise RuntimeError(f"WS closed: {msg}")
    raise TimeoutError(f"timeout waiting for {wanted}")


async def run_ws() -> str:
    async with aiohttp.ClientSession() as session:
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
        await asyncio.sleep(0.2)
        while True:
            try:
                await asyncio.wait_for(ws.receive(), timeout=0.1)
            except asyncio.TimeoutError:
                break
        print(f"[>] nate_query: {QUERY}")
        await ws.send_str(
            json.dumps({"type": "nate_query", "text": QUERY, "nate_query": QUERY})
        )
        full = ""
        deadline = time.monotonic() + 120
        while time.monotonic() < deadline:
            msg = await asyncio.wait_for(
                ws.receive(), timeout=max(0.1, deadline - time.monotonic())
            )
            if msg.type != aiohttp.WSMsgType.TEXT:
                continue
            data = json.loads(msg.data)
            mt = data.get("type", "")
            chunk = data.get("text") or data.get("response") or ""
            if mt in ("nate_response", "ai_response") and chunk:
                full = chunk
                print(f"[<] {mt} len={len(chunk)}")
                break
            print(f"[<] {mt}")
        await ws.close()
        if not full:
            raise RuntimeError("no response")
        return full


def verify(response_text: str) -> int:
    fail = 0
    flag = subprocess.check_output(
        ["docker", "exec", "nate_backend", "printenv", "ENABLE_CRYSTAL_GRAPH"],
        text=True,
    ).strip()
    print(f"[*] ENABLE_CRYSTAL_GRAPH={flag}")
    if flag.lower() != "true":
        print("FAIL: graph flag must be true")
        fail = 1
    else:
        print("OK: graph flag true")

    logs = subprocess.check_output(
        ["docker", "logs", "nate_backend", "--since", "10m"],
        text=True,
        stderr=subprocess.STDOUT,
    )
    if "CrystalGraph initialized" not in logs and "crystal_graph" not in logs.lower():
        # allow either init line or health registry
        if "CrystalGraph" not in logs:
            print("FAIL: no CrystalGraph init evidence in backend logs")
            fail = 1
        else:
            print("OK: CrystalGraph mentioned in logs")
    else:
        print("OK: CrystalGraph initialized")

    if not (response_text or "").strip():
        print("FAIL: empty chat response")
        fail = 1
    else:
        print("OK: client1 chat response received")

    # Isolation still clean
    env = os.environ.copy()
    env["PROD_5D_ALLOW_FLAG_ON"] = "1"
    rc = subprocess.call(
        [
            "python3",
            "/opt/clinical-sovereignty-lab/backend/scripts/prod_phase5d_isolation_audit.py",
        ],
        env=env,
    )
    if rc != 0:
        print("FAIL: isolation audit non-zero")
        fail = 1
    else:
        print("OK: isolation audit still clean")

    return fail


async def main() -> int:
    try:
        text = await run_ws()
    except Exception as e:
        print(f"FAIL: WS: {e}")
        return 1
    return verify(text)


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
