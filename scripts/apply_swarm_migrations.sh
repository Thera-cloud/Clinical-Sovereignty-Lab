#!/usr/bin/env bash
# =============================================================================
# Apply Sovereign Swarm Migrations
# Run this on an existing deployment where migrations 007-012 have NOT been
# applied yet (i.e., the Docker postgres container already exists).
#
# Usage (from project root):
#   bash scripts/apply_swarm_migrations.sh
#
# Or on the server via SSH:
#   ssh root@68.183.168.75 "cd /opt/clinical-sovereignty-lab && bash scripts/apply_swarm_migrations.sh"
# =============================================================================

set -euo pipefail

CONTAINER="nate_postgres"
DB_USER="nate_admin"
DB_NAME="little_nate"
MIGRATION_DIR="backend/migrations"

MIGRATIONS=(
    "007_strategic_memory.sql"
    "008_swarm_genesis.sql"
    "009_legacy_vault.sql"
    "010_skyeye_phase2.sql"
    "011_prospect_to_user_linking.sql"
    "012_performance_indexes.sql"
    "013_stripe_tables.sql"
    "014_approval_categories.sql"
    "015_nate_nudges_wisdom_profiles.sql"
    "016_family_sanctuary_tables.sql"
    "017_subscriptions_payment_history.sql"
    "018_stripe_user_columns.sql"
    "019_check_constraint_fixes.sql"
    "020_phd_compliance_tables.sql"
    "021_zefcp_tables.sql"
    "022_quakete_tables.sql"
    "023_sovereign_mind_tables.sql"
    "024_fibre_trust_tables.sql"
    "025_counter_intelligence.sql"
    "026_missing_indexes.sql"
    "027_solutions_tables.sql"
    "028_me2me_tables.sql"
    "029_trust_tables.sql"
    "030_hive_defense_foundation.sql"
    "031_hive_defense_supplemental.sql"
    "032_user_store_profile_data.sql"
    "033_family_pricing_v3_founding.sql"
    "034_sovereign_vault.sql"
    "035_founding_member_constraint.sql"
    "036_webhook_idempotency.sql"
    "037_transfer_conversations.sql"
    "038_organization_sessions.sql"
    "039_billing_fortress.sql"
    "040_guardian_fibre.sql"
    "041_advanced_protections.sql"
    "042_sentinel_mesh.sql"
    "043_pipeline_drum.sql"
    "044_hepa_filter.sql"
    "045_campaign_episodes.sql"
    "046_deadman_activity_tracking.sql"
)

echo "=== Sovereign Swarm Migration Runner ==="
echo ""

# Check if postgres container is running
if ! docker ps --format '{{.Names}}' | grep -q "^${CONTAINER}$"; then
    echo "ERROR: Container '${CONTAINER}' is not running."
    echo "Start it with: docker-compose up -d postgres"
    exit 1
fi

# Check postgres is ready
if ! docker exec "${CONTAINER}" pg_isready -U "${DB_USER}" -d "${DB_NAME}" > /dev/null 2>&1; then
    echo "ERROR: PostgreSQL is not ready in '${CONTAINER}'."
    exit 1
fi

echo "PostgreSQL is ready."
echo ""

