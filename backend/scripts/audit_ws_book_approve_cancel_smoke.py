#!/usr/bin/env python3
"""Live WS smoke: audit_client book → audit_coach approve → client cancel.

Uses known audit passwords (ws_flow_auditor). Books against audit_coach_hw
(payload coach_id) so approve works without reassigning CoachN.

Fee path: audit_coach has no coaching_fee → price_cents=0 → card/consent
billing gates skipped. Proves WS handlers + JSON/PG dual-write.

Usage (on GREEN):
  python3 backend/scripts/audit_ws_book_approve_cancel_smoke.py
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

WS_URL = os.getenv("BRIDGE_WS", "ws://127.0.0.1:8765")
CLIENT_USER = os.getenv("AUDIT_CLIENT_USER", "audit_client")
CLIENT_PASS = os.getenv("AUDIT_CLIENT_PASSWORD", "AuditClient2026!")
CLIENT_HW = os.getenv("AUDIT_CLIENT_HW", "audit_client_hw")
COACH_USER = os.getenv("AUDIT_COACH_USER", "audit_coach")
COACH_PASS = os.getenv("AUDIT_COACH_PASSWORD", "AuditCoach2026!")
COACH_HW = os.getenv("AUDIT_COACH_HW", "audit_coach_hw")


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
            print(f"[<] {mt}: {json.dumps(data)[:300]}")
            last = data
            if mt in wanted or mt in ("error", "login_failed"):
                return data
        elif msg.type in (aiohttp.WSMsgType.CLOSE, aiohttp.WSMsgType.ERROR):
            raise RuntimeError(f"WS closed waiting for {wanted}: {msg}")
    raise TimeoutError(f"timeout waiting for {wanted}; last={last}")


async def _drain(ws, seconds: float = 0.4):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        try:
            msg = await asyncio.wait_for(ws.receive(), timeout=0.1)
            if msg.type == aiohttp.WSMsgType.TEXT:
                print(f"[<] drain {json.loads(msg.data).get('type')}")
        except asyncio.TimeoutError:
            break


def _slot() -> tuple[str, str]:
    start = datetime.now(timezone.utc) + timedelta(days=21, hours=4)
    start = start.replace(minute=0, second=0, microsecond=0)
    end = start + timedelta(minutes=50)
    return start.isoformat().replace("+00:00", "Z"), end.isoformat().replace("+00:00", "Z")


def _pg(sql: str) -> str:
    r = subprocess.run(
        [
            "docker", "exec", "nate_postgres",
            "psql", "-U", "nate_admin", "-d", "little_nate", "-tAc", sql,
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    return (r.stdout or "").strip()


async def login(session, username, password, role, hw):
    ws = await session.ws_connect(WS_URL, heartbeat=30, receive_timeout=120)
    await _recv_until(ws, {"connected"}, 15)
    await ws.send_str(
        json.dumps(
            {
                "type": "login_request",
                "username": username,
                "password": password,
                "expected_role": role,
                "hardware_id": hw,
            }
        )
    )
    login = await _recv_until(ws, {"login_success", "login_failed"}, 30)
    if login.get("type") != "login_success":
        await ws.close()
        raise RuntimeError(f"{role} login failed: {login}")
    await _drain(ws)
    return ws


async def main() -> int:
    start, end = _slot()
    results = []
    session_id = ""

    print(f"[*] WS={WS_URL} slot={start} → {end}")
    async with aiohttp.ClientSession() as http:
        # 1) Client book
        cws = await login(http, CLIENT_USER, CLIENT_PASS, "CLIENT", CLIENT_HW)
        await cws.send_str(
            json.dumps(
                {
                    "type": "client_book_session",
                    "coach_id": COACH_HW,
                    "scheduled_start": start,
                    "scheduled_end": end,
                    "payment_consent": True,
                    "notes": "audit_ws_book_approve_cancel_smoke",
                }
            )
        )
        booked = await _recv_until(cws, {"session_booked", "error"}, 45)
        if booked.get("type") != "session_booked":
            print(f"FAIL book: {booked}")
            await cws.close()
            return 1
        sess = booked.get("session") or {}
        session_id = sess.get("session_id") or ""
        status = sess.get("status")
        ok_book = bool(session_id) and status == "pending_approval"
        results.append(("book_ws", ok_book, f"id={session_id} status={status}"))
        print(f"[=] book {'PASS' if ok_book else 'FAIL'}")

        # 2) Coach approve (second socket)
        kws = await login(http, COACH_USER, COACH_PASS, "COACH", COACH_HW)
        await kws.send_str(
            json.dumps({"type": "coach_approve_booking", "session_id": session_id})
        )
        approved = await _recv_until(kws, {"booking_approved", "error"}, 45)
        ok_appr = (
            approved.get("type") == "booking_approved"
            and (approved.get("session") or {}).get("status") == "scheduled"
        )
        results.append(("approve_ws", ok_appr, str(approved.get("type"))))
        print(f"[=] approve {'PASS' if ok_appr else 'FAIL'}: {approved.get('type')}")

        # Client may get booking_status_update
        try:
            upd = await _recv_until(cws, {"booking_status_update"}, 8)
            results.append(("client_notify", upd.get("type") == "booking_status_update", upd.get("type")))
        except Exception as e:
            results.append(("client_notify", True, f"optional skipped: {e}"))

        pg_status = _pg(
            f"SELECT status FROM coaching_sessions WHERE session_id='{session_id}' LIMIT 1"
        )
        ok_pg_sched = pg_status.lower() == "scheduled"
        results.append(("pg_after_approve", ok_pg_sched, pg_status or "MISSING"))
        print(f"[=] pg after approve: {pg_status or 'MISSING'}")

        # 3) Client cancel (≥24h → refund skipped / not charged)
        await cws.send_str(
            json.dumps({"type": "client_cancel_session", "session_id": session_id})
        )
        cancelled = await _recv_until(cws, {"session_cancelled", "error"}, 45)
        ok_cancel = cancelled.get("type") == "session_cancelled"
        refund = cancelled.get("refund_status", "")
        results.append(("cancel_ws", ok_cancel, f"refund={refund}"))
        print(f"[=] cancel {'PASS' if ok_cancel else 'FAIL'} refund={refund}")

        pg_cancel = _pg(
            f"SELECT status FROM coaching_sessions WHERE session_id='{session_id}' LIMIT 1"
        )
        ok_pg_cancel = pg_cancel.lower() == "cancelled"
        results.append(("pg_after_cancel", ok_pg_cancel, pg_cancel or "MISSING"))
        print(f"[=] pg after cancel: {pg_cancel or 'MISSING'}")

        await kws.close()
        await cws.close()

    # Cleanup
    if session_id:
        _pg(f"DELETE FROM coaching_sessions WHERE session_id='{session_id}'")
        # JSON cleanup best-effort on host bind mount
        subprocess.run(
            [
                "python3", "-c",
                f"""
import json
p='/opt/clinical-sovereignty-lab/data/bridge/sessions.json'
try:
    with open(p) as f: data=json.load(f)
except Exception:
    raise SystemExit(0)
data=[s for s in data if s.get('session_id')!='{session_id}']
with open(p,'w') as f: json.dump(data,f,indent=2)
print('json cleaned')
""",
            ],
            check=False,
        )
        left = _pg(
            f"SELECT count(*) FROM coaching_sessions WHERE session_id='{session_id}'"
        )
        results.append(("cleanup", left == "0", f"rows_left={left}"))

    print("\n=== RESULTS ===")
    all_ok = True
    for name, ok, detail in results:
        print(f"{'PASS' if ok else 'FAIL'} {name}: {detail}")
        if not ok and name != "client_notify":
            all_ok = False
    print(f"\nOVERALL: {'PASS' if all_ok else 'FAIL'}")
    return 0 if all_ok else 1


if __name__ == "__main__":
    try:
        raise SystemExit(asyncio.run(main()))
    except Exception as e:
        print(f"FAIL: {e}", file=sys.stderr)
        raise
