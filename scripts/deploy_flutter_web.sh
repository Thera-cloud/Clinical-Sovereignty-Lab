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

LEGAL_PAGES=(
  try.html signup.html privacy.html terms.html
  data-deletion.html sms-policy.html payment-complete.html payment-cancelled.html
)

overlay_legal_pages() {
  local dest="$1"
  mkdir -p "${dest}"
  for f in "${LEGAL_PAGES[@]}"; do
    local src=""
    if [[ -f "${ROOT}/dashboard/${f}" ]]; then
      src="${ROOT}/dashboard/${f}"
    elif [[ -f "${ROOT}/mobile/web/${f}" ]]; then
      src="${ROOT}/mobile/web/${f}"
    else
      echo "FAIL: missing dashboard/${f} and mobile/web/${f}" >&2
      exit 1
    fi
    cp "${src}" "${dest}/${f}"
  done
  if ! grep -q "Talk to Little Nate" "${dest}/try.html"; then
    echo "FAIL: ${dest}/try.html is not the trial page (missing Talk to Little Nate)" >&2
    exit 1
  fi
}

cd "${ROOT}/mobile"
if [[ "${NO_BUILD}" -eq 0 ]]; then
  flutter build web --release
fi

overlay_legal_pages "${ROOT}/mobile/build/web"

VERSION="$(date +%Y.%m.%d.%H%M)"
COMMIT="$(cd "${ROOT}" && git rev-parse --short HEAD 2>/dev/null || echo unknown)"
printf '%s\n' "{\"version\":\"${VERSION}\",\"build\":\"${COMMIT}\",\"deployed_at\":\"$(date -u +%Y-%m-%dT%H:%M:%SZ)\"}" > "${ROOT}/mobile/build/web/version.json"

echo "rsync → ${SERVER}:${WEB_ROOT}"
# Never --delete: extras on this root (legal pages, studio HTML) must not be pruned.
rsync -avz "${ROOT}/mobile/build/web/" "${SERVER}:${WEB_ROOT}"

# Overlay again on the live docroot so a future rsync --delete of build/web
# cannot leave try.html / Stripe / Meta pages missing (SPA then serves Flutter gateway).
rsync -avz \
  "${ROOT}/mobile/build/web/try.html" \
  "${ROOT}/mobile/build/web/signup.html" \
  "${ROOT}/mobile/build/web/privacy.html" \
  "${ROOT}/mobile/build/web/terms.html" \
  "${ROOT}/mobile/build/web/data-deletion.html" \
  "${ROOT}/mobile/build/web/sms-policy.html" \
  "${ROOT}/mobile/build/web/payment-complete.html" \
  "${ROOT}/mobile/build/web/payment-cancelled.html" \
  "${SERVER}:${WEB_ROOT}"

ssh "${SERVER}" "grep -q 'Talk to Little Nate' ${WEB_ROOT}try.html && grep -q flutter_bootstrap ${WEB_ROOT}index.html"
echo "verified try.html + Flutter index.html on ${SERVER}"

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
