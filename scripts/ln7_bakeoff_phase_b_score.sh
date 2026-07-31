#!/usr/bin/env bash
# Attempt 5 Phase B — score a frozen completion set (zero GPU).
#
#   bash scripts/ln7_bakeoff_phase_b_score.sh path/to/frozen.jsonl
#
# QUANTUM-CRYSTAL-ARCH
set -euo pipefail
REPO="$(cd "$(dirname "$0")/.." && pwd)"
FROZEN="${1:?usage: ln7_bakeoff_phase_b_score.sh <frozen.jsonl>}"
export PYTHONPATH="${REPO}/backend${PYTHONPATH:+:$PYTHONPATH}"
SMOKE_N="${LN7_PHASE_B_SMOKE_N:-5}"

PY="$REPO/.venv/bin/python"
[[ -x "$PY" ]] || PY="$(command -v python3)"

"$PY" - "$FROZEN" "$SMOKE_N" <<'PY'
import json
import sys
from pathlib import Path

from app.services.ln7_decoupled_bakeoff import load_frozen_set, run_phase_b

path = Path(sys.argv[1])
smoke_n = int(sys.argv[2])
rows = load_frozen_set(path)
real_n = sum(1 for r in rows if not r.is_anchor)
smoke_n = min(smoke_n, real_n)
out = run_phase_b(rows, smoke_n=smoke_n)
print(json.dumps(out["verdict"], indent=2))
assert out["ok"] and out["verdict"].get("bakeoff_verdict")
print("PHASE_B_SCORE=PASS", "winner=", out["verdict"]["winner"])
PY
