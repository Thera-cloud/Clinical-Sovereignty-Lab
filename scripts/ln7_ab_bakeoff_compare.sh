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
# Idle early-accept floor — must reach EXPECTED unless explicitly lowered
MIN_ACCEPT="${LN7_BAKEOFF_MIN_ACCEPT_PACKS:-$EXPECTED_PACKS}"
POLL_MAX="${LN7_BAKEOFF_POLL_MAX_S:-}"
if [[ -z "$POLL_MAX" ]]; then
  POLL_MAX=$(( EXPECTED_PACKS * 600 ))
  [[ "$POLL_MAX" -lt 7200 ]] && POLL_MAX=7200
fi
POLL_INTERVAL="${LN7_BAKEOFF_POLL_INTERVAL_S:-30}"
mkdir -p "$STATE_DIR"

log() { echo "[ab-compare] $*" >&2; }
log "$(date -u +%Y-%m-%dT%H%M%SZ) a=$REV_A b=$REV_B poll_max=${POLL_MAX}s packs=$EXPECTED_PACKS min_accept=$MIN_ACCEPT"

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

# Last JSON object from a noisy multi-line blob → single-line JSON (or ok:false stub)
_extract_json() {
  local rev="$1" raw="$2"
  python3 -c '
import json, sys
rev, raw = sys.argv[1], sys.argv[2]
last = None
for line in (raw or "").splitlines():
    s = line.strip()
    if not s or s[0] not in "{[":
        continue
    try:
        last = json.loads(s)
    except Exception:
        continue
if not isinstance(last, dict):
    last = {}
pr = last.get("pass_rate") if isinstance(last.get("pass_rate"), dict) else {}
# Accept either flattened result or raw scorecard shape
if "mean" not in last and pr:
    last = {
        "revision_id": rev,
        "mean": float(pr.get("mean") or 0),
        "lo": float(pr.get("lo") or 0),
        "hi": float(pr.get("hi") or 0),
        "n": int(last.get("n") or 0),
        "ok": int(last.get("n") or 0) > 0,
        "since": last.get("since"),
    }
out = {
    "revision_id": last.get("revision_id") or rev,
    "mean": float(last.get("mean") or 0),
    "lo": float(last.get("lo") or 0),
    "hi": float(last.get("hi") or 0),
    "n": int(last.get("n") or 0),
    "ok": bool(last.get("ok")) if "ok" in last else int(last.get("n") or 0) > 0,
    "since": last.get("since"),
}
print(json.dumps(out))
' "$rev" "$raw"
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
except Exception:
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

fire_bakeoff() {
  local rev="$1"
  ssh -o BatchMode=yes -o ConnectTimeout=30 "$GREEN" \
    "REV='$rev' python3 -" <<'PY' >&2
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
    print(json.dumps(d), flush=True)
    if not d.get("started") and not d.get("ok"):
        sys.exit(3)
except urllib.error.HTTPError as e:
    body = e.read().decode()[:300]
    print(json.dumps({"ok": False, "http": e.code, "body": body}), flush=True)
    # 409 = already running — treat as ok for poller
    if e.code != 409:
        sys.exit(3)
PY
}

run_one() {
  local rev="$1" adapter="$2"
  local result_file
  result_file="$(mktemp "${TMPDIR:-/tmp}/ln7_ab_XXXXXX.json")"
  # Always emit a JSON line to stdout (captured by caller); noise → stderr
  log "=== $rev (adapter=$adapter) ==="

  log "verify scorecard $rev"
  local verify_out
  verify_out="$(ssh -o BatchMode=yes -o ConnectTimeout=30 "$GREEN" \
    "REV='$rev' python3 -" <<'PY' || true
import json, os, re, urllib.request
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

  log "deploy PEFT $adapter"
  bash "$REPO/scripts/ln7_deploy_peft_serve_orange.sh" "$adapter" >&2
  log "deploy done $adapter"

  log "wait bakeoff idle"
  wait_bakeoff_idle 900 || true

  SINCE="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  log "fire background bakeoff since=$SINCE"
  fire_bakeoff "$rev" || log "WARN: fire_bakeoff exit $? — continuing poll"

  local elapsed=0
  local score_json="{}"
  local n=0
  local idle_streak=0
  local refires=0
  while [[ $elapsed -lt $POLL_MAX ]]; do
    sleep "$POLL_INTERVAL"
    elapsed=$((elapsed + POLL_INTERVAL))
    score_json="$(ssh -o BatchMode=yes -o ConnectTimeout=30 "$GREEN" \
      "REV='$rev' SINCE='$SINCE' python3 -" <<'PY'
import json, os, re, urllib.request, urllib.parse, sys
rev = os.environ["REV"]
since = os.environ["SINCE"]
env = open("/opt/clinical-sovereignty-lab/.env").read()
tok = re.search(r"^SKYEYE_AUDIT_TOKEN=(.*)$", env, re.M).group(1).strip()
q = urllib.parse.urlencode({"since": since})
req = urllib.request.Request(
    f"http://localhost:8000/api/ln7/scorecard/{rev}?{q}",
    headers={"Authorization": f"Bearer {tok}"},
)
try:
    with urllib.request.urlopen(req, timeout=60) as r:
        print(r.read().decode())
except Exception as e:
    print(json.dumps({"n": 0, "error": str(e)[:120]}))
PY
)" || true
    n="$(python3 -c 'import json,sys; d=json.loads(sys.argv[1] or "{}"); print(int(d.get("n") or 0))' "$score_json" 2>/dev/null || echo 0)"
    log "poll ${elapsed}s n=$n (need $EXPECTED_PACKS min_accept=$MIN_ACCEPT)"

    if [[ "$n" -ge "$EXPECTED_PACKS" ]]; then
      break
    fi

    local still
    still="$(ssh -o BatchMode=yes -o ConnectTimeout=20 "$GREEN" 'python3 -' <<'PY' 2>/dev/null || echo '[]'
import json, re, urllib.request
env = open("/opt/clinical-sovereignty-lab/.env").read()
tok = re.search(r"^SKYEYE_AUDIT_TOKEN=(.*)$", env, re.M).group(1).strip()
req = urllib.request.Request(
    "http://localhost:8000/api/ln7/bakeoff/running",
    headers={"Authorization": f"Bearer {tok}"},
)
try:
    with urllib.request.urlopen(req, timeout=30) as r:
        print(json.dumps((json.loads(r.read().decode())).get("running") or []))
except Exception:
    print("[]")
PY
)"
    if [[ "$still" == "[]" ]]; then
      idle_streak=$((idle_streak + 1))
      if [[ "$n" -ge "$MIN_ACCEPT" && $elapsed -gt 120 ]]; then
        log "bakeoff idle with n=$n >= min_accept=$MIN_ACCEPT — accept"
        break
      fi
      # Bakeoff died short — re-fire up to 3 times (same since= accumulates)
      if [[ $idle_streak -ge 2 && $refires -lt 3 && $elapsed -gt 180 ]]; then
        log "bakeoff idle early n=$n < $MIN_ACCEPT — re-fire ($((refires+1))/3)"
        fire_bakeoff "$rev" || true
        refires=$((refires + 1))
        idle_streak=0
      fi
    else
      idle_streak=0
    fi
  done

  # Flatten scorecard → result JSON file (stdout of run_one = this file only)
  python3 -c '
import json, sys
rev, raw, path = sys.argv[1], sys.argv[2], sys.argv[3]
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
open(path, "w").write(json.dumps(out) + "\n")
print(json.dumps(out))
' "$rev" "$score_json" "$result_file"
  # stdout is only the final JSON line above
}

ADAPTER_A="$(resolve_adapter "$REV_A" "${LN7_ADAPTER_ALIAS_A:-}")"
ADAPTER_B="$(resolve_adapter "$REV_B" "${LN7_ADAPTER_ALIAS_B:-}")"

A_RAW="$(run_one "$REV_A" "$ADAPTER_A")"
A_JSON="$(_extract_json "$REV_A" "$A_RAW")"
log "A result: $A_JSON"

B_RAW="$(run_one "$REV_B" "$ADAPTER_B")"
B_JSON="$(_extract_json "$REV_B" "$B_RAW")"
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