for migration in "${MIGRATIONS[@]}"; do
    FILE="${MIGRATION_DIR}/${migration}"

    if [ ! -f "${FILE}" ]; then
        echo "SKIP: ${FILE} not found"
        continue
    fi

    echo -n "Applying ${migration}... "

    # Check if migration has already been applied (check for a table from each migration)
    case "${migration}" in
        "007_strategic_memory.sql")
            TABLE_CHECK="standing_orders"
            ;;
        "008_swarm_genesis.sql")
            TABLE_CHECK="fibres"
            ;;
        "009_legacy_vault.sql")
            TABLE_CHECK="legacy_vault_consent"
            ;;
        "010_skyeye_phase2.sql")
            TABLE_CHECK="skyeye_content_queue"
            ;;
        "011_prospect_to_user_linking.sql")
            # Uses ALTER TABLE, so check for a column instead of a table
            TABLE_CHECK=""
            ;;
        "012_performance_indexes.sql")
            # Index-only migration, no new tables
            TABLE_CHECK=""
            ;;
        "013_stripe_tables.sql")
            TABLE_CHECK="session_packs"
            ;;
        "014_approval_categories.sql")
            # ALTER TABLE migration, check for column
            TABLE_CHECK=""
            ;;
        "015_nate_nudges_wisdom_profiles.sql")
            TABLE_CHECK="nate_nudges"
            ;;
        "016_family_sanctuary_tables.sql")
            TABLE_CHECK="family_sanctuary_sessions"
            ;;
        "017_subscriptions_payment_history.sql")
            TABLE_CHECK="subscriptions"
            ;;
        "018_stripe_user_columns.sql")
            # ALTER TABLE migration — check for column
            TABLE_CHECK=""
            ;;
        "019_check_constraint_fixes.sql")
            TABLE_CHECK=""
            ;;
        "020_phd_compliance_tables.sql")
            TABLE_CHECK="phd_compliance_events"
            ;;
        "021_zefcp_tables.sql")
            TABLE_CHECK="zefcp_fragments"
            ;;
        "022_quakete_tables.sql")
            TABLE_CHECK="quakete_zones"
            ;;
        "023_sovereign_mind_tables.sql")
            TABLE_CHECK="sovereign_mind_states"
            ;;
        "024_fibre_trust_tables.sql")
            TABLE_CHECK="fibre_trust_scores"
            ;;
        "025_counter_intelligence.sql")
            TABLE_CHECK="counter_intelligence_events"
            ;;
        "026_missing_indexes.sql")
            # Index-only migration
            TABLE_CHECK=""
            ;;
        "027_solutions_tables.sql")
            TABLE_CHECK="solutions"
            ;;
        "028_me2me_tables.sql")
            TABLE_CHECK="me2me_avatars"
            ;;
        "029_trust_tables.sql")
            TABLE_CHECK="trust_events"
            ;;
        "030_hive_defense_foundation.sql")
            TABLE_CHECK="hive_forensic_logs"
            ;;
        "031_hive_defense_supplemental.sql")
            TABLE_CHECK="hive_heartbeats"
            ;;
        "032_user_store_profile_data.sql")
            TABLE_CHECK="user_store_profiles"
            ;;
        "033_family_pricing_v3_founding.sql")
            TABLE_CHECK="platform_config"
            ;;
        "034_sovereign_vault.sql")
            TABLE_CHECK="vault_folders"
            ;;
        "035_founding_member_constraint.sql")
            # ALTER TABLE + trigger, no new table
            TABLE_CHECK=""
            ;;
        "036_webhook_idempotency.sql")
            TABLE_CHECK="webhook_events"
            ;;
        "037_transfer_conversations.sql")
            # Index-only migration
            TABLE_CHECK=""
            ;;
        "038_organization_sessions.sql")
            TABLE_CHECK="organization_sessions"
            ;;
        "039_billing_fortress.sql")
            TABLE_CHECK="webhook_events_v2"
            ;;
        "040_guardian_fibre.sql")
            TABLE_CHECK="guardian_fibres"
            ;;
        "041_advanced_protections.sql")
            TABLE_CHECK="sentinel_records"
            ;;
        "042_sentinel_mesh.sql")
            TABLE_CHECK="guardian_heartbeat_log"
            ;;
        "043_pipeline_drum.sql")
            TABLE_CHECK="drum_baselines"
            ;;
        "044_hepa_filter.sql")
            TABLE_CHECK="staged_deletions"
            ;;
        "045_campaign_episodes.sql")
            TABLE_CHECK="campaign_templates"
            ;;
        "046_deadman_activity_tracking.sql")
            # ALTER TABLE + index, no new table
            TABLE_CHECK=""
            ;;
        *)
            TABLE_CHECK=""
            ;;
    esac

    if [ -n "${TABLE_CHECK}" ]; then
        EXISTS=$(docker exec "${CONTAINER}" psql -U "${DB_USER}" -d "${DB_NAME}" -tAc \
            "SELECT EXISTS (SELECT FROM information_schema.tables WHERE table_name = '${TABLE_CHECK}');")
        if [ "${EXISTS}" = "t" ]; then
            echo "ALREADY APPLIED (table '${TABLE_CHECK}' exists)"
            continue
        fi
    fi

    # Apply the migration
    docker exec -i "${CONTAINER}" psql -U "${DB_USER}" -d "${DB_NAME}" < "${FILE}"
    echo "OK"
done

echo ""
echo "=== Migration complete ==="
echo ""

# Verify tables exist
echo "Verification:"
for table in standing_orders insight_log strategy_proposals coherence_briefings \
             foresight_alerts swarm_oversight_log coherence_measurements \
             fibres fibre_evolution_journal wisdom_mesh_messages \
             legacy_vault_consent legacy_vault_entries swarm_teams fibre_templates \
             skyeye_content_queue skyeye_platform_tokens skyeye_session_actions \
             session_packs coaching_sessions \
             nate_nudges wisdom_extractions legacy_vault_access_log \
             family_sanctuary_sessions sanctuary_members sanctuary_messages \
             sanctuary_interventions sanctuary_billing_events sanctuary_archives \
             subscriptions subscription_items payment_history \
             hive_forensic_logs attacker_fingerprints curiosity_events \
             containment_zones defcon_state drift_scores ghost_missions \
             hive_heartbeats curiosity_state ring_membership hive_events \
             platform_config vault_folders vault_items transfer_crystals \
             webhook_events organization_sessions webhook_events_v2 \
             trial_fingerprints usage_meters \
             guardian_fibres device_imprints guardian_snapshots \
             sentinel_records minor_data_access_log custody_dispute_records \
             guardian_heartbeat_log cross_guardian_alerts sentinel_mesh_state \
             drum_baselines drum_alerts \
             staged_deletions heritage_vault_records legacy_wishes \
             campaign_templates storytelling_campaigns; do
    EXISTS=$(docker exec "${CONTAINER}" psql -U "${DB_USER}" -d "${DB_NAME}" -tAc \
        "SELECT EXISTS (SELECT FROM information_schema.tables WHERE table_name = '${table}');")
    STATUS="OK"
    [ "${EXISTS}" != "t" ] && STATUS="MISSING"
    printf "  %-30s %s\n" "${table}" "${STATUS}"
done
