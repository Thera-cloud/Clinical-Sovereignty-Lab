#!/usr/bin/env bash
# One-time / refresh: little_nate_staging DB + staging_backend container (:8011).
# Run on GREEN after git pull. Does not touch production backend flags or :8000 traffic.
# Usage: bash scripts/staging_bake_setup.sh [--refresh-db]

set -euo pipefail

cd /opt/clinical-sovereignty-lab

REFRESH_DB=0
if [ "${1:-}" = "--refresh-db" ]; then
  REFRESH_DB=1
fi

echo "[staging_bake] Pre-flight backup"
if [ -x scripts/daily_backup.sh ]; then
  bash scripts/daily_backup.sh || echo "[staging_bake] WARN: daily_backup non-zero (continuing)"
fi

echo "[staging_bake] Apply agentic migrations to production little_nate"
bash scripts/staging_apply_agentic_migrations.sh little_nate

STAGING_EXISTS=$(docker exec nate_postgres psql -U "${POSTGRES_USER:-nate_admin}" -d postgres -tAc \
  "SELECT 1 FROM pg_database WHERE datname='little_nate_staging'" | tr -d '[:space:]')

if [ "$STAGING_EXISTS" != "1" ] || [ "$REFRESH_DB" = "1" ]; then
  echo "[staging_bake] (Re)create little_nate_staging via pg_dump (no lock on live little_nate)"
  # NOTE: CREATE DATABASE ... TEMPLATE requires zero connections to the SOURCE db.
  # little_nate is live prod (backend + bridge pools) — never terminate its backends here.
  # Terminate only staging's own connections (safe: staging has no traffic).
  docker exec nate_postgres psql -U "${POSTGRES_USER:-nate_admin}" -d postgres -v ON_ERROR_STOP=1 <<'SQL'
SELECT pg_terminate_backend(pid)
FROM pg_stat_activity
WHERE datname = 'little_nate_staging' AND pid <> pg_backend_pid();
SQL
  docker exec nate_postgres psql -U "${POSTGRES_USER:-nate_admin}" -d postgres -v ON_ERROR_STOP=1 \
    -c "DROP DATABASE IF EXISTS little_nate_staging;"
  docker exec nate_postgres psql -U "${POSTGRES_USER:-nate_admin}" -d postgres -v ON_ERROR_STOP=1 \
    -c "CREATE DATABASE little_nate_staging OWNER nate_admin;"
  echo "[staging_bake] pg_dump little_nate | psql little_nate_staging (MVCC snapshot, no exclusive lock)"
  docker exec nate_postgres bash -c \
    "pg_dump -U ${POSTGRES_USER:-nate_admin} -d little_nate --no-owner --no-privileges | psql -U ${POSTGRES_USER:-nate_admin} -d little_nate_staging -v ON_ERROR_STOP=1 -q" \
    > /tmp/staging_clone.log 2>&1 || { echo "[staging_bake] ERROR: clone failed, see /tmp/staging_clone.log"; tail -40 /tmp/staging_clone.log; exit 1; }
  echo "[staging_bake] Clone complete"
else
  echo "[staging_bake] little_nate_staging exists — applying migrations only"
  bash scripts/staging_apply_agentic_migrations.sh little_nate_staging
fi

mkdir -p data/backend_staging
chown -R 1000:1000 data/backend_staging 2>/dev/null || true

echo "[staging_bake] Start staging_backend (flags default off — use staging_phase_flags.sh)"
docker compose -f docker-compose.prod.yml -f docker-compose.staging.yml up -d staging_backend

sleep 15
curl -sf http://127.0.0.1:8011/health | head -c 200
echo ""
docker logs nate_staging_backend --since 30s 2>&1 | grep -E 'STARTUP COMPLETE|staging' | tail -3 || true
echo "[staging_bake] OK — health http://127.0.0.1:8011/health"
