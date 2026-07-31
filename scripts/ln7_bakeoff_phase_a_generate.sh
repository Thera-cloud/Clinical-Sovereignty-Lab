#!/usr/bin/env bash
# Attempt 5 Phase A — generate-only on burst host, freeze, destroy.
# Default: dry-run / refuse. Paid GPU requires LN7_BURST_ALLOW_PAID=1 + row gate.
#
#   LN7_PHASE_A_DRY_RUN=1 bash scripts/ln7_bakeoff_phase_a_generate.sh
#
# QUANTUM-CRYSTAL-ARCH
set -euo pipefail
REPO="$(cd "$(dirname "$0")/.." && pwd)"
# shellcheck source=scripts/ln7_host_roles.sh
source "$REPO/scripts/ln7_host_roles.sh"

DRY="${LN7_PHASE_A_DRY_RUN:-1}"

echo "=== Attempt 5 Phase A (generate → freeze → destroy) ==="
bash "$REPO/scripts/ln7_host_roles_preflight.sh"
bash "$REPO/scripts/ln7_binary_audit_preflight.sh"

if [[ "$DRY" == "1" || "$DRY" == "true" ]]; then
  echo "PHASE_A_DRY_RUN=PASS (no droplet; freeze path is local fixture / Phase B)"
  echo "Paid launch still requires: ≥300 organic G1 rows + reviewed patch + LN7_BURST_ALLOW_PAID=1"
  exit 0
fi

ln7_assert_paid_burst_allowed || {
  echo "FATAL: paid Phase A refused (gate)" >&2
  exit 10
}

echo "FATAL: live Phase A generate-on-droplet not wired in this engineering cut." >&2
echo "Use fixture freeze + Phase B until organic G1 ≥300 and generate path lands on main." >&2
exit 11
