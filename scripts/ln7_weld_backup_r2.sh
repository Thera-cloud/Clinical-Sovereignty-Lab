#!/usr/bin/env bash
# QUANTUM-CRYSTAL-ARCH — Step 0 / W13: versioned frozen-config backup (local + R2).
# Usage: bash scripts/ln7_weld_backup_r2.sh [--dry-run]
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
FROZEN="${FROZEN_CONFIG_DIR:-$ROOT/frozen-config}"
STAMP="${LN7_WELD_STAMP:-$(date -u +%Y%m%dT%H%M%SZ)}"
LOCAL_DIR="${ROOT}/archive/frozen-config-backups/${STAMP}"
DRY=0
[[ "${1:-}" == "--dry-run" ]] && DRY=1

# Prefer venv; load r2_storage by file path (avoid app.services → numpy SIGFPE on macOS).
if [[ -x "${ROOT}/.venv/bin/python" ]]; then
  PY="${ROOT}/.venv/bin/python"
elif [[ -n "${LN7_PYTHON:-}" ]]; then
  PY="$LN7_PYTHON"
else
  PY="python3"
fi

if [[ ! -d "$FROZEN" ]]; then
  echo "[weld-backup] missing frozen-config: $FROZEN" >&2
  exit 1
fi
if [[ ! -f "$FROZEN/manifest.sha256.json" ]]; then
  echo "[weld-backup] missing manifest.sha256.json" >&2
  exit 1
fi

echo "[weld-backup] stamp=${STAMP} frozen=${FROZEN} py=${PY}"
if [[ "$DRY" == "1" ]]; then
  echo "[weld-backup] dry-run — would copy to $LOCAL_DIR and R2 prefix frozen-config/weld/${STAMP}/"
  exit 0
fi

mkdir -p "$LOCAL_DIR"
cp -R "$FROZEN"/. "$LOCAL_DIR"/
TAR="${LOCAL_DIR}.tar.gz"
tar -C "$(dirname "$LOCAL_DIR")" -czf "$TAR" "$(basename "$LOCAL_DIR")"
echo "[weld-backup] local=${LOCAL_DIR} tar=${TAR}"

# Load R2_* only (never full .env — avoids clobber / secret dump).
if [[ -f "${ROOT}/.env" ]]; then
  set -a
  # shellcheck disable=SC1090
  source <(grep -E '^R2_[A-Z0-9_]+=' "${ROOT}/.env" | sed 's/\r$//' || true)
  set +a
fi

R2_MOD="${ROOT}/backend/app/services/r2_storage.py"
"$PY" - "$R2_MOD" "$LOCAL_DIR" "$TAR" "$STAMP" <<'PY'
import importlib.util
import json
import sys
from pathlib import Path

mod_path, local_s, tar_s, stamp = sys.argv[1:5]
local = Path(local_s)
tar_path = Path(tar_s)
prefix = f"frozen-config/weld/{stamp}"

spec = importlib.util.spec_from_file_location("r2_storage", mod_path)
mod = importlib.util.module_from_spec(spec)
assert spec.loader is not None
try:
    spec.loader.exec_module(mod)
except Exception as e:
    print(f"[weld-backup] r2 load failed: {e}", file=sys.stderr)
    sys.exit(0)

if not mod.is_r2_configured():
    print("[weld-backup] R2 not configured — local backup only")
    sys.exit(0)

manifest = (local / "manifest.sha256.json").read_bytes()
mod.upload_bytes(
    key=f"{prefix}/manifest.sha256.json",
    content=manifest,
    content_type="application/json",
    metadata={"weld_stamp": stamp},
)
mod.upload_bytes(
    key=f"{prefix}/frozen-config.tar.gz",
    content=tar_path.read_bytes(),
    content_type="application/gzip",
    metadata={"weld_stamp": stamp},
)
meta = {
    "stamp": stamp,
    "prefix": prefix,
    "manifest_bytes": len(manifest),
    "tar_bytes": tar_path.stat().st_size,
}
mod.upload_bytes(
    key=f"{prefix}/backup_meta.json",
    content=(json.dumps(meta, indent=2) + "\n").encode(),
    content_type="application/json",
)
print(f"[weld-backup] r2_ok prefix={prefix}")
PY
