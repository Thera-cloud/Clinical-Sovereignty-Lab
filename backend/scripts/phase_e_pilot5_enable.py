#!/usr/bin/env python3
"""Phase E: pilot_5 cohort + full activation for 5 clients + master switch ON.

Run on GREEN inside backend container (has DATABASE_URL):
  docker compose -f docker-compose.prod.yml exec -T backend \\
    python /app/scripts/phase_e_pilot5_enable.py

Dry-run (no writes):
  ... python /app/scripts/phase_e_pilot5_enable.py --dry-run
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os

import asyncpg

# Inline SSOT (migration 220 / FULL_ACTIVATION_GAP_FEATURES) — no app import needed in container.
FULL_ACTIVATION_GAP_FEATURES = {
    "gap_introjection_enabled": True,
    "gap_thalamic_gate_enabled": True,
    "gap_reengagement_enabled": True,
    "gap_arousal_cap_enabled": True,
    "gap_polyvictim_load_enabled": True,
    "gap_dual_diagnosis_enabled": True,
    "gap_active_disclosure_enabled": True,
    "gap_codeword_enabled": True,
    "gap_trigger_dates_enabled": True,
    "gap_legal_status_enabled": True,
    "gap_embodiment_phase_enabled": True,
    "gap_jurisdiction_compliance_enabled": True,
    "gap_minor_survivor_protections_enabled": True,
    "gap_parenting_no_pathologization_enabled": True,
    "gap_rj_companioning_enabled": True,
    "gap_cultural_context_enabled": True,
    "v1_4_codeword_listener_enabled": True,
    "v1_4_addiction_branches_enabled": True,
    "v1_4_cross_addiction_overlay_enabled": True,
    "v1_4_dst_lens_enabled": True,
    "v1_4_framework_lens_enabled": True,
    "v1_4_crystal_factory_enabled": True,
    "v1_4_alert_dispatch_enabled": True,
}

PILOT_USERNAMES = (
    "LetsGoLisa",   # Lisa West
    "magicguy72",   # Magicguy72
    "lanasmith",    # Lana Smith
    "hennons31",    # Marcus Hennon
    "longra",       # Ryan Long
)

OPERATOR = "DrNevedal1"
SCRIPT_TAG = "phase_e_pilot5_enable"


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


async def _verify_users(conn, usernames: tuple[str, ...]) -> list[str]:
    missing = []
    for u in usernames:
        row = await conn.fetchval("SELECT 1 FROM users WHERE username = $1", u)
        if not row:
            missing.append(u)
    return missing


async def run(*, dry_run: bool) -> int:
    gap_json = json.dumps(FULL_ACTIVATION_GAP_FEATURES)
    pool = await asyncpg.create_pool(_database_url(), min_size=1, max_size=2)
    try:
        async with pool.acquire() as conn:
            missing = await _verify_users(conn, PILOT_USERNAMES)
            if missing:
                print("ABORT: users not found:", ", ".join(missing))
                return 1

            master_before = await conn.fetchval(
                "SELECT setting_value FROM app_settings "
                "WHERE setting_key = 'sensitive_bridge_master_enabled'"
            )
            print("master_before:", master_before)

            enrollments = await conn.fetch(
                "SELECT user_id, cohort_label, gap_features_enabled "
                "FROM sensitive_bridge_enrollment ORDER BY user_id"
            )
            print("enrollments_before:", len(enrollments), "rows")
            for r in enrollments:
                flags = r["gap_features_enabled"]
                if isinstance(flags, str):
                    flags = json.loads(flags)
                nflags = len(flags) if isinstance(flags, dict) else 0
                print(f"  {r['user_id']}: cohort={r['cohort_label']} flags={nflags}")

            if dry_run:
                print("DRY-RUN: no writes")
                return 0

            async with conn.transaction():
                blanked = await conn.fetch(
                    """
                    UPDATE sensitive_bridge_enrollment e
                       SET gap_features_enabled = '{}'::jsonb,
                           last_modified_at = NOW(),
                           last_modified_by = $1
                     WHERE cohort_label IS DISTINCT FROM 'pilot_5'
                       AND gap_features_enabled IS NOT NULL
                       AND gap_features_enabled <> '{}'::jsonb
                    RETURNING e.user_id, e.cohort_label
                    """,
                    SCRIPT_TAG,
                )
                for row in blanked:
                    await conn.execute(
                        """
                        INSERT INTO sensitive_bridge_log (
                            user_id, event_type, event_severity, payload_json,
                            decision_summary, occurred_at, recorded_by,
                            access_classification, pii_screened_at, redaction_pass_count
                        ) VALUES (
                            $1, 'sensitive_profile_mutation', 'low', $2::jsonb,
                            $3::jsonb, NOW(), $4, 'clinician_and_admin', NOW(), 1
                        )
                        """,
                        row["user_id"],
                        json.dumps({
                            "mutation_kind": "gap_features_blanked",
                            "phase": "E",
                            "prior_cohort": row["cohort_label"],
                        }),
                        json.dumps({"contract_version": SCRIPT_TAG}),
                        SCRIPT_TAG,
                    )
                print("blanked_non_pilot:", len(blanked))

                for username in PILOT_USERNAMES:
                    existed = await conn.fetchval(
                        "SELECT 1 FROM sensitive_bridge_enrollment WHERE user_id = $1",
                        username,
                    )
                    await conn.execute(
                        """
                        INSERT INTO sensitive_bridge_enrollment (
                            user_id, cohort_label, gap_features_enabled,
                            enrolled_by, notes, last_modified_at, last_modified_by
                        ) VALUES ($1, 'pilot_5', $2::jsonb, $3, $4, NOW(), $5)
                        ON CONFLICT (user_id) DO UPDATE SET
                            cohort_label = 'pilot_5',
                            gap_features_enabled = EXCLUDED.gap_features_enabled,
                            last_modified_at = NOW(),
                            last_modified_by = EXCLUDED.last_modified_by,
                            notes = COALESCE(sensitive_bridge_enrollment.notes, '')
                                || ' | ' || EXCLUDED.notes
                        """,
                        username,
                        gap_json,
                        OPERATOR,
                        "Phase E pilot_5 — full activation",
                        SCRIPT_TAG,
                    )
                    evt = "enrollment_created" if not existed else "enrollment_backfilled_to_full_activation"
                    await conn.execute(
                        """
                        INSERT INTO sensitive_bridge_log (
                            user_id, event_type, event_severity, payload_json,
                            decision_summary, occurred_at, recorded_by,
                            access_classification, pii_screened_at, redaction_pass_count
                        ) VALUES (
                            $1, $2, 'moderate', $3::jsonb, $4::jsonb, NOW(), $5,
                            'clinician_and_admin', NOW(), 1
                        )
                        """,
                        username,
                        evt,
                        json.dumps({
                            "phase": "E",
                            "cohort_label": "pilot_5",
                            "gap_features": "full_activation",
                        }),
                        json.dumps({"contract_version": SCRIPT_TAG}),
                        SCRIPT_TAG,
                    )

                await conn.execute(
                    """
                    UPDATE app_settings
                       SET setting_value = 'true'::jsonb,
                           updated_at = NOW(),
                           updated_by = $1
                     WHERE setting_key = 'sensitive_bridge_master_enabled'
                    """,
                    OPERATOR,
                )
                await conn.execute(
                    """
                    INSERT INTO sensitive_bridge_log (
                        user_id, event_type, event_severity, payload_json,
                        decision_summary, occurred_at, recorded_by,
                        access_classification, pii_screened_at, redaction_pass_count
                    ) VALUES (
                        'system', 'feature_flags_initialized', 'info', $1::jsonb,
                        $2::jsonb, NOW(), $3, 'admin_only_redacted', NOW(), 1
                    )
                    """,
                    json.dumps({
                        "phase": "E",
                        "action": "master_switch_enabled",
                        "pilot_usernames": list(PILOT_USERNAMES),
                        "observation_window_hours": 24,
                    }),
                    json.dumps({"contract_version": SCRIPT_TAG}),
                    OPERATOR,
                )

            master_after = await conn.fetchval(
                "SELECT setting_value FROM app_settings "
                "WHERE setting_key = 'sensitive_bridge_master_enabled'"
            )
            print("master_after:", master_after)
            for username in PILOT_USERNAMES:
                row = await conn.fetchrow(
                    "SELECT cohort_label, gap_features_enabled "
                    "FROM sensitive_bridge_enrollment WHERE user_id = $1",
                    username,
                )
                flags = row["gap_features_enabled"]
                if isinstance(flags, str):
                    flags = json.loads(flags)
                nflags = len(flags) if isinstance(flags, dict) else 0
                print(f"  {username}: cohort={row['cohort_label']} flags={nflags}")
            print("OK: Phase E pilot_5 + master ON")
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
