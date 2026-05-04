"""Backfill profile_data.family_role for users with family_id but missing role.

Default: dry-run (prints planned updates). Mutate only with --execute.

Run inside backend container so DATABASE_URL matches production:

  docker compose -f docker-compose.prod.yml exec -T backend \\
    python /app/scripts/backfill_family_role.py

  docker compose -f docker-compose.prod.yml exec -T backend \\
    python /app/scripts/backfill_family_role.py --execute
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from collections import defaultdict
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

_script_dir = os.path.dirname(os.path.abspath(__file__))
for _root in (os.path.abspath(os.path.join(_script_dir, "..")), "/app"):
    if _root not in sys.path and os.path.isdir(os.path.join(_root, "app")):
        sys.path.insert(0, _root)

from app.constants.tiers import normalize_tier, tier_rank  # noqa: E402

ACTIVE_STATUSES = frozenset(
    {"ACTIVE", "TRIAL_ACTIVE", "FAMILY_PLAN_ACTIVE", "GRACE_PERIOD"}
)


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "--execute",
        action="store_true",
        help="Write jsonb_set updates to users.profile_data (default: dry-run)",
    )
    return p.parse_args()


def _created_ts(val: Any) -> float:
    if val is None:
        return float("inf")
    if isinstance(val, datetime):
        return float(val.timestamp())
    if isinstance(val, str) and val.strip():
        try:
            return float(datetime.fromisoformat(val.replace("Z", "+00:00")).timestamp())
        except Exception:
            return float("inf")
    return float("inf")


def _pick_head(rows: List[dict]) -> Tuple[dict, List[dict]]:
    """Return (head_row, other_rows). Head = best payer tier; prefer subscription-active."""
    if not rows:
        raise ValueError("empty family")

    def score(r: dict) -> Tuple[int, int, float]:
        tr = tier_rank((r.get("tier") or r.get("plan") or ""))
        sub = (r.get("subscription_status") or "").upper()
        active_boost = 1 if sub in ACTIVE_STATUSES else 0
        ts = _created_ts(r.get("created_at"))
        return (tr, active_boost, -ts)

    sorted_r = sorted(rows, key=score, reverse=True)
    return sorted_r[0], sorted_r[1:]


async def _run(execute: bool) -> int:
    import asyncpg

    url = os.getenv("DATABASE_URL", "").strip()
    if not url:
        print("DATABASE_URL is not set", file=sys.stderr)
        return 1

    conn = await asyncpg.connect(url)
    try:
        rows = await conn.fetch(
            """
            SELECT username,
                   tier,
                   subscription_status,
                   COALESCE(profile_data->>'subscription_plan','') AS plan,
                   COALESCE(profile_data->>'family_id','') AS family_id,
                   NULLIF(trim(profile_data->>'family_role'),'') AS family_role,
                   profile_data AS profile_data,
                   created_at
            FROM users
            WHERE COALESCE(profile_data->>'family_id','') <> ''
              AND (
                    profile_data->>'family_role' IS NULL
                 OR trim(profile_data->>'family_role') = ''
                  )
              AND role = 'CLIENT'
            ORDER BY username
            """
        )
    finally:
        await conn.close()

    by_fid: Dict[str, List[dict]] = defaultdict(list)
    for r in rows:
        fid = r["family_id"].strip()
        if not fid:
            continue
        by_fid[fid].append(
            {
                "username": r["username"],
                "tier": r["tier"],
                "plan": r["plan"],
                "subscription_status": r["subscription_status"],
                "created_at": r["created_at"],
                "family_role": r["family_role"],
                "profile_data": r["profile_data"],
            }
        )

    updates: List[Tuple[str, str, dict]] = []
    anomalies: List[str] = []
    families = 0

    for fid, members in sorted(by_fid.items(), key=lambda x: x[0]):
        families += 1
        payer_tiers = [tier_rank(normalize_tier(m["tier"] or m["plan"] or "")) for m in members]
        tops = sum(1 for pt in payer_tiers if pt >= tier_rank("TOP_TIER"))
        if tops > 1:
            anomalies.append(f"family_id={fid}: multiple TOP_TIER-like payers in needs-backfill set ({tops})")

        head, others = _pick_head(members)
        if tier_rank(normalize_tier(head["tier"] or head["plan"] or "")) < tier_rank("STANDARD"):
            anomalies.append(f"family_id={fid}: selected head payer rank < STANDARD ({head['username']})")

        updates.append((head["username"], "HEAD", head))
        for o in others:
            updates.append((o["username"], "MEMBER", o))

    print(json.dumps({"families": families, "users_to_touch": len(updates), "anomalies": anomalies}, indent=2))

    for un, role, rec in updates[:500]:
        print(f"plan: {role:6} username={un} fid={(rec.get('profile_data') or {}).get('family_id')}")

    if len(updates) > 500:
        print(f"... truncated listing ({len(updates) - 500} more)", file=sys.stderr)

    if not execute:
        print("[dry-run] no database writes — pass --execute to apply.")
        return 0

    conn = await asyncpg.connect(url)
    try:
        ucount = 0
        async with conn.transaction():
            for username, role, rec in updates:
                pd = rec["profile_data"]
                if isinstance(pd, str):
                    try:
                        pd = json.loads(pd)
                    except Exception:
                        pd = {}
                if not isinstance(pd, dict):
                    pd = {}
                pd = dict(pd)
                pd["family_role"] = role
                await conn.execute(
                    "UPDATE users SET profile_data = $1::jsonb WHERE username = $2",
                    pd,
                    username,
                )
                ucount += 1
        print(f"[execute] updated {ucount} user rows.")
    finally:
        await conn.close()

    print("Restart nate_bridge after execute so registry picks up profile_data.")
    return 0


def main() -> None:
    args = _parse_args()
    raise SystemExit(asyncio.run(_run(args.execute)))


if __name__ == "__main__":
    main()
