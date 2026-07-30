#!/usr/bin/env bash
# QUANTUM-CRYSTAL-ARCH — hive_burst window: multi-LoRA vLLM A/B serving.
#
#   bash scripts/ln7_hive_burst.sh <rev_a> <rev_b>
#
# Seven steps, in order. Each one refuses to proceed on failure:
#   1 provision GPU droplet (cloud-init carries TTL self-destruct)
#   2 write handoff env (BLUE state dir + GREEN container-readable path)
#   3 rsync base weights + both arm adapters
#   4 launch vLLM --enable-lora --max-loras 4 --api-key --port 11436
#   5 identity probe AS A GATE — loop until BOTH arms return distinct adapter_ok
#   6 hand off to ln7_ab_bakeoff_compare.sh
#   7 destroy droplet + rename handoff -> .destroyed
#
# Step 5 is the whole point: the window itself refuses to run a comparison it
# cannot prove is comparing two different sets of weights.
set -euo pipefail

REPO="$(cd "$(dirname "$0")/.." && pwd)"
REV_A="${1:-${LN7_BURST_REV_A:-}}"
REV_B="${2:-${LN7_BURST_REV_B:-}}"
[[ -n "$REV_A" && -n "$REV_B" ]] || {
  echo "usage: ln7_hive_burst.sh <rev_a> <rev_b>" >&2
  exit 64
}
[[ "$REV_A" != "$REV_B" ]] || { echo "[hive_burst] rev_a == rev_b — refuse" >&2; exit 64; }

STATE_DIR="${LN7_GPU_WATCH_STATE_DIR:-$HOME/.local/state/ln7_gpu_watch}"
mkdir -p "$STATE_DIR"
BURST_ID="${LN7_BURST_ID:-burst_$(date -u +%Y%m%dT%H%M%SZ)}"
HANDOFF="${LN7_BURST_HANDOFF_LOCAL:-$STATE_DIR/ln7_burst_window.env}"
GREEN="${LN7_GREEN_HOST:-root@68.183.168.75}"
GREEN_HANDOFF="${LN7_BURST_HANDOFF_GREEN:-/opt/clinical-sovereignty-lab/data/backend/ln7_burst_window.env}"
# QUANTUM-CRYSTAL-ARCH — dry run exercises the whole window lifecycle (provision,
# vLLM, LoRA attach, probe gate, GREEN read-back, teardown) without a compare and
# without arming the live resolver. Handoff goes to a .dryrun path so production
# inference cannot accidentally route to the throwaway droplet.
DRY_RUN="${LN7_BURST_DRY_RUN:-0}"
if [[ "$DRY_RUN" == "1" ]]; then
  GREEN_HANDOFF="${GREEN_HANDOFF%.env}.dryrun.env"
fi
GREEN_WG_IP="${LN7_GREEN_WG_IP:-}"
PORT="${LN7_BURST_PORT:-11436}"
TTL_S="${LN7_BURST_TTL_S:-5400}"
SIZE="${LN7_GPU_SIZE:-gpu-4000adax1-20gb}"
REGION="${LN7_GPU_REGION:-tor1}"
HF_BASE="${LN7_QLORA_HF_BASE:-Qwen/Qwen2.5-Coder-7B-Instruct}"
ADAPTER_ROOT="${LN7_ADAPTER_ROOT:-$REPO/.ln7-adapters}"
PROBE_MAX_S="${LN7_BURST_PROBE_MAX_S:-900}"
PROBE_INTERVAL_S="${LN7_BURST_PROBE_INTERVAL_S:-15}"
# QUANTUM-CRYSTAL-ARCH — dead peer → exit ≤~60s (not wedged forever)
SSH_OPTS=(-o BatchMode=yes -o StrictHostKeyChecking=no -o ConnectTimeout=30
          -o ServerAliveInterval=15 -o ServerAliveCountMax=4)

API_KEY="${LN7_BURST_API_KEY:-$(openssl rand -hex 24)}"
DROPLET_ID=""
DROPLET_IP=""
_TORN_DOWN=0

log() { echo "[hive_burst] $*" >&2; }
die() { log "FATAL $*"; exit "${2:-1}"; }

