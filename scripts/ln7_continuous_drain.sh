#!/usr/bin/env bash
# Drain one LN7 train job on ephemeral CUDA: train → persist → register → destroy.
# Never runs training on GREEN. Durable store: ORANGE /opt/ln7/adapters + BLUE .ln7-adapters/
#
#   bash scripts/ln7_continuous_drain.sh
# Reuse / keep droplet (A/B handoff):
#   LN7_EXISTING_DROPLET_*  LN7_KEEP_DROPLET=1  LN7_HANDOFF_ENV=path
#
# # QUANTUM-CRYSTAL-ARCH
set -euo pipefail
REPO="$(cd "$(dirname "$0")/.." && pwd)"
SIZE="${LN7_GPU_SIZE:-gpu-4000adax1-20gb}"
REGION="${LN7_GPU_REGION:-tor1}"
# Idle grace: destroy only if heartbeat goes stale this long (train keeps it fresh).
TTL="${LN7_GPU_TTL_S:-1800}"
STORE="${LN7_ADAPTER_STORE:-/opt/ln7/adapters}"
GREEN="${LN7_GREEN_HOST:-root@68.183.168.75}"
HF_BASE="${LN7_QLORA_HF_BASE:-Qwen/Qwen2.5-Coder-7B-Instruct}"
TRAIN_TIER="${LN7_TRAIN_TIER:-fast}"
LORA_RECIPE="${LN7_LORA_RECIPE:-default}"
MIN_ROWS="${LN7_QLORA_MIN_ROWS:-500}"
KEEP="${LN7_KEEP_DROPLET:-0}"
KEEP_ON_PREFAIL="${LN7_KEEP_ON_PREFAIL:-1}"
ADAPTER_KEEP_N="${LN7_ADAPTER_KEEP_N:-6}"
STATE_DIR="${LN7_GPU_WATCH_STATE_DIR:-$HOME/.local/state/ln7_gpu_watch}"
mkdir -p "$STATE_DIR"
HB="$STATE_DIR/ttl_heartbeat"
DRAIN_HB="$STATE_DIR/DRAIN_HEARTBEAT"
DRAIN_LOCK="$STATE_DIR/DRAIN_LOCK"
REV_OUT="${LN7_REVISION_OUT:-$STATE_DIR/last_revision_id}"
_TRAIN_STARTED=0
_CLEANUP_DONE=0
_DRAIN_PHASE="init"
# Post-train persist failure must not KEEP the droplet (overnight orphan GPUs).
_PERSIST_FAIL=0

