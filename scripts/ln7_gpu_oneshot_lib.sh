#!/usr/bin/env bash
# One-shot GPU size fallback + telemetry when preferred SKU is inventory-blocked.
# Source from drain / capacity watch — does not create droplets itself.
#
# Env:
#   LN7_GPU_SIZE                     preferred (default Ada 20GB)
#   LN7_GPU_ONESHOT_FALLBACK_SIZE    default gpu-l40sx1-48gb
#   LN7_GPU_ONESHOT_FALLBACK         1=allow (default), 0=disable
#   LN7_GPU_ONESHOT_COOLDOWN_S       skip re-arm within window (default 21600=6h)
#
# Artifacts under LN7_GPU_WATCH_STATE_DIR:
#   ONESHOT_TELEMETRY.jsonl  append-only events
#   ONESHOT_LAST.json        last event object
#   ONESHOT_ARMED            size/region used for current cycle
#
# # QUANTUM-CRYSTAL-ARCH
# shellcheck shell=bash

: "${LN7_GPU_WATCH_STATE_DIR:=$HOME/.local/state/ln7_gpu_watch}"
: "${LN7_GPU_SIZE:=gpu-4000adax1-20gb}"
: "${LN7_GPU_PREFERRED_SIZE:=${LN7_GPU_SIZE}}"
: "${LN7_GPU_ONESHOT_FALLBACK_SIZE:=gpu-l40sx1-48gb}"
: "${LN7_GPU_ONESHOT_FALLBACK:=1}"
: "${LN7_GPU_ONESHOT_COOLDOWN_S:=21600}"

ln7_oneshot_enabled() {
  [[ "${LN7_GPU_ONESHOT_FALLBACK}" == "1" || "${LN7_GPU_ONESHOT_FALLBACK}" == "true" ]]
}

ln7_oneshot_preferred_size() {
  echo "${LN7_GPU_PREFERRED_SIZE:-${LN7_GPU_SIZE}}"
}

ln7_oneshot_fallback_size() {
  echo "${LN7_GPU_ONESHOT_FALLBACK_SIZE}"
}

ln7_oneshot_telemetry() {
  # Usage: ln7_oneshot_telemetry <event> [k=v ...]
  local event="${1:?event}"
  shift || true
  local state_dir="${LN7_GPU_WATCH_STATE_DIR}"
  mkdir -p "$state_dir"
  local ts
  ts="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  python3 - "$state_dir" "$event" "$ts" "$@" <<'PY'
import json, sys, time
from pathlib import Path
state, event, ts = Path(sys.argv[1]), sys.argv[2], sys.argv[3]
extra = {}
for a in sys.argv[4:]:
    if "=" in a:
        k, v = a.split("=", 1)
        extra[k] = v
import os
obj = {
    "ts": ts,
    "unix": int(time.time()),
    "event": event,
    "preferred_size": os.environ.get("LN7_GPU_PREFERRED_SIZE")
        or os.environ.get("LN7_GPU_SIZE", ""),
    "fallback_size": os.environ.get("LN7_GPU_ONESHOT_FALLBACK_SIZE", ""),
    **extra,
}
jl = state / "ONESHOT_TELEMETRY.jsonl"
with jl.open("a", encoding="utf-8") as f:
    f.write(json.dumps(obj, default=str) + "\n")
(state / "ONESHOT_LAST.json").write_text(json.dumps(obj, indent=2) + "\n", encoding="utf-8")
print(json.dumps(obj))
PY
}

ln7_oneshot_cooldown_active() {
  local last="${LN7_GPU_WATCH_STATE_DIR}/ONESHOT_LAST.json"
  [[ -f "$last" ]] || return 1
  python3 - "$last" "${LN7_GPU_ONESHOT_COOLDOWN_S}" <<'PY'
import json, sys, time
from pathlib import Path
p, cool = Path(sys.argv[1]), int(sys.argv[2])
try:
    d = json.loads(p.read_text())
except Exception:
    raise SystemExit(1)
# Only cooldown after a successful arm / consume — allow retry after blocked
if d.get("event") not in ("oneshot_armed", "oneshot_consume"):
    raise SystemExit(1)
age = time.time() - float(d.get("unix") or 0)
raise SystemExit(0 if age < cool else 1)
PY
}

ln7_oneshot_mark_armed() {
  local size="$1" region="$2" id="${3:-}" ip="${4:-}"
  {
    echo "size=$size"
    echo "region=$region"
    echo "id=$id"
    echo "ip=$ip"
    echo "ts=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  } >"${LN7_GPU_WATCH_STATE_DIR}/ONESHOT_ARMED"
  ln7_oneshot_telemetry oneshot_armed "size=$size" "region=$region" "droplet_id=$id" "ip=$ip"
}

ln7_oneshot_should_try() {
  ln7_oneshot_enabled || return 1
  local fb pref
  fb="$(ln7_oneshot_fallback_size)"
  pref="$(ln7_oneshot_preferred_size)"
  [[ -n "$fb" && "$fb" != "$pref" ]] || return 1
  if ln7_oneshot_cooldown_active; then
    ln7_oneshot_telemetry oneshot_skip_cooldown "reason=cooldown" "fallback=$fb" >/dev/null || true
    return 1
  fi
  return 0
}

ln7_oneshot_mark_consume() {
  # Call after successful train/register when ONESHOT_ARMED exists
  local armed="${LN7_GPU_WATCH_STATE_DIR}/ONESHOT_ARMED"
  [[ -f "$armed" ]] || return 0
  local size region id
  size="$(sed -n 's/^size=//p' "$armed" | head -1)"
  region="$(sed -n 's/^region=//p' "$armed" | head -1)"
  id="$(sed -n 's/^id=//p' "$armed" | head -1)"
  ln7_oneshot_telemetry oneshot_consume \
    "size=${size:-}" "region=${region:-}" "droplet_id=${id:-}" \
    "revision_id=${1:-}" >/dev/null || true
  rm -f "$armed"
}
