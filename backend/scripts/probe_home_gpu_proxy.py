#!/usr/bin/env python3
"""Probe Twin mac-agent Ollama proxy from GREEN (no token printed)."""
from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request
from pathlib import Path


def _token_from_env(path: str = "/opt/clinical-sovereignty-lab/.env") -> str:
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        if line.startswith("MAC_AGENT_TOKEN="):
            return line.split("=", 1)[1].strip().strip("\"'")
    return ""


def main() -> int:
    base = (
        sys.argv[1]
        if len(sys.argv) > 1
        else "https://twin-agent.sovereignsanctuary.net/ollama"
    ).rstrip("/")
    tok = _token_from_env()
    if not tok:
        print("missing_mac_agent_token")
        return 2
    url = f"{base}/v1/models"
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {tok}"})
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            data = json.load(resp)
            ids = [
                (m.get("id") or m.get("name"))
                for m in data.get("data", data.get("models", []))
            ]
            print(json.dumps({"ok": True, "status": resp.status, "models": ids[:12]}))
            return 0
    except urllib.error.HTTPError as exc:
        print(json.dumps({"ok": False, "status": exc.code, "error": str(exc.reason)[:120]}))
        return 1
    except Exception as exc:
        print(json.dumps({"ok": False, "error": f"{type(exc).__name__}:{str(exc)[:160]}"}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
