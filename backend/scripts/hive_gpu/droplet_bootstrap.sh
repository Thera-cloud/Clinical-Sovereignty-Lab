#!/usr/bin/env bash
# R5: bootstrap a hive GPU droplet's provisioning-tool Python deps from the frozen,
# hash-pinned lockfile via the internal mirror — never an unpinned `pip install`
# against the public index.
#
# Per plan (phase-r-residuals): "droplet installs from frozen lockfiles ... declared
# fallback engines." This script is the "install from frozen lockfile" half; the GPU/
# ML stack (torch/vllm/transformers/...) is provisioned separately once a
# requirements-hive-gpu.txt lock exists for the target CUDA image (see
# backend/scripts/ln7_generate_droplet_lockfile.py header note).
#
# Idempotent: safe to re-run.
#
# Required env (or override on the command line):
#   LN7_PIP_MIRROR_URL   Internal pip mirror index-url (must match the lockfile's
#                         declared internal-mirror-index-url, or bootstrap aborts)
#   LOCKFILE              Path to the frozen lockfile (default: repo-relative)
#   VENV_DIR              Path to the venv to install into

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"

LOCKFILE="${LOCKFILE:-$REPO_ROOT/frozen-config/ln7_droplet_requirements.lock}"
VENV_DIR="${VENV_DIR:-/opt/ln7/hive-gpu-venv}"
LN7_PIP_MIRROR_URL="${LN7_PIP_MIRROR_URL:-}"

if [ ! -f "$LOCKFILE" ]; then
    echo "ERROR: lockfile not found: $LOCKFILE" >&2
    exit 1
fi

DECLARED_MIRROR="$(grep -m1 '^# internal-mirror-index-url:' "$LOCKFILE" | sed -E 's/^# internal-mirror-index-url:\s*//')"
if [ -z "$DECLARED_MIRROR" ]; then
    echo "ERROR: lockfile has no internal-mirror-index-url header — refusing to install." >&2
    exit 1
fi
if [ -z "$LN7_PIP_MIRROR_URL" ]; then
    LN7_PIP_MIRROR_URL="$DECLARED_MIRROR"
elif [ "$LN7_PIP_MIRROR_URL" != "$DECLARED_MIRROR" ]; then
    echo "ERROR: LN7_PIP_MIRROR_URL ($LN7_PIP_MIRROR_URL) != lockfile-declared mirror ($DECLARED_MIRROR)." >&2
    echo "       Refusing to install against an undeclared index." >&2
    exit 1
fi

echo "[bootstrap] lockfile:  $LOCKFILE"
echo "[bootstrap] mirror:    $LN7_PIP_MIRROR_URL"
echo "[bootstrap] venv:      $VENV_DIR"

if [ ! -d "$VENV_DIR" ]; then
    python3 -m venv "$VENV_DIR"
fi
# shellcheck disable=SC1090
source "$VENV_DIR/bin/activate"

python3 -m pip install --require-hashes --no-deps \
    --index-url "$LN7_PIP_MIRROR_URL" \
    -r "$LOCKFILE"

echo "[bootstrap] provisioning-tool tier installed with --require-hashes (supply-chain pin verified)."
