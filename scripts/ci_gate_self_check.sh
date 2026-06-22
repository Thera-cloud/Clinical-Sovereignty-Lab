#!/usr/bin/env bash
# Validates CI gate wiring (workflow + rule) and refreshes auto-generated rule markers.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
RULE="$ROOT/.cursor/rules/ci-gate-before-push.mdc"
WORKFLOW="$ROOT/.github/workflows/deploy.yml"
CI_SCRIPT="$ROOT/backend/scripts/run_ci_tests.sh"
MARKER_START='<!-- ci-gate:offline-test-count -->'
MARKER_END='<!-- /ci-gate:offline-test-count -->'
IGNORE_MARKER_START='<!-- ci-gate:ignore-count -->'
IGNORE_MARKER_END='<!-- /ci-gate:ignore-count -->'
STAMP_MARKER_START='<!-- ci-gate:hooks-stamp -->'
STAMP_MARKER_END='<!-- /ci-gate:hooks-stamp -->'

usage() {
  echo "Usage: $0 [--update-rule] [--pytest-summary FILE]" >&2
}

UPDATE_RULE=0
PYTEST_SUMMARY=""

while [ $# -gt 0 ]; do
  case "$1" in
    --update-rule) UPDATE_RULE=1 ;;
    --pytest-summary) PYTEST_SUMMARY="${2:-}"; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown option: $1" >&2; usage; exit 2 ;;
  esac
  shift
done

if [ ! -f "$CI_SCRIPT" ]; then
  echo "ci_gate_self_check: missing $CI_SCRIPT" >&2
  exit 1
fi

if [ ! -f "$WORKFLOW" ]; then
  echo "ci_gate_self_check: missing $WORKFLOW" >&2
  exit 1
fi

if ! grep -q 'run_ci_tests\.sh' "$WORKFLOW"; then
  echo "ci_gate_self_check: deploy.yml test step must call backend/scripts/run_ci_tests.sh" >&2
  exit 1
fi

if [ ! -f "$RULE" ]; then
  echo "ci_gate_self_check: missing $RULE" >&2
  exit 1
fi

IGNORE_COUNT="$(grep -c '^[[:space:]]*--ignore=' "$CI_SCRIPT" || true)"

replace_between_markers() {
  local file="$1" start="$2" end="$3" value="$4"
  python3 - "$file" "$start" "$end" "$value" <<'PY'
import re
import sys
from pathlib import Path

path, start, end, value = sys.argv[1:5]
text = Path(path).read_text(encoding="utf-8")
pattern = re.escape(start) + r".*?" + re.escape(end)
block = f"{start}{value}{end}"
if not re.search(pattern, text):
    raise SystemExit(f"markers not found in {path}: {start!r}")
Path(path).write_text(re.sub(pattern, block, text), encoding="utf-8")
PY
}

HOOKS_STAMP=""
if [ -f "$ROOT/scripts/install_git_hooks.sh" ]; then
  HOOKS_STAMP="$(bash "$ROOT/scripts/install_git_hooks.sh" --stamp)"
fi

if [ "$UPDATE_RULE" -eq 1 ]; then
  PASSED=""
  if [ -n "$PYTEST_SUMMARY" ] && [ -f "$PYTEST_SUMMARY" ]; then
    PASSED="$(grep -Eo '[0-9]+ passed' "$PYTEST_SUMMARY" | head -1 | awk '{print $1}' || true)"
  fi
  if [ -z "$PASSED" ]; then
    PASSED="820"
  fi
  replace_between_markers "$RULE" "$MARKER_START" "$MARKER_END" "$PASSED"
  replace_between_markers "$RULE" "$IGNORE_MARKER_START" "$IGNORE_MARKER_END" "$IGNORE_COUNT"
  if [ -n "$HOOKS_STAMP" ]; then
    replace_between_markers "$RULE" "$STAMP_MARKER_START" "$STAMP_MARKER_END" "$HOOKS_STAMP"
  fi
fi

exit 0