# --- step 7 (runs on every exit path) ----------------------------------------
teardown() {
  local ec=$?
  [[ "$_TORN_DOWN" == "1" ]] && exit "$ec"
  _TORN_DOWN=1
  if [[ -f "$HANDOFF" ]]; then
    mv -f "$HANDOFF" "${HANDOFF}.destroyed" 2>/dev/null || true
    log "handoff renamed -> ${HANDOFF}.destroyed"
  fi
  # Stale host must fail loudly on GREEN, never fall back to ORANGE.
  ssh "${SSH_OPTS[@]}" "$GREEN" \
    "mv -f '$GREEN_HANDOFF' '${GREEN_HANDOFF}.destroyed' 2>/dev/null || true" || true
  if [[ -n "$DROPLET_ID" ]]; then
    log "destroying droplet $DROPLET_ID"
    doctl compute droplet delete "$DROPLET_ID" --force >/dev/null 2>&1 \
      || log "WARN destroy failed — orphan reaper must catch $DROPLET_ID"
    # API can briefly still GET a droplet mid-delete; wait before asserting.
    sleep 8
    if doctl compute droplet get "$DROPLET_ID" >/dev/null 2>&1; then
      log "ANOMALY burst_destroy_fail id=$DROPLET_ID"
    else
      log "destroy verified id=$DROPLET_ID"
    fi
  fi
  log "window closed burst_id=$BURST_ID ec=$ec"
  exit "$ec"
}
trap teardown EXIT INT TERM

# --- step 1: provision --------------------------------------------------------
# QUANTUM-CRYSTAL-ARCH — GPU stock rotates; try preferred size×region then the
# same watch list the capacity agent uses. A single-region 422 must not abort
# the dry run when another AZ (or the L40S fallback) still has capacity.
SIZES="${LN7_GPU_SIZE_FALLBACKS:-$SIZE ${LN7_GPU_FALLBACK_SIZE:-gpu-l40sx1-48gb}}"
SIZES="$(awk '{for(i=1;i<=NF;i++) if(!seen[$i]++) printf "%s%s", (n++?" ":""), $i}' <<<"$SIZES")"
REGIONS="${LN7_GPU_WATCH_REGIONS:-$REGION tor1 nyc1 nyc3 atl1 sfo3 fra1}"
REGIONS="$(awk '{for(i=1;i<=NF;i++) if(!seen[$i]++) printf "%s%s", (n++?" ":""), $i}' <<<"$REGIONS")"
log "step 1/7 provision sizes=[$SIZES] regions=[$REGIONS] burst_id=$BURST_ID"
if [[ -n "${LN7_EXISTING_DROPLET_IP:-}" ]]; then
  DROPLET_IP="$LN7_EXISTING_DROPLET_IP"
  DROPLET_ID="${LN7_EXISTING_DROPLET_ID:-}"
  log "reusing droplet id=${DROPLET_ID:-unknown} ip=$DROPLET_IP"
else
  PROV_OUT=""
  for try_size in $SIZES; do
    for try_region in $REGIONS; do
      log "  trying size=$try_size region=$try_region"
      if PROV_OUT="$(LN7_GPU_TTL_S="$TTL_S" bash "$REPO/scripts/ln7_provision_cuda_droplet.sh" \
           "$try_size" "$try_region" 2>&1)"; then
        SIZE="$try_size"
        REGION="$try_region"
        break 2
      fi
      log "  unavailable: $(echo "$PROV_OUT" | tr '\n' ' ' | head -c 160)"
      PROV_OUT=""
    done
  done
  [[ -n "$PROV_OUT" ]] || die "provision_failed sizes=[$SIZES] regions=[$REGIONS]" 2
  DROPLET_ID="$(awk 'NR>1 && $1 ~ /^[0-9]+$/ {print $1; exit}' <<<"$PROV_OUT")"
  DROPLET_IP="$(grep -oE '([0-9]{1,3}\.){3}[0-9]{1,3}' <<<"$PROV_OUT" | head -1)"
  [[ -n "$DROPLET_ID" && -n "$DROPLET_IP" ]] || { log "$PROV_OUT"; die "provision_no_ip" 2; }
