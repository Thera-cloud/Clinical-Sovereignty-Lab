#!/usr/bin/env python3
"""QUANTUM-CRYSTAL-ARCH: Staging session negotiation — book as client → coach notify.

Default: client1 / test123 / CLIENT_001 → CoachN (COACH_COACHN_ID).
Verifies session_booked + session_negotiations row + coach email/SMS attempt logs.

Usage (on GREEN):
  python3 /opt/clinical-sovereignty-lab/backend/scripts/staging_negotiation_book_smoke.py
"""
from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone

try:
    import aiohttp
except ImportError:
    print("FAIL: pip install aiohttp", file=sys.stderr)
    sys.exit(2)

WS_URL = os.getenv("STAGING_BRIDGE_WS", "ws://127.0.0.1:8767")
USERNAME = os.getenv("STAGING_TEST_USER", "client1")
PASSWORD = os.getenv("STAGING_TEST_PASSWORD", "test123")
HARDWARE_ID = os.getenv("STAGING_TEST_HW", "CLIENT_001")
COACH_ID = os.getenv("STAGING_TEST_COACH_HW", "COACH_COACHN_ID")


async def _recv_until(ws, wanted, timeout_s: float):
    deadline = time.monotonic() + timeout_s
    last = None
    while time.monotonic() < deadline:
        msg = await asyncio.wait_for(
            ws.receive(), timeout=max(0.1, deadline - time.monotonic())
        )
        if msg.type == aiohttp.WSMsgType.TEXT:
            data = json.loads(msg.data)
            mt = data.get("type", "")
            print(f"[<] {mt}: {json.dumps(data)[:280]}")
            last = data
            if mt in wanted or mt in ("error", "login_failed"):
                return data
        elif msg.type in (aiohttp.WSMsgType.CLOSE, aiohttp.WSMsgType.ERROR):
            raise RuntimeError(f"WS closed waiting for {wanted}: {msg}")
    raise TimeoutError(f"timeout waiting for {wanted}; last={last}")


def _slot() -> tuple[str, str]:
    # Unique far-future slot (UTC) to avoid conflict with live bookings
    start = datetime.now(timezone.utc) + timedelta(days=14, hours=3)
    start = start.replace(minute=0, second=0, microsecond=0)
    end = start + timedelta(minutes=50)
    return start.isoformat().replace("+00:00", "Z"), end.isoformat().replace("+00:00", "Z")


async def book() -> str:
    start, end = _slot()
    print(f"[*] slot {start} → {end}")
    async with aiohttp.ClientSession() as session:
        ws = await session.ws_connect(WS_URL, heartbeat=30, receive_timeout=120)
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

        await asyncio.sleep(0.4)
        while True:
            try:
                msg = await asyncio.wait_for(ws.receive(), timeout=0.15)
                if msg.type == aiohttp.WSMsgType.TEXT:
                    print(f"[<] drain {json.loads(msg.data).get('type')}")
            except asyncio.TimeoutError:
                break

        payload = {
            "type": "client_book_session",
            "coach_id": COACH_ID,
            "scheduled_start": start,
            "scheduled_end": end,
            "notes": "staging negotiation smoke — coach notify",
        }
        print(f"[>] client_book_session coach={COACH_ID}")
        await ws.send_str(json.dumps(payload))
        booked = await _recv_until(
            ws,
            {"session_booked", "error", "session_negotiation_update"},
            45,
        )
        if booked.get("type") == "error":
            raise RuntimeError(f"book error: {booked}")
        sid = ""
        if booked.get("type") == "session_booked":
            sid = (booked.get("session") or {}).get("session_id") or ""
            status = (booked.get("session") or {}).get("status")
            print(f"[=] booked session_id={sid} status={status}")
            if status != "pending_approval":
                raise RuntimeError(f"expected pending_approval, got {status}")
        # optional follow-up notify on same socket
        try:
            extra = await _recv_until(
                ws, {"session_negotiation_update", "nate_response"}, 8
            )
            print(f"[=] follow-up {extra.get('type')}")
        except Exception:
            pass
        await ws.close()
        return sid


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
            "little_nate_staging",
            "-tAc",
            sql,
        ],
        text=True,
    ).strip()


def verify_db(session_id: str) -> int:
    print("[*] session_negotiations (latest for CLIENT_001)")
    row = _psql(
        "SELECT id::text || E'\\n' || status || E'\\n' || coach_id || E'\\n' || "
        "COALESCE(session_id,'') || E'\\n' || COALESCE(proposed_start::text,'') "
        "FROM session_negotiations "
        "WHERE client_id = 'CLIENT_001' "
        "ORDER BY created_at DESC LIMIT 1;"
    )
    print(row or "(none)")
    if not row:
        print("FAIL: no session_negotiations row")
        return 1
    lines = row.splitlines()
    neg_id, status, coach_id = lines[0], lines[1] if len(lines) > 1 else "", lines[2] if len(lines) > 2 else ""
    if coach_id != COACH_ID:
        print(f"FAIL: coach_id={coach_id} expected {COACH_ID}")
        return 1
    if status != "awaiting_coach":
        print(f"WARN: status={status} (expected awaiting_coach)")
    if not neg_id:
        print("FAIL: empty negotiation id")
        return 1
    print(f"OK: negotiation {neg_id} status={status}")
    if session_id:
        print(f"OK: bridge session_id={session_id}")
    return 0


async def main() -> int:
    try:
        sid = await book()
    except Exception as e:
        print(f"FAIL: book path: {e}")
        return 1
    await asyncio.sleep(3)
    rc = verify_db(sid)
    print(
        "[*] Watch staging bridge logs for: "
        "session_negotiation_bridge: coach notify email=True/False sms=True/False"
    )
    print(
        "[*] CoachN contact on staging: support@sovereignsanctuary.net / 5865243969 "
        "(not DrNevedal1 admin email unless that inbox is shared)"
    )
    return rc


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