# QUANTUM-CRYSTAL-ARCH — continuous-learning: merge fresh outcomes/golden rows into
# the training file before every drain. Union (dedup by patch_hash) so the corpus
# only grows — never blocks the MIN_ROWS gate, never loses the existing baseline.
refresh_training_data() {
  local fresh="/tmp/ln7_export_fresh_$$.jsonl"
  echo "[drain] refreshing train data from GREEN outcomes"
  if ! ssh -o BatchMode=yes -o ConnectTimeout=20 "$GREEN" \
      'cd /opt/clinical-sovereignty-lab && \
       docker compose -f docker-compose.prod.yml exec -T backend \
         python /app/scripts/ln7_export_train_jsonl.py --out /tmp/ln7_export_fresh.jsonl >/tmp/ln7_export_stats.json 2>&1; \
       docker compose -f docker-compose.prod.yml exec -T backend cat /tmp/ln7_export_fresh.jsonl' \
      >"$fresh" 2>/dev/null; then
    echo "[drain] export fetch failed — keeping existing data/ln7_train.jsonl"
    rm -f "$fresh"
    return 0
  fi
  local nfresh
  nfresh="$(wc -l <"$fresh" 2>/dev/null | tr -d '[:space:]')"
  if [[ -z "$nfresh" || "$nfresh" -lt 1 ]]; then
    echo "[drain] export returned 0 rows — keeping existing data/ln7_train.jsonl"
    rm -f "$fresh"
    return 0
  fi
  echo "[drain] fetched $nfresh fresh rows — merging into data/ln7_train.jsonl"
  python3 - "$REPO/data/ln7_train.jsonl" "$fresh" <<'PY' || true
import json, sys
existing_path, fresh_path = sys.argv[1], sys.argv[2]
seen = set()
merged = []


def _key(rec):
    ph = rec.get("patch_hash")
    if ph:
        return ph
    return json.dumps(rec.get("messages"), sort_keys=True)


try:
    with open(existing_path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except Exception:
                continue
            k = _key(rec)
            if k in seen:
                continue
            seen.add(k)
            merged.append(line)
except FileNotFoundError:
    pass

added = 0
with open(fresh_path) as f:
    for line in f:
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
        except Exception:
            continue
        k = _key(rec)
        if k in seen:
            continue
        seen.add(k)
        merged.append(line)
        added += 1

with open(existing_path, "w") as f:
    for line in merged:
        f.write(line + "\n")
print(f"[drain] merged +{added} new rows, total={len(merged)}")
PY
  rm -f "$fresh"
}
refresh_training_data

# Preflight: refuse thin / stub JSONL before burning GPU $
CLEAN_N="$(python3 - <<PY
import json
from pathlib import Path
import re
stub=re.compile(r'^\[patch_hash=', re.I)
diff=re.compile(r'(?m)^(diff --git |--- |\+\+\+ |@@ )')
n=0
p=Path("$REPO/data/ln7_train.jsonl")
if p.is_file():
  for line in p.open():
    line=line.strip()
    if not line: continue
    r=json.loads(line)
    asst=""
    for m in r.get("messages") or []:
      if m.get("role")=="assistant": asst=m.get("content") or ""
    if asst and not stub.match(asst.strip()) and (diff.search(asst) or asst.count(chr(10)+'+')+asst.count(chr(10)+'-')>=2):
      n+=1
print(n)
PY
)"
# Growth tiers: env overrides always win; else scale from clean_n
if [[ -z "${LN7_QLORA_ITERS:-}" ]]; then
  if [[ "${CLEAN_N:-0}" -lt 50 ]]; then ITERS=40
  elif [[ "${CLEAN_N:-0}" -lt 200 ]]; then ITERS=80
  elif [[ "${CLEAN_N:-0}" -lt 500 ]]; then ITERS=120
  else ITERS=200
  fi
else
  ITERS="$LN7_QLORA_ITERS"
fi
if [[ -z "${LN7_GPU_HARD_MAX_S:-}" ]]; then
  if [[ "${CLEAN_N:-0}" -lt 200 ]]; then HARD_MAX=14400
  elif [[ "${CLEAN_N:-0}" -lt 500 ]]; then HARD_MAX=18000
  else HARD_MAX=21600
  fi
else
  HARD_MAX="$LN7_GPU_HARD_MAX_S"
fi
echo "[drain] clean_rows=$CLEAN_N min=$MIN_ROWS iters=$ITERS hard_max=${HARD_MAX}s recipe=$LORA_RECIPE hf=$HF_BASE keep=$KEEP"
if [[ "${CLEAN_N:-0}" -lt "$MIN_ROWS" && "${LN7_QLORA_FORCE_THIN:-}" != "1" ]]; then
  echo "[drain] refuse thin train set (set LN7_QLORA_FORCE_THIN=1 to override)"
  exit 5
fi

REGIONS="${LN7_GPU_WATCH_REGIONS:-$REGION nyc1 nyc3 atl1 sfo3 fra1}"
PROVISION_RETRIES="${LN7_GPU_PROVISION_RETRIES:-3}"
DROPLET_ID=""
IP=""
# QUANTUM-CRYSTAL-ARCH — preferred SKU; oneshot fallback only after inventory block
PREFERRED_SIZE="$SIZE"
# shellcheck disable=SC1091
source "$REPO/scripts/ln7_gpu_oneshot_lib.sh"
export LN7_GPU_WATCH_STATE_DIR="$STATE_DIR"
export LN7_GPU_PREFERRED_SIZE="$PREFERRED_SIZE"
export LN7_GPU_SIZE="$PREFERRED_SIZE"