fi
log "droplet id=$DROPLET_ID ip=$DROPLET_IP size=$SIZE region=$REGION"

for _ in $(seq 1 40); do
  ssh "${SSH_OPTS[@]}" "root@$DROPLET_IP" true 2>/dev/null && break
  sleep 10
done
ssh "${SSH_OPTS[@]}" "root@$DROPLET_IP" true 2>/dev/null || die "ssh_unreachable" 2

# --- step 2: write handoff env -----------------------------------------------
# Advertise the WireGuard IP when the droplet has one; otherwise the public IP
# behind an api-key + firewall pinned to GREEN.
ADVERTISE_HOST="${LN7_BURST_ADVERTISE_HOST:-$DROPLET_IP}"
TTL_UNTIL="$(python3 -c "
import datetime
print((datetime.datetime.now(datetime.timezone.utc)
       + datetime.timedelta(seconds=$TTL_S)).strftime('%Y-%m-%dT%H:%M:%SZ'))")"
log "step 2/7 handoff host=$ADVERTISE_HOST ttl_until=$TTL_UNTIL"
cat >"$HANDOFF" <<EOF
LN7_SERVE_ENGINE=vllm_burst
LN7_BURST_ID=$BURST_ID
LN7_BURST_HOST=$ADVERTISE_HOST
LN7_BURST_PORT=$PORT
LN7_BURST_TTL_UNTIL=$TTL_UNTIL
LN7_BURST_API_KEY=$API_KEY
LN7_BURST_BASE_MODEL=$HF_BASE
LN7_BURST_DROPLET_ID=$DROPLET_ID
EOF
chmod 600 "$HANDOFF"
scp "${SSH_OPTS[@]}" "$HANDOFF" "$GREEN:$GREEN_HANDOFF" >/dev/null \
  || die "handoff_push_failed" 2
ssh "${SSH_OPTS[@]}" "$GREEN" "chown 1000:1000 '$GREEN_HANDOFF'; chmod 640 '$GREEN_HANDOFF'" || true

# --- step 3: rsync base + arm adapters ---------------------------------------
log "step 3/7 rsync adapters"
ssh "${SSH_OPTS[@]}" "root@$DROPLET_IP" "mkdir -p /opt/ln7/adapters" >/dev/null
for rev in "$REV_A" "$REV_B"; do
  # Reused training droplet already holds the weights it just wrote.
  if ssh "${SSH_OPTS[@]}" "root@$DROPLET_IP" \
       "test -s /opt/ln7/adapters/$rev/adapter_model.safetensors" 2>/dev/null; then
    log "  adapter $rev already on droplet — skip rsync"
    continue
  fi
  src="$ADAPTER_ROOT/$rev"
  [[ -d "$src" ]] || die "adapter_missing:$rev (not on droplet, not at $src)" 3
  rsync -az -e "ssh ${SSH_OPTS[*]}" "$src/" "root@$DROPLET_IP:/opt/ln7/adapters/$rev/" \
    || die "rsync_failed:$rev" 3
  log "  adapter $rev -> /opt/ln7/adapters/$rev"
done

# --- step 4: launch vLLM multi-LoRA ------------------------------------------
log "step 4/7 launch vLLM :$PORT (--enable-lora --max-loras 4)"
FIREWALL_SRC="${GREEN_WG_IP:-$(ssh "${SSH_OPTS[@]}" "$GREEN" 'curl -s -4 ifconfig.co' 2>/dev/null || echo '')}"
ssh "${SSH_OPTS[@]}" "root@$DROPLET_IP" \
  "REV_A='$REV_A' REV_B='$REV_B' HF_BASE='$HF_BASE' PORT='$PORT' \
   API_KEY='$API_KEY' TTL_S='$TTL_S' FW_SRC='$FIREWALL_SRC' bash -s" <<'REMOTE' \
  || die "vllm_launch_failed" 4
set -euo pipefail
export DEBIAN_FRONTEND=noninteractive
# Mirror the drain bootstrap: GPU base images often have python3 without pip on PATH.
apt-get update -qq >/dev/null 2>&1 || true
apt-get install -y -qq python3-pip python3-venv >/dev/null 2>&1 || true
mkdir -p /opt/ln7
if [[ ! -x /opt/ln7/.venv/bin/python ]]; then
  python3 -m venv /opt/ln7/.venv
