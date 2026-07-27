#!/usr/bin/env bash
# Official harness wrapper — replace body with SWE-bench / LCB / Aider / Terminal-Bench CLI.
# Must write $LN7_PUBLIC_RESULTS_DIR/aider_polyglot.json (or repo docs/ln7/public_results/aider_polyglot.json).
set -euo pipefail
ROOT="${LN7_PUBLIC_RESULTS_DIR:-}"
if [[ -z "$ROOT" ]]; then
  ROOT="$(cd "$(dirname "$0")/../../../.." && pwd)/docs/ln7/public_results"
fi
mkdir -p "$ROOT"
OUT="$ROOT/aider_polyglot.json"
cat > "$OUT" <<'JSON'
{"benchmark":"aider_polyglot","status":"ok","mode":"full","report_only":true,"pass_rate":{"mean":0.0,"lo":0.0,"hi":0.0,"n":0},"note":"Replace run.sh with official harness; this stub records schema only."}
JSON
echo "wrote $OUT"
