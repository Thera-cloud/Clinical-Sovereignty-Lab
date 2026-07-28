#!/usr/bin/env bash
# Private-pack bakeoff for A/B shadow revisions; pick winner by mean (CI lo as tie-break).
# Never activates — writes AB_COMPARE. CEO activate only on READY canary.
#
#   bash scripts/ln7_ab_bakeoff_compare.sh LN7-...A LN7-...B
#
# # QUANTUM-CRYSTAL-ARCH
set -euo pipefail
REV_A="${1:?usage: ln7_ab_bakeoff_compare.sh <rev_a> <rev_b>}"
REV_B="${2:?usage: ln7_ab_bakeoff_compare.sh <rev_a> <rev_b>}"
GREEN="${LN7_GREEN_HOST:-root@68.183.168.75}"
STATE_DIR="${LN7_GPU_WATCH_STATE_DIR:-$HOME/.local/state/ln7_gpu_watch}"
OUT="${LN7_AB_COMPARE_OUT:-$STATE_DIR/AB_COMPARE}"
mkdir -p "$STATE_DIR"

echo "[ab-compare] $(date -u +%Y-%m-%dT%H%M%SZ) a=$REV_A b=$REV_B"

ssh -o BatchMode=yes -o ConnectTimeout=30 "$GREEN" \
  "REV_A='$REV_A' REV_B='$REV_B' python3 -" <<'PY' | tee "$OUT"
import json, os, re, urllib.request, sys

rev_a = os.environ["REV_A"]
rev_b = os.environ["REV_B"]
env = open("/opt/clinical-sovereignty-lab/.env").read()
tok = re.search(r"^SKYEYE_AUDIT_TOKEN=(.*)$", env, re.M).group(1).strip()

def post(path, payload, timeout=900):
    req = urllib.request.Request(
        f"http://localhost:8000{path}",
        data=json.dumps(payload).encode(),
        headers={"Authorization": f"Bearer {tok}", "Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())

def mean_of(rid):
    out = post("/api/ln7/bakeoff", {
        "revision_id": rid,
        "mode": "max",
        "include_public": False,
        "include_private": True,
        "seed_golden": False,
    })
    pr = (out.get("private") or {}).get("pass_rate") or {}
    if not isinstance(pr, dict):
        pr = {}
    return {
        "revision_id": rid,
        "mean": float(pr.get("mean") or 0),
        "lo": float(pr.get("lo") or 0),
        "hi": float(pr.get("hi") or 0),
        "n": int(pr.get("n") or 0),
        "ok": bool(out.get("ok")),
        "ceo_notify": out.get("ceo_notify"),
    }

a = mean_of(rev_a)
b = mean_of(rev_b)
if (b["mean"], b["lo"]) > (a["mean"], a["lo"]):
    winner, loser = b, a
else:
    winner, loser = a, b
gate_hint = "hold"
if winner["n"] >= 3 and winner["lo"] > loser["mean"]:
    gate_hint = "candidate_ci_above_other_mean"
summary = {
    "a": a,
    "b": b,
    "winner": winner["revision_id"],
    "loser": loser["revision_id"],
    "gate_hint": gate_hint,
    "activate": False,
    "note": "CEO activate only after canary await_ceo READY; ENABLE_LN7_AUTO_PROMOTE=false",
}
print(json.dumps(summary, indent=2))
sys.exit(0 if (a.get("ok") or b.get("ok")) else 1)
PY

echo "[ab-compare] wrote $OUT"
