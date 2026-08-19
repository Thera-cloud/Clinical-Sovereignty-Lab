#!/usr/bin/env bash
# Purge Cloudflare edge cache for Flutter web bootstrap files (coach + app hosts).
# Reads CLOUDFLARE_ZONE_ID + CLOUDFLARE_PURGE_TOKEN from repo-root .env via grep (safe if .env has shell metacharacters).
# Token: Cloudflare Dashboard → API Tokens → e.g. "Sovereign Deploy Cache Purge"
#         Permissions: Zone · Cache Purge · Purge · Include · sovereignsanctuary.net
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
ENVF="${ROOT}/.env"
if [[ ! -f "$ENVF" ]]; then
  echo "Missing ${ENVF}"
  exit 1
fi

get_kv() {
  local k="$1"
  grep -E "^${k}=" "$ENVF" 2>/dev/null | tail -1 | cut -d= -f2- | tr -d '\r' | sed 's/^["'\'']//;s/["'\'']$//'
}

ZONE="$(get_kv CLOUDFLARE_ZONE_ID)"
TOKEN="$(get_kv CLOUDFLARE_PURGE_TOKEN)"
if [[ -z "$TOKEN" ]]; then
  TOKEN="$(get_kv CLOUDFLARE_API_TOKEN)"
fi

if [[ -z "$ZONE" || -z "$TOKEN" ]]; then
  echo "Set CLOUDFLARE_ZONE_ID and CLOUDFLARE_PURGE_TOKEN in .env (see .env.template)."
  exit 1
fi

BODY=$(python3 - <<'PY'
import json
hosts = ("coach.sovereignsanctuary.net", "app.sovereignsanctuary.net")
paths = (
    "main.dart.js",
    "flutter_service_worker.js",
    "flutter_bootstrap.js",
    "index.html",
    "version.json",
    "signup.html",
    "try.html",
    "studio_livekit_room.html",
    "livekit-client.umd.min.js",
    "avatar-modes/expression_viewer.html",
    "avatar-modes/vendor/three.module.js",
)
files = [f"https://{h}/{p}" for h in hosts for p in paths]
print(json.dumps({"files": files}))
PY
)

RESP="$(curl -s -X POST "https://api.cloudflare.com/client/v4/zones/${ZONE}/purge_cache" \
  -H "Authorization: Bearer ${TOKEN}" \
  -H "Content-Type: application/json" \
  --data "${BODY}")"

echo "$RESP" | python3 -c "import sys,json; r=json.load(sys.stdin); print('Cloudflare purge:', 'ok' if r.get('success') else r.get('errors', r)); sys.exit(0 if r.get('success') else 1)"
