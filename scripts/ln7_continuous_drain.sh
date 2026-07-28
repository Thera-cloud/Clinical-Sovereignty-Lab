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
HF_BASE="${LN7_QLORA_HF_BASE:-Qwen/Qwen2.5-Coder-1.5B-Instruct}"

echo "[drain] provision $SIZE @ $REGION"
CREATE_OUT="$(bash "$REPO/scripts/ln7_provision_cuda_droplet.sh" "$SIZE" "$REGION")"
echo "$CREATE_OUT"
DROPLET_ID="$(echo "$CREATE_OUT" | awk 'NR==2{print $1}')"
IP="$(echo "$CREATE_OUT" | awk 'NR==2{print $3}')"
[[ -n "$DROPLET_ID" && -n "$IP" && "$IP" != "PublicIPv4" ]] || { echo provision_failed; exit 2; }

cleanup() { bash "$REPO/scripts/ln7_destroy_cuda_droplet.sh" "$DROPLET_ID" || true; }
trap cleanup EXIT
( sleep "$TTL"; echo "[drain] TTL"; cleanup ) &
WATCH=$!

for _ in $(seq 1 36); do
  ssh -o BatchMode=yes -o ConnectTimeout=8 -o StrictHostKeyChecking=accept-new "root@$IP" 'echo up' && break
  sleep 5
done

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
python backend/scripts/ln7_qlora_train.py \
  --train-jsonl data/ln7_train.jsonl --backend cuda --iters $ITERS \
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