_provision_size_across_regions() {
  local size="$1" retries="${2:-$PROVISION_RETRIES}"
  local _attempt _r _prc CREATE_OUT
  local _try_regions="$REGION"
  for _r in $REGIONS; do
    [[ " $_try_regions " == *" $_r "* ]] && continue
    _try_regions="$_try_regions $_r"
  done
  for _attempt in $(seq 1 "$retries"); do
    for _r in $_try_regions; do
      echo "[drain] provision attempt ${_attempt}/${retries} $size @ $_r"
      set +e
      CREATE_OUT="$(bash "$REPO/scripts/ln7_provision_cuda_droplet.sh" "$size" "$_r" 2>&1)"
      _prc=$?
      set -e
      echo "$CREATE_OUT"
      if [[ $_prc -ne 0 ]]; then
        echo "[drain] provision fail rc=$_prc"
        continue
      fi
      DROPLET_ID="$(echo "$CREATE_OUT" | awk 'NR==2{print $1}')"
      IP="$(echo "$CREATE_OUT" | awk 'NR==2{print $3}')"
      if [[ -n "$DROPLET_ID" && -n "$IP" && "$IP" != "PublicIPv4" ]]; then
        REGION="$_r"
        SIZE="$size"
        return 0
      fi
      DROPLET_ID=""; IP=""
    done
    sleep $((5 * _attempt))
  done
  return 1
}

if [[ -n "${LN7_EXISTING_DROPLET_ID:-}" && -n "${LN7_EXISTING_DROPLET_IP:-}" ]]; then
  DROPLET_ID="$LN7_EXISTING_DROPLET_ID"
  IP="$LN7_EXISTING_DROPLET_IP"
  REGION="${LN7_EXISTING_DROPLET_REGION:-$REGION}"
  # Honor size from watcher handoff / oneshot arm when reusing probe
  if [[ -n "${LN7_GPU_SIZE:-}" && "$LN7_GPU_SIZE" != "$PREFERRED_SIZE" ]]; then
    SIZE="$LN7_GPU_SIZE"
  elif [[ -f "$STATE_DIR/ONESHOT_ARMED" ]]; then
    SIZE="$(sed -n 's/^size=//p' "$STATE_DIR/ONESHOT_ARMED" | head -1)"
    SIZE="${SIZE:-$PREFERRED_SIZE}"
  fi
  echo "[drain] reusing probe droplet id=$DROPLET_ID ip=$IP region=$REGION size=$SIZE"
else
  if ! _provision_size_across_regions "$PREFERRED_SIZE" "$PROVISION_RETRIES"; then
    ln7_oneshot_telemetry primary_blocked \
      "size=$PREFERRED_SIZE" "regions=$REGIONS" "clean_n=$CLEAN_N" \
      "tier=$TRAIN_TIER" "hf=$HF_BASE" >/dev/null || true
    echo "[drain] preferred $PREFERRED_SIZE unavailable across regions"
    if ln7_oneshot_should_try; then
      _fb="$(ln7_oneshot_fallback_size)"
      echo "[drain] ONE-SHOT fallback → $_fb (advance blocked cycle)"
      ln7_oneshot_telemetry oneshot_attempt "size=$_fb" "reason=primary_inventory_block" >/dev/null || true
      if _provision_size_across_regions "$_fb" 1; then
        ln7_oneshot_mark_armed "$SIZE" "$REGION" "$DROPLET_ID" "$IP"
        export LN7_GPU_SIZE="$SIZE"
        echo "[drain] oneshot armed size=$SIZE region=$REGION id=$DROPLET_ID"
      else
        ln7_oneshot_telemetry oneshot_blocked "size=$_fb" "reason=fallback_also_unavailable" >/dev/null || true
        echo "[drain] oneshot fallback also unavailable"
      fi
    else
      echo "[drain] oneshot disabled or cooldown — not trying fallback"
    fi
  else
    ln7_oneshot_telemetry preferred_ok "size=$SIZE" "region=$REGION" "droplet_id=$DROPLET_ID" >/dev/null || true
  fi
