#!/usr/bin/env bash
# =============================================================================
# Apply Sovereign Swarm Migrations
# Run this on an existing deployment where migrations 007-009 have NOT been
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
             legacy_vault_consent legacy_vault_entries swarm_teams fibre_templates; do
    EXISTS=$(docker exec "${CONTAINER}" psql -U "${DB_USER}" -d "${DB_NAME}" -tAc \
        "SELECT EXISTS (SELECT FROM information_schema.tables WHERE table_name = '${table}');")
    STATUS="OK"
    [ "${EXISTS}" != "t" ] && STATUS="MISSING"
    printf "  %-30s %s\n" "${table}" "${STATUS}"
done
