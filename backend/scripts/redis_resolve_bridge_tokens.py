#!/usr/bin/env python3
"""Resolve bridge auth tokens from Redis by exact username + role (not substring grep).

Run inside the backend container (has REDIS_URL + ENVIRONMENT):

  docker exec nate_backend python3 /app/scripts/redis_resolve_bridge_tokens.py \\
    --username CoachN --role COACH

Optional: --list-all (every matching session, sorted by last_login desc).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

try:
    import redis
except ImportError:
    print("redis package required", file=sys.stderr)
    sys.exit(2)


def _parse_last_login(raw: Dict[str, Any]) -> Optional[datetime]:
    prof = raw.get("profile") or raw.get("profile_data") or {}
    if isinstance(prof, str):
        try:
            prof = json.loads(prof)
        except Exception:
            prof = {}
    if not isinstance(prof, dict):
        return None
    ll = prof.get("last_login")
    if not ll or not isinstance(ll, str):
        return None
    for fmt in (
        "%Y-%m-%d %H:%M:%S.%f",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%dT%H:%M:%S.%f",
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%dT%H:%M:%S.%f%z",
    ):
        try:
            return datetime.strptime(ll.replace("+00:00", ""), fmt.replace("%z", ""))
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(ll.replace("Z", "+00:00"))
    except ValueError:
        return None


def _scan_matches(
    r: redis.Redis,
    env: str,
    want_user: str,
    want_role: str,
) -> List[Tuple[str, str, Optional[datetime]]]:
    """Return list of (token, username, last_login_dt)."""
    prefix = f"nate:{env}:auth:"
    pattern = f"{prefix}*"
    want_role_u = want_role.strip().upper()
    want_user = want_user.strip()
    out: List[Tuple[str, str, Optional[datetime]]] = []
    for key in r.scan_iter(match=pattern):
        tok = key.split(":")[-1]
        raw_b = r.get(key)
        if not raw_b:
            continue
        try:
            raw = json.loads(raw_b)
        except Exception:
            continue
        un = (raw.get("username") or "").strip()
        role = (raw.get("role") or "").strip().upper()
        if un != want_user or role != want_role_u:
            continue
        out.append((tok, un, _parse_last_login(raw)))
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="Resolve Little Nate bridge Redis tokens.")
    ap.add_argument("--username", required=True, help="Exact username on the session blob")
    ap.add_argument("--role", required=True, help="Exact role, e.g. COACH or ADMIN")
    ap.add_argument(
        "--environment",
        default=os.getenv("ENVIRONMENT", "production"),
        help="Redis key namespace (default: $ENVIRONMENT or production)",
    )
    ap.add_argument(
        "--list-all",
        action="store_true",
        help="Print every matching session (not only the preferred one)",
    )
    ap.add_argument("--json", action="store_true", help="Emit JSON lines")
    args = ap.parse_args()

    url = os.getenv("REDIS_URL")
    if not url:
        print("REDIS_URL is not set", file=sys.stderr)
        return 2

    client = redis.from_url(url, decode_responses=True)
    matches = _scan_matches(client, args.environment, args.username, args.role)
    if not matches:
        print(
            f"No session for username={args.username!r} role={args.role!r} "
            f"under nate:{args.environment}:auth:*",
            file=sys.stderr,
        )
        return 1

    def sort_key(row: Tuple[str, str, Optional[datetime]]) -> Tuple[int, str]:
        _, _, ll = row
        ts = int(ll.timestamp()) if ll else 0
        return (ts, row[0])

    matches.sort(key=sort_key, reverse=True)

    if args.list_all:
        rows = matches
    else:
        rows = [matches[0]]

    if args.json:
        for tok, un, ll in rows:
            print(
                json.dumps(
                    {
                        "username": un,
                        "role": args.role.strip().upper(),
                        "token": tok,
                        "last_login": ll.isoformat() if ll else None,
                    }
                )
            )
        return 0

    var = f"{args.username.upper().replace('-', '_')}_TOKEN"
    for tok, _, ll in rows:
        suffix = f" # last_login={ll}" if ll else ""
        print(f"{var}={tok}{suffix}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