fi
[[ -n "$DROPLET_ID" && -n "$IP" && "$IP" != "PublicIPv4" ]] || { echo provision_failed; exit 2; }

write_handoff() {
  local dest="${1:-${LN7_HANDOFF_ENV:-}}"
  [[ -n "$dest" ]] || dest="$STATE_DIR/droplet_handoff.env"
  {
    echo "LN7_EXISTING_DROPLET_ID=$DROPLET_ID"
    echo "LN7_EXISTING_DROPLET_IP=$IP"
    echo "LN7_EXISTING_DROPLET_REGION=$REGION"
    echo "LN7_GPU_SIZE=$SIZE"
  } >"$dest"
  cp "$dest" "$STATE_DIR/probe.env" 2>/dev/null || true
  echo "[drain] handoff written $dest id=$DROPLET_ID size=$SIZE"
}

cleanup() {
  [[ "$_CLEANUP_DONE" == "1" ]] && return 0
  _CLEANUP_DONE=1
  rm -f "$HB" "$DRAIN_HB" "$DRAIN_LOCK" 2>/dev/null || true
  # QUANTUM-CRYSTAL-ARCH — persist/scp fail after train: always destroy (ignore KEEP)
  if [[ "$_PERSIST_FAIL" == "1" ]]; then
    echo "[drain] persist fail — destroying $DROPLET_ID (KEEP ignored)"
    rm -f "$STATE_DIR/probe.env" "$STATE_DIR/droplet_handoff.env" \
      "${LN7_HANDOFF_ENV:-}" 2>/dev/null || true
    bash "$REPO/scripts/ln7_destroy_cuda_droplet.sh" "$DROPLET_ID" || true
    return 0
  fi
  if [[ "$KEEP" == "1" ]]; then
    write_handoff "${LN7_HANDOFF_ENV:-$STATE_DIR/droplet_handoff.env}"
    echo "[drain] KEEP_DROPLET=1 — not destroying $DROPLET_ID"
    return 0
  fi
  if [[ "$KEEP_ON_PREFAIL" == "1" && "$_TRAIN_STARTED" != "1" ]]; then
    write_handoff "$STATE_DIR/probe.env"
    echo "[drain] pre-train fail — keeping droplet $DROPLET_ID for retry (probe.env)"
    return 0
  fi
  bash "$REPO/scripts/ln7_destroy_cuda_droplet.sh" "$DROPLET_ID" || true
}
trap cleanup EXIT

hb() {
  touch "$HB"
  {
    echo "ts=$(date -u +%Y-%m-%dT%H%M%SZ)"
    echo "phase=${_DRAIN_PHASE:-init}"
    echo "droplet_id=${DROPLET_ID:-}"
    echo "ip=${IP:-}"
    echo "pid=$$"
    echo "recipe=${LORA_RECIPE:-}"
  } >"$DRAIN_HB"
}

{
  echo "pid=$$"
  echo "started=$(date -u +%Y-%m-%dT%H%M%SZ)"
  echo "droplet_id=${DROPLET_ID:-}"
  echo "ip=${IP:-}"
} >"$DRAIN_LOCK"

hb
_START_EPOCH="$(date +%s)"
(
  while true; do
    sleep 30
    [[ -f "$HB" ]] || exit 0
    now="$(date +%s)"
    if [[ $((now - _START_EPOCH)) -gt "$HARD_MAX" ]]; then
      echo "[drain] HARD_MAX ${HARD_MAX}s — destroy"
      bash "$REPO/scripts/ln7_destroy_cuda_droplet.sh" "$DROPLET_ID" || true
      exit 0
    fi
    # macOS stat -f %m; Linux stat -c %Y
    mtime="$(stat -f %m "$HB" 2>/dev/null || stat -c %Y "$HB" 2>/dev/null || echo 0)"
    age=$((now - mtime))
    if [[ "$age" -gt "$TTL" ]]; then
      echo "[drain] idle TTL ${TTL}s (no heartbeat) — destroy"
      bash "$REPO/scripts/ln7_destroy_cuda_droplet.sh" "$DROPLET_ID" || true
      exit 0
    fi
  done
) &
WATCH=$!

