#!/usr/bin/env bash
# QUANTUM-CRYSTAL-ARCH — Attempt 4 offline preflight: host-role matrix + destroy path.
# $0 GPU. Both orchestration shapes must pass identical assertions.
#
#   bash scripts/ln7_host_roles_preflight.sh
#
set -euo pipefail
REPO="$(cd "$(dirname "$0")/.." && pwd)"
# shellcheck source=scripts/ln7_host_roles.sh
source "$REPO/scripts/ln7_host_roles.sh"

FAILS=0
pass() { echo "PASS $*"; }
fail() { echo "FAIL $*"; FAILS=$((FAILS + 1)); }

assert_refuse_loopback() {
  local label="$1" spec="$2"
  if ln7_assert_not_loopback_ssh "$spec" "$label" 2>/dev/null; then
    fail "$label accepted loopback $spec"
  else
    pass "$label refuses loopback $spec"
  fi
}

echo "=== LN7 host-role matrix (offline) ==="

# --- Shape A: BLUE orch → remote GREEN SSH + droplet BURST_SSH -------------
export LN7_ORCH_HOST=blue
export LN7_GREEN_HOST=root@68.183.168.75
unset LN7_AUTH_BASE || true
ln7_resolve_host_roles
[[ "$LN7_GREEN_EXEC_MODE" == "ssh" ]] || fail "blue orch exec_mode=$LN7_GREEN_EXEC_MODE want=ssh"
[[ "$LN7_GREEN_SSH" == "root@68.183.168.75" ]] || fail "blue orch GREEN_SSH=$LN7_GREEN_SSH"
[[ "$LN7_AUTH_BASE" == https://* || "$LN7_AUTH_BASE" == http://* ]] || fail "blue AUTH_BASE=$LN7_AUTH_BASE"
pass "shape_blue orch=blue exec=ssh auth=$LN7_AUTH_BASE"
assert_refuse_loopback "shape_blue_green" "root@127.0.0.1"
if ln7_set_burst_ssh "203.0.113.10" 2>/dev/null && [[ "$LN7_BURST_SSH" == "root@203.0.113.10" ]]; then
  pass "BURST_SSH set from handoff ip=203.0.113.10"
else
  fail "BURST_SSH reject/set failed for TEST-NET ip"
fi
if ln7_set_burst_ssh "127.0.0.1" 2>/dev/null; then
  fail "shape_blue accepted BURST_SSH loopback"
else
  pass "shape_blue refuses BURST_SSH loopback"
fi

# --- Shape B: GREEN orch → local AUTH, SSH only to droplet ------------------
export LN7_ORCH_HOST=green
export LN7_GREEN_HOST=root@127.0.0.1   # poison — must NOT become SSH peer
unset LN7_AUTH_BASE || true
ln7_resolve_host_roles
[[ "$LN7_GREEN_EXEC_MODE" == "local" ]] || fail "green orch exec_mode=$LN7_GREEN_EXEC_MODE want=local"
[[ -z "${LN7_GREEN_SSH:-}" ]] || fail "green orch must leave GREEN_SSH empty, got=$LN7_GREEN_SSH"
[[ "$LN7_AUTH_BASE" == "http://127.0.0.1:8000" ]] || fail "green AUTH_BASE=$LN7_AUTH_BASE"
pass "shape_green orch=green exec=local auth=$LN7_AUTH_BASE (ignores LN7_GREEN_HOST=127.0.0.1)"
if ln7_set_burst_ssh "159.203.38.217" 2>/dev/null; then
  pass "BURST_SSH set from handoff ip=159.203.38.217"
else
  fail "BURST_SSH set failed for droplet-shaped ip"
fi

# Seam-7 regression: blue orch + loopback GREEN_HOST must refuse
export LN7_ORCH_HOST=blue
export LN7_GREEN_HOST=root@127.0.0.1
unset LN7_AUTH_BASE || true
if ln7_resolve_host_roles 2>/dev/null; then
  fail "blue+LN7_GREEN_HOST=127.0.0.1 did not refuse"
else
  pass "blue+LN7_GREEN_HOST=127.0.0.1 refuses (seam-7 regression)"
fi

# Restore a valid blue resolve for any later checks
export LN7_ORCH_HOST=blue
export LN7_GREEN_HOST=root@68.183.168.75
ln7_resolve_host_roles >/dev/null

# --- Paid gate + PRE6 (≥300 organic; Attempt 6 bypass closed) ---------------
if LN7_BURST_DRY_RUN=0 LN7_BURST_ALLOW_PAID=0 ln7_assert_paid_burst_allowed 2>/dev/null; then
  fail "paid gate open without LN7_BURST_ALLOW_PAID"
else
  pass "paid gate closed by default"
fi
if LN7_BURST_ALLOW_PAID=1 LN7_ORGANIC_G1_COUNT=3 ln7_assert_paid_burst_allowed 2>/dev/null; then
  fail "PRE6 bypass still open (ALLOW_PAID alone / low organic)"
else
  pass "PRE6 refuses ALLOW_PAID when organic < 300"
fi
if LN7_BURST_ALLOW_PAID=1 LN7_ORGANIC_G1_COUNT=300 ln7_assert_paid_burst_allowed 2>/dev/null; then
  pass "paid gate opens with ALLOW_PAID=1 and PRE6 organic≥300"
else
  fail "paid gate stuck closed with ALLOW_PAID=1 + organic=300"
fi
if LN7_BURST_DRY_RUN=1 LN7_BURST_ALLOW_PAID=0 ln7_assert_paid_burst_allowed 2>/dev/null; then
  pass "dry-run bypasses paid gate"
else
  fail "dry-run blocked by paid gate"
fi

# --- Destroy path self-test (penny rehearsal: fake id → 404) ----------------
echo "=== destroy path self-test (penny) ==="
if ln7_destroy_path_selftest; then
  pass "destroy verified-gone for nonexistent id"
else
  fail "destroy selftest (see above)"
fi

# --- Binary/script audit ----------------------------------------------------
if bash "$REPO/scripts/ln7_binary_audit_preflight.sh"; then
  pass "binary_audit nested"
else
  fail "binary_audit nested"
fi

# --- Syntax / source sanity -------------------------------------------------
bash -n "$REPO/scripts/ln7_host_roles.sh"
bash -n "$REPO/scripts/ln7_host_roles_preflight.sh"
bash -n "$REPO/scripts/ln7_hive_burst.sh"
bash -n "$REPO/scripts/ln7_ab_bakeoff_compare.sh"
bash -n "$REPO/scripts/ln7_binary_audit_preflight.sh"
pass "bash -n host_roles + preflight + burst + compare + binary_audit"

echo "=== RESULT fails=$FAILS ==="
[[ "$FAILS" -eq 0 ]] || exit 1
echo "HOST_ROLES_PREFLIGHT=PASS"
