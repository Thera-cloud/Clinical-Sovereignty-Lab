#!/usr/bin/env python3
"""Sync outdated platform consent versions — column + profile_data only.

Does NOT touch: sensitive_bridge_enrollment, gap_features, master switch,
subscription_status, or coach_sensitive_bridge fields.

Run on GREEN:
  docker compose -f docker-compose.prod.yml exec -T backend \\
    python /app/scripts/consent_outdated_resync.py --dry-run
  docker compose -f docker-compose.prod.yml exec -T backend \\
    python /app/scripts/consent_outdated_resync.py

After live run, restart bridge so registry cache reloads from PG.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os

import asyncpg

REQUIRED = "v13.0_2026"
SCRIPT_TAG = "consent_outdated_resync"
PILOT_FIVE = (
    "LetsGoLisa",
    "magicguy72",
    "lanasmith",
    "hennons31",
    "longra",
)


def _database_url() -> str:
    url = os.getenv("DATABASE_URL", "")
    if url:
        return url
    host = os.getenv("POSTGRES_HOST", "postgres")
    port = os.getenv("POSTGRES_PORT", "5432")
    user = os.getenv("POSTGRES_USER", "nate_admin")
    password = os.getenv("POSTGRES_PASSWORD", "")
    db = os.getenv("POSTGRES_DB", "little_nate")
    return f"postgresql://{user}:{password}@{host}:{port}/{db}"


async def _enrollment_snapshot(conn) -> dict:
    rows = await conn.fetch(
        """
        SELECT user_id, cohort_label,
               (SELECT count(*)::int FROM jsonb_each(e.gap_features_enabled)) AS flag_count
          FROM sensitive_bridge_enrollment e
         ORDER BY user_id
        """
    )
    master = await conn.fetchval(
        "SELECT setting_value::text FROM app_settings "
        "WHERE setting_key = 'sensitive_bridge_master_enabled'"
    )
    return {
        "master_enabled": master,
        "enrollment_count": len(rows),
        "enrollments": [dict(r) for r in rows],
    }


async def _consent_audit(conn) -> list[dict]:
    return [
        dict(r)
        for r in await conn.fetch(
            """
            SELECT username, role,
                   COALESCE(consent_version, '') AS col_consent,
                   COALESCE(profile_data->>'consent_version', '') AS pd_consent,
                   (COALESCE(consent_version, '') = $1
                    AND COALESCE(profile_data->>'consent_version', '') = $1) AS fully_current,
                   (COALESCE(consent_version, '') <> COALESCE(profile_data->>'consent_version', '')) AS mismatched
              FROM users
             WHERE role IN ('CLIENT', 'COACH')
             ORDER BY username
            """,
            REQUIRED,
        )
    ]


async def run(*, dry_run: bool) -> int:
    pool = await asyncpg.create_pool(_database_url(), min_size=1, max_size=2)
    try:
        async with pool.acquire() as conn:
            before_enroll = await _enrollment_snapshot(conn)
            audit = await _consent_audit(conn)
            outdated = [a for a in audit if not a["fully_current"]]
            mismatched = [a for a in audit if a["mismatched"]]

            print("required_consent:", REQUIRED)
            print("clients_coaches:", len(audit))
            print("outdated_or_mismatch:", len(outdated))
            print("mismatched_only:", len(mismatched))
            print("enrollments_before:", before_enroll["enrollment_count"])
            print("master_before:", before_enroll["master_enabled"])

            for u in outdated:
                print(
                    f"  {u['username']} ({u['role']}): "
                    f"col={u['col_consent'] or '(empty)'} "
                    f"pd={u['pd_consent'] or '(empty)'} "
                    f"mismatch={u['mismatched']}"
                )

            if dry_run:
                print("DRY-RUN: no writes")
                return 0

            async with conn.transaction():
                # Column is bridge source of truth. If column says current but JSONB
                # is stale, downgrade column to JSONB so ReConsentScreen fires.
                downgraded = await conn.fetch(
                    """
                    UPDATE users u
                       SET consent_version = COALESCE(NULLIF(u.profile_data->>'consent_version', ''), 'v0.0'),
                           profile_data = jsonb_set(
                               jsonb_set(
                                   COALESCE(u.profile_data, '{}'::jsonb),
                                   '{consent_version}',
                                   to_jsonb(COALESCE(NULLIF(u.profile_data->>'consent_version', ''), 'v0.0')::text),
                                   true
                               ),
                               '{consent_resync_at}',
                               to_jsonb(NOW()::text),
                               true
                           )
                     WHERE u.role IN ('CLIENT', 'COACH')
                       AND COALESCE(u.consent_version, '') = $1
                       AND COALESCE(u.profile_data->>'consent_version', '') NOT IN ('', $1)
                    RETURNING u.username, u.consent_version AS new_col
                    """,
                    REQUIRED,
                )
                print("downgraded_column_to_stale_jsonb:", len(downgraded))
                for r in downgraded:
                    print(f"  {r['username']} -> {r['new_col']}")

                # Sync JSONB to column when column is already outdated (no version change).
                synced = await conn.fetch(
                    """
                    UPDATE users u
                       SET profile_data = jsonb_set(
                               COALESCE(u.profile_data, '{}'::jsonb),
                               '{consent_version}',
                               to_jsonb(COALESCE(u.consent_version, 'v0.0')::text),
                               true
                           )
                     WHERE u.role IN ('CLIENT', 'COACH')
                       AND COALESCE(u.consent_version, '') <> $1
                       AND COALESCE(u.profile_data->>'consent_version', '') IS DISTINCT FROM COALESCE(u.consent_version, 'v0.0')
                    RETURNING u.username, u.consent_version AS col
                    """,
                    REQUIRED,
                )
                print("synced_jsonb_to_outdated_column:", len(synced))
                for r in synced:
                    print(f"  {r['username']} col={r['col']}")

                # Empty/null column but JSONB has value — promote JSONB to column then sync.
                promoted = await conn.fetch(
                    """
                    UPDATE users u
                       SET consent_version = COALESCE(NULLIF(u.profile_data->>'consent_version', ''), 'v0.0')
                     WHERE u.role IN ('CLIENT', 'COACH')
                       AND COALESCE(u.consent_version, '') = ''
                       AND COALESCE(u.profile_data->>'consent_version', '') <> ''
                    RETURNING u.username, u.consent_version AS col
                    """,
                )
                print("promoted_empty_column_from_jsonb:", len(promoted))

            after_audit = await _consent_audit(conn)
            still_outdated = [a for a in after_audit if not a["fully_current"]]
            still_mismatch = [a for a in after_audit if a["mismatched"]]
            after_enroll = await _enrollment_snapshot(conn)

            print("still_outdated (will see ReConsent on login):", len(still_outdated))
            print("still_mismatched:", len(still_mismatch))
            print("enrollments_after:", after_enroll["enrollment_count"])
            print("master_after:", after_enroll["master_enabled"])

            if before_enroll["enrollment_count"] != after_enroll["enrollment_count"]:
                print("ABORT: enrollment count changed")
                return 1
            if before_enroll["master_enabled"] != after_enroll["master_enabled"]:
                print("ABORT: master switch changed")
                return 1

            for username in PILOT_FIVE:
                before = next(
                    (e for e in before_enroll["enrollments"] if e["user_id"] == username),
                    None,
                )
                after = next(
                    (e for e in after_enroll["enrollments"] if e["user_id"] == username),
                    None,
                )
                if before != after:
                    print(f"ABORT: pilot enrollment changed for {username}")
                    print("  before:", before)
                    print("  after:", after)
                    return 1
                if after:
                    print(
                        f"pilot_ok {username}: cohort={after['cohort_label']} "
                        f"flags={after['flag_count']}"
                    )
                else:
                    print(f"pilot_warn {username}: not enrolled")

            if still_mismatch:
                print("WARN: remaining mismatches — manual review")
                return 1

            print("OK: consent resync complete; enrollments unchanged")
            print("NEXT: restart nate_bridge to reload registry cache")
            return 0
    finally:
        await pool.close()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    raise SystemExit(asyncio.run(run(dry_run=args.dry_run)))


if __name__ == "__main__":
    main()
