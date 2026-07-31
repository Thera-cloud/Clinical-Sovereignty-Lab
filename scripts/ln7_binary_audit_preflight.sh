#!/usr/bin/env bash
# QUANTUM-CRYSTAL-ARCH — Attempt 4 binary/script audit ($0 GPU).
# Fail-closed scan of LN7 orch scripts for host-role seam patterns.
#
#   bash scripts/ln7_binary_audit_preflight.sh
#
set -euo pipefail
REPO="$(cd "$(dirname "$0")/.." && pwd)"
FAILS=0
pass() { echo "PASS $*"; }
fail() { echo "FAIL $*"; FAILS=$((FAILS + 1)); }

SCRIPTS=(
  "$REPO/scripts/ln7_host_roles.sh"
  "$REPO/scripts/ln7_host_roles_preflight.sh"
  "$REPO/scripts/ln7_hive_burst.sh"
  "$REPO/scripts/ln7_ab_bakeoff_compare.sh"
  "$REPO/scripts/ln7_destroy_cuda_droplet.sh"
  "$REPO/scripts/ln7_binary_audit_preflight.sh"
  "$REPO/scripts/ln7_bakeoff_phase_a_generate.sh"
  "$REPO/scripts/ln7_bakeoff_phase_b_score.sh"
  "$REPO/scripts/ln7_penny_droplet_rehearsal.sh"
)

echo "=== LN7 binary/script audit (host-role seams) ==="

for f in "${SCRIPTS[@]}"; do
  [[ -f "$f" ]] || { fail "missing $f"; continue; }
  bash -n "$f" || fail "bash -n $(basename "$f")"
done
pass "bash -n all audited scripts"

# Contract library must define the three named roles
src="$REPO/scripts/ln7_host_roles.sh"
for needle in LN7_AUTH_BASE LN7_ORCH_HOST LN7_BURST_SSH ln7_assert_not_loopback_ssh ln7_destroy_droplet_verified; do
  grep -q "$needle" "$src" || fail "host_roles missing $needle"
done
pass "host_roles defines AUTH_BASE/ORCH_HOST/BURST_SSH + loopback + verified destroy"
grep -q 'ln7_doctl_droplet_scope_ok' "$src" || fail "host_roles missing droplet-scope auth probe"
if grep -nE 'doctl[[:space:]]+account[[:space:]]+get' "$src" \
  "$REPO/scripts/ln7_penny_droplet_rehearsal.sh" 2>/dev/null \
  | grep -vE '^\s*#|Never |never '; then
  fail "doctl account endpoint still invoked (use droplet-scope probe)"
else
  pass "auth probes are droplet-scoped (no account endpoint)"
fi

# Burst must source host roles and gate paid provision
burst="$REPO/scripts/ln7_hive_burst.sh"
grep -q 'ln7_host_roles.sh' "$burst" || fail "hive_burst does not source host_roles"
grep -q 'ln7_assert_paid_burst_allowed' "$burst" || fail "hive_burst missing paid gate"
grep -q 'green_run' "$burst" || fail "hive_burst missing green_run (no SSH-to-self)"
grep -q 'ln7_destroy_droplet_verified\|ln7_set_burst_ssh' "$burst" || fail "hive_burst missing burst SSH/destroy contract"
pass "hive_burst wired to host-role contract"

# Forbidden: assigning BURST_SSH from GREEN_HOST (role collapse)
# Allow comments; flag real assignments.
if grep -nE '^\s*(export\s+)?LN7_BURST_SSH=.*GREEN' "$REPO"/scripts/ln7_*.sh 2>/dev/null | grep -vE '^\s*#|refuse|never|NOT'; then
  fail "LN7_BURST_SSH assigned from GREEN*"
else
  pass "no BURST_SSH←GREEN assignment"
fi

# Forbidden: SSH to loopback as operational GREEN peer outside refuse paths
# (preflight may set poison LN7_GREEN_HOST=root@127.0.0.1 to assert refuse)
if grep -nE 'ssh\s+.*root@127\.0\.0\.1' "$REPO"/scripts/ln7_hive_burst.sh "$REPO"/scripts/ln7_ab_bakeoff_compare.sh 2>/dev/null; then
  fail "operational script SSHes root@127.0.0.1"
else
  pass "burst/compare do not SSH loopback"
fi

# Destroy path must not "ANOMALY then exit" without verified-gone
if grep -q 'billing_resource_still_alive' "$src" && grep -q 'ln7_destroy_droplet_verified' "$src"; then
  pass "destroy path retains verified-gone + billing alive anomaly"
else
  fail "destroy verified path incomplete"
fi

# Attempt 5: required host tools (fail-closed). macOS: accept gtimeout (coreutils).
if command -v timeout >/dev/null 2>&1; then
  pass "tool timeout ($(command -v timeout))"
elif command -v gtimeout >/dev/null 2>&1; then
  pass "tool gtimeout ($(command -v gtimeout)) [darwin coreutils]"
elif [[ "$(uname -s)" == "Darwin" && "${LN7_REQUIRE_TIMEOUT:-0}" != "1" ]]; then
  pass "tool timeout absent on Darwin (optional; brew install coreutils → gtimeout)"
else
  fail "missing required tool: timeout (or gtimeout)"
fi
for bin in jq curl python3 rsync; do
  if command -v "$bin" >/dev/null 2>&1; then
    pass "tool $bin ($(command -v "$bin"))"
  else
    fail "missing required tool: $bin"
  fi
done
if command -v doctl >/dev/null 2>&1; then
  pass "doctl present ($(command -v doctl))"
elif [[ "${LN7_REQUIRE_DOCTL:-0}" == "1" ]]; then
  fail "missing required tool: doctl (LN7_REQUIRE_DOCTL=1)"
else
  pass "doctl absent (CI/offline ok; set LN7_REQUIRE_DOCTL=1 for penny/Phase A host)"
fi

# Phase A must stay dry/gated by default
phase_a="$REPO/scripts/ln7_bakeoff_phase_a_generate.sh"
grep -q 'LN7_BURST_ALLOW_PAID\|ln7_assert_paid_burst_allowed' "$phase_a" \
  || fail "phase_a missing paid gate"
grep -q 'LN7_PHASE_A_DRY_RUN' "$phase_a" || fail "phase_a missing dry-run default"
pass "phase_a dry-run + paid gate present"

echo "=== RESULT fails=$FAILS ==="
[[ "$FAILS" -eq 0 ]] || exit 1
echo "BINARY_AUDIT_PREFLIGHT=PASS"
