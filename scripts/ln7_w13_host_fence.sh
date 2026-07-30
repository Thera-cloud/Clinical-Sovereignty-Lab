#!/usr/bin/env bash
# QUANTUM-CRYSTAL-ARCH — W13 host fence: SA-unwritable frozen-config on GREEN host.
# Syncs repo weld into /opt/clinical-sovereignty-lab/frozen-config and hardens mode.
# Does NOT flip G2 flags. Does NOT docker --force-recreate.
set -euo pipefail
ROOT="${1:-/opt/clinical-sovereignty-lab}"
SRC="${ROOT}/frozen-config"
MODE_DIR=755
MODE_FILE=644

if [[ ! -d "$SRC" ]]; then
  echo "[w13] missing $SRC — git pull first" >&2
  exit 1
fi

echo "[w13] harden ACL on $SRC"
# Owner write; group/other read+traverse only (containers mount :ro)
find "$SRC" -type d -exec chmod "$MODE_DIR" {} +
find "$SRC" -type f -exec chmod "$MODE_FILE" {} +
# Drop write for group/other explicitly
chmod -R a-w,u+rwX,go+rX "$SRC" 2>/dev/null || true
find "$SRC" -type d -exec chmod u+x {} +

if [[ -f "$SRC/manifest.sha256.json" ]]; then
  echo "[w13] manifest present"
  head -3 "$SRC/manifest.sha256.json"
else
  echo "[w13] WARNING: manifest.sha256.json missing" >&2
fi

echo "[w13] done — ensure compose mounts ./frozen-config:/opt/ln7/frozen-config:ro"
