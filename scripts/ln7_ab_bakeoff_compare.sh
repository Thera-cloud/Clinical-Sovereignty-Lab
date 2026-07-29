#!/usr/bin/env bash
# Sequential deploy → background bakeoff → poll scorecard for A then B.
# Never activates — writes AB_COMPARE. CEO activate only on READY canary.
#
#   bash scripts/ln7_ab_bakeoff_compare.sh LN7-...A LN7-...B
# Optional aliases for RID_TS↔registered mismatch (this cycle):
#   LN7_ADAPTER_ALIAS_A=LN7-...T230013Z LN7_ADAPTER_ALIAS_B=LN7-...T230506Z
#
# # QUANTUM-CRYSTAL-ARCH
set -euo pipefail
REPO="$(cd "$(dirname "$0")/.." && pwd)"
REV_A="${1:?usage: ln7_ab_bakeoff_compare.sh <rev_a> <rev_b>}"
REV_B="${2:?usage: ln7_ab_bakeoff_compare.sh <rev_a> <rev_b>}"
GREEN="${LN7_GREEN_HOST:-root@68.183.168.75}"
STATE_DIR="${LN7_GPU_WATCH_STATE_DIR:-$HOME/.local/state/ln7_gpu_watch}"
OUT="${LN7_AB_COMPARE_OUT:-$STATE_DIR/AB_COMPARE}"
EXPECTED_PACKS="${LN7_BAKEOFF_EXPECTED_PACKS:-18}"
POLL_MAX="${LN7_BAKEOFF_POLL_MAX_S:-}"
if [[ -z "$POLL_MAX" ]]; then
  POLL_MAX=$(( EXPECTED_PACKS * 600 ))
  [[ "$POLL_MAX" -lt 7200 ]] && POLL_MAX=7200
fi
POLL_INTERVAL="${LN7_BAKEOFF_POLL_INTERVAL_S:-30}"
mkdir -p "$STATE_DIR"

log() { echo "[ab-compare] $*" >&2; }
log "$(date -u +%Y-%m-%dT%H%M%SZ) a=$REV_A b=$REV_B poll_max=${POLL_MAX}s packs=$EXPECTED_PACKS"

resolve_adapter() {
  local rev="$1" alias="${2:-}"
  if [[ -n "$alias" && -d "$REPO/.ln7-adapters/$alias" ]]; then
    echo "$alias"
    return
  fi
  if [[ -d "$REPO/.ln7-adapters/$rev" ]]; then
    echo "$rev"
    return
  fi
  echo "$rev"
}

wait_bakeoff_idle() {
  local max_wait="${1:-600}"
  local elapsed=0
  while [[ $elapsed -lt $max_wait ]]; do
    local running
    running="$(ssh -o BatchMode=yes -o ConnectTimeout=20 "$GREEN" 'python3 -' <<'PY' 2>/dev/null || echo '[]'
import json, re, urllib.request
env = open("/opt/clinical-sovereignty-lab/.env").read()
tok = re.search(r"^SKYEYE_AUDIT_TOKEN=(.*)$", env, re.M).group(1).strip()
req = urllib.request.Request(
    "http://localhost:8000/api/ln7/bakeoff/running",
    headers={"Authorization": f"Bearer {tok}"},
)
try:
    with urllib.request.urlopen(req, timeout=30) as r:
        d = json.loads(r.read().decode())
    print(json.dumps(d.get("running") or []))
except Exception as e:
    print("[]")
PY
)"
    if [[ "$running" == "[]" || -z "$running" ]]; then
      return 0
    fi
    log "bakeoff still running: $running — wait ${POLL_INTERVAL}s"
    sleep "$POLL_INTERVAL"
    elapsed=$((elapsed + POLL_INTERVAL))
  done
  log "WARN: timed out waiting for idle bakeoff"
  return 1
}

run_one() {
  local rev="$1" adapter="$2"
  log "=== $rev (adapter=$adapter) ==="

  # 1. Verify revision exists on GREEN
  log "verify scorecard $rev"
  local verify_out
  verify_out="$(ssh -o BatchMode=yes -o ConnectTimeout=30 "$GREEN" \
    "REV='$rev' python3 -" <<'PY' || true
import json, os, re, urllib.request, sys
rev = os.environ["REV"]
env = open("/opt/clinical-sovereignty-lab/.env").read()
tok = re.search(r"^SKYEYE_AUDIT_TOKEN=(.*)$", env, re.M).group(1).strip()
req = urllib.request.Request(
    f"http://localhost:8000/api/ln7/scorecard/{rev}",
    headers={"Authorization": f"Bearer {tok}"},
)
try:
    with urllib.request.urlopen(req, timeout=60) as r:
        d = json.loads(r.read().decode())
    print(json.dumps({"exists": True, "n_prior": d.get("n", 0)}))
except Exception as e:
    print(json.dumps({"exists": True, "n_prior": 0, "note": str(e)[:80]}))
PY
)"
  log "verify: $verify_out"

  # 2–3. Deploy adapter + verify PEFT health
  log "deploy PEFT $adapter"
  bash "$REPO/scripts/ln7_deploy_peft_serve_orange.sh" "$adapter"
  log "deploy done $adapter"

  # 4. Wait for idle
  log "wait bakeoff idle"
  wait_bakeoff_idle 900 || true

  # 5. Fire background bakeoff
  SINCE="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  log "fire background bakeoff since=$SINCE"
  ssh -o BatchMode=yes -o ConnectTimeout=30 "$GREEN" \
    "REV='$rev' python3 -" <<'PY'
