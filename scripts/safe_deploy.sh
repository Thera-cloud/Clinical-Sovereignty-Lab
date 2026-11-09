#!/usr/bin/env bash
# Safe deploy wrapper for sovereignsanctuary GREEN
# Snapshots vault BEFORE deploy, counts metrics files, refuses if count drops >10%
# Usage: ./scripts/safe_deploy.sh <service1> [<service2> ...]

set -euo pipefail

cd /opt/clinical-sovereignty-lab

# Email-window advisory (non-blocking). Scheduler dedup is per-process; a backend
# restart inside these windows re-runs auditors and can re-send ops digests.
if printf '%s\n' "$@" | grep -qx backend; then
  et_hour=$(TZ=America/New_York date +%H)
  utc_hm=$(date -u +%H%M)
  if [ "$et_hour" = "06" ] || [ "$et_hour" = "20" ]; then
    echo "[safe_deploy] WARNING: ${et_hour}:xx ET is a Schedule-Ops digest hour — restarting backend now may re-send the ops digest."
  fi
  case "$utc_hm" in
    05[0-1][0-9]|17[0-1][0-9]|23[0-1][0-9])
      echo "[safe_deploy] WARNING: audit window (05/17/23 UTC :00-:19) — restarting backend re-runs 45 auditors + Trust Enforcer." ;;
  esac
fi

ts=$(date -u +%Y%m%dT%H%M%SZ)
snapshot_dir="/opt/clinical-sovereignty-lab/backups/vaults"
mkdir -p "$snapshot_dir"

echo "[safe_deploy] Snapshot: pre_deploy_${ts}.tar.gz"
tar -czf "${snapshot_dir}/pre_deploy_${ts}.tar.gz" data/bridge/Vaults data/backend/Vaults 2>/dev/null || true

pre_count=$(find data/bridge/Vaults/Clients -name 'metrics.json' 2>/dev/null | wc -l)
echo "[safe_deploy] Pre-deploy vault metrics count: ${pre_count}"

echo "[safe_deploy] Running: docker compose -f docker-compose.prod.yml up -d $@"
docker compose -f docker-compose.prod.yml up -d "$@"

# Bind-mounted Python code requires process restart to load new routes/modules.
if printf '%s\n' "$@" | grep -qxE 'backend|bridge'; then
  echo "[safe_deploy] Restarting: $* (reload bind-mounted app code)"
  docker compose -f docker-compose.prod.yml restart "$@"
fi

sleep 10

post_count=$(find data/bridge/Vaults/Clients -name 'metrics.json' 2>/dev/null | wc -l)
echo "[safe_deploy] Post-deploy vault metrics count: ${post_count}"

threshold=$((pre_count * 9 / 10))

if [ "$post_count" -lt "$threshold" ]; then
  echo ""
  echo "================================================"
  echo "ALERT: VAULT WIPE DETECTED"
  echo "Pre-deploy:  ${pre_count} metrics files"
  echo "Post-deploy: ${post_count} metrics files"
  echo "Threshold:   ${threshold} (90% of pre-count)"
  echo "Snapshot:    ${snapshot_dir}/pre_deploy_${ts}.tar.gz"
  echo "================================================"
  exit 2
fi

echo "[safe_deploy] OK: vault metrics ${pre_count} -> ${post_count}"
