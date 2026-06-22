#!/usr/bin/env bash
# Pre-push CI gate — same suite as GitHub Actions deploy.yml test job.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

# Refresh hook entrypoints when installer or gate scripts change.
bash "$ROOT/scripts/install_git_hooks.sh" --sync

bash "$ROOT/scripts/ci_gate_self_check.sh"

TMP_SUMMARY="$(mktemp)"
trap 'rm -f "$TMP_SUMMARY"' EXIT

set +e
bash "$ROOT/backend/scripts/run_ci_tests.sh" 2>&1 | tee "$TMP_SUMMARY"
RC=${PIPESTATUS[0]}
set -e

if [ "$RC" -ne 0 ]; then
  echo "" >&2
  echo "pre-push CI gate FAILED (exit $RC). Fix tests or update backend/scripts/run_ci_tests.sh ignores." >&2
  echo "Push blocked — matches GitHub Actions deploy.yml test job." >&2
  exit "$RC"
fi

bash "$ROOT/scripts/ci_gate_self_check.sh" --update-rule --pytest-summary "$TMP_SUMMARY"

if ! git diff --quiet -- "$ROOT/.cursor/rules/ci-gate-before-push.mdc" 2>/dev/null; then
  echo "ci-gate rule auto-updated (.cursor/rules/ci-gate-before-push.mdc). Stage and commit if counts changed." >&2
fi

exit 0
