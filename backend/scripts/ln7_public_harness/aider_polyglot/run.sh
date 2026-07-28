#!/usr/bin/env bash
# Official harness wrapper. If upstream/ exists, expect operator CLI; else schema stub.
set -euo pipefail
BENCH=aider_polyglot
HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="${LN7_PUBLIC_RESULTS_DIR:-}"
if [[ -z "$ROOT" ]]; then
  # scripts/ln7_public_harness/<bench> → repo root = ../../..
  # .ln7-harness/<bench> → repo root = ../..
  if [[ -d "$(cd "$HERE/../../docs/ln7/public_results" 2>/dev/null && pwd)" ]]; then
    ROOT="$(cd "$HERE/../../docs/ln7/public_results" && pwd)"
  else
    ROOT="$(cd "$HERE/../../../docs/ln7/public_results" && pwd)"
  fi
fi
mkdir -p "$ROOT"
OUT="$ROOT/${BENCH}.json"
UP="$HERE/upstream"
if [[ -d "$UP/.git" || -x "$UP/run_official.sh" ]]; then
  if [[ -x "$UP/run_official.sh" ]]; then
    "$UP/run_official.sh" "$OUT"
    echo "wrote $OUT (official)"
    exit 0
  fi
  cat > "$OUT" <<JSON
{"benchmark":"$BENCH","status":"blocked_needs_official_cli","mode":"full","report_only":true,"pass_rate":{"mean":0.0,"lo":0.0,"hi":0.0,"n":0},"note":"upstream/ cloned but run_official.sh missing — wire official CLI here."}
JSON
  echo "wrote $OUT (blocked)"
  exit 0
fi
cat > "$OUT" <<JSON
{"benchmark":"$BENCH","status":"ok","mode":"full_stub","report_only":true,"pass_rate":{"mean":0.0,"lo":0.0,"hi":0.0,"n":0},"note":"Stub only — clone official harness into upstream/ and add run_official.sh. Not a competitive score."}
JSON
echo "wrote $OUT (stub)"
