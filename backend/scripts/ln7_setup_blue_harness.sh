#!/usr/bin/env bash
# Scaffold LN7 public harness root on BLUE (never GREEN).
# Official clones are optional — stubs write ingest-ready JSON until operators clone.
set -euo pipefail
ROOT="${1:-$HOME/ln7-harness}"
REPO="$(cd "$(dirname "$0")/../.." && pwd)"
SRC="$REPO/backend/scripts/ln7_public_harness"
mkdir -p "$ROOT"
for bench in swe_bench_verified livecodebench aider_polyglot terminal_bench; do
  mkdir -p "$ROOT/$bench"
  cp -f "$SRC/$bench/run.sh" "$ROOT/$bench/run.sh"
  chmod +x "$ROOT/$bench/run.sh"
done
cat > "$ROOT/README.md" <<EOF
# LN7 public harness root (BLUE)

Created by ln7_setup_blue_harness.sh

Replace each run.sh body with the official harness CLI, or clone under:
  $ROOT/<bench>/upstream/

Then:
  LN7_PUBLIC_HARNESS_MODE=full LN7_PUBLIC_HARNESS_ROOT=$ROOT \\
    LN7_PUBLIC_RESULTS_DIR=$REPO/docs/ln7/public_results \\
    PYTHONPATH=$REPO/backend python $REPO/backend/scripts/ln7_run_public_benches.py --write

Copy JSON to GREEN docs/ln7/public_results/ and set LN7_PUBLIC_HARNESS_MODE=ingest.
EOF
echo "harness_root=$ROOT"
ls -la "$ROOT"/*/run.sh
