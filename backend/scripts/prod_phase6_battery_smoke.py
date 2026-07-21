#!/usr/bin/env python3
"""QUANTUM-CRYSTAL-ARCH: Phase 6 pre/post-flip battery smoke (GREEN host).

Checks (read-mostly; dry_run only unless PROD_6_LIVE_WS=1):
  - ENABLE_SIX_QUOTIENT_BATTERY / LIVE_WS / TEST_PASSWORD env on backend
  - Runner has websockets try/finally (not broken async-with)
  - GET /api/admin/six-quotient/health (tables + bank)
  - POST trigger dry_run=true limit=1 persist=false
  - Optional: CEO inbox peek for six_quotient_* items (staging or after scores)

Usage on GREEN:
  python3 backend/scripts/prod_phase6_battery_smoke.py
  PROD_6_API=http://127.0.0.1:8011 python3 backend/scripts/prod_phase6_battery_smoke.py  # staging
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import urllib.error
import urllib.request

API = os.getenv("PROD_6_API", "http://127.0.0.1:8000").rstrip("/")
TOKEN = os.getenv("SKYEYE_AUDIT_TOKEN") or os.getenv("PROD_6_TOKEN", "")


def _token() -> str:
    if TOKEN.strip():
        return TOKEN.strip()
    try:
        out = subprocess.check_output(
            ["bash", "-c", 'grep ^SKYEYE_AUDIT_TOKEN= /opt/clinical-sovereignty-lab/.env | cut -d= -f2-'],
            text=True,
            timeout=10,
        ).strip().strip("'\"")
        return out
    except Exception as e:
        print(f"FAIL: no SKYEYE_AUDIT_TOKEN ({e})", file=sys.stderr)
        sys.exit(2)


def _req(method: str, path: str, body: dict | None = None) -> tuple[int, dict]:
    data = None if body is None else json.dumps(body).encode()
    req = urllib.request.Request(
        f"{API}{path}",
        data=data,
        method=method,
        headers={
            "Authorization": f"Bearer {_token()}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            raw = resp.read().decode()
            return resp.status, (json.loads(raw) if raw else {})
    except urllib.error.HTTPError as e:
        raw = e.read().decode() if e.fp else ""
        try:
            return e.code, json.loads(raw) if raw else {"detail": str(e)}
        except Exception:
            return e.code, {"detail": raw or str(e)}


def _backend_env(key: str) -> str:
    try:
        return subprocess.check_output(
            ["docker", "exec", "nate_backend", "printenv", key],
            text=True,
            timeout=15,
        ).strip()
    except Exception:
        return ""


def _runner_ok() -> bool:
    path = "/opt/clinical-sovereignty-lab/backend/scripts/six_quotient_battery_runner.py"
    try:
        text = open(path, encoding="utf-8").read()
    except OSError:
        try:
            text = open("backend/scripts/six_quotient_battery_runner.py", encoding="utf-8").read()
        except OSError:
            return False
    return "async context manager" in text or "await ws.close()" in text


def main() -> int:
    fails = []
    print(f"[*] API={API}")

    batt = _backend_env("ENABLE_SIX_QUOTIENT_BATTERY")
    live = _backend_env("SIX_QUOTIENT_BATTERY_LIVE_WS")
    pwd = _backend_env("TEST_PASSWORD") or _backend_env("AUDIT_CLIENT_PASSWORD")
    print(f"[*] ENABLE_SIX_QUOTIENT_BATTERY={batt!r}")
    print(f"[*] SIX_QUOTIENT_BATTERY_LIVE_WS={live!r}")
    print(f"[*] TEST/AUDIT password set={'yes' if pwd else 'no'}")

    if not _runner_ok():
        fails.append("battery_runner missing websockets try/finally fix (pull 04073d99+)")
    else:
        print("[*] runner: try/finally present")

    if live.lower() in ("1", "true", "yes", "on") and not pwd:
        fails.append("LIVE_WS true but TEST_PASSWORD/AUDIT_CLIENT_PASSWORD empty")

    code, health = _req("GET", "/api/admin/six-quotient/health")
    print(f"[*] health HTTP {code}: {json.dumps(health)[:300]}")
    if code != 200 or not health.get("tables_ok"):
        fails.append(f"health failed: {code} {health}")
    bank = int(health.get("bank_approved") or 0)
    if bank < 1:
        fails.append(f"bank_approved={bank} (need approved scenarios)")

    code, trig = _req(
        "POST",
        "/api/admin/six-quotient/trigger",
        {
            "dry_run": True,
            "limit": 1,
            "environment": os.getenv("PROD_6_ENV", "production"),
            "persist": False,
            "multi_turn": False,
        },
    )
    print(f"[*] dry_run trigger HTTP {code}: {json.dumps(trig)[:400]}")
    result = (trig or {}).get("result") or {}
    if code != 200 or not result.get("ok"):
        fails.append(f"dry_run trigger failed: {code} {trig}")

    # CEO inbox (shared Redis) — informational
    code, inbox = _req("GET", "/api/ceo/inbox?limit=5")
    if code == 200:
        items = inbox.get("items") or []
        sq = [i for i in items if "Six-Quotient" in str(i.get("title", ""))]
        print(f"[*] ceo inbox: {len(items)} top, {len(sq)} six-quotient titles in peek")
    else:
        print(f"[!] ceo inbox HTTP {code} (non-fatal)")

    # Growth / PHI evidence (informational — staging may have rows; prod may be 0 pre-flip)
    try:
        grow = subprocess.check_output(
            [
                "docker", "exec", "nate_postgres", "psql", "-U", "nate_admin", "-d", "little_nate",
                "-tAc",
                "SELECT COUNT(*) FROM nate_intelligence_crystals "
                "WHERE crystal_text ILIKE '%BATTERY-VALIDATED%' OR crystal_text ILIKE '%six_quotient%';",
            ],
            text=True,
            timeout=20,
        ).strip()
        print(f"[*] growth-ish crystals (ILIKE): {grow}")
    except Exception as e:
        print(f"[!] growth crystal count skipped: {e}")

    try:
        phi = subprocess.check_output(
            [
                "docker", "logs", "nate_backend", "--since", "48h",
            ],
            text=True,
            stderr=subprocess.STDOUT,
            timeout=30,
        )
        n = phi.count("graph_surfaced")
        print(f"[*] backend logs graph_surfaced mentions (48h): {n}")
    except Exception as e:
        print(f"[!] phi log peek skipped: {e}")

    if fails:
        print("FAIL:")
        for f in fails:
            print(f"  - {f}")
        return 1
    print("OK: phase6 battery smoke passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
