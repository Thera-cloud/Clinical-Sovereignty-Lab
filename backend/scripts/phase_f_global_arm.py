#!/usr/bin/env python3
"""Phase F: global arm — re-arm ALL enrolled users + set global gap flags.

Fixes the GA re-arming flaw found in the 2026-06-09 pre-GA review:
Phase E blanked gap_features_enabled ('{}') for every non-pilot enrollment.
Flipping the master switch global WITHOUT re-arming leaves those users
enrolled-but-dormant (pipeline runs, every feature gate evaluates false).

This script (NOT executed automatically — operator runs it at GA time):
  1. Re-arms every enrolled user's gap_features_enabled to full activation
     (pilot_5 rows are already armed; idempotent upsert covers both).
  2. Writes sensitive_bridge_global_gap_flags in app_settings so users
     enrolled AFTER GA inherit the global defaults.
  3. Ensures sensitive_bridge_master_enabled = true.
  4. Audit-logs every mutation to sensitive_bridge_log.

Run on GREEN inside backend container (has DATABASE_URL):
  docker compose -f docker-compose.prod.yml exec -T backend \\
    python /app/scripts/phase_f_global_arm.py --dry-run   # preview first
  docker compose -f docker-compose.prod.yml exec -T backend \\
    python /app/scripts/phase_f_global_arm.py             # execute
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os

import asyncpg

# Inline SSOT (migration 220 / FULL_ACTIVATION_GAP_FEATURES) — no app import needed.
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

OPERATOR = "DrNevedal1"
SCRIPT_TAG = "phase_f_global_arm"
COHORT_LABEL = "global"


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


def _nflags(raw) -> int:
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except Exception:
            return 0
    return len(raw) if isinstance(raw, dict) else 0


async def run(*, dry_run: bool) -> int:
    gap_json = json.dumps(FULL_ACTIVATION_GAP_FEATURES)
    pool = await asyncpg.create_pool(_database_url(), min_size=1, max_size=2)
    try:
        async with pool.acquire() as conn:
            master_before = await conn.fetchval(
                "SELECT setting_value FROM app_settings "
                "WHERE setting_key = 'sensitive_bridge_master_enabled'"
            )
            global_before = await conn.fetchval(
                "SELECT setting_value FROM app_settings "
                "WHERE setting_key = 'sensitive_bridge_global_gap_flags'"
            )
            print("master_before:", master_before)
            print("global_gap_flags_before:", _nflags(global_before), "flags")

            enrollments = await conn.fetch(
                "SELECT user_id, cohort_label, gap_features_enabled "
                "FROM sensitive_bridge_enrollment ORDER BY user_id"
            )
            dormant = [r for r in enrollments if _nflags(r["gap_features_enabled"]) == 0]
            print(f"enrollments: {len(enrollments)} total, {len(dormant)} dormant (0 flags)")
            for r in enrollments:
                print(
                    f"  {r['user_id']}: cohort={r['cohort_label']} "
                    f"flags={_nflags(r['gap_features_enabled'])}"
                )

            if dry_run:
                print("DRY-RUN: no writes. Would re-arm", len(dormant),
                      "dormant users, set global gap flags "
                      f"({len(FULL_ACTIVATION_GAP_FEATURES)}), master=true.")
                return 0

            async with conn.transaction():
                # 1. Re-arm every enrolled user (idempotent for already-armed rows).
                rearmed = await conn.fetch(
                    """
                    UPDATE sensitive_bridge_enrollment e
                       SET gap_features_enabled = $1::jsonb,
                           cohort_label = $2,
                           last_modified_at = NOW(),
                           last_modified_by = $3
                     WHERE e.gap_features_enabled IS DISTINCT FROM $1::jsonb
                        OR e.cohort_label IS DISTINCT FROM $2
                    RETURNING e.user_id
                    """,
                    gap_json,
                    COHORT_LABEL,
                    SCRIPT_TAG,
                )
                for row in rearmed:
                    await conn.execute(
                        """
                        INSERT INTO sensitive_bridge_log (
                            user_id, event_type, event_severity, payload_json,
                            decision_summary, occurred_at, recorded_by,
                            access_classification, pii_screened_at, redaction_pass_count
                        ) VALUES (
                            $1, 'sensitive_profile_mutation', 'moderate', $2::jsonb,
                            $3::jsonb, NOW(), $4, 'clinician_and_admin', NOW(), 1
                        )
                        """,
                        row["user_id"],
                        json.dumps({
                            "mutation_kind": "gap_features_rearmed_global",
                            "phase": "F",
                            "cohort_label": COHORT_LABEL,
                        }),
                        json.dumps({"contract_version": SCRIPT_TAG}),
                        SCRIPT_TAG,
                    )
                print("rearmed:", len(rearmed))

                # 2. Global gap flags — inherited by post-GA enrollments.
                await conn.execute(
                    """
                    INSERT INTO app_settings (setting_key, setting_value, updated_at, updated_by)
                    VALUES ('sensitive_bridge_global_gap_flags', $1::jsonb, NOW(), $2)
                    ON CONFLICT (setting_key) DO UPDATE SET
                        setting_value = EXCLUDED.setting_value,
                        updated_at = NOW(),
                        updated_by = EXCLUDED.updated_by
                    """,
                    gap_json,
                    OPERATOR,
                )

                # 3. Master switch ON (idempotent if already true).
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

                # 4. System audit row.
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
                        "phase": "F",
                        "action": "global_arm",
                        "rearmed_count": len(rearmed),
                        "global_gap_flags_count": len(FULL_ACTIVATION_GAP_FEATURES),
                    }),
                    json.dumps({"contract_version": SCRIPT_TAG}),
                    OPERATOR,
                )

            master_after = await conn.fetchval(
                "SELECT setting_value FROM app_settings "
                "WHERE setting_key = 'sensitive_bridge_master_enabled'"
            )
            global_after = await conn.fetchval(
                "SELECT setting_value FROM app_settings "
                "WHERE setting_key = 'sensitive_bridge_global_gap_flags'"
            )
            print("master_after:", master_after)
            print("global_gap_flags_after:", _nflags(global_after), "flags")
            rows = await conn.fetch(
                "SELECT user_id, cohort_label, gap_features_enabled "
                "FROM sensitive_bridge_enrollment ORDER BY user_id"
            )
            for r in rows:
                print(
                    f"  {r['user_id']}: cohort={r['cohort_label']} "
                    f"flags={_nflags(r['gap_features_enabled'])}"
                )
            print("OK: Phase F global arm complete. NOTE: settings cache TTL is",
                  os.getenv("SENSITIVE_BRIDGE_SETTINGS_CACHE_TTL", "15"),
                  "s — live processes pick up new flags within that window.")
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