_DRAIN_PHASE="ssh_wait"
_ssh_ok=0
for _ in $(seq 1 72); do
  hb
  if ssh -o BatchMode=yes -o ConnectTimeout=8 -o StrictHostKeyChecking=accept-new \
      "root@$IP" 'echo up' >/dev/null 2>&1; then
    _ssh_ok=1
    break
  fi
  sleep 5
done
if [[ "$_ssh_ok" != "1" ]]; then
  echo "[drain] ssh never became ready on $IP"
  exit 3
fi
echo "[drain] ssh open root@$IP — waiting apt/cloud-init"

_DRAIN_PHASE="apt_wait"
_apt_ok=0
for _ in $(seq 1 90); do
  hb
  if ssh -o BatchMode=yes -o ConnectTimeout=10 -o StrictHostKeyChecking=accept-new "root@$IP" \
    'set -e
     # cloud-init done or absent
     if command -v cloud-init >/dev/null 2>&1; then
       st=$(cloud-init status 2>/dev/null | head -1 || true)
       echo "$st" | grep -qiE "done|disabled|error" || exit 1
     fi
     # apt locks free
     if command -v fuser >/dev/null 2>&1; then
       fuser /var/lib/dpkg/lock-frontend >/dev/null 2>&1 && exit 1
       fuser /var/lib/apt/lists/lock >/dev/null 2>&1 && exit 1
     fi
     command -v python3 >/dev/null
     echo apt_ready' >/dev/null 2>&1; then
    _apt_ok=1
    break
  fi
  sleep 5
done
if [[ "$_apt_ok" != "1" ]]; then
  echo "[drain] apt/cloud-init never ready on $IP"
  exit 4
fi
echo "[drain] apt ready root@$IP"
_DRAIN_PHASE="bootstrap"
hb

ssh -o BatchMode=yes -o StrictHostKeyChecking=accept-new "root@$IP" \
  'export DEBIAN_FRONTEND=noninteractive
   apt-get update -qq
   apt-get install -y -qq python3.10-venv python3-pip >/dev/null
   mkdir -p /opt/ln7/{backend/scripts,data,adapters,hf_cache}'
hb
scp -o BatchMode=yes "$REPO/backend/scripts/ln7_qlora_train.py" "root@$IP:/opt/ln7/backend/scripts/"
scp -o BatchMode=yes "$REPO/data/ln7_train.jsonl" "root@$IP:/opt/ln7/data/ln7_train.jsonl"
hb

RID_TS="$(date -u +%Y-%m-%dT%H%M%SZ)"
_TRAIN_STARTED=1
_DRAIN_PHASE="train"
hb
# Heartbeat while remote train runs
(
  while kill -0 $$ 2>/dev/null; do
    touch "$HB"
    {
      echo "ts=$(date -u +%Y-%m-%dT%H%M%SZ)"
      echo "phase=train"
      echo "droplet_id=${DROPLET_ID:-}"
      echo "ip=${IP:-}"
      echo "pid=$$"
      echo "recipe=${LORA_RECIPE:-}"
    } >"$DRAIN_HB"
    sleep 20
  done
) &
_HB_PID=$!

ssh -o BatchMode=yes "root@$IP" "bash -s" <<EOF
set -euo pipefail
cd /opt/ln7
if [[ ! -x .venv/bin/python ]]; then
  python3 -m venv .venv
fi
. .venv/bin/activate
pip install -q --upgrade pip
# Skip torch reinstall if already present (A/B second recipe)
python -c 'import torch' 2>/dev/null || pip install -q torch --index-url https://download.pytorch.org/whl/cu124
python -c 'import peft, transformers, bitsandbytes, datasets, accelerate' 2>/dev/null \
  || pip install -q peft transformers bitsandbytes datasets accelerate