fi
# shellcheck disable=SC1091
. /opt/ln7/.venv/bin/activate
python -m pip install -q --upgrade pip
python -c 'import vllm' 2>/dev/null \
  || python -m pip install -q --root-user-action=ignore 'vllm>=0.6.0'
VLLM_BIN="$(command -v vllm || echo /opt/ln7/.venv/bin/vllm)"
[[ -x "$VLLM_BIN" ]] || { echo "[droplet] vllm binary missing after install" >&2; exit 1; }

# Belt to cloud-init's suspenders: the serving process dies with the window.
nohup bash -c "sleep ${TTL_S}; pkill -f 'vllm serve' || true; \
  shutdown -h now || true" >/dev/null 2>&1 &

if command -v ufw >/dev/null 2>&1; then
  ufw --force enable >/dev/null 2>&1 || true
  ufw allow 22/tcp >/dev/null 2>&1 || true
  ufw allow from 10.13.13.0/24 to any port "${PORT}" proto tcp >/dev/null 2>&1 || true
  [[ -n "${FW_SRC}" ]] && ufw allow from "${FW_SRC}" to any port "${PORT}" proto tcp >/dev/null 2>&1 || true
fi

pkill -f 'vllm serve' 2>/dev/null || true
nohup "$VLLM_BIN" serve "${HF_BASE}" \
  --port "${PORT}" --host 0.0.0.0 \
  --api-key "${API_KEY}" \
  --enable-lora --max-loras 4 --max-lora-rank 32 \
  --lora-modules "${REV_A}=/opt/ln7/adapters/${REV_A}" "${REV_B}=/opt/ln7/adapters/${REV_B}" \
  --served-model-name "${HF_BASE}" \
  --max-model-len 8192 --gpu-memory-utilization 0.90 \
  >/var/log/ln7_vllm.log 2>&1 &
echo "[droplet] vllm launched pid=$! bin=$VLLM_BIN"
REMOTE

# --- step 5: identity probe AS A GATE ----------------------------------------
# Refuse to hand off until BOTH arms answer as themselves and are distinct.
# Probe over SSH → localhost so UFW (GREEN + WG only) does not block BLUE.
log "step 5/7 identity probe gate (max ${PROBE_MAX_S}s)"
elapsed=0
gate_ok=0
while [[ $elapsed -lt $PROBE_MAX_S ]]; do
  if ssh "${SSH_OPTS[@]}" "root@$DROPLET_IP" \
       "REV_A='$REV_A' REV_B='$REV_B' PORT='$PORT' API_KEY='$API_KEY' python3 -" <<'PY'
import json, os, sys, urllib.error, urllib.request

url = f"http://127.0.0.1:{os.environ['PORT']}/v1"
key = os.environ["API_KEY"]
a, b = os.environ["REV_A"], os.environ["REV_B"]
hdr = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}


def get(path):
    req = urllib.request.Request(f"{url}{path}", headers=hdr)
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read().decode())


def completes(model):
    """A LoRA can be advertised and still fail to attach — force one token."""
    body = json.dumps({
        "model": model,
        "messages": [{"role": "user", "content": "ok"}],
        "max_tokens": 1,
        "temperature": 0,
    }).encode()
    req = urllib.request.Request(f"{url}/chat/completions", data=body, headers=hdr, method="POST")
    with urllib.request.urlopen(req, timeout=90) as r:
        json.loads(r.read().decode())
    return True


try:
    ids = [str((m or {}).get("id") or "") for m in (get("/models").get("data") or [])]
except (urllib.error.URLError, OSError, ValueError) as exc:
    print(f"not_ready:{str(exc)[:80]}")
    sys.exit(1)

missing = [r for r in (a, b) if r not in ids]
if missing:
    print(f"missing_loras:{','.join(missing)} served={','.join(ids)[:120]}")
    sys.exit(1)
if a == b:
    print("arms_identical")
    sys.exit(2)
