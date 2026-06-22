#!/bin/bash
# Back-compat wrapper — installs pre-commit + pre-push CI gate hooks.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
exec bash "$ROOT/scripts/install_git_hooks.sh" install
