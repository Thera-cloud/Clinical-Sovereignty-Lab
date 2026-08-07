#!/usr/bin/env python3
"""Paid WS smoke: book → approve → agent charge → cancel refund.

Uses ONLY audit_client's own Stripe customer + card on file.
Never borrows another client's payment method / customer id.

Prereqs:
  - audit_client must already have a dedicated card on its own Stripe customer
  - RUN_PREP=1 sets audit_coach coaching_fee=$30 (agent MIN_FEE_CENTS) and restarts bridge

If audit_client has no card, the script exits with instructions — it does not
attach or reuse any real client's card.

Slot is ~48h out (inside 72h charge window, outside 24h no-refund window).

Usage (on GREEN):
  RUN_PREP=1 python3 backend/scripts/audit_ws_paid_book_charge_cancel_smoke.py
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
CLIENT_USER = "audit_client"
CLIENT_PASS = os.getenv("AUDIT_CLIENT_PASSWORD", "AuditClient2026!")
CLIENT_HW = "audit_client_hw"
COACH_USER = "audit_coach"
COACH_PASS = os.getenv("AUDIT_COACH_PASSWORD", "AuditCoach2026!")
COACH_HW = "audit_coach_hw"
RUN_PREP = os.getenv("RUN_PREP", "1") == "1"
RESTORE = os.getenv("RESTORE", "1") == "1"


def _sh(cmd: str) -> str:
    r = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    if r.returncode != 0 and r.stderr:
        print(f"[!] cmd rc={r.returncode}: {r.stderr[:400]}")
    return (r.stdout or "").strip()


def _pg(sql: str) -> str:
    return _sh(
        "docker exec nate_postgres psql -U nate_admin -d little_nate -tAc "
        + json.dumps(sql)
    )


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
            raise RuntimeError(f"WS closed: {msg}")
    raise TimeoutError(f"timeout {wanted}; last={last}")


async def _drain(ws, seconds: float = 0.5):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        try:
            msg = await asyncio.wait_for(ws.receive(), timeout=0.1)
            if msg.type == aiohttp.WSMsgType.TEXT:
                print(f"[<] drain {json.loads(msg.data).get('type')}")
        except asyncio.TimeoutError:
            break


def _slot_48h() -> tuple[str, str]:
    start = datetime.now(timezone.utc) + timedelta(hours=48)
    start = start.replace(minute=0, second=0, microsecond=0)
    end = start + timedelta(minutes=50)
    return start.isoformat().replace("+00:00", "Z"), end.isoformat().replace("+00:00", "Z")


def audit_client_has_own_card() -> tuple[bool, str]:
    """True only if audit_client's own Stripe customer has a card. Never reassigns customers."""
    cus = _pg(
        "SELECT COALESCE(stripe_customer_id, profile_data->>'stripe_customer_id') "
        "FROM users WHERE username='audit_client' AND role='CLIENT' LIMIT 1"
    )
    if not cus or not cus.startswith("cus_"):
        return False, "audit_client has no stripe_customer_id"
    out = _sh(
        "docker exec nate_backend python3 -c "
        + json.dumps(
            "import os,stripe; stripe.api_key=os.environ.get('STRIPE_SECRET_KEY',''); "
            f"pms=stripe.PaymentMethod.list(customer={cus!r}, type='card', limit=1); "
            "print(len(pms.data))"
        )
    )
    try:
        n = int((out.splitlines()[-1] if out else "0").strip())
    except ValueError:
        return False, f"stripe list failed: {out[:200]}"
    if n < 1:
        return False, (
            f"audit_client customer {cus} has 0 cards. "
            "Attach a dedicated test card to audit_client only — "
            "do not reuse any real client's card."
        )
    return True, f"{cus} cards={n}"


def prep():
    print("[*] PREP: set audit_coach fee=$30 (no Stripe customer reassignment)")
    ok, detail = audit_client_has_own_card()
    if not ok:
        raise SystemExit(f"ABORT paid smoke: {detail}")
    print(f"[*] card check OK: {detail}")
    _pg(
        "UPDATE users SET profile_data = jsonb_set("
        "COALESCE(profile_data,'{}'::jsonb), '{coaching_fee}', '30'::jsonb) "
        "WHERE username='audit_coach' AND role='COACH'"
    )
    print(_pg(
        "SELECT username, profile_data->>'coaching_fee' "
        "FROM users WHERE username IN ('audit_client','audit_coach') ORDER BY 1"
    ))
    print("[*] Restarting bridge for registry cache")
    _sh("cd /opt/clinical-sovereignty-lab && bash scripts/safe_deploy.sh bridge")
    time.sleep(8)


def restore():
    print("[*] RESTORE: clear audit_coach fee only")
    _pg(
        "UPDATE users SET profile_data = profile_data - 'coaching_fee' "
        "WHERE username='audit_coach' AND role='COACH'"
    )
    _sh("cd /opt/clinical-sovereignty-lab && bash scripts/safe_deploy.sh bridge")


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
        raise RuntimeError(f"login failed: {login}")
    await _drain(ws)
    return ws


