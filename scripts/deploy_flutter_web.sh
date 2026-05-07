#!/usr/bin/env bash
# Canonical Flutter web deploy for coach.sovereignsanctuary.net + app.sovereignsanctuary.net.
# Host nginx root: /var/www/sovereignsanctuary-web/ (see flutter-build-verification.mdc — NOT coach-portal).
# Optional purge: scripts/cf_purge_flutter_web.sh (needs CLOUDFLARE_PURGE_TOKEN in repo-root .env).
#
# Usage:
#   bash scripts/deploy_flutter_web.sh
#   bash scripts/deploy_flutter_web.sh --no-build    # rsync existing mobile/build/web only
#   bash scripts/deploy_flutter_web.sh --no-purge    # skip Cloudflare API purge
#
# Env overrides:
#   DEPLOY_GREEN_HOST=root@68.183.168.75
#   DEPLOY_FLUTTER_WEB_ROOT=/var/www/sovereignsanctuary-web/
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SERVER="${DEPLOY_GREEN_HOST:-root@68.183.168.75}"
WEB_ROOT="${DEPLOY_FLUTTER_WEB_ROOT:-/var/www/sovereignsanctuary-web/}"

NO_BUILD=0
NO_PURGE=0
for a in "$@"; do
  case "$a" in
    --no-build) NO_BUILD=1 ;;
    --no-purge) NO_PURGE=1 ;;
    *) echo "Unknown arg: $a (use --no-build / --no-purge)"; exit 2 ;;
  esac
done

cd "${ROOT}/mobile"
if [[ "${NO_BUILD}" -eq 0 ]]; then
  flutter build web --release
fi

VERSION="$(date +%Y.%m.%d.%H%M)"
COMMIT="$(cd "${ROOT}" && git rev-parse --short HEAD 2>/dev/null || echo unknown)"
printf '%s\n' "{\"version\":\"${VERSION}\",\"build\":\"${COMMIT}\",\"deployed_at\":\"$(date -u +%Y-%m-%dT%H:%M:%SZ)\"}" > "${ROOT}/mobile/build/web/version.json"

echo "rsync → ${SERVER}:${WEB_ROOT}"
rsync -avz "${ROOT}/mobile/build/web/" "${SERVER}:${WEB_ROOT}"

ssh "${SERVER}" "systemctl reload nginx"
echo "nginx reloaded on ${SERVER}"

if [[ "${NO_PURGE}" -eq 0 ]]; then
  if bash "${ROOT}/scripts/cf_purge_flutter_web.sh"; then
    :
  else
    echo ""
    echo "WARN: Cloudflare purge failed or skipped (missing CLOUDFLARE_PURGE_TOKEN?). Purge dashboard or run: bash scripts/cf_purge_flutter_web.sh"
  fi
fi

echo "Deploy complete v=${VERSION} commit=${COMMIT}"