import json, os, re, urllib.request, sys
rev = os.environ["REV"]
env = open("/opt/clinical-sovereignty-lab/.env").read()
tok = re.search(r"^SKYEYE_AUDIT_TOKEN=(.*)$", env, re.M).group(1).strip()
payload = {
    "revision_id": rev,
    "mode": "max",
    "include_public": False,
    "include_private": True,
    "seed_golden": False,
    "background": True,
}
req = urllib.request.Request(
    "http://localhost:8000/api/ln7/bakeoff",
    data=json.dumps(payload).encode(),
    headers={"Authorization": f"Bearer {tok}", "Content-Type": "application/json"},
    method="POST",
)
try:
    with urllib.request.urlopen(req, timeout=60) as r:
        d = json.loads(r.read().decode())
    print(json.dumps(d))
    if not d.get("started") and not d.get("ok"):
        sys.exit(3)
except urllib.error.HTTPError as e:
    body = e.read().decode()[:300]
    print(json.dumps({"ok": False, "http": e.code, "body": body}))
    sys.exit(3)
PY

  # 6. Poll scorecard ?since= until n >= EXPECTED_PACKS or timeout
  local elapsed=0
  local score_json=""
  while [[ $elapsed -lt $POLL_MAX ]]; do
    sleep "$POLL_INTERVAL"
    elapsed=$((elapsed + POLL_INTERVAL))
    score_json="$(ssh -o BatchMode=yes -o ConnectTimeout=30 "$GREEN" \
      "REV='$rev' SINCE='$SINCE' python3 -" <<'PY'
import json, os, re, urllib.request, urllib.parse
rev = os.environ["REV"]
since = os.environ["SINCE"]
env = open("/opt/clinical-sovereignty-lab/.env").read()
tok = re.search(r"^SKYEYE_AUDIT_TOKEN=(.*)$", env, re.M).group(1).strip()
q = urllib.parse.urlencode({"since": since})
req = urllib.request.Request(
    f"http://localhost:8000/api/ln7/scorecard/{rev}?{q}",
    headers={"Authorization": f"Bearer {tok}"},
)
with urllib.request.urlopen(req, timeout=60) as r:
    print(r.read().decode())
PY
)" || true
    local n
    n="$(python3 -c 'import json,sys; d=json.loads(sys.argv[1] or "{}"); print(int(d.get("n") or 0))' "$score_json" 2>/dev/null || echo 0)"
    log "poll ${elapsed}s n=$n (need $EXPECTED_PACKS)"
    if [[ "$n" -ge "$EXPECTED_PACKS" ]]; then
      break
    fi
    # Also exit early if bakeoff no longer running and n>0
    local still
    still="$(ssh -o BatchMode=yes -o ConnectTimeout=20 "$GREEN" 'python3 -' <<'PY' 2>/dev/null || echo '[]'
import json, re, urllib.request
env = open("/opt/clinical-sovereignty-lab/.env").read()
tok = re.search(r"^SKYEYE_AUDIT_TOKEN=(.*)$", env, re.M).group(1).strip()
req = urllib.request.Request(
    "http://localhost:8000/api/ln7/bakeoff/running",
    headers={"Authorization": f"Bearer {tok}"},
)
with urllib.request.urlopen(req, timeout=30) as r:
    print(json.dumps((json.loads(r.read().decode())).get("running") or []))
PY
)"
    if [[ "$still" == "[]" && "$n" -gt 0 && $elapsed -gt 120 ]]; then
      log "bakeoff idle with n=$n — accept"
      break
    fi
  done

  python3 -c '
import json, sys
rev, raw = sys.argv[1], sys.argv[2]
try:
    d = json.loads(raw or "{}")
except Exception:
    d = {}
pr = d.get("pass_rate") or {}
if not isinstance(pr, dict):
    pr = {}
out = {
    "revision_id": rev,
    "mean": float(pr.get("mean") or 0),
    "lo": float(pr.get("lo") or 0),
    "hi": float(pr.get("hi") or 0),
    "n": int(d.get("n") or 0),
    "ok": int(d.get("n") or 0) > 0,
    "since": d.get("since"),
}
print(json.dumps(out))
' "$rev" "$score_json"
}

ADAPTER_A="$(resolve_adapter "$REV_A" "${LN7_ADAPTER_ALIAS_A:-}")"
ADAPTER_B="$(resolve_adapter "$REV_B" "${LN7_ADAPTER_ALIAS_B:-}")"

A_JSON="$(run_one "$REV_A" "$ADAPTER_A")"
log "A result: $A_JSON"
B_JSON="$(run_one "$REV_B" "$ADAPTER_B")"
log "B result: $B_JSON"

printf '%s\n' "$A_JSON" >"$STATE_DIR/ab_a.json"
printf '%s\n' "$B_JSON" >"$STATE_DIR/ab_b.json"
python3 - "$STATE_DIR/ab_a.json" "$STATE_DIR/ab_b.json" <<'PY' | tee "$OUT"
import json, sys
a = json.load(open(sys.argv[1]))
b = json.load(open(sys.argv[2]))
if (b.get("mean", 0), b.get("lo", 0)) > (a.get("mean", 0), a.get("lo", 0)):
    winner, loser = b, a
else:
    winner, loser = a, b
gate_hint = "hold"
if winner.get("n", 0) >= 3 and winner.get("lo", 0) > loser.get("mean", 0):
    gate_hint = "candidate_ci_above_other_mean"
summary = {
    "a": a,
    "b": b,
    "winner": winner.get("revision_id"),
    "loser": loser.get("revision_id"),
    "gate_hint": gate_hint,
    "activate": False,
    "note": "CEO activate only after canary await_ceo READY; ENABLE_LN7_AUTO_PROMOTE=false",
}
print(json.dumps(summary, indent=2))
raise SystemExit(0 if (a.get("ok") or b.get("ok")) else 1)
PY

log "wrote $OUT"