def trigger_charge_cycle() -> str:
    return _sh(
        "docker exec -e PYTHONPATH=/app nate_backend "
        "python3 /app/scripts/run_session_payment_cycle_once.py"
    )


async def main() -> int:
    results = []
    session_id = ""
    try:
        if RUN_PREP:
            prep()
        else:
            ok, detail = audit_client_has_own_card()
            if not ok:
                raise SystemExit(f"ABORT paid smoke: {detail}")
            print(f"[*] card check OK: {detail}")

        start, end = _slot_48h()
        print(f"[*] paid smoke slot {start} → {end}")

        async with aiohttp.ClientSession() as http:
            cws = await login(http, CLIENT_USER, CLIENT_PASS, "CLIENT", CLIENT_HW)
            await cws.send_str(
                json.dumps(
                    {
                        "type": "client_book_session",
                        "coach_id": COACH_HW,
                        "scheduled_start": start,
                        "scheduled_end": end,
                        "payment_consent": True,
                        "notes": "audit_ws_paid_book_charge_cancel_smoke",
                    }
                )
            )
            booked = await _recv_until(cws, {"session_booked", "error"}, 45)
            if booked.get("type") != "session_booked":
                results.append(("book_ws", False, str(booked)[:200]))
                print("FAIL book", booked)
                await cws.close()
                return 1
            sess = booked.get("session") or {}
            session_id = sess.get("session_id") or ""
            price = sess.get("price_cents")
            pay_st = sess.get("payment_status")
            ok_book = (
                sess.get("status") == "pending_approval"
                and int(price or 0) == 3000
                and pay_st == "pending"
            )
            results.append(("book_ws", ok_book, f"{session_id} price={price} pay={pay_st}"))

            kws = await login(http, COACH_USER, COACH_PASS, "COACH", COACH_HW)
            await kws.send_str(
                json.dumps({"type": "coach_approve_booking", "session_id": session_id})
            )
            approved = await _recv_until(kws, {"booking_approved", "error"}, 45)
            ok_ap = (
                approved.get("type") == "booking_approved"
                and (approved.get("session") or {}).get("status") == "scheduled"
            )
            results.append(("approve_ws", ok_ap, approved.get("type")))
            try:
                await _recv_until(cws, {"booking_status_update"}, 8)
            except Exception:
                pass

            print("[*] Triggering SessionPaymentAgent cycle")
            print(trigger_charge_cycle()[-500:])
            pay_row = _pg(
                "SELECT payment_status || '|' || COALESCE(stripe_payment_intent_id,'') "
                f"FROM coaching_sessions WHERE session_id='{session_id}'"
            )
            ok_paid = pay_row.startswith("paid|pi_")
            results.append(("agent_charge", ok_paid, pay_row or "MISSING"))

            await cws.send_str(
                json.dumps({"type": "client_cancel_session", "session_id": session_id})
            )
            cancelled = await _recv_until(cws, {"session_cancelled", "error"}, 45)
            refund = cancelled.get("refund_status", "")
            ok_ref = cancelled.get("type") == "session_cancelled" and refund == "refunded"
            results.append(
                (
                    "cancel_refund",
                    ok_ref,
                    f"refund={refund} detail={cancelled.get('refund_detail')}",
                )
            )

            pg_final = _pg(
                "SELECT status || '|' || payment_status "
                f"FROM coaching_sessions WHERE session_id='{session_id}'"
            )
            ok_final = pg_final.lower().startswith("cancelled|refunded")
            results.append(("pg_final", ok_final, pg_final or "MISSING"))

            await kws.close()
            await cws.close()

        if session_id:
            _pg(f"DELETE FROM coaching_sessions WHERE session_id='{session_id}'")
            cleaner = (
                "import json\n"
                "p='/opt/clinical-sovereignty-lab/data/bridge/sessions.json'\n"
                f"sid={session_id!r}\n"
                "d=json.load(open(p))\n"
                "d=[s for s in d if s.get('session_id')!=sid]\n"
                "json.dump(d, open(p,'w'), indent=2)\n"
                "print('json_cleaned')\n"
            )
            path = "/tmp/cleanup_sessions_smoke.py"
            with open(path, "w") as f:
                f.write(cleaner)
            _sh(f"python3 {path}")
            left = _pg(
                f"SELECT count(*) FROM coaching_sessions WHERE session_id='{session_id}'"
            )
            results.append(("cleanup", left == "0", f"left={left}"))

    finally:
        if RESTORE:
            try:
                restore()
            except Exception as e:
                print(f"[!] restore failed: {e}")
                results.append(("restore", False, str(e)))

    print("\n=== RESULTS ===")
    all_ok = True
    for name, ok, detail in results:
        print(f"{'PASS' if ok else 'FAIL'} {name}: {detail}")
        if not ok:
            all_ok = False
    print(f"\nOVERALL: {'PASS' if all_ok else 'FAIL'}")
    return 0 if all_ok else 1


if __name__ == "__main__":
    try:
        raise SystemExit(asyncio.run(main()))
    except Exception as e:
        print(f"FAIL: {e}", file=sys.stderr)
        raise
