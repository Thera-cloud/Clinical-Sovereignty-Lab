#!/usr/bin/env bash
# Offline self-test: three dead-man cases — no droplet, no money.
#   A) HB exists + stale mtime → age printed, rc=0 (legitimate re-dispatch path)
#   B) HB absent → rc=1 + alarm, freeze
#   C) State I/O fail (read-only dir) → probe_io fails, freeze
#
# Usage: bash scripts/ln7_watchdog_blind_selftest.sh
# # QUANTUM-CRYSTAL-ARCH
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
# shellcheck disable=SC1091
source "$ROOT/scripts/ln7_watchdog_observability.sh"

TMP="$(mktemp -d "${TMPDIR:-/tmp}/ln7_wd_selftest.XXXXXX")"
cleanup() {
  chmod -R u+w "$TMP" 2>/dev/null || true
  rm -rf "$TMP"
}
trap cleanup EXIT

export LN7_GPU_WATCH_STATE_DIR="$TMP/state"
mkdir -p "$LN7_GPU_WATCH_STATE_DIR"
pass=0
fail=0

ok() { echo "PASS: $*"; pass=$((pass + 1)); }
bad() { echo "FAIL: $*"; fail=$((fail + 1)); }

# ── Case A: positive staleness ───────────────────────────────────────────────
HB="$LN7_GPU_WATCH_STATE_DIR/COMPARE_HEARTBEAT"
echo "phase=running ts=old" >"$HB"
# Age via utime only (macOS touch -t + UTC date string can land in the future)
python3 -c "import os,time; p=r'$HB'; t=time.time()-7200; os.utime(p, (t, t))"
age="$(ln7_wd_hb_age "$HB")" && rc=0 || rc=$?
if [[ "$rc" -eq 0 && "${age:-0}" -ge 600 ]]; then
  ok "Case A positive stale age=${age}s rc=0"
else
  bad "Case A expected rc=0 age>=600 got rc=$rc age=${age:-none}"
fi

# ── Case B: heartbeat absent ─────────────────────────────────────────────────
rm -f "$HB"
rm -f "$LN7_GPU_WATCH_STATE_DIR/WATCHDOG_BLIND_ALARM"
age="$(ln7_wd_hb_age "$HB")" && rc=0 || rc=$?
if [[ "$rc" -eq 1 ]]; then
  ln7_wd_alarm "hb_absent" "selftest_case_b"
  if [[ -f "$LN7_GPU_WATCH_STATE_DIR/WATCHDOG_BLIND_ALARM" ]]; then
    ok "Case B absent → rc=1 + alarm marker"
  else
    bad "Case B alarm marker missing"
  fi
else
  bad "Case B expected rc=1 got rc=$rc"
fi

# Simulate watchdog early-exit: with absent HB, ab-compare must not launch.
# We only assert helpers + that operator would freeze (no COMPARE_LOCK money path).
if ! ln7_wd_probe_io; then
  bad "Case B unexpectedly blind on writable dir"
else
  ok "Case B state I/O still healthy (absent ≠ blind I/O)"
fi

# ── Case C: watchdog own I/O fails ───────────────────────────────────────────
RO="$TMP/readonly_state"
mkdir -p "$RO"
# Populate then freeze writes
touch "$RO/.keep"
chmod a-w "$RO"
export LN7_GPU_WATCH_STATE_DIR="$RO"
if ln7_wd_probe_io; then
  # Some systems allow write via ownership quirks — try file chmod instead
  chmod u+w "$RO" 2>/dev/null || true
  echo x >"$RO/block" 2>/dev/null || true
  chmod 000 "$RO/block" 2>/dev/null || true
  # Force fail path: non-writable nested probe by making dir 555
  chmod 555 "$RO"
  if ln7_wd_probe_io; then
    bad "Case C probe_io unexpectedly succeeded on read-only dir"
  else
    ok "Case C state I/O fail → freeze (probe_io=1)"
  fi
else
  ok "Case C state I/O fail → freeze (probe_io=1)"
fi
chmod u+w "$RO" 2>/dev/null || true

# ── Case B′: unreadable heartbeat ────────────────────────────────────────────
export LN7_GPU_WATCH_STATE_DIR="$TMP/state2"
mkdir -p "$LN7_GPU_WATCH_STATE_DIR"
HB2="$LN7_GPU_WATCH_STATE_DIR/COMPARE_HEARTBEAT"
echo "phase=running" >"$HB2"
chmod 000 "$HB2"
age="$(ln7_wd_hb_age "$HB2")" && rc=0 || rc=$?
chmod 644 "$HB2" 2>/dev/null || true
if [[ "$rc" -eq 2 ]]; then
  ok "Case B′ unreadable HB → rc=2"
else
  # root may still read mode 000 — accept if we are root and note soft-pass
  if [[ "$(id -u)" -eq 0 && "$rc" -eq 0 ]]; then
    ok "Case B′ skipped under uid0 (mode 000 still readable)"
  else
    bad "Case B′ expected rc=2 got rc=$rc"
  fi
fi

# ── Integration: ab-compare watchdog early freeze with WORKER_PAUSED ─────────
export LN7_GPU_WATCH_STATE_DIR="$TMP/integ"
mkdir -p "$LN7_GPU_WATCH_STATE_DIR"
echo "selftest_pause" >"$LN7_GPU_WATCH_STATE_DIR/WORKER_PAUSED"
echo "phase=running" >"$LN7_GPU_WATCH_STATE_DIR/COMPARE_HEARTBEAT"
# Point REPO at this workspace so sourced helper matches
export LN7_SOVEREIGN_HOME="$ROOT"
# Stub GREEN ssh so pick_next never fires if freeze fails
export PATH="$TMP/bin:$PATH"
mkdir -p "$TMP/bin"
printf '#!/bin/bash\necho STUB_SSH_SHOULD_NOT_RUN >&2; exit 99\n' >"$TMP/bin/ssh"
chmod +x "$TMP/bin/ssh"
set +e
out="$(LN7_COMPARE_HEARTBEAT_STALE_S=1 bash "$ROOT/scripts/ln7_ab_compare_watchdog.sh" 2>&1)"
rc=$?
set -e
if [[ "$rc" -eq 0 ]] && echo "$out" | grep -qiE 'WORKER_PAUSED|freeze|operator hold'; then
  ok "Integration: ab-compare freezes on WORKER_PAUSED (no ssh)"
else
  bad "Integration: ab-compare did not freeze (rc=$rc) out=$(echo "$out" | tail -3)"
fi
if echo "$out" | grep -q STUB_SSH_SHOULD_NOT_RUN; then
  bad "Integration: watchdog attempted SSH despite pause"
else
  ok "Integration: no money-path SSH under pause"
fi

echo "───"
echo "results: pass=$pass fail=$fail"
[[ "$fail" -eq 0 ]]