export HF_HOME=/opt/ln7/hf_cache LN7_QLORA_HF_BASE='$HF_BASE'
export LN7_QLORA_MIN_ROWS='$MIN_ROWS' LN7_QLORA_FORCE_THIN='${LN7_QLORA_FORCE_THIN:-}'
python backend/scripts/ln7_qlora_train.py \
  --train-jsonl data/ln7_train.jsonl --backend cuda --iters $ITERS \
  --lora-recipe $LORA_RECIPE --base '$HF_BASE' \
  --revision-id LN7-${RID_TS} \
  --out-dir /opt/ln7/adapters/LN7-${RID_TS}
EOF
kill "$_HB_PID" 2>/dev/null || true
_DRAIN_PHASE="persist"
hb

REG_REV="LN7-${RID_TS}"
LOCAL_TMP="/tmp/ln7_adapter_${REG_REV}"
rm -rf "$LOCAL_TMP" && mkdir -p "$LOCAL_TMP" "$REPO/.ln7-adapters/${REG_REV}"
scp -o BatchMode=yes -r "root@$IP:/opt/ln7/adapters/${REG_REV}/." "$LOCAL_TMP/"
cp -a "$LOCAL_TMP/." "$REPO/.ln7-adapters/${REG_REV}/"
hb

# Prefer revision_id from train manifest (must match --revision-id)
if [[ -f "$LOCAL_TMP/revision_manifest.json" ]]; then
  _man_rid="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1])).get("revision_id",""))' "$LOCAL_TMP/revision_manifest.json" 2>/dev/null || true)"
  [[ -n "$_man_rid" ]] && REG_REV="$_man_rid"
fi

_DRAIN_PHASE="register"
hb
# QUANTUM-CRYSTAL-ARCH — mkdir full adapter path (scp fails if REG_REV dir missing)
if ! ssh -o BatchMode=yes "$GREEN" \
  "ssh -o BatchMode=yes -o IdentitiesOnly=yes -i /root/.ssh/id_ed25519_orange root@10.13.13.5 \
   'mkdir -p \"$STORE/${REG_REV}\" && test -d \"$STORE/${REG_REV}\"'"; then
  echo "[drain] ORANGE mkdir failed for $STORE/${REG_REV}"
  _PERSIST_FAIL=1
  exit 7
fi
if ! scp -o BatchMode=yes -o ProxyJump="$GREEN" -r "$LOCAL_TMP/." \
  "root@10.13.13.5:$STORE/${REG_REV}/"; then
  echo "[drain] ORANGE scp failed for $STORE/${REG_REV}"
  _PERSIST_FAIL=1
  exit 7
fi
hb

if ! scp -o BatchMode=yes "$LOCAL_TMP/revision_manifest.json" "$GREEN:/tmp/ln7_revision_manifest.json"; then
  echo "[drain] GREEN manifest scp failed"
  _PERSIST_FAIL=1
  exit 7
fi
REG_OUT="$(ssh -o BatchMode=yes "$GREEN" "STORE='$STORE/${REG_REV}' python3 -" <<'PY'
import json, re, os, urllib.request
man = json.load(open("/tmp/ln7_revision_manifest.json"))
body = man["register_body"]
body["notify_ceo"] = True
body.setdefault("harness_config", {})["durable_store"] = os.environ.get("STORE", "")
env = open("/opt/clinical-sovereignty-lab/.env").read()
tok = re.search(r"^SKYEYE_AUDIT_TOKEN=(.*)$", env, re.M).group(1).strip()

