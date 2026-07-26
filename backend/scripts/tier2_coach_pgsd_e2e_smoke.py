#!/usr/bin/env python3
"""
Coach PGSD REST E2E smoke (flags + tier2/latest + optional client).  # QUANTUM-CRYSTAL-ARCH

  export SKYEYE_AUDIT_TOKEN=...
  python backend/scripts/tier2_coach_pgsd_e2e_smoke.py
  python backend/scripts/tier2_coach_pgsd_e2e_smoke.py CLIENT_LETSGOLISA_ID
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request


def _get(url: str, token: str) -> tuple:
    req = urllib.request.Request(
        url,
        headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            body = resp.read().decode("utf-8", errors="replace")
            return resp.status, body
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", errors="replace")
    except Exception as e:
        return 0, str(e)


def main() -> int:
    base = os.environ.get("API_BASE", "http://127.0.0.1:8000").rstrip("/")
    token = (os.environ.get("SKYEYE_AUDIT_TOKEN") or "").strip()
    if not token:
        print("FAIL: SKYEYE_AUDIT_TOKEN unset")
        return 2
    client = (sys.argv[1] if len(sys.argv) > 1 else "").strip()
    fails = []

    code, body = _get(f"{base}/api/coach/pgsd/flags", token)
    print(f"flags HTTP {code}")
    if code != 200:
        fails.append(f"flags->{code}")
    else:
        try:
            data = json.loads(body)
            print(json.dumps(data, indent=2)[:800])
            if data.get("status") != "ok":
                fails.append("flags.status!=ok")
        except Exception as e:
            fails.append(f"flags.json:{e}")

    code, body = _get(f"{base}/api/coach/pgsd/tier2/latest", token)
    print(f"tier2/latest HTTP {code}")
    if code != 200:
        fails.append(f"tier2/latest->{code}")
    else:
        try:
            data = json.loads(body)
            print(json.dumps({"status": data.get("status"), "packs": len(data.get("packs") or [])}, indent=2))
        except Exception as e:
            fails.append(f"tier2.json:{e}")

    if client:
        code, body = _get(f"{base}/api/coach/pgsd/client/{client}", token)
        print(f"client/{client} HTTP {code}")
        if code not in (200, 404):
            fails.append(f"client->{code}")

    if fails:
        print("E2E: RED " + "; ".join(fails))
        return 1
    print("E2E: GREEN — coach PGSD REST smoke ok")
    return 0


if __name__ == "__main__":
    sys.exit(main())