for rev in (a, b):
    try:
        completes(rev)
    except Exception as exc:
        print(f"lora_completion_failed:{rev}:{str(exc)[:80]}")
        sys.exit(1)
print(f"adapter_ok:{a} adapter_ok:{b} distinct=true")
PY
  then
    gate_ok=1
    break
  fi
  rc=$?
  [[ $rc -eq 2 ]] && die "probe_gate_arms_identical" 5
  sleep "$PROBE_INTERVAL_S"
  elapsed=$((elapsed + PROBE_INTERVAL_S))
  log "  probe not converged (${elapsed}s/${PROBE_MAX_S}s)"
done
[[ "$gate_ok" == "1" ]] || {
  ssh "${SSH_OPTS[@]}" "root@$DROPLET_IP" 'tail -30 /var/log/ln7_vllm.log' 2>/dev/null >&2 || true
  die "probe_gate_never_converged — refusing to compare indistinguishable arms" 5
}
log "step 5/7 GATE PASSED — arms provably distinct"

# Keep the resolver's model name in sync with what vLLM actually serves.
# A dry run must not write to the production ledger for throwaway revisions.
[[ "$DRY_RUN" == "1" ]] || ssh "${SSH_OPTS[@]}" "$GREEN" \
  "docker exec nate_postgres psql -U nate_admin -d little_nate -c \
   \"UPDATE ln7_revisions SET vllm_lora_name = revision_id \
     WHERE revision_id IN ('$REV_A','$REV_B')\"" >/dev/null 2>&1 || true

# --- step 6: hand off to compare ---------------------------------------------
if [[ "$DRY_RUN" == "1" ]]; then
  # QUANTUM-CRYSTAL-ARCH — dry run stops here and instead proves the half of the
  # path a droplet-side probe cannot see: that GREEN's container reads this
  # handoff through the bind mount, resolves both arms to DISTINCT burst targets,
  # and refuses an expired or absent window instead of falling back to ORANGE.
  log "step 6/7 DRY RUN — resolver read-back instead of compare"
  # The bind mount is provable without deploying code: if the container can read
  # the file the resolver will be handed, the mount and ownership are correct.
  GREEN_CONTAINER_HANDOFF="/app/data/$(basename "$GREEN_HANDOFF")"
  if ssh "${SSH_OPTS[@]}" "$GREEN" \
       "docker exec nate_backend sh -c \"grep -q '^LN7_BURST_HOST=' '$GREEN_CONTAINER_HANDOFF'\"" 2>/dev/null; then
    log "  bind mount OK — container reads $GREEN_CONTAINER_HANDOFF"
  else
    die "green_bind_mount_unreadable:$GREEN_CONTAINER_HANDOFF" 6
  fi

  # Resolver logic runs against the same handoff from the repo checkout, so the
  # dry run does not require this branch to be deployed yet.
  LN7_BURST_HANDOFF="$HANDOFF" \
  LN7_SERVE_ENGINE=vllm_burst \
  REV_A="$REV_A" REV_B="$REV_B" EXPECT_HOST="$ADVERTISE_HOST" \
  PYTHONPATH="$REPO/backend" python3 - <<'PY' || die "resolver_readback_failed" 6
import os, sys
from app.services.little_nate_7 import burst_window, serve_engine, serve_target_from_revision

fails = []
if serve_engine() != "vllm_burst":
    fails.append(f"serve_engine={serve_engine()!r} (per-call read did not see env)")

w = burst_window()
if not w.get("ok"):
    fails.append(f"burst_window not ok: {w.get('error')}")
elif w.get("host") != os.environ["EXPECT_HOST"]:
    fails.append(f"host {w.get('host')!r} != {os.environ['EXPECT_HOST']!r}")

a, b = os.environ["REV_A"], os.environ["REV_B"]
# Arm A exercises the revision_id fallback; arm B the migration-305 column.
ta = serve_target_from_revision({"revision_id": a})
tb = serve_target_from_revision({"revision_id": b, "vllm_lora_name": b})
bare = serve_target_from_revision({"revision_id": "baseline", "base_checkpoint": "bare_hf"})

