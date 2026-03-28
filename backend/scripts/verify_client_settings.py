#!/usr/bin/env python3
"""
Verify client portal settings REST + WebSocket (SettingsTabAuditor parity).

One-shot (password only — same as LoginAuditor / ws_flow_auditor test account):
  python3 backend/scripts/verify_client_settings.py \\
    --base-url https://api.sovereignsanctuary.net \\
    --ws-url wss://api.sovereignsanctuary.net/ws \\
    --password 'AuditClient2026!'

Or: export AUDIT_CLIENT_PASSWORD='AuditClient2026!'

With existing bridge token (skip WS login):
  python3 backend/scripts/verify_client_settings.py --base-url ... --token '<token>' --skip-ws
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import urllib.error
import urllib.request
import ssl

TRUSTED = frozenset({200, 400, 404, 422})
DEFAULT_AUDIT_PASSWORD = "AuditClient2026!"  # matches login_auditor / ws_flow_auditor


def http_get(url: str, token: str, timeout: int = 25) -> tuple[int, str]:
    req = urllib.request.Request(
        url,
        headers={
            "Authorization": f"Bearer {token}",
            "User-Agent": "Mozilla/5.0 (compatible; CSL-SettingsVerify/1.0)",
        },
    )
    ctx = ssl.create_default_context()
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=ctx) as r:
            return r.status, r.read(8000).decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        body = e.read(4000).decode("utf-8", errors="replace") if e.fp else ""
        return e.code, body[:500]
    except Exception as e:
        return 0, str(e)[:200]


def rest_verify(base: str, token: str, user: str, hw: str) -> tuple[int, int]:
    endpoints = [
        ("Weekly Brief", f"{base}/api/research/nevedal/reports/brief"),
        ("Vault stats", f"{base}/api/v1/vault/stats?user_id={hw}"),
        ("Vault list", f"{base}/api/vault/list/{hw}"),
        ("Billing plans", f"{base}/api/billing/plans"),
        ("Subscription", f"{base}/api/billing/subscription/{hw}"),
        ("Data export", f"{base}/api/users/{user}/data-export"),
        ("Assessments available", f"{base}/api/assessments/available/{hw}"),
        ("Assessments history", f"{base}/api/assessments/history/{hw}"),
        ("AI modes", f"{base}/api/ai-modes/list"),
        ("Community attendance", f"{base}/api/community/attendance/{hw}"),
        ("Client health-check", f"{base}/api/client/health-check"),
        ("Family members", f"{base}/api/client/family/members/{hw}"),
    ]
    ok = bad = 0
    for name, url in endpoints:
        code, _ = http_get(url, token)
        st = "OK" if code in TRUSTED else "FAIL"
        if code in TRUSTED:
            ok += 1
        else:
            bad += 1
        print(f"  [{st}] {code:3d}  {name}")
        print(f"        {url}")
    return ok, bad


async def ws_login_and_checks(
    ws_url: str, user: str, password: str, hw_fallback: str
) -> tuple[str | None, str, int]:
    """Returns (token, hw_id, exit_code)."""
    try:
        import websockets
    except ImportError:
        print("pip install websockets")
        return None, hw_fallback, 2
    token = None
    hw = hw_fallback
    try:
        async with websockets.connect(ws_url, close_timeout=12) as ws:
            raw = await asyncio.wait_for(ws.recv(), timeout=10)
            d = json.loads(raw)
            if d.get("type") != "connected":
                print("WS FAIL: first frame not connected")
                return None, hw, 1
            await ws.send(
                json.dumps(
                    {
                        "type": "login_request",
                        "username": user,
                        "password": password,
                        "expected_role": "CLIENT",
                    }
                )
            )
            for _ in range(20):
                try:
                    raw = await asyncio.wait_for(ws.recv(), timeout=12)
                    d = json.loads(raw)
                    t = d.get("type")
                    if t == "login_success":
                        token = d.get("token")
                        prof = d.get("profile") or {}
                        hw = prof.get("hardware_id") or hw_fallback
                        break
                    if t == "login_failed":
                        print("WS FAIL: login_failed", d.get("message", d))
                        return None, hw, 1
                    if t == "accept_consent_update":
                        print("WS: consent required — complete in app once for audit_client")
                except asyncio.TimeoutError:
                    break
            if not token:
                print("WS FAIL: no login_success token")
                return None, hw, 1
            print("  [OK] WS login_success (token acquired)")
            # Backend resolves Bearer via Redis; bridge stores async — brief wait avoids 403 race
            await asyncio.sleep(2.5)

            await ws.send(json.dumps({"type": "get_coherence_report"}))
            cr_ok = False
            for _ in range(10):
                try:
                    raw = await asyncio.wait_for(ws.recv(), timeout=15)
                    d = json.loads(raw)
                    if d.get("type") == "coherence_report":
                        cr_ok = True
                        break
                    if d.get("type") == "coherence_report_error":
                        print("  [WARN] coherence_report_error:", d.get("error"))
                        break
                except asyncio.TimeoutError:
                    break
            print(f"  [{'OK' if cr_ok else 'FAIL'}] WS coherence_report")

            await ws.send(
                json.dumps({"type": "memory_search", "query": "test", "limit": 3})
            )
            ms_ok = False
            for _ in range(10):
                try:
                    raw = await asyncio.wait_for(ws.recv(), timeout=15)
                    d = json.loads(raw)
                    if d.get("type") == "memory_search_results":
                        ms_ok = True
                        break
                    if d.get("type") == "memory_search_error":
                        print("  [WARN] memory_search_error:", d.get("error"))
                        break
                except asyncio.TimeoutError:
                    break
            print(f"  [{'OK' if ms_ok else 'FAIL'}] WS memory_search_results")

    except Exception as e:
        print("WS error:", e)
        return None, hw, 1
    return token, hw, 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base-url", default="http://localhost:8000")
    ap.add_argument("--token", default="", help="Bearer token (optional if WS login)")
    ap.add_argument("--username", default="audit_client")
    ap.add_argument("--hw-id", default="audit_client_hw")
    ap.add_argument("--ws-url", default="", help="wss://host/ws (default: from --base-url)")
    ap.add_argument("--skip-ws", action="store_true", help="REST only; requires --token")
    ap.add_argument(
        "--password",
        default="",
        help="audit_client password (default from AUDIT_CLIENT_PASSWORD or AuditClient2026!)",
    )
    args = ap.parse_args()
    base = args.base_url.rstrip("/")
    user = args.username
    hw = args.hw_id
    pwd = (args.password or os.environ.get("AUDIT_CLIENT_PASSWORD") or DEFAULT_AUDIT_PASSWORD).strip()
    ws_url = args.ws_url.strip()
    if not ws_url and not args.skip_ws:
        ws_url = base.replace("https://", "wss://").replace("http://", "ws://") + "/ws"

    token = args.token.strip()

    print("=" * 60)
    print("CLIENT SETTINGS VERIFY (REST + WS)")
    print("=" * 60)

    if args.skip_ws:
        if not token:
            print("ERROR: --token required with --skip-ws")
            return 2
        print("REST only (--skip-ws)")
        ok, bad = rest_verify(base, token, user, hw)
        print("-" * 60)
        print(f"REST: {ok} trusted / {ok + bad} total")
        return 0 if bad == 0 else 1

    # Full run: WS login → REST with session token → WS checks already done inside async
    async def run():
        nonlocal token, hw
        t, h, rc = await ws_login_and_checks(ws_url, user, pwd, hw)
        if rc != 0 or not t:
            return 1
        token, hw = t, h
        print("-" * 60)
        print("CLIENT SETTINGS REST (Bearer from login)")
        print("-" * 60)
        ok, bad = rest_verify(base, token, user, hw)
        print("-" * 60)
        print(f"REST: {ok} trusted / {ok + bad} total")
        return 0 if bad == 0 else 1

    return asyncio.run(run())


if __name__ == "__main__":
    sys.exit(main())
