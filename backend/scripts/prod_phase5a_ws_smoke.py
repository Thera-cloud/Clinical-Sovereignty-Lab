#!/usr/bin/env python3
"""QUANTUM-CRYSTAL-ARCH: Phase 5a live WS smoke on production bridge.

Usage (on GREEN):
  python3 /opt/clinical-sovereignty-lab/backend/scripts/prod_phase5a_ws_smoke.py
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
QUERY = os.getenv(
    "PROD_TEST_QUERY",
    "I am going to therapy next Tuesday afternoon for Phase 5a prod smoke.",
)
DB_NAME = os.getenv("PROD_TEST_DB", "little_nate")


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


async def run_ws() -> None:
    async with aiohttp.ClientSession() as session:
        print(f"[*] connect {WS_URL}")
        ws = await session.ws_connect(WS_URL, heartbeat=30, receive_timeout=180)
        await _recv_until(ws, {"connected"}, 15)
        print(f"[>] login_request {USERNAME} expected_role=CLIENT hw={HARDWARE_ID}")
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
                if msg.type == aiohttp.WSMsgType.TEXT:
                    print(f"[<] drain {json.loads(msg.data).get('type')}")
                elif msg.type in (aiohttp.WSMsgType.CLOSE, aiohttp.WSMsgType.ERROR):
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
        resp = await _recv_until(ws, {"nate_response", "ai_response"}, 120)
        text = resp.get("text") or resp.get("response") or resp.get("message") or ""
        print(f"[=] response len={len(text)} preview={text[:160]!r}")
        await ws.close()


def _psql(sql: str) -> str:
    return subprocess.check_output(
        [
            "docker",
            "exec",
            "nate_postgres",
            "psql",
            "-U",
            "nate_admin",
            "-d",
            DB_NAME,
            "-tAc",
            sql,
        ],
        text=True,
    ).strip()


def db_verify() -> int:
    q_esc = QUERY.replace("'", "''")
    u_esc = USERNAME.replace("'", "''")
    hw_esc = HARDWARE_ID.replace("'", "''")

    print("[*] DB conversation_history.metadata.symbols")
    row = _psql(
        "SELECT COALESCE((metadata ? 'symbols')::int, 0)::text "
        "|| E'\\n' || COALESCE((metadata->'symbols')::text, 'null') "
        "|| E'\\n' || left(user_text, 80) "
        "FROM conversation_history "
        f"WHERE user_id = '{u_esc}' "
        f"AND user_text LIKE '{q_esc[:40]}%' "
        "ORDER BY created_at DESC LIMIT 1;"
    )
    print(row or "(no row)")
    lines = (row or "").splitlines()
    if not lines or lines[0].strip() != "1":
        print("FAIL: no metadata.symbols on matching turn")
        return 1
    symbols_raw = lines[1] if len(lines) > 1 else ""
    if '"state"' not in symbols_raw:
        print("FAIL: symbols missing state key")
        return 1
    print("OK: symbols.state present")

    print("[*] DB nate_commitments (last 15m)")
    out2 = _psql(
        "SELECT count(*)::text || E'\\n' || COALESCE(string_agg(left(commitment_text, 80), ' || '), '') "
        "FROM nate_commitments "
        "WHERE created_at > NOW() - INTERVAL '15 minutes' "
        f"AND (user_id = '{hw_esc}' OR user_id = '{u_esc}');"
    )
    print(out2 or "0")
    count = int((out2 or "0").splitlines()[0] or "0")
    require_commit = os.getenv("PROD_REQUIRE_COMMITMENT", "1") not in (
        "0",
        "false",
        "no",
    )
    if count < 1:
        msg = "no commitment row in last 15m for this user"
        if require_commit:
            print(f"FAIL: {msg}")
            return 1
        print(f"WARN: {msg}")
        return 0

    print("OK: commitment row present")
    if '"commitment"' not in symbols_raw:
        print("WARN: waiting for symbols.commitment merge...")
        time.sleep(5)
        row2 = _psql(
            "SELECT COALESCE((metadata->'symbols')::text, 'null') "
            "FROM conversation_history "
            f"WHERE user_id = '{u_esc}' "
            f"AND user_text LIKE '{q_esc[:40]}%' "
            "ORDER BY created_at DESC LIMIT 1;"
        )
        print(row2)
        if '"commitment"' not in (row2 or ""):
            print("FAIL: commitment row exists but symbols.commitment missing")
            return 1
        print("OK: commitment merged into metadata.symbols")
    else:
        print("OK: symbols.commitment present")
    return 0


async def main() -> int:
    try:
        await run_ws()
    except Exception as e:
        print(f"FAIL: WS path: {e}")
        return 1
    await asyncio.sleep(8)
    return db_verify()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
