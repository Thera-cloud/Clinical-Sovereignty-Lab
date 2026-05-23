#!/usr/bin/env python3
"""
Phase 1 backfill: stamp parent_username + UUID guardian fields on family members.

Dry-run by default. Use --execute to write.

  cd backend && python scripts/backfill_family_linkage_phase1.py
  cd backend && python scripts/backfill_family_linkage_phase1.py --execute
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import asyncpg

from app.services.family_linkage import enrich_family_profile, extract_family_columns


SELECT_SQL = """
SELECT id, username, profile_data, family_id, guardian_id, linked_by, family_role, is_minor
FROM users
WHERE deleted_at IS NULL
  AND family_id IS NOT NULL
  AND COALESCE(
        NULLIF(family_role, ''),
        LOWER(profile_data->>'family_role'),
        ''
      ) NOT IN ('head', 'head_of_household')
  AND (
        COALESCE(profile_data->>'parent_username', '') = ''
        OR guardian_id IS NULL
        OR linked_by IS NULL
        OR profile_data->>'guardian_id' LIKE '%\\_ID'
      )
ORDER BY username
"""


def _parse_profile(raw):
    if isinstance(raw, dict):
        return dict(raw)
    if isinstance(raw, str) and raw:
        try:
            return json.loads(raw)
        except Exception:
            return {}
    return {}


async def run(execute: bool) -> int:
    dsn = os.getenv("DATABASE_URL")
    if not dsn:
        print("DATABASE_URL not set")
        return 1

    pool = await asyncpg.create_pool(dsn, min_size=1, max_size=2)
    updated = 0
    try:
        async with pool.acquire() as conn:
            rows = await conn.fetch(SELECT_SQL)
            print(f"Candidates: {len(rows)}")
            for row in rows:
                profile = _parse_profile(row["profile_data"])
                profile["family_role"] = (
                    profile.get("family_role") or row["family_role"] or ""
                )
                if profile.get("is_minor") is None:
                    profile["is_minor"] = row["is_minor"]
                enriched = await enrich_family_profile(
                    conn,
                    profile=profile,
                    parent_username=profile.get("parent_username") or None,
                    family_role=profile.get("family_role") or None,
                )
                cols = extract_family_columns(enriched)
                if not enriched.get("parent_username") and not cols["guardian_id"]:
                    print(f"  SKIP {row['username']}: could not resolve HoH")
                    continue
                print(
                    f"  {'WRITE' if execute else 'DRY'} {row['username']}: "
                    f"parent={enriched.get('parent_username')} "
                    f"guardian={cols['guardian_id']}"
                )
                if execute:
                    await conn.execute(
                        """
                        UPDATE users SET
                            profile_data = $1::jsonb,
                            guardian_id = COALESCE($2::uuid, guardian_id),
                            linked_by = COALESCE($3::uuid, linked_by),
                            family_role = COALESCE($4, family_role),
                            is_minor = CASE WHEN $5 THEN TRUE ELSE is_minor END,
                            updated_at = NOW()
                        WHERE id = $6
                        """,
                        json.dumps(enriched, default=str),
                        cols["guardian_id"],
                        cols["linked_by"],
                        cols["family_role"],
                        cols["is_minor"],
                        row["id"],
                    )
                updated += 1
    finally:
        await pool.close()

    print(f"{'Updated' if execute else 'Would update'}: {updated}")
    return 0


def main():
    parser = argparse.ArgumentParser(description="Phase 1 family linkage backfill")
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Apply updates (default is dry-run)",
    )
    args = parser.parse_args()
    raise SystemExit(asyncio.run(run(execute=args.execute)))


if __name__ == "__main__":
    main()