for name, t in (("A", ta), ("B", tb), ("bare", bare)):
    if t.get("mode") != "vllm_burst":
        fails.append(f"arm {name} mode={t.get('mode')!r} err={t.get('error')!r}")
    if str(os.environ["EXPECT_HOST"]) not in str(t.get("url") or ""):
        fails.append(f"arm {name} url {t.get('url')!r} does not point at burst host")
if (ta.get("model") or "") == (tb.get("model") or ""):
    fails.append(f"arms COLLIDE on model={ta.get('model')!r} — the bug this window exists to prevent")
if (bare.get("model") or "") in ((ta.get("model") or ""), (tb.get("model") or "")):
    fails.append(f"bare arm resolved to an adapter name: {bare.get('model')!r}")

# Absent window must refuse, not silently fall back to ORANGE. This is the
# .destroyed rename seen from the resolver's side.
live = os.environ["LN7_BURST_HANDOFF"]
os.environ["LN7_BURST_HANDOFF"] = live + ".no_such_window"
gone = burst_window()
if gone.get("ok") or gone.get("error") != "no_active_burst_window":
    fails.append(f"missing handoff did not refuse: {gone}")
stale = serve_target_from_revision({"revision_id": a})
if stale.get("mode") != "unavailable":
    fails.append(f"stale window resolved to {stale.get('url')!r} instead of refusing")

# An expired TTL is a droplet the reaper already took; it must refuse too.
expired = live + ".expired"
with open(live, encoding="utf-8") as fh:
    body = fh.read()
with open(expired, "w", encoding="utf-8") as fh:
    fh.write(body.replace(w.get("ttl_until") or "", "2000-01-01T00:00:00Z"))
os.environ["LN7_BURST_HANDOFF"] = expired
exp = burst_window()
if exp.get("ok"):
    fails.append(f"expired TTL accepted: {exp}")
os.remove(expired)
os.environ["LN7_BURST_HANDOFF"] = live

print(f"green_readback engine=vllm_burst host={w.get('host')} "
      f"arm_a_model={ta.get('model')!r} arm_b_model={tb.get('model')!r} "
      f"bare_model={bare.get('model')!r} "
      f"distinct={ta.get('model') != tb.get('model')}")
if fails:
    for f in fails:
        print("FAIL " + f)
    raise SystemExit(1)
print("GREEN_READBACK_OK")
PY
  log "  local resolver read-back OK"

  # QUANTUM-CRYSTAL-ARCH — GREEN must reach the exact URL serve_target_from_revision
  # hands the harness. SSH→localhost proves the droplet; this proves the production
  # path (GREEN → public burst host:11436 with the handoff API key). Fail here is
  # the bounded cause for a Branch-B attempt — fix before any drain spend.
  log "  GREEN auth HTTP preflight (resolver URL)"
  ssh "${SSH_OPTS[@]}" "$GREEN" \
    "REV_A='$REV_A' REV_B='$REV_B' HANDOFF='$GREEN_HANDOFF' \
     EXPECT_HOST='$ADVERTISE_HOST' PORT='$PORT' python3 -" <<'PY' \
    || die "green_auth_http_preflight_failed" 6
import json, os, sys, urllib.error, urllib.request

path = os.environ["HANDOFF"]
# Prefer container path when running inside docker; host path is for bare python on GREEN.
if not os.path.isfile(path):
    path = "/opt/clinical-sovereignty-lab/data/backend/" + os.path.basename(path)
kv = {}
with open(path, encoding="utf-8") as fh:
    for line in fh:
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        kv[k.strip()] = v.strip().strip('"').strip("'")

host = kv.get("LN7_BURST_HOST", "")
port = kv.get("LN7_BURST_PORT", os.environ.get("PORT", "11436"))
key = kv.get("LN7_BURST_API_KEY", "")
expect = os.environ["EXPECT_HOST"]
if host != expect:
    print(f"FAIL handoff host {host!r} != expect {expect!r}")
    raise SystemExit(1)
if not key:
    print("FAIL handoff missing LN7_BURST_API_KEY")
    raise SystemExit(1)

# Exact shape serve_target_from_revision returns for vllm_burst.
url = f"http://{host}:{port}/v1"
hdr = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
fails = []

