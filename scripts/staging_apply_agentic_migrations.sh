#!/usr/bin/env bash
# Apply agentic roadmap migrations 237–239 to one or more PostgreSQL databases.
# Usage: ./scripts/staging_apply_agentic_migrations.sh [db_name ...]
# Default: little_nate little_nate_staging

set -euo pipefail

cd "$(dirname "$0")/.."

DBS=("$@")
if [ ${#DBS[@]} -eq 0 ]; then
  DBS=(little_nate little_nate_staging)
fi

MIGRATIONS=(
  backend/migrations/237_proactive_touch_policy.sql
  backend/migrations/238_nate_commitments.sql
  backend/migrations/239_nate_therapeutic_plans.sql
)

for db in "${DBS[@]}"; do
  echo "[agentic-migrate] database=${db}"
  for mig in "${MIGRATIONS[@]}"; do
    if [ ! -f "$mig" ]; then
      echo "[agentic-migrate] MISSING ${mig}" >&2
      exit 1
    fi
    echo "[agentic-migrate]   -> $(basename "$mig")"
    docker exec -i nate_postgres psql -U "${POSTGRES_USER:-nate_admin}" -d "$db" -v ON_ERROR_STOP=1 <"$mig"
  done
  docker exec nate_postgres psql -U "${POSTGRES_USER:-nate_admin}" -d "$db" -tAc \
    "SELECT EXISTS(SELECT 1 FROM pg_class WHERE relname='proactive_touch_outcome_view');"
  docker exec nate_postgres psql -U "${POSTGRES_USER:-nate_admin}" -d "$db" -tAc \
    "SELECT EXISTS(SELECT 1 FROM pg_class WHERE relname='nate_commitments');"
  docker exec nate_postgres psql -U "${POSTGRES_USER:-nate_admin}" -d "$db" -tAc \
    "SELECT EXISTS(SELECT 1 FROM pg_class WHERE relname='nate_therapeutic_plans');"
done

echo "[agentic-migrate] OK"
