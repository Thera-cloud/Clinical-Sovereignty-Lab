#!/usr/bin/env bash
# Sync DATA_DIR newsletter library HTML to app www roots (host nginx).
# QUANTUM-CRYSTAL-ARCH — Little Nate Dispatch
set -euo pipefail
SRC="${DATA_DIR:-/opt/clinical-sovereignty-lab/data/backend}/newsletter_library"
DESTS=(
  "/var/www/sovereignsanctuary-web/library"
  "/var/www/sovereign-command/library"
)
if [[ ! -d "$SRC" ]]; then
  echo "No library dir at $SRC"
  exit 0
fi
for d in "${DESTS[@]}"; do
  mkdir -p "$d"
  rsync -av --exclude='.pending_sync' "$SRC/" "$d/"
done
# Shell index
if [[ -f /opt/clinical-sovereignty-lab/dashboard/nate_story_library.html ]]; then
  rsync -av /opt/clinical-sovereignty-lab/dashboard/nate_story_library.html \
    /var/www/sovereignsanctuary-web/nate_story_library.html
  rsync -av /opt/clinical-sovereignty-lab/dashboard/nate_story_library.html \
    /var/www/sovereign-command/nate_story_library.html
fi
if [[ -f /opt/clinical-sovereignty-lab/dashboard/newsletter_dispatch.html ]]; then
  rsync -av /opt/clinical-sovereignty-lab/dashboard/newsletter_dispatch.html \
    /var/www/sovereign-command/newsletter_dispatch.html
fi
systemctl reload nginx 2>/dev/null || true
echo "Synced newsletter library from $SRC"