def models():
    req = urllib.request.Request(f"{url}/models", headers=hdr)
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode())

def complete(model):
    body = json.dumps({
        "model": model,
        "messages": [{"role": "user", "content": "ok"}],
        "max_tokens": 1,
        "temperature": 0,
    }).encode()
    req = urllib.request.Request(f"{url}/chat/completions", data=body, headers=hdr, method="POST")
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.loads(r.read().decode())

try:
    ids = [str((m or {}).get("id") or "") for m in (models().get("data") or [])]
except Exception as exc:
    print(f"FAIL green→{url}/models: {exc}")
    raise SystemExit(1)

a, b = os.environ["REV_A"], os.environ["REV_B"]
for rev in (a, b):
    if rev not in ids:
        fails.append(f"model {rev!r} not in GREEN-visible /models: {ids[:8]}")
        continue
    try:
        complete(rev)
    except Exception as exc:
        fails.append(f"GREEN chat/completions {rev}: {exc}")

print(f"green_auth_http url={url} models_ok={a in ids and b in ids} "
      f"arm_a={a!r} arm_b={b!r}")
if fails:
    for f in fails:
        print("FAIL " + f)
    raise SystemExit(1)
print("GREEN_AUTH_HTTP_OK")
PY
  log "step 6/7 DRY RUN PASSED — GREEN resolves + reaches distinct burst targets"
  log "dry run complete: provision, handoff, rsync, vLLM, LoRA attach, probe gate, GREEN read-back, GREEN auth HTTP"
  COMPARE_EC=0
  exit "$COMPARE_EC"
fi

# Live compare also requires GREEN can hit the resolver URL before pack spend.
log "step 6/7 GREEN auth HTTP preflight (before compare)"
GREEN_CONTAINER_HANDOFF="/app/data/$(basename "$GREEN_HANDOFF")"
ssh "${SSH_OPTS[@]}" "$GREEN" \
  "REV_A='$REV_A' REV_B='$REV_B' HANDOFF='$GREEN_HANDOFF' \
   EXPECT_HOST='$ADVERTISE_HOST' PORT='$PORT' python3 -" <<'PY' \
  || die "green_auth_http_preflight_failed" 6
import json, os, sys, urllib.error, urllib.request
path = os.environ["HANDOFF"]
kv = {}
with open(path, encoding="utf-8") as fh:
    for line in fh:
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        kv[k.strip()] = v.strip().strip('"').strip("'")
host, port, key = kv["LN7_BURST_HOST"], kv.get("LN7_BURST_PORT", "11436"), kv["LN7_BURST_API_KEY"]
url = f"http://{host}:{port}/v1"
hdr = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
req = urllib.request.Request(f"{url}/models", headers=hdr)
with urllib.request.urlopen(req, timeout=30) as r:
    ids = [str((m or {}).get("id") or "") for m in (json.loads(r.read().decode()).get("data") or [])]
a, b = os.environ["REV_A"], os.environ["REV_B"]
missing = [x for x in (a, b) if x not in ids]
if missing:
    print(f"FAIL missing_from_green:{missing} url={url}")
    raise SystemExit(1)
for rev in (a, b):
    body = json.dumps({"model": rev, "messages": [{"role": "user", "content": "ok"}],
                       "max_tokens": 1, "temperature": 0}).encode()
    req = urllib.request.Request(f"{url}/chat/completions", data=body, headers=hdr, method="POST")
    with urllib.request.urlopen(req, timeout=120) as r:
        json.loads(r.read().decode())
print(f"GREEN_AUTH_HTTP_OK url={url} arm_a={a} arm_b={b}")
PY

log "step 6/7 compare $REV_A vs $REV_B"
LN7_SERVE_ENGINE=vllm_burst \
LN7_BURST_HANDOFF_LOCAL="$HANDOFF" \
  bash "$REPO/scripts/ln7_ab_bakeoff_compare.sh" "$REV_A" "$REV_B"
COMPARE_EC=$?
log "compare exit=$COMPARE_EC"

# --- step 7 runs from the EXIT trap ------------------------------------------
exit "$COMPARE_EC"
