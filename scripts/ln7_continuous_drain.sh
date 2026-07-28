#!/usr/bin/env bash
# Drain one LN7 train job on ephemeral CUDA: train → persist → register → destroy.
# Never runs training on GREEN. Durable store: ORANGE /opt/ln7/adapters + BLUE .ln7-adapters/
#
#   bash scripts/ln7_continuous_drain.sh
set -euo pipefail
REPO="$(cd "$(dirname "$0")/.." && pwd)"
SIZE="${LN7_GPU_SIZE:-gpu-4000adax1-20gb}"
REGION="${LN7_GPU_REGION:-tor1}"
TTL="${LN7_GPU_TTL_S:-3600}"
ITERS="${LN7_QLORA_ITERS:-40}"
STORE="${LN7_ADAPTER_STORE:-/opt/ln7/adapters}"
GREEN="${LN7_GREEN_HOST:-root@68.183.168.75}"
# Must match ORANGE ln7_peft_server.py / :11435
HF_BASE="${LN7_QLORA_HF_BASE:-Qwen/Qwen2.5-Coder-1.5B-Instruct}"
LORA_RECIPE="${LN7_LORA_RECIPE:-default}"
MIN_ROWS="${LN7_QLORA_MIN_ROWS:-50}"

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
echo "[drain] clean_rows=$CLEAN_N min=$MIN_ROWS recipe=$LORA_RECIPE hf=$HF_BASE"
if [[ "${CLEAN_N:-0}" -lt "$MIN_ROWS" && "${LN7_QLORA_FORCE_THIN:-}" != "1" ]]; then
  echo "[drain] refuse thin train set (set LN7_QLORA_FORCE_THIN=1 to override)"
  exit 5
fi

REGIONS="${LN7_GPU_WATCH_REGIONS:-$REGION nyc1 nyc3 atl1 sfo3 fra1}"
PROVISION_RETRIES="${LN7_GPU_PROVISION_RETRIES:-3}"
DROPLET_ID=""
IP=""

if [[ -n "${LN7_EXISTING_DROPLET_ID:-}" && -n "${LN7_EXISTING_DROPLET_IP:-}" ]]; then
  DROPLET_ID="$LN7_EXISTING_DROPLET_ID"
  IP="$LN7_EXISTING_DROPLET_IP"
  REGION="${LN7_EXISTING_DROPLET_REGION:-$REGION}"
  echo "[drain] reusing probe droplet id=$DROPLET_ID ip=$IP region=$REGION"
else
  _try_regions="$REGION"
  for _r in $REGIONS; do
    [[ " $_try_regions " == *" $_r "* ]] && continue
    _try_regions="$_try_regions $_r"
  done
  for _attempt in $(seq 1 "$PROVISION_RETRIES"); do
    for _r in $_try_regions; do
      echo "[drain] provision attempt ${_attempt}/${PROVISION_RETRIES} $SIZE @ $_r"
      set +e
      CREATE_OUT="$(bash "$REPO/scripts/ln7_provision_cuda_droplet.sh" "$SIZE" "$_r" 2>&1)"
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
        break 2
      fi
      DROPLET_ID=""; IP=""
    done
    sleep $((5 * _attempt))
  done
fi
[[ -n "$DROPLET_ID" && -n "$IP" && "$IP" != "PublicIPv4" ]] || { echo provision_failed; exit 2; }

cleanup() { bash "$REPO/scripts/ln7_destroy_cuda_droplet.sh" "$DROPLET_ID" || true; }
trap cleanup EXIT
( sleep "$TTL"; echo "[drain] TTL"; cleanup ) &
WATCH=$!

_ssh_ok=0
for _ in $(seq 1 72); do
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
echo "[drain] ssh ready root@$IP"

ssh -o BatchMode=yes -o StrictHostKeyChecking=accept-new "root@$IP" \
  'export DEBIAN_FRONTEND=noninteractive; apt-get update -qq; apt-get install -y -qq python3.10-venv python3-pip >/dev/null; mkdir -p /opt/ln7/{backend/scripts,data,adapters,hf_cache}'
scp -o BatchMode=yes "$REPO/backend/scripts/ln7_qlora_train.py" "root@$IP:/opt/ln7/backend/scripts/"
scp -o BatchMode=yes "$REPO/data/ln7_train.jsonl" "root@$IP:/opt/ln7/data/ln7_train.jsonl"

RID_TS="$(date -u +%Y-%m-%dT%H%M%SZ)"
ssh -o BatchMode=yes "root@$IP" "bash -s" <<EOF
set -euo pipefail
cd /opt/ln7
python3 -m venv .venv
. .venv/bin/activate
pip install -q --upgrade pip
pip install -q torch --index-url https://download.pytorch.org/whl/cu124
pip install -q peft transformers bitsandbytes datasets accelerate
export HF_HOME=/opt/ln7/hf_cache LN7_QLORA_HF_BASE='$HF_BASE'
export LN7_QLORA_MIN_ROWS='$MIN_ROWS' LN7_QLORA_FORCE_THIN='${LN7_QLORA_FORCE_THIN:-}'
python backend/scripts/ln7_qlora_train.py \
  --train-jsonl data/ln7_train.jsonl --backend cuda --iters $ITERS \
  --lora-recipe $LORA_RECIPE --base '$HF_BASE' \
  --out-dir /opt/ln7/adapters/LN7-${RID_TS}
EOF

LOCAL_TMP="/tmp/ln7_adapter_LN7-${RID_TS}"
rm -rf "$LOCAL_TMP" && mkdir -p "$LOCAL_TMP" "$REPO/.ln7-adapters/LN7-${RID_TS}"
scp -o BatchMode=yes -r "root@$IP:/opt/ln7/adapters/LN7-${RID_TS}/." "$LOCAL_TMP/"
cp -a "$LOCAL_TMP/." "$REPO/.ln7-adapters/LN7-${RID_TS}/"

# Durable on ORANGE (via GREEN jump)
ssh -o BatchMode=yes "$GREEN" "ssh -o BatchMode=yes -o IdentitiesOnly=yes -i /root/.ssh/id_ed25519_orange root@10.13.13.5 'mkdir -p $STORE'"
scp -o BatchMode=yes -o ProxyJump="$GREEN" -r "$LOCAL_TMP" \
  "root@10.13.13.5:$STORE/LN7-${RID_TS}"

# Register from GREEN
scp -o BatchMode=yes "$LOCAL_TMP/revision_manifest.json" "$GREEN:/tmp/ln7_revision_manifest.json"
ssh -o BatchMode=yes "$GREEN" "STORE='$STORE/LN7-${RID_TS}' python3 -" <<'PY'
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
PY

kill "$WATCH" 2>/dev/null || true
echo "[drain] ok LN7-${RID_TS} durable=$STORE/LN7-${RID_TS} blue=.ln7-adapters/LN7-${RID_TS}"