def post(path, payload):
    req = urllib.request.Request(
        f"http://localhost:8000{path}",
        data=json.dumps(payload).encode(),
        headers={"Authorization": f"Bearer {tok}", "Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=180) as r:
        return json.loads(r.read().decode())

print(json.dumps({"register": post("/api/ln7/revision/register", body)}))
print(json.dumps({"canary": post("/api/ln7/canary/evaluate", {"revision_id": body["revision_id"], "start": True})}))
print("REVISION_ID=" + body["revision_id"])
PY
)"
echo "$REG_OUT"
REG_REV="$(echo "$REG_OUT" | awk -F= '/^REVISION_ID=/{print $2; exit}')"
[[ -n "$REG_REV" ]] || REG_REV="LN7-${RID_TS}"
echo "$REG_REV" >"$REV_OUT"
echo "[drain] ok $REG_REV durable=$STORE/${REG_REV} blue=.ln7-adapters/${REG_REV}"
# QUANTUM-CRYSTAL-ARCH — oneshot cycle advanced; clear arm + telemetry
ln7_oneshot_mark_consume "$REG_REV" 2>/dev/null || true

# Close out any continuous-learning job-queue rows consumed by this batch —
# without this, ln7_train_jobs rows claimed by ln7_continuous_agent.py stay
# stuck in 'training' forever (worker never marks them done).
ssh -o BatchMode=yes -o ConnectTimeout=20 "$GREEN" \
  "docker exec nate_postgres psql -U nate_admin -d little_nate -c \
   \"UPDATE ln7_train_jobs SET status='canary', revision_id='$REG_REV', updated_at=now() \
     WHERE status IN ('queued','claimed','training')\"" 2>/dev/null || true

# Adapter retention: keep last N on BLUE + ORANGE; never delete active
_prune_adapters() {
  local keep_n="$1"
  local protect="${LN7_ADAPTER_PROTECT:-}"
  local active=""
  active="$(ssh -o BatchMode=yes -o ConnectTimeout=20 "$GREEN" 'python3 -' <<'PY' 2>/dev/null || true
import json, re, urllib.request
env = open("/opt/clinical-sovereignty-lab/.env").read()
tok = re.search(r"^SKYEYE_AUDIT_TOKEN=(.*)$", env, re.M).group(1).strip()
req = urllib.request.Request(
    "http://localhost:8000/api/ln7/revision",
    headers={"Authorization": f"Bearer {tok}"},
)
with urllib.request.urlopen(req, timeout=30) as r:
    d = json.loads(r.read().decode())
print((d.get("active") or {}).get("revision_id") or "")
PY
)"
  protect="$protect $active $REG_REV"
  python3 - <<PY
import os, shutil
from pathlib import Path
root = Path("$REPO/.ln7-adapters")
keep_n = int("$keep_n")
protect = set(x for x in """$protect""".split() if x)
if not root.is_dir():
    raise SystemExit(0)
dirs = sorted([p for p in root.iterdir() if p.is_dir() and p.name.startswith("LN7-")], key=lambda p: p.name)
drop = [p for p in dirs[:-keep_n] if p.name not in protect] if len(dirs) > keep_n else []
for p in drop:
    shutil.rmtree(p, ignore_errors=True)
    print(f"[drain] pruned blue {p.name}")
PY
  ssh -o BatchMode=yes -o ProxyJump="$GREEN" "root@10.13.13.5" \
    "KEEP_N='$keep_n' PROTECT='$protect' STORE='$STORE' bash -s" <<'REMOTE' || true
set -euo pipefail
cd "$STORE" 2>/dev/null || exit 0
mapfile -t dirs < <(ls -1d LN7-* 2>/dev/null | sort)
n=${#dirs[@]}
(( n > KEEP_N )) || exit 0
drop_n=$((n - KEEP_N))
for d in "${dirs[@]:0:$drop_n}"; do
  skip=0
  for p in $PROTECT; do [[ "$d" == "$p" ]] && skip=1 && break; done
  [[ $skip -eq 1 ]] && continue
  rm -rf "$d"
  echo "[drain] pruned orange $d"
done
REMOTE
}
_prune_adapters "$ADAPTER_KEEP_N"

kill "$WATCH" 2>/dev/null || true
# Success path: if KEEP, handoff; else trap destroys
if [[ "$KEEP" == "1" ]]; then
  write_handoff "${LN7_HANDOFF_ENV:-$STATE_DIR/droplet_handoff.env}"
fi
