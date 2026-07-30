#!/usr/bin/env bash
# QUANTUM-CRYSTAL-ARCH — Step 0: run fence tests + flip G2 flags when green.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
export PYTHONPATH="${ROOT}/backend:${PYTHONPATH:-}"
export FROZEN_CONFIG_DIR="${FROZEN_CONFIG_DIR:-$ROOT/frozen-config}"

echo "[step0] verify manifest"
python3 - <<'PY'
from app.services.ln7_frozen_config import verify_manifest
ok, bad = verify_manifest()
print("manifest_ok", ok, "mismatches", bad[:10])
raise SystemExit(0 if ok else 1)
PY

echo "[step0] fence pytest"
python3 -m pytest "$FROZEN_CONFIG_DIR/fence_tests" -q

echo "[step0] fence suite green — G2 flip requires DB (run via backend):"
echo "  await flip_g2_governance(db_pool, reason='step0_green')"
